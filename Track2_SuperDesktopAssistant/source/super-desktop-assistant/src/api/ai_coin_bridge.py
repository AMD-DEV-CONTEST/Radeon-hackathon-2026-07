"""
ai-coin 接入桥 —— 用 ai-coin 统一管理供应商/模型 + LLM/视觉调用（Phase B 全量迁移）。

迁移后数据分布：
- 供应商/模型        → ai-coin 的 SQLite（data/ai_coin.db），含 base_url / api_key / 模型目录
- 分配 / 启停 / 本地标记 → data/ai_coin_state.json（只存 env_api_key 引用，不存明文 Key）
- config.json        → 仅保留 settings（providers/assignments 移出）

本桥提供：
- 供应商/模型管理（ensure_seeded 一次性迁移 + CRUD 重定向）
- 统一入口 chat / chat_json / chat_with_tools / analyze_image（复用 ai-coin 的
  工具循环 / JSON 修复 / schema 校验 / 重试 / 错误分类）
- 能力路由 resolve_model_id（子能力回退 + 禁用过滤 + 本地优先）
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from loguru import logger

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = _PROJECT_ROOT / "data" / "ai_coin.db"
STATE_PATH = _PROJECT_ROOT / "data" / "ai_coin_state.json"
CONFIG_PATH = _PROJECT_ROOT / "config.json"

# 媒体文件大小上限（base64 后接近多数 API 请求体限制）
_MAX_MEDIA_SIZE = 50 * 1024 * 1024  # 50 MB

_ai = None


# ═══════════════════════════════════════════════════════════
# 单例
# ═══════════════════════════════════════════════════════════

def get_ai():
    """获取 AICoin 单例（SQLite 存储）。"""
    global _ai
    if _ai is None:
        from ai_coin import AICoin
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _ai = AICoin(str(DB_PATH))
    return _ai


# ═══════════════════════════════════════════════════════════
# state 文件（分配/启停/本地标记，不含明文 Key）
# ═══════════════════════════════════════════════════════════

def load_state() -> dict | None:
    """读取 state 文件；不存在返回 None。"""
    if not STATE_PATH.exists():
        return None
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"[AICOIN] 读取 state 失败: {e}")
        return None


def save_state(state: dict):
    """原子写入 state 文件。"""
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp.json")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    tmp.replace(STATE_PATH)


# ═══════════════════════════════════════════════════════════
# 迁移
# ═══════════════════════════════════════════════════════════

def _infer_api_type(name: str, base_url: str) -> str:
    n = (name or "").lower()
    b = (base_url or "").lower()
    if n in ("anthropic", "claude") or "anthropic" in b:
        return "anthropic"
    if n == "gemini" or "generativelanguage.googleapis.com" in b:
        return "gemini"
    if n == "azure" or ".azure.com" in b or "azureopenai" in b:
        return "azure"
    return "openai_compatible"


def _preset_key(name: str) -> str | None:
    """把配置里的供应商名映射到 ai-coin 内置预设 key（匹配不到返回 None=自定义）。"""
    from ai_coin.presets import get_preset
    n = (name or "").lower()
    alias = {
        "deepseek": "deepseek", "openai": "openai", "zhipu": "zhipu",
        "glm": "zhipu", "qwen": "qwen", "tongyi": "qwen",
        "moonshot": "moonshot", "kimi": "moonshot", "ollama": "ollama",
        "anthropic": "anthropic", "gemini": "gemini", "azure": "azure",
        "groq": "groq", "xai": "xai", "mistral": "mistral",
        "minimax": "minimax", "stepfun": "stepfun", "together": "together",
        "volcengine": "volcengine", "doubao": "volcengine",
        "mimo": "mimo",
    }
    key = alias.get(n)
    return key if key and get_preset(key) else None


def _is_local(name: str, base_url: str) -> bool:
    n = (name or "").lower()
    if n in ("vllm", "ollama", "lmstudio", "local", "localhost"):
        return True
    b = (base_url or "").lower()
    return "127.0.0.1" in b or "localhost" in b


def _read_config_json() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _upsert_model(ai, provider_id: int, name: str, display_name: str, capabilities: dict):
    """模型元数据以调用方为准：同名行先删后插（绕开 ai-coin 的 INSERT OR IGNORE 去重）。

    ai-coin 0.3.1 的 add_provider(preset=...) 会预先按预设默认模型建行
    （display 用裸名、capabilities 为空），随后 add_model 对同名行被静默忽略，
    导致 config 的 display_name/capabilities 写不进 DB。这里先删后插确保权威。
    """
    for m in ai.list_models(provider_id):
        if m.name == name:
            ai.remove_model(m.id)
            break
    ai.add_model(provider_id, name, display_name=display_name, capabilities=capabilities)


def ensure_seeded() -> dict:
    """一次性迁移 config.json 的 providers/assignments 到 ai-coin + state。

    幂等：ai-coin 已有供应商则直接返回当前 state。
    """
    ai = get_ai()
    state = load_state()
    if state is not None:
        return state
    if ai.list_providers():
        # 有供应商但没 state（异常残留），重建 state
        return _rebuild_state_from_ai()

    raw = _read_config_json()
    providers = raw.get("providers", {})
    assignments = raw.get("assignments", {})
    settings = raw.get("settings", {})

    state = {
        "api_preference": settings.get("api_preference", "cloud_default"),
        "providers": {},
        "models": {},
        "assignments": {
            cap: {"provider": a.get("provider", ""), "model": a.get("model", "")}
            for cap, a in assignments.items()
        },
    }

    for name, pdata in providers.items():
        env_key = pdata.get("env_api_key", "")
        api_key = os.getenv(env_key, "") if env_key else pdata.get("api_key", "")
        base_url = pdata.get("base_url", "")
        api_type = pdata.get("api_type") or _infer_api_type(name, base_url)
        # 注意：ai-coin 的 providers.preset 是 NOT NULL DEFAULT ''，无预设时传 "" 而非 None
        preset = _preset_key(name) or ""
        try:
            prov = ai.add_provider(
                name, base_url=base_url, api_key=api_key,
                api_type=api_type, preset=preset,
            )
        except Exception as e:
            logger.warning(f"[AICOIN] 迁移供应商 {name} 失败: {e}")
            continue

        state["providers"][name] = {
            "base_url": base_url,
            "env_api_key": env_key,
            "enabled": pdata.get("enabled", True),
            "is_local": _is_local(name, base_url),
            "api_type": api_type,
            "description": pdata.get("description", ""),
        }
        state["models"][name] = {}
        for mid, mdata in pdata.get("models", {}).items():
            try:
                _upsert_model(
                    ai, prov.id, mid,
                    display_name=mdata.get("display", mid),
                    capabilities={
                        "capabilities": mdata.get("capabilities", []),
                        **mdata.get("default_params", {}),
                    },
                )
            except Exception as e:
                logger.warning(f"[AICOIN] 迁移模型 {name}/{mid} 失败: {e}")
                continue
            state["models"][name][mid] = {
                "capabilities": mdata.get("capabilities", []),
                "display": mdata.get("display", mid),
                "default_params": mdata.get("default_params", {}),
            }

    save_state(state)
    logger.info(f"[AICOIN] 迁移完成: {len(state['providers'])} 供应商 / "
                f"{sum(len(v) for v in state['models'].values())} 模型 → {DB_PATH.name}")
    return state


def migrate_and_slim() -> dict:
    """一次性迁移 config.json → ai-coin + state，然后瘦身 config.json（只留 settings）。

    幂等：state 已存在时仅确认并返回。
    """
    state = ensure_seeded()
    raw = _read_config_json()
    if "providers" in raw or "assignments" in raw:
        raw.pop("providers", None)
        raw.pop("assignments", None)
        tmp = CONFIG_PATH.with_suffix(".tmp.json")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False, indent=2)
        tmp.replace(CONFIG_PATH)
        logger.info("[AICOIN] config.json 已瘦身（providers/assignments → ai-coin state + DB）")
    return state


def reset_state_from_config() -> dict:
    """从 config.json 重新构建 ai-coin DB + state（测试还原 / 手动恢复用）。

    注意：config.json 需仍含 providers/assignments（即尚未 --init-ai-coin 瘦身时可用）。
    """
    global _ai
    for _f in (DB_PATH, STATE_PATH, DB_PATH.with_suffix(".db-journal")):
        try:
            if _f.exists():
                _f.unlink()
        except Exception:
            pass
    _ai = None
    return ensure_seeded()


def _rebuild_state_from_ai() -> dict:
    """从 ai-coin DB 重建 state（当 DB 有数据但 state 丢失时）。"""
    ai = get_ai()
    state = {"api_preference": "cloud_default", "providers": {}, "models": {}, "assignments": {}}
    for p in ai.list_providers():
        state["providers"][p.name] = {
            "base_url": p.base_url, "env_api_key": "",
            "enabled": True, "is_local": _is_local(p.name, p.base_url),
            "api_type": p.api_type, "description": "",
        }
        state["models"][p.name] = {}
        for m in ai.list_models(p.id):
            caps = (m.capabilities or {}).get("capabilities", [])
            state["models"][p.name][m.name] = {
                "capabilities": caps, "display": m.display_name or m.name,
                "default_params": {k: v for k, v in (m.capabilities or {}).items() if k != "capabilities"},
            }
    save_state(state)
    return state


def resync_models_from_state() -> dict:
    """一次性把 state.json 的 display_name/capabilities 回填到 ai-coin DB。

    修复 ai-coin 0.3.1 预设自动建行导致的 capabilities={} 元数据丢失：
    - 在 state 且元数据不一致 → 先删后插写回（updated）
    - 不在 state 且 capabilities 为空 → 剪除预设噪音行（removed）
    - 其余保留（kept）
    幂等：仅不一致才写。只读 state.json，不会重新创建缺失的 state。
    """
    state = load_state()
    if state is None:
        return {"updated": [], "removed": [], "kept": 0}
    ai = get_ai()
    provs = {p.name: p for p in ai.list_providers()}
    state_models = state.get("models", {})
    updated: list[str] = []
    removed: list[str] = []
    kept = 0
    for pname, p in provs.items():
        s_models = state_models.get(pname, {})
        for m in ai.list_models(p.id):
            info = s_models.get(m.name)
            if info is None:
                if not (m.capabilities or {}):
                    ai.remove_model(m.id)
                    removed.append(f"{pname}/{m.name}")
                else:
                    kept += 1
                continue
            want_disp = info.get("display") or m.name
            want_caps = {
                "capabilities": info.get("capabilities", []),
                **info.get("default_params", {}),
            }
            cur_caps = (m.capabilities or {}).get("capabilities", [])
            if m.display_name == want_disp and sorted(cur_caps) == sorted(info.get("capabilities", [])):
                kept += 1
                continue
            ai.remove_model(m.id)
            ai.add_model(p.id, m.name, display_name=want_disp, capabilities=want_caps)
            updated.append(f"{pname}/{m.name}")
    logger.info(f"[AICOIN] resync: updated={updated} removed={removed} kept={kept}")
    return {"updated": updated, "removed": removed, "kept": kept}


# ═══════════════════════════════════════════════════════════
# 能力路由
# ═══════════════════════════════════════════════════════════

def _model_id_for(provider_name: str, model_name: str) -> int:
    ai = get_ai()
    provs = {p.name: p for p in ai.list_providers()}
    p = provs.get(provider_name)
    if p is None:
        raise ValueError(f"供应商不存在: {provider_name}")
    for m in ai.list_models(p.id):
        if m.name == model_name:
            return m.id
    raise ValueError(f"模型 {model_name} 不存在于供应商 {provider_name}")


def resolve_model_id(capability: str, provider: str | None = None,
                     model: str | None = None) -> int:
    """能力 → ai-coin 模型 id。

    支持：子能力回退（llm_reasoning→llm）、禁用过滤、local_first 本地优先。
    显式指定 provider+model 时直接查库。
    """
    if provider and model:
        return _model_id_for(provider, model)

    state = ensure_seeded()

    # 子能力回退链
    caps = [capability]
    if capability.startswith("llm_") and capability != "llm":
        caps.append("llm")

    for cap in caps:
        assign = state.get("assignments", {}).get(cap)
        if not assign:
            continue
        pname, mname = assign.get("provider"), assign.get("model")
        pinfo = state.get("providers", {}).get(pname)
        if not pinfo or not pinfo.get("enabled", True):
            continue
        if pname in state.get("models", {}) and mname in state["models"][pname]:
            return _model_id_for(pname, mname)

    # 兜底：其他 enabled 供应商中匹配能力的模型
    candidates: list[tuple[str, str]] = []
    base_cap = "llm" if capability.startswith("llm_") else capability
    for pname, models in state.get("models", {}).items():
        pinfo = state.get("providers", {}).get(pname)
        if not pinfo or not pinfo.get("enabled", True):
            continue
        for mname, minfo in models.items():
            if base_cap in minfo.get("capabilities", []):
                candidates.append((pname, mname))

    if not candidates:
        raise ValueError(
            f"功能 '{capability}' 未分配可用的供应商/模型。"
            f"请在配置中选择模型（当前 enabled 供应商: {list(state.get('providers', {}).keys())}）"
        )

    if state.get("api_preference") == "local_first":
        candidates.sort(key=lambda x: (0 if state["providers"][x[0]].get("is_local") else 1,))
    pname, mname = candidates[0]
    return _model_id_for(pname, mname)


def _settings_timeout(capability: str) -> float:
    """按能力从 config.json settings 读超时（对齐 executor 的类型超时）。"""
    raw = _read_config_json()
    exec_cfg = raw.get("settings", {}).get("execution", {})
    if capability in ("stt", "tts"):
        return float(exec_cfg.get("timeout_audio", 20))
    if capability in ("image_gen", "image_edit"):
        return float(exec_cfg.get("timeout_image", 120))
    return float(exec_cfg.get("timeout_text", 240))


# ═══════════════════════════════════════════════════════════
# 统一调用入口（供 api/llm.py、api/vision.py 委托）
# ═══════════════════════════════════════════════════════════

def chat(messages: list[dict], capability: str = "llm",
         provider: str | None = None, model: str | None = None,
         temperature: float | None = None, max_tokens: int | None = None,
         **extra) -> str:
    """统一 LLM 对话。返回文本。"""
    model_id = resolve_model_id(capability, provider, model)
    s = _read_config_json().get("settings", {}).get("execution", {})
    retries = max(0, int(s.get("max_retries", 1)))
    try:
        return get_ai().chat(
            model_id, messages, temperature=temperature,
            max_tokens=max_tokens, retries=retries,
            timeout=_settings_timeout(capability),
        )
    except Exception as e:
        raise RuntimeError(f"LLM API 调用失败: {e}") from e


def chat_stream(messages: list[dict], capability: str = "llm",
                provider: str | None = None, model: str | None = None,
                temperature: float | None = None, max_tokens: int | None = None):
    """流式对话。返回增量文本生成器（yield str）。

    委托 ai-coin 的 stream_chat（SSE）。注意 stream_chat 不支持 tools/json_schema；
    gemini 供应商未实现流式，迭代首块会抛 NotImplementedError，调用方需 try/except 回退 chat。
    """
    model_id = resolve_model_id(capability, provider, model)
    s = _read_config_json().get("settings", {}).get("execution", {})
    retries = max(0, int(s.get("max_retries", 1)))
    return get_ai().stream_chat(
        model_id, messages, temperature=temperature, max_tokens=max_tokens,
        retries=retries, timeout=_settings_timeout(capability),
    )


def chat_json(messages: list[dict], capability: str = "llm",
              provider: str | None = None, model: str | None = None,
              temperature: float = 0.1, **extra) -> str:
    """强制 JSON 输出。ai-coin 结构化输出（JSON 修复 + schema 校验 + 回喂重试），返回 JSON 字符串。"""
    from ai_coin.errors import AICoinError
    model_id = resolve_model_id(capability, provider, model)
    schema = extra.get("json_schema") or {"type": "object"}
    s = _read_config_json().get("settings", {}).get("execution", {})
    retries = max(0, int(s.get("max_retries", 1)))
    try:
        obj = get_ai().chat(
            model_id, messages, json_schema=schema,
            temperature=temperature, retries=retries,
            timeout=_settings_timeout(capability),
        )
    except AICoinError as e:
        # 结构化输出彻底失败：回退到普通 chat_json 提示 + 手工清洗
        logger.warning(f"[AICOIN] 结构化输出失败，回退普通 JSON 提示: {e}")
        text = chat(messages, capability=capability, provider=provider,
                    model=model, temperature=temperature, **extra)
        import re as _re
        m = _re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, _re.DOTALL)
        if m:
            text = m.group(1).strip()
        return text
    return json.dumps(obj, ensure_ascii=False)


def chat_with_tools(messages: list[dict], tools: list[dict],
                    capability: str = "llm", provider: str | None = None,
                    model: str | None = None, temperature: float | None = None,
                    max_tokens: int | None = None, max_tool_rounds: int = 8,
                    on_tool_call=None, **extra) -> str:
    """带工具循环的 LLM 对话（ai-coin 原生 tool_calls + 文本式 <tool_call> 兼容）。

    ai-coin 原生 `_tool_loop` 只处理 API 返回的 tool_calls 字段；
    推理类模型（如 mimo-v2.5）常以**文本式** `<tool_call>` 输出工具调用，
    这里在每轮结果里解析 `<tool_call>` 并执行，再回传工具输出，直到模型收尾。
    """
    model_id = resolve_model_id(capability, provider, model)
    s = _read_config_json().get("settings", {}).get("execution", {})
    retries = max(0, int(s.get("max_retries", 1)))

    api_tools = None
    if tools and on_tool_call is not None:
        api_tools = []
        for t in tools:
            fn = t.get("function") or {}
            name = fn.get("name") or t.get("name")
            if not name:
                continue

            def _make(nm: str):
                return lambda **kw: on_tool_call(nm, kw)

            api_tools.append({
                "name": name,
                "description": fn.get("description", ""),
                "parameters": fn.get("parameters", {"type": "object", "properties": {}}),
                "function": _make(name),
            })

    from .llm import _parse_text_tool_calls

    msgs = list(messages)
    max_rounds = max(1, int(max_tool_rounds or 8))
    last_text = ""
    for _ in range(max_rounds):
        try:
            text = get_ai().chat(
                model_id, msgs, tools=api_tools or None,
                temperature=temperature, max_tokens=max_tokens,
                retries=retries, timeout=_settings_timeout(capability),
            )
        except Exception as e:
            raise RuntimeError(f"LLM Tool API 调用失败: {e}") from e
        last_text = text
        if "<tool_call>" not in text or on_tool_call is None:
            return text
        calls = _parse_text_tool_calls(text)
        if not calls:
            return text
        # 追加 assistant 原始回复（含 <tool_call>），再逐个执行并回传结果
        msgs = msgs + [{"role": "assistant", "content": text}]
        for name, args in calls:
            try:
                output = on_tool_call(name, args)
            except Exception as e:
                output = f"[TOOL ERROR] {e}"
            msgs = msgs + [{
                "role": "user",
                "content": f"工具 {name} 返回：{str(output)[:2000]}",
            }]
    # 达到轮数上限：返回最后一次模型文本（避免把工具输出误当最终答案）
    return last_text


def analyze_image(image_path: str | None = None, image_url: str | None = None,
                  prompt: str = "", provider: str | None = None,
                  model: str | None = None, temperature: float | None = None,
                  max_tokens: int | None = None) -> str:
    """视觉分析（ai-coin 多模态）。本地图片自动 base64。"""
    from ai_coin import image_part
    if max_tokens is None:
        max_tokens = 300  # 限制输出长度，避免视觉生成完整长文拖慢（约 10-20s）
    model_id = resolve_model_id("vision", provider, model)
    content = [{"type": "text", "text": prompt or "请描述这张图片"}]
    if image_path:
        content.append(image_part(image_path))
    elif image_url:
        content.append({"type": "image_url", "image_url": {"url": image_url}})
    try:
        return get_ai().chat(
            model_id, [{"role": "user", "content": content}],
            temperature=temperature, max_tokens=max_tokens,
            retries=0, timeout=_settings_timeout("vision"),
        )
    except Exception as e:
        raise RuntimeError(f"Vision API 调用失败: {e}") from e


def analyze_media(image_path: str | None = None, audio_path: str | None = None,
                  video_path: str | None = None, prompt: str = "",
                  provider: str | None = None, model: str | None = None,
                  temperature: float | None = None, max_tokens: int | None = None) -> str:
    """多模态媒体分析（图片/音频/视频）。本地文件自动 base64。

    复用 ai-coin 的 image_part / audio_part / video_part。
    注意：gemini 供应商的多模态暂不支持（适配器只发文本），
    openai_compatible / anthropic 可用。
    """
    from ai_coin import image_part, audio_part, video_part
    model_id = resolve_model_id("vision", provider, model)
    content = [{"type": "text", "text": prompt or "请分析这段媒体内容"}]
    if video_path:
        size = os.path.getsize(video_path)
        if size > _MAX_MEDIA_SIZE:
            raise ValueError(f"视频文件过大: {size} bytes > {_MAX_MEDIA_SIZE} limit")
        content.append(video_part(video_path))
    if audio_path:
        content.append(audio_part(audio_path))
    if image_path:
        content.append(image_part(image_path))
    try:
        return get_ai().chat(
            model_id, [{"role": "user", "content": content}],
            temperature=temperature, max_tokens=max_tokens,
            retries=0, timeout=_settings_timeout("vision"),
        )
    except Exception as e:
        raise RuntimeError(f"Media API 调用失败: {e}") from e


# ═══════════════════════════════════════════════════════════
# 写入重定向（Layer 1 配置指令 / UI 修改）
# ═══════════════════════════════════════════════════════════

def set_assignment(capability: str, provider_name: str, model_id: str):
    """更新能力分配 → state.json（模型需已在 ai-coin 中）。"""
    state = ensure_seeded()
    state.setdefault("assignments", {})[capability] = {
        "provider": provider_name, "model": model_id,
    }
    save_state(state)


def set_provider_enabled(provider_name: str, enabled: bool):
    """启停供应商 → state.json。"""
    state = ensure_seeded()
    pinfo = state.get("providers", {}).get(provider_name)
    if pinfo is None:
        raise ValueError(f"供应商不存在: {provider_name}")
    pinfo["enabled"] = bool(enabled)
    save_state(state)


def set_api_preference(pref: str):
    """写 api_preference（同步到 config.json settings）。"""
    if pref not in ("local_first", "cloud_default"):
        raise ValueError("api_preference 只能为 local_first 或 cloud_default")
    raw = _read_config_json()
    raw.setdefault("settings", {})["api_preference"] = pref
    tmp = CONFIG_PATH.with_suffix(".tmp.json")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False, indent=2)
    tmp.replace(CONFIG_PATH)
    # 同步 state
    state = ensure_seeded()
    state["api_preference"] = pref
    save_state(state)


def provider_state_for_config() -> tuple[dict, dict, str]:
    """供 ConfigManager 构建 ProviderSpec/Assignment：
    返回 (providers_raw, assignments_raw, api_preference)。providers_raw 与
    config.json 的 providers 结构同构（models 内嵌）。
    """
    state = ensure_seeded()
    providers_raw: dict = {}
    for name, pinfo in state.get("providers", {}).items():
        models = state.get("models", {}).get(name, {})
        providers_raw[name] = {
            "env_api_key": pinfo.get("env_api_key", ""),
            "base_url": pinfo.get("base_url", ""),
            "enabled": pinfo.get("enabled", True),
            "description": pinfo.get("description", ""),
            "models": {
                mid: {
                    "capabilities": minfo.get("capabilities", []),
                    "display": minfo.get("display", mid),
                    "default_params": minfo.get("default_params", {}),
                }
                for mid, minfo in models.items()
            },
        }
    return providers_raw, dict(state.get("assignments", {})), state.get("api_preference", "cloud_default")
