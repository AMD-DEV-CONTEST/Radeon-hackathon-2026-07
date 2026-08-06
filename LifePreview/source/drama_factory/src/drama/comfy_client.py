"""ComfyUI 客户端：加载 workflow_api.json、注入参数、提交、轮询、下载产物。

支持双卡：通过传入不同 base_url(如 8188 / 8189 两个 ComfyUI 实例)实现把
不同镜头分发到两张 4090 上并行生成。见 orchestrator 的并行调度。

工作流参数注入采用“占位符替换”策略：在 workflow_api.json 中把需要动态改的值
写成形如  {{POS_PROMPT}} / {{IMAGE}} / {{SEED}} 的占位符，本客户端按 mapping 替换。
这样 agent 不需要硬编码节点 ID，换工作流只改 mapping。
"""
from __future__ import annotations

import copy
import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

try:
    import websocket  # websocket-client: 订阅 ComfyUI 进度事件(逐步/逐帧)。缺失则降级为无进度。
except Exception:  # noqa: BLE001
    websocket = None


class ComfyClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8188",
                 dry_run: bool = False, timeout_sec: int = 1800):
        self.base = base_url.rstrip("/")
        self.dry_run = dry_run
        self.timeout = timeout_sec

    # ---- 工作流加载 + 占位符注入 ----
    @staticmethod
    def load_workflow(path: str | Path) -> dict:
        return json.loads(Path(path).read_text(encoding="utf-8"))

    @staticmethod
    def inject(workflow: dict, params: dict[str, Any]) -> dict:
        """把 {{KEY}} 占位符替换为 params[KEY]。深拷贝，不污染模板。"""
        wf = copy.deepcopy(workflow)
        raw = json.dumps(wf, ensure_ascii=False)
        for key, val in params.items():
            token = "{{%s}}" % key
            if isinstance(val, str):
                raw = raw.replace(token, _json_escape(val))
            else:
                # 数值/布尔：替换并去掉包裹的引号 "{{SEED}}" -> 123
                raw = raw.replace('"%s"' % token, json.dumps(val))
                raw = raw.replace(token, json.dumps(val))
        return json.loads(raw)

    # ---- 上传文件到 ComfyUI input/(I2V/对口型需要把关键帧/参考图/音频喂进去) ----
    def upload_file(self, path: str | Path, *, field: str = "image",
                    subfolder: str = "") -> str:
        """把任意文件放进 ComfyUI 的 input/ 目录, 返回存储后的文件名。

        ComfyUI 事实上的“塞文件进 input/”端点是 POST /upload/image(multipart,
        字段名 image), 实践中对任意文件(含音频)都生效并返回 {"name": ...}。
        工作流随后用 LoadImage/LoadAudio 按文件名加载。
        """
        if self.dry_run:
            return Path(path).name
        if requests is None:
            raise RuntimeError("缺少 requests 包，请 pip install requests")
        p = Path(path)
        files = {field: (p.name, p.read_bytes())}
        data = {"overwrite": "true", "subfolder": subfolder}
        r = requests.post(f"{self.base}/upload/image", files=files, data=data, timeout=120)
        r.raise_for_status()
        return r.json().get("name", p.name)

    def upload_image(self, path: str | Path, subfolder: str = "") -> str:
        """上传参考图/关键帧, 委托给通用 upload_file。"""
        return self.upload_file(path, field="image", subfolder=subfolder)

    def upload_audio(self, path: str | Path, subfolder: str = "") -> str:
        """上传音频(对口型/LoadAudio), 语义别名, 同样落进 input/。"""
        return self.upload_file(path, field="image", subfolder=subfolder)

    # ---- 提交 + 等待 + 下载 ----
    def run(self, workflow: dict, out_dir: str | Path,
            save_node_types: tuple[str, ...] = ("images", "gifs", "videos"),
            prefix: str = "", progress_cb=None, check_cb=None) -> list[Path]:
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        if self.dry_run:
            # 写一个占位产物，保证下游能继续
            tag = f"{prefix}_" if prefix else ""
            placeholder = out / f"{tag}_mock_{uuid.uuid4().hex[:8]}.txt"
            placeholder.write_text("dry-run placeholder asset", encoding="utf-8")
            return [placeholder]

        if requests is None:
            raise RuntimeError("缺少 requests 包，请 pip install requests")
        # 进度订阅(可选): 用与提交相同的 client_id 连 WebSocket, 作为 owner 必收到本
        # prompt 的 progress 事件(KSampler 步数)。完成判定仍走原有 /history 轮询(稳)。
        client_id = uuid.uuid4().hex
        stop = threading.Event()
        listener: Optional[threading.Thread] = None
        if progress_cb is not None and websocket is not None:
            listener = threading.Thread(
                target=self._ws_listen, args=(client_id, progress_cb, stop), daemon=True)
            listener.start()
        try:
            prompt_id = self._queue(workflow, client_id=client_id)
            history = self._wait(prompt_id, check_cb=check_cb)
        finally:
            stop.set()
            if listener is not None:
                listener.join(timeout=2)
        return self._download(history, out, save_node_types, prefix)

    def _ws_listen(self, client_id: str, progress_cb, stop: "threading.Event") -> None:
        """后台线程: 订阅 ComfyUI WebSocket, 把 progress 事件(value/max/node)回调出去。
        任何异常都安静退出(进度只是锦上添花, 绝不影响生成)。"""
        if websocket is None:
            return
        ws_url = (self.base.replace("https://", "wss://").replace("http://", "ws://")
                  + f"/ws?clientId={client_id}")
        try:
            ws = websocket.create_connection(ws_url, timeout=10)
            ws.settimeout(1.0)
        except Exception:  # noqa: BLE001
            return
        try:
            while not stop.is_set():
                try:
                    msg = ws.recv()
                except Exception:  # noqa: BLE001 — 超时/断开
                    if stop.is_set():
                        break
                    continue
                if isinstance(msg, (bytes, bytearray)):
                    continue  # 预览图二进制帧, 忽略
                try:
                    d = json.loads(msg)
                except Exception:  # noqa: BLE001
                    continue
                if d.get("type") == "progress":
                    data = d.get("data") or {}
                    try:
                        progress_cb(data.get("value", 0), data.get("max", 0), data.get("node"))
                    except Exception:  # noqa: BLE001
                        pass
        finally:
            try:
                ws.close()
            except Exception:  # noqa: BLE001
                pass

    def _queue(self, workflow: dict, client_id: Optional[str] = None) -> str:
        # 只保留真正的节点条目(value 是 dict)。工作流 JSON 里的 _comment / _stub 等
        # 字符串元数据键必须剔除，否则 ComfyUI 的 prompt 处理会因 "string indices" 报 500。
        prompt = {k: v for k, v in workflow.items() if isinstance(v, dict)}
        payload = {"prompt": prompt, "client_id": client_id or str(uuid.uuid4())}
        r = requests.post(f"{self.base}/prompt", json=payload, timeout=60)
        # 节点校验失败时 ComfyUI 返回 400 + JSON(node_errors), 优先把它带出来
        if r.status_code >= 400:
            detail = _safe_resp_text(r)
            raise RuntimeError(f"ComfyUI 校验失败(HTTP {r.status_code}): {detail}")
        data = r.json()
        if "prompt_id" not in data:
            raise RuntimeError(f"ComfyUI 校验失败: {json.dumps(data, ensure_ascii=False)[:800]}")
        return data["prompt_id"]

    def _wait(self, prompt_id: str, check_cb=None) -> dict:
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            if check_cb is not None:
                check_cb()
            r = requests.get(f"{self.base}/history/{prompt_id}", timeout=30)
            r.raise_for_status()
            data = r.json()
            if prompt_id in data:
                entry = data[prompt_id]
                status = entry.get("status", {})
                if status.get("status_str") == "error":
                    # 优先提取节点级报错(messages 里常带 execution_error 详情)
                    node_errors = entry.get("node_errors") or status.get("messages")
                    detail = json.dumps(node_errors, ensure_ascii=False)[:800] if node_errors else status
                    raise RuntimeError(f"ComfyUI 执行报错: {detail}")
                return entry
            time.sleep(2)
        raise TimeoutError(f"ComfyUI 任务超时: {prompt_id}")

    def _download(self, history: dict, out: Path, keys: tuple[str, ...],
                  prefix: str = "") -> list[Path]:
        saved: list[Path] = []
        for node_output in history.get("outputs", {}).values():
            for key in keys:
                for item in node_output.get(key, []):
                    params = {
                        "filename": item["filename"],
                        "subfolder": item.get("subfolder", ""),
                        "type": item.get("type", "output"),
                    }
                    r = requests.get(f"{self.base}/view", params=params, timeout=300)
                    r.raise_for_status()
                    # 双卡并行: 用镜头唯一前缀重命名, 否则两个实例各自的 SaveImage/VHS
                    # 计数器(keyframe_iid_00001_ 等)会在共享项目目录里互相覆盖。
                    name = f"{prefix}_{item['filename']}" if prefix else item["filename"]
                    target = out / name
                    target.write_bytes(r.content)
                    saved.append(target)
        return saved

    def is_alive(self) -> bool:
        if self.dry_run:
            return True
        if requests is None:
            return False
        try:
            r = requests.get(f"{self.base}/system_stats", timeout=5)
            return r.status_code == 200
        except Exception:  # noqa: BLE001
            return False

    def preflight(self) -> None:
        """提交前自检: 缺 requests 或 ComfyUI 不在线时抛出清晰错误(dry-run 直接通过)。"""
        if self.dry_run:
            return
        if requests is None:
            raise RuntimeError("缺少 requests 包，请 pip install requests")
        if not self.is_alive():
            raise RuntimeError(f"ComfyUI 不可达: {self.base}(检查实例是否启动)")


def _json_escape(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)[1:-1]


def _safe_resp_text(r: Any) -> str:
    """尽量把响应体转成可读字符串(优先 JSON, 失败回退到文本截断)。"""
    try:
        return json.dumps(r.json(), ensure_ascii=False)[:800]
    except Exception:  # noqa: BLE001
        return (getattr(r, "text", "") or "")[:800]
