"""分层 LLM 路由：根据任务复杂度选择不同级别的模型。

设计：所有文本模型统一走 OpenAI-compatible 协议，因此本地与远端 API 可混用：
  - 远端高阶(reasoning)  : GPT-5 / Gemini 2.5 Pro 等(创意/审核/复杂结构化)
  - 远端通用(balanced)   : GPT-5-mini / Gemini Flash 等(分镜/改写)
  - 本地轻量(local)      : 本机 vLLM / Ollama / LM Studio 跑 Qwen 等(拆书/格式化/批量)
  - 视觉(vision)         : 多模态模型(关键帧/成片质检打分)

分层在 config/models.yaml 里声明，agent 只需说明自己要哪一“档”(tier)，
由本路由把 tier 映射到具体 provider+model。这样换模型不用改 agent 代码。
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None


# 任务复杂度 -> 档位。agent 用这些语义档位请求模型。
TIER_CREATIVE = "creative"     # 故事圣经/人物设计/分镜创意, 需要最强模型
TIER_STRUCTURE = "structure"   # 结构化抽取/改写/分镜表, 通用模型即可
TIER_BULK = "bulk"             # 拆书/格式清洗/大批量, 本地轻量模型
TIER_VISION = "vision"         # 图像/成片质检打分, 多模态
TIER_IMAGE = "image"           # 文生图(人物/场景参考图), 如智谱 CogView-4


@dataclass
class ProviderConfig:
    name: str
    base_url: str
    api_key_env: str
    model: str
    temperature: float = 0.4
    max_tokens: int = 4096
    supports_vision: bool = False
    disable_thinking: bool = False   # 关掉 GLM 推理(extraction/格式化任务不需要思考):
    #                                  推理会拖慢(399s→99s)并吃光 max_tokens 致 JSON 被截断。


def _credential(name: str) -> str:
    """Read a credential from an environment value or a mounted secret file."""
    direct = os.getenv(name)
    if direct:
        return direct
    secret_path = os.getenv(f"{name}_FILE")
    if not secret_path:
        return ""
    descriptor: int | None = None
    try:
        descriptor = os.open(secret_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > 4096:
            raise OSError
        raw = os.read(descriptor, 4097)
    except OSError:
        raise RuntimeError("模型凭据不可用") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if not raw or len(raw) > 4096 or any(byte < 0x21 or byte > 0x7E for byte in raw):
        raise RuntimeError("模型凭据无效")
    return raw.decode("ascii")


class LLMRouter:
    """把语义档位路由到具体 provider，并提供统一的 chat / json / vision 接口。"""

    def __init__(
        self,
        config_path: str | Path,
        dry_run: bool = False,
        credential_resolver: Callable[[str, str], str] | None = None,
    ):
        self.dry_run = dry_run
        self._credential_resolver = credential_resolver
        self.tiers: dict[str, ProviderConfig] = {}
        self._clients: dict[str, Any] = {}
        self._credential_fingerprints: dict[str, str] = {}
        if config_path and Path(config_path).exists() and yaml:
            self._load(config_path)

    def _load(self, path: str | Path) -> None:
        cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        for tier, c in (cfg.get("tiers") or {}).items():
            self.tiers[tier] = ProviderConfig(
                name=c.get("provider", tier),
                base_url=c["base_url"],
                api_key_env=c.get("api_key_env", "OPENAI_API_KEY"),
                model=c["model"],
                temperature=c.get("temperature", 0.4),
                max_tokens=c.get("max_tokens", 4096),
                supports_vision=c.get("supports_vision", False),
                disable_thinking=c.get("disable_thinking", False),
            )

    def _resolve_credential(self, provider: ProviderConfig) -> str:
        return (
            self._credential_resolver(provider.name, provider.model)
            if self._credential_resolver is not None
            else _credential(provider.api_key_env)
        )

    def _client(self, tier: str):
        if tier not in self.tiers:
            # 回退：未配置的档位降级到 structure，再降到任意已配置档
            tier = TIER_STRUCTURE if TIER_STRUCTURE in self.tiers else next(iter(self.tiers))
        pc = self.tiers[tier]
        credential = self._resolve_credential(pc)
        credential = credential or "sk-local"
        fingerprint = hashlib.sha256(
            credential.encode("utf-8")
        ).hexdigest()
        if (
            tier not in self._clients
            or self._credential_fingerprints.get(tier) != fingerprint
        ):
            if OpenAI is None:
                raise RuntimeError("缺少 openai 包，请 pip install openai")
            self._clients[tier] = OpenAI(
                api_key=credential,
                base_url=pc.base_url,
            )
            self._credential_fingerprints[tier] = fingerprint
        return self._clients[tier], self.tiers[tier]

    @staticmethod
    def _think_off(pc: "ProviderConfig") -> dict:
        """该档关思考时, 返回给 create() 的额外参数(GLM: extra_body.thinking.type=disabled); 否则空。"""
        return {"extra_body": {"thinking": {"type": "disabled"}}} if pc.disable_thinking else {}

    # ---- 文本对话 ----
    def chat(self, tier: str, system: str, user: str,
             temperature: Optional[float] = None, max_tokens: Optional[int] = None) -> str:
        if self.dry_run:
            return self._mock(tier, system, user)
        client, pc = self._client(tier)
        last = ""
        # ★流式★ 长生成(分镜/圣经, glm-5.1 推理模型)非流式时, 服务器在长时间生成里会掐连接
        #   (APIConnectionError: Server disconnected)。流式边生成边收 token、连接不空闲, 根治该问题;
        #   再加每请求超时(防 thinking 阶段挂死)+ 5 次指数退避(2/4/8/16s)抗瞬时抖动。
        retries = 5
        timeout = 600.0          # 每请求硬超时(秒): 防 thinking 阶段无限挂死
        for attempt in range(retries):
            try:
                stream = client.chat.completions.create(
                    model=pc.model,
                    messages=[{"role": "system", "content": system},
                              {"role": "user", "content": user}],
                    temperature=temperature if temperature is not None else pc.temperature,
                    max_tokens=max_tokens or pc.max_tokens,
                    stream=True,
                    timeout=timeout,
                    **self._think_off(pc),
                )
                parts = []
                for chunk in stream:
                    if not getattr(chunk, "choices", None):
                        continue
                    delta = chunk.choices[0].delta
                    piece = getattr(delta, "content", None)
                    if piece:
                        parts.append(piece)
                last = "".join(parts)
                if last.strip():
                    return last
                # 空响应(推理预算耗在思考上 / 限流抖动 → content 全空): 当作可重试, 避免 chat_json 空串炸流水线。
            except Exception:  # noqa: BLE001  连接断开/限流/超时都重试
                if attempt == retries - 1:
                    raise
            if attempt < retries - 1:
                time.sleep(min(20, 2 ** (attempt + 1)))
        return last

    # ---- 强制 JSON 输出(结构化资产用) ----
    def chat_json(self, tier: str, system: str, user: str, **kw) -> Any:
        sys2 = system + "\n\n严格只输出合法 JSON，不要任何解释文字或 markdown 代码围栏。"
        raw = self.chat(tier, sys2, user, **kw)
        return _extract_json(raw)

    # ---- 视觉质检(图像) ----
    def vision_score(self, system: str, user: str, image_paths: list[str],
                     return_raw: bool = False) -> Any:
        if self.dry_run:
            r = {"score": 0.9, "issues": [], "pass": True}
            return (r, "") if return_raw else r
        import base64
        content: list[dict] = [{"type": "text", "text": user}]
        for p in image_paths:
            b = base64.b64encode(Path(p).read_bytes()).decode()
            content.append({"type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{b}"}})
        return self._vision_call(system, content, return_raw=return_raw)

    # 视频质检结论(散文)→ 结构化 JSON 的轻量转换提示词(走 bulk 文本档, 快且 JSON 稳)。
    _VID_PROSE2JSON = (
        "把下面这段【视频动态质检结论】转成 JSON, 字段: "
        "{motion:0-5, physics:0-5, temporal:0-5, artifact:0-5, overall:0-5, issues:[中文短标签], fix:str}。"
        "按结论语义打分: 明显问题(崩坏/穿模/morph/闪烁/瞬移/几乎静止frozen)给低分(<=2), 正常给4-5; "
        "issues 摘出结论里提到的问题(没有则空); fix 给一句怎么改(没问题留空)。只输出 JSON。")

    # ---- 视觉质检(视频, base64 video_url) ----
    def vision_video_score(self, system: str, user: str, video_path: str,
                           return_raw: bool = False) -> Any:
        """把整段(或一个滑窗片段)视频以 base64 video_url 传给视觉模型(GLM-4.6V 支持视频)。
        ★实测 GLM-4.6V 看视频只肯吐散文不吐 JSON★ → 先拿散文(不强制 JSON), 再用一次廉价文本调用
        把散文转成结构化 JSON。比"强制 JSON 失败→回退抽帧"快得多, 且保留模型对【运动】的判断
        (抽帧是静帧, 判不出 frozen)。调用方负责保证体积在上传上限内(超限先拆窗)。
        return_raw=True 时返回 (结构化, GLM原始散文)(供 Web 展示原始反馈)。"""
        if self.dry_run:
            r = {"motion": 5, "physics": 5, "temporal": 5, "artifact": 5,
                 "overall": 5, "issues": [], "fix": ""}
            return (r, "") if return_raw else r
        import base64
        b = base64.b64encode(Path(video_path).read_bytes()).decode()
        content = [{"type": "text", "text": user},
                   {"type": "video_url", "video_url": {"url": f"data:video/mp4;base64,{b}"}}]
        prose = self._vision_call(system, content, parse=False, force_json=False)   # GLM 原始散文
        if not isinstance(prose, str) or not prose.strip():
            return ({}, "") if return_raw else {}
        try:
            structured = self.chat_json(TIER_BULK, self._VID_PROSE2JSON, prose)
        except Exception:  # noqa: BLE001  转换失败也别炸, 让调用方按空结果处理
            structured = {}
        return (structured, prose) if return_raw else structured

    # 视觉模型(尤其看视频)爱返回叙述散文 → 解析不出 JSON 就回退抽帧, 慢一倍。强约束只输出 JSON。
    _JSON_ONLY = ("\n\n【输出格式·强制】只输出一个合法 JSON 对象, 例如 {\"overall\":4,...}。"
                  "禁止任何叙述/解释/点评/小标题/markdown 代码围栏/前后缀。第一个字符必须是 { 。")

    def _vision_call(self, system: str, content: list[dict], retries: int = 4,
                     parse: bool = True, force_json: bool = True, return_raw: bool = False) -> Any:
        """带 429/限流退避的视觉调用(智谱账号限流较紧, 必须重试)。空响应也重试。
        · force_json: 系统提示追加"只输出 JSON"强约束(看图有效; 看视频模型仍爱吐散文, 故视频走 parse=False)。
        · parse: True→_extract_json 解析返回; False→返回原始文本(给视频"散文→JSON"二次转换用)。
        · return_raw: True→返回 (结果, 模型原始文本)(供 Web 展示"原始反馈"); False→只返回结果。"""
        client, pc = self._client(TIER_VISION)
        if force_json:
            system = system + self._JSON_ONLY
        last: Any = None
        for attempt in range(retries):
            try:
                resp = client.chat.completions.create(
                    model=pc.model,
                    messages=[{"role": "system", "content": system},
                              {"role": "user", "content": content}],
                    temperature=pc.temperature if pc.temperature is not None else 0.1,
                    max_tokens=pc.max_tokens or 4096,
                    **self._think_off(pc),
                )
                txt = resp.choices[0].message.content or ""
                if txt.strip():
                    result = _extract_json(txt) if parse else txt
                    return (result, txt) if return_raw else result
                last = RuntimeError("空响应")
            except Exception as e:  # noqa: BLE001
                last = e
            if attempt < retries - 1:
                msg = str(last).lower()
                throttled = any(k in msg for k in ("429", "rate", "速率", "1302", "limit"))
                time.sleep((6 if throttled else 2) * (attempt + 1))
        if isinstance(last, Exception):
            raise last
        empty = "" if not parse else {}
        return (empty, "") if return_raw else empty

    # ---- 文生图(人物/场景参考图)：智谱 CogView 等 OpenAI 兼容的 images 接口 ----
    def generate_image(self, prompt: str, out_path: str | Path,
                       *, size: str = "1024x1024", tier: str = TIER_IMAGE,
                       seed: int | None = None) -> Path:
        """调用文生图模型生成一张图并下载到 out_path，返回路径。

        - dry-run：写占位文件，保证无 key 也能跑通编排。
        - 走 image 档(models.yaml)的 base_url/model；用 /images/generations(OpenAI 兼容)。
        - CogView 返回图片 URL(也兼容 b64_json)；size 形如 "768x1344"(长宽需被 32 整除)。
        - seed：传入则固定随机种子(同一角色多视图/跨镜头复用同种子→更一致)。若该模型
          不接受 seed 字段，首次尝试失败后会自动去掉 seed 兜底重试，不会让出图整体失败。
        """
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        if self.dry_run:
            out.write_text("dry-run placeholder image", encoding="utf-8")
            return out
        if requests is None:
            raise RuntimeError("缺少 requests 包，请 pip install requests")
        pc = self.tiers.get(tier)
        if pc is None:
            raise RuntimeError(f"models.yaml 未配置 '{tier}' 档(文生图)")
        url = pc.base_url.rstrip("/") + "/images/generations"
        headers = {"Authorization": f"Bearer {self._resolve_credential(pc)}",
                   "Content-Type": "application/json"}
        base_body = {"model": pc.model, "prompt": prompt, "size": size}
        last: Exception | None = None
        for attempt in range(3):
            body = dict(base_body)
            # 仅在首次尝试带 seed；若模型不认 seed 字段而失败，后续尝试自动去掉 seed 兜底。
            if seed is not None and attempt == 0:
                body["seed"] = int(seed)
            try:
                r = requests.post(url, json=body, headers=headers, timeout=300)
                r.raise_for_status()
                data = r.json()["data"][0]
                if data.get("url"):
                    ir = requests.get(data["url"], timeout=300)
                    ir.raise_for_status()
                    raw = ir.content
                elif data.get("b64_json"):
                    raw = base64.b64decode(data["b64_json"])
                else:
                    raise RuntimeError(f"文生图无产物: {str(data)[:300]}")
                # CogView 实际常返回 JPEG/WEBP; 按真实字节纠正扩展名, 避免"扩展名与内容不符"
                # 让某些本地查看器/工具打不开。返回纠正后的真实路径供调用方写入 ref_images。
                out = out.with_suffix(_img_ext(raw))
                out.write_bytes(raw)
                return out
            except Exception as e:  # noqa: BLE001
                last = e
                if attempt == 2:
                    raise
                time.sleep(2 ** attempt)
        raise last if last else RuntimeError("文生图失败")

    # ---- dry-run 桩：返回结构合理的假数据，便于无 GPU/无 key 跑通编排 ----
    def _mock(self, tier: str, system: str, user: str) -> str:
        if "JSON" in system or "json" in user.lower():
            return '{"_mock": true, "tier": "%s"}' % tier
        return f"[MOCK-{tier}] " + user[:60]


def _img_ext(b: bytes) -> str:
    """按图片魔数返回正确扩展名(CogView 多为 JPEG)。识别不出则保守用 .png。"""
    if b[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return ".webp"
    return ".png"


def _extract_json(raw: str) -> Any:
    """从模型输出里稳健地提取 JSON(容忍代码围栏/前后缀)。"""
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?", "", raw).strip()
    raw = re.sub(r"```$", "", raw).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # 抓第一个 { 到最后一个 } / 第一个 [ 到最后一个 ]
        for op, cl in (("{", "}"), ("[", "]")):
            i, j = raw.find(op), raw.rfind(cl)
            if i != -1 and j != -1 and j > i:
                try:
                    return json.loads(raw[i:j + 1])
                except json.JSONDecodeError:
                    continue
        raise ValueError(f"无法从模型输出解析 JSON:\n{raw[:500]}")
