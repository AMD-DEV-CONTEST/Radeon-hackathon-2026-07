"""ComfyUI HTTP API 客户端.

封装与 ComfyUI 后端的交互:
  - 加载/修改工作流模板
  - 上传输入图像
  - 提交工作流到队列
  - 通过 WebSocket 监听进度
  - 轮询/等待结果并下载输出文件

ComfyUI API 文档参考: https://github.com/comfyanonymous/ComfyUI/blob/master/comfy-cli/README.md
工作流 JSON 采用 ComfyUI 的 "API 格式" (节点 ID 为键, 含 inputs/class_type)。
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Iterator

from config import WORKFLOWS_DIR


def _require_requests():
    """惰性导入 requests (避免纯工作流操作也强依赖网络库)."""
    import requests
    return requests


class ComfyUIError(RuntimeError):
    """ComfyUI 交互异常."""


class ComfyUIClient:
    """ComfyUI HTTP + WebSocket 客户端.

    Parameters
    ----------
    base_url : str
        ComfyUI 服务地址, 如 ``http://127.0.0.1:8188``。
    output_dir : Path
        下载结果文件的本地保存目录。
    """

    def __init__(self, base_url: str = "http://127.0.0.1:8188",
                 output_dir: Path | None = None):
        self.base_url = base_url.rstrip("/")
        self.ws_url = base_url.replace("http://", "ws://").replace("https://", "wss://")
        self.output_dir = output_dir or Path("outputs")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._client_id = str(uuid.uuid4())
        self._session = None  # 惰性创建, 避免强依赖 requests

    @property
    def session(self):
        """惰性 requests.Session (首次访问时创建)."""
        if self._session is None:
            self._session = _require_requests().Session()
        return self._session

    # ------------------------------------------------------------------ #
    # 健康检查
    # ------------------------------------------------------------------ #
    def health(self) -> bool:
        """检查 ComfyUI 是否可达."""
        try:
            r = self.session.get(f"{self.base_url}/system_stats", timeout=5)
            return r.status_code == 200
        except Exception:
            return False

    # ------------------------------------------------------------------ #
    # 工作流模板
    # ------------------------------------------------------------------ #
    def load_workflow(self, workflow_path: str | Path) -> dict:
        """加载 JSON 工作流模板 (API 格式).

        既可传绝对路径, 也可传 ``WORKFLOWS_DIR`` 下的文件名。
        """
        p = Path(workflow_path)
        if not p.is_absolute():
            p = WORKFLOWS_DIR / workflow_path
        if not p.exists():
            raise ComfyUIError(f"工作流模板不存在: {p}")
        with p.open("r", encoding="utf-8") as f:
            wf = json.load(f)
        # 移除非节点字段 (如 _comment), 否则 ComfyUI 会把它当节点处理报错
        wf.pop("_comment", None)
        return wf

    @staticmethod
    def set_node_param(workflow: dict, node_id: str, key: str, value: Any) -> dict:
        """设置某节点某参数 (原地修改并返回).

        ComfyUI API 格式: ``workflow[node_id]["inputs"][key] = value``。
        """
        if node_id not in workflow:
            raise ComfyUIError(f"节点不存在: {node_id} (可用: {list(workflow.keys())})")
        workflow[node_id]["inputs"][key] = value
        return workflow

    # ------------------------------------------------------------------ #
    # 文件上传
    # ------------------------------------------------------------------ #
    def upload_image(self, image_path: str | Path,
                     overwrite: bool = True) -> str:
        """上传图像到 ComfyUI 的 input 目录, 返回文件名.

        Returns
        -------
        str
            ComfyUI 内部使用的文件名 (用于 LoadImage 节点的 image 参数)。
        """
        image_path = Path(image_path)
        if not image_path.exists():
            raise ComfyUIError(f"图像不存在: {image_path}")
        with image_path.open("rb") as f:
            files = {"image": (image_path.name, f, "image/png")}
            data = {"overwrite": "true" if overwrite else "false",
                    "type": "input"}
            r = self.session.post(
                f"{self.base_url}/upload/image",
                files=files, data=data, timeout=60,
            )
        if r.status_code != 200:
            raise ComfyUIError(f"上传失败 {r.status_code}: {r.text}")
        info = r.json()
        return info.get("name", image_path.name)

    def upload_mask(self, mask_path: str | Path,
                    overwrite: bool = True) -> str:
        """上传 mask 到 ComfyUI 的 input 目录."""
        return self.upload_image(mask_path, overwrite=overwrite)

    # ------------------------------------------------------------------ #
    # 提交 & 等待
    # ------------------------------------------------------------------ #
    def queue_prompt(self, workflow: dict) -> str:
        """提交工作流到队列, 返回 ``prompt_id``."""
        payload = {"prompt": workflow, "client_id": self._client_id}
        r = self.session.post(
            f"{self.base_url}/prompt", json=payload, timeout=30,
        )
        if r.status_code != 200:
            raise ComfyUIError(f"提交失败 {r.status_code}: {r.text}")
        data = r.json()
        if "error" in data:
            raise ComfyUIError(f"工作流错误: {data['error']}")
        return data["prompt_id"]

    def get_history(self, prompt_id: str) -> dict:
        """获取某 prompt 的历史记录 (含输出)."""
        r = self.session.get(
            f"{self.base_url}/history/{prompt_id}", timeout=15,
        )
        if r.status_code != 200:
            raise ComfyUIError(f"查询历史失败 {r.status_code}")
        history = r.json()
        return history.get(prompt_id, {})

    def get_status(self) -> dict:
        """获取队列状态."""
        r = self.session.get(f"{self.base_url}/queue", timeout=10)
        return r.json() if r.status_code == 200 else {}

    def cancel(self, prompt_id: str | None = None,
               delete_next: bool = False) -> bool:
        """取消队列任务."""
        data = {"delete_next": str(delete_next).lower()}
        if prompt_id:
            data["cancel"] = [prompt_id]
        r = self.session.post(f"{self.base_url}/queue", json=data, timeout=10)
        return r.status_code == 200

    # ------------------------------------------------------------------ #
    # 输出下载
    # ------------------------------------------------------------------ #
    def download_output(self, filename: str, subfolder: str = "",
                        output_type: str = "output") -> Path:
        """下载 ComfyUI 输出文件到本地.

        Parameters
        ----------
        filename : str
            ComfyUI 输出文件名。
        subfolder : str
            输出子目录。
        output_type : str
            ``output`` / ``temp``。
        """
        params = {"filename": filename, "type": output_type}
        if subfolder:
            params["subfolder"] = subfolder
        r = self.session.get(
            f"{self.base_url}/view", params=params, timeout=120,
        )
        if r.status_code != 200:
            raise ComfyUIError(f"下载失败 {r.status_code}: {filename}")
        local = self.output_dir / filename
        local.write_bytes(r.content)
        return local

    def get_output(self, prompt_id: str) -> list[Path]:
        """获取某 prompt 的所有输出文件 (下载到本地).

        Returns
        -------
        list[Path]
            下载到本地的输出文件路径列表。
        """
        history = self.get_history(prompt_id)
        if not history:
            return []
        outputs: list[Path] = []
        for node_id, node_out in history.get("outputs", {}).items():
            for kind in ("images", "gifs", "videos", "audio"):
                for item in node_out.get(kind, []) or []:
                    fname = item.get("filename")
                    if not fname:
                        continue
                    local = self.download_output(
                        fname,
                        subfolder=item.get("subfolder", ""),
                        output_type=item.get("type", "output"),
                    )
                    outputs.append(local)
        return outputs

    # ------------------------------------------------------------------ #
    # 等待完成
    # ------------------------------------------------------------------ #
    def wait_for_result(self, prompt_id: str, timeout: int = 600) -> dict:
        """阻塞等待 prompt 完成, 返回历史记录 (轮询模式)."""
        deadline = time.time() + timeout
        return self._wait_via_polling(prompt_id, deadline)

    def _wait_via_websocket(self, prompt_id: str, deadline: float) -> dict:
        import websocket  # 惰性导入
        ws = websocket.create_connection(
            f"{self.ws_url}/ws?clientId={self._client_id}",
            timeout=max(5, int(deadline - time.time())),
        )
        try:
            while time.time() < deadline:
                ws.settimeout(max(1, int(deadline - time.time())))
                try:
                    msg = json.loads(ws.recv())
                except websocket.WebSocketTimeoutException:
                    continue
                if msg.get("type") == "executing":
                    data = msg.get("data", {})
                    if data.get("node") is None and data.get("prompt_id") == prompt_id:
                        # 执行完毕
                        return self.get_history(prompt_id)
                elif msg.get("type") == "execution_error":
                    data = msg.get("data", {})
                    if data.get("prompt_id") == prompt_id:
                        raise ComfyUIError(
                            f"执行错误: {data.get('exception_message', 'unknown')}"
                        )
            raise ComfyUIError(f"等待超时 ({prompt_id})")
        finally:
            ws.close()

    def _wait_via_polling(self, prompt_id: str, deadline: float) -> dict:
        interval = 1.0
        while time.time() < deadline:
            history = self.get_history(prompt_id)
            if history:
                status = history.get("status", {})
                if status.get("completed", False) or status.get("status_str") == "error":
                    if status.get("status_str") == "error":
                        raise ComfyUIError(f"执行错误: {status.get('messages', '')}")
                    return history
            time.sleep(interval)
        raise ComfyUIError(f"等待超时 ({prompt_id})")

    # ------------------------------------------------------------------ #
    # 进度迭代器 (用于 UI 显示进度)
    # ------------------------------------------------------------------ #
    def iter_progress(self, prompt_id: str, timeout: int = 600
                      ) -> Iterator[dict]:
        """生成器: 产出进度事件, 完成时产出 ``{"done": True, "outputs": [...]}``.

        优先使用 WebSocket 获取实时进度 (节点执行 / 采样进度),
        不可用时回退到轮询模式。
        """
        deadline = time.time() + timeout
        try:
            yield from self._iter_via_websocket(prompt_id, deadline)
        except Exception:
            # WebSocket 不可用, 回退到轮询
            yield from self._iter_via_polling(prompt_id, deadline)

    def _iter_via_websocket(self, prompt_id: str,
                            deadline: float) -> Iterator[dict]:
        """通过 WebSocket 获取实时进度事件."""
        import websocket  # 惰性导入
        ws = websocket.create_connection(
            f"{self.ws_url}/ws?clientId={self._client_id}",
            timeout=max(5, int(deadline - time.time())),
        )
        try:
            while time.time() < deadline:
                ws.settimeout(max(1, int(deadline - time.time())))
                try:
                    msg = json.loads(ws.recv())
                except Exception:
                    # WebSocket 超时或错误, 回退到轮询
                    break

                msg_type = msg.get("type")
                data = msg.get("data", {})

                if msg_type == "progress":
                    # 采样进度: {value, max, prompt_id}
                    if data.get("prompt_id") == prompt_id:
                        value = data.get("value", 0)
                        max_val = data.get("max", 1)
                        ratio = value / max_val if max_val > 0 else 0
                        yield {"type": "progress", "value": ratio,
                               "message": f"采样中 {int(ratio * 100)}%"}
                elif msg_type == "executing":
                    node = data.get("node")
                    if data.get("prompt_id") == prompt_id:
                        if node is None:
                            # 执行完毕
                            yield {"type": "done",
                                   "outputs": self.get_output(prompt_id)}
                            return
                        yield {"type": "executing", "node": node}
                elif msg_type == "execution_error":
                    if data.get("prompt_id") == prompt_id:
                        yield {"type": "error",
                               "message": data.get("exception_message",
                                                   "unknown error")}
                        return
                elif msg_type == "execution_cached":
                    # 缓存命中, 跳过
                    pass
            # 超时后回退到轮询
            yield from self._iter_via_polling(prompt_id, deadline)
        finally:
            ws.close()

    def _iter_via_polling(self, prompt_id: str,
                         deadline: float) -> Iterator[dict]:
        """轮询模式: 周期性检查 ComfyUI 队列状态."""
        interval = 1.0
        while time.time() < deadline:
            # 检查队列状态以获取执行进度
            try:
                status = self.get_status()
                running = status.get("queue_running", [])
                if running:
                    for item in running:
                        if isinstance(item, list) and len(item) > 3:
                            node = item[3]
                            yield {"type": "executing", "node": str(node)}
                            break
            except Exception:
                pass

            history = self.get_history(prompt_id)
            if history:
                yield {"type": "done",
                       "outputs": self.get_output(prompt_id)}
                return
            yield {"type": "status", "message": "等待推理..."}
            time.sleep(interval)
        yield {"type": "error", "message": "超时"}


# 模块级单例 (惰性)
_default_client: ComfyUIClient | None = None


def get_default_client(base_url: str | None = None) -> ComfyUIClient:
    """获取/创建模块级默认客户端."""
    global _default_client
    if _default_client is None or base_url is not None:
        from config import CONFIG
        _default_client = ComfyUIClient(base_url or CONFIG.comfyui_url)
    return _default_client
