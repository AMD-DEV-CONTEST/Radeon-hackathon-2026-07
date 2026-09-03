"""Local conversational control panel for AutoFlow."""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from autoflow.assistant import AssistantService
from autoflow.agent_runtime import AgentRuntime
from autoflow.desktop_control import DesktopRecorder, DesktopReplayer, DesktopTaskStore, ReplayStopped

AGENT_SESSION_ROUTE = re.compile(r"^/api/agent/sessions/(agent_[a-f0-9]{12})$")


class AutomationController:
    """Legacy recorder controller kept as an optional fallback and API compatibility layer."""

    def __init__(self, store=None, recorder_factory=DesktopRecorder, replayer_factory=DesktopReplayer) -> None:
        self.store = store or DesktopTaskStore()
        self.recorder_factory = recorder_factory
        self.replayer_factory = replayer_factory
        self._lock = threading.RLock()
        self._mode = "idle"
        self._message = "准备好了。"
        self._recorder = None
        self._replayer = None
        self._recording_name = ""
        self._last_task_id = None

    def state(self) -> dict[str, Any]:
        with self._lock:
            return {"mode": self._mode, "message": self._message, "recording_name": self._recording_name, "last_task_id": self._last_task_id, "tasks": self.store.list(), "stop_hotkey": "Ctrl+Shift+F12"}

    def start_recording(self, name: str) -> dict[str, Any]:
        if not name.strip():
            raise ValueError("请先输入名称。")
        with self._lock:
            self._require_idle()
            recorder = self.recorder_factory()
            recorder.start()
            self._recorder = recorder
            self._recording_name = name.strip()
            self._mode = "recording"
        threading.Thread(target=self._watch_recording, args=(recorder,), daemon=True).start()
        return self.state()

    def stop_recording(self) -> dict[str, Any]:
        with self._lock:
            if self._mode != "recording" or self._recorder is None:
                raise ValueError("当前没有正在录制的操作。")
            recorder = self._recorder
        recorder.stop()
        self._finish_recording(recorder)
        return self.state()

    def _watch_recording(self, recorder) -> None:
        recorder.wait_stopped()
        self._finish_recording(recorder)

    def _finish_recording(self, recorder) -> None:
        with self._lock:
            if recorder is not self._recorder:
                return
            recording = recorder.stop()
            name = self._recording_name
            self._recorder = None
            self._recording_name = ""
            if recording.get("events"):
                task = self.store.save(recording, name)
                self._last_task_id = task["id"]
                self._message = f"已学会：{name}"
            else:
                self._message = "没有录到操作。"
            self._mode = "idle"

    def run_task(self, task_id: str, speed: float = 1.0) -> dict[str, Any]:
        with self._lock:
            self._require_idle()
            task = self.store.get(task_id)
            replayer = self.replayer_factory()
            self._replayer = replayer
            self._mode = "running"
        threading.Thread(target=self._run_worker, args=(replayer, task, speed), daemon=True).start()
        return self.state()

    def _run_worker(self, replayer, task, speed: float) -> None:
        try:
            replayer.run(task, speed=speed, progress=lambda message: setattr(self, "_message", message))
            self.store.mark_run(task["id"])
            message = f"执行完成：{task['name']}"
        except ReplayStopped as exc:
            message = str(exc)
        except Exception as exc:
            message = f"执行失败：{exc}"
        with self._lock:
            self._replayer = None
            self._mode = "idle"
            self._message = message

    def emergency_stop(self) -> dict[str, Any]:
        with self._lock:
            recorder, replayer = self._recorder, self._replayer
        if recorder is not None:
            recorder.stop()
            self._finish_recording(recorder)
        if replayer is not None:
            replayer.stop()
        return self.state()

    def _require_idle(self) -> None:
        if self._mode != "idle":
            raise ValueError("请先结束当前操作。")


class AutoFlowRequestHandler(BaseHTTPRequestHandler):
    server: "AutoFlowHTTPServer"

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path.startswith("/api/") and not self._same_origin():
            self._json({"error": "不允许从外部页面访问本地接口。"}, HTTPStatus.FORBIDDEN)
            return
        if path == "/api/settings":
            self._json(self.server.assistant.settings())
            return
        match = AGENT_SESSION_ROUTE.fullmatch(path)
        if match:
            try:
                self._json(self.server.agent.get(match.group(1)))
            except ValueError as exc:
                self._json({"error": str(exc)}, HTTPStatus.NOT_FOUND)
            return
        assets = {
            "/": ("index.html", "text/html; charset=utf-8"),
            "/index.html": ("index.html", "text/html; charset=utf-8"),
            "/agent.html": ("agent.html", "text/html; charset=utf-8"),
            "/models.html": ("models.html", "text/html; charset=utf-8"),
            "/styles.css": ("styles.css", "text/css; charset=utf-8"),
            "/pages.css": ("pages.css", "text/css; charset=utf-8"),
            "/agent.css": ("agent.css", "text/css; charset=utf-8"),
            "/model-center.css": ("model-center.css", "text/css; charset=utf-8"),
            "/home.js": ("home.js", "text/javascript; charset=utf-8"),
            "/agent.js": ("agent.js", "text/javascript; charset=utf-8"),
            "/models.js": ("models.js", "text/javascript; charset=utf-8"),
        }
        asset = assets.get(path)
        if asset is None:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        filename, content_type = asset
        content = (self.server.webui_root / filename).read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self) -> None:  # noqa: N802
        if not self._same_origin():
            self._json({"error": "不允许从外部页面访问本地接口。"}, HTTPStatus.FORBIDDEN)
            return
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().casefold()
        if content_type != "application/json":
            self._json({"error": "本地接口只接受 JSON 请求。"}, HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
            return
        try:
            body = self._body()
            path = urlparse(self.path).path
            if path == "/api/assistant/command":
                result = self.server.assistant.submit(str(body.get("command", "")))
            elif path == "/api/agent/start":
                result = self.server.agent.start(str(body.get("goal", "")), int(body.get("max_steps", 20)), bool(body.get("autonomous", True)), bool(body.get("silent", True)))
            elif path == "/api/agent/confirm":
                result = self.server.agent.confirm(str(body.get("session_id", "")), bool(body.get("approved", False)))
            elif path == "/api/agent/stop":
                result = self.server.agent.stop(str(body.get("session_id", "")))
            elif path == "/api/agent/input":
                result = self.server.agent.provide_input(str(body.get("session_id", "")), str(body.get("answer", "")))
            elif path == "/api/assistant/execute":
                result = self.server.assistant.execute(str(body.get("plan_id", "")))
            elif path == "/api/settings/deepseek":
                result = self.server.assistant.configure_deepseek(str(body.get("api_key", "")))
            elif path == "/api/settings/provider":
                result = self.server.assistant.configure_provider(body)
            elif path == "/api/settings/model":
                result = self.server.assistant.select_model(str(body.get("model", "")))
            elif path == "/api/settings/deepseek/disconnect":
                result = self.server.assistant.disconnect_deepseek()
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self._json(result)
        except (ValueError, RuntimeError, OSError) as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def _same_origin(self) -> bool:
        """Only accept local requests from our own pages, not cross-origin web attacks."""
        origin = self.headers.get("Origin", "")
        port = self.server.server_address[1]
        allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if not origin:
            return self.headers.get("Host", "").strip().casefold() in allowed_hosts
        try:
            parsed = urlparse(origin)
            return parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"} and parsed.port == port
        except ValueError:
            return False

    def _body(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("Content-Length 不正确。") from exc
        if length < 0 or length > 65536:
            raise ValueError("指令太长了。")
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("请求格式不正确。") from exc
        return value if isinstance(value, dict) else {}

    def _json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, _format: str, *_args: Any) -> None:
        return


class AutoFlowHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], assistant: AssistantService, webui_root: Path, agent: AgentRuntime | None = None) -> None:
        self.assistant = assistant
        self.agent = agent or AgentRuntime(assistant.interpreter)
        self.webui_root = webui_root
        super().__init__(address, AutoFlowRequestHandler)


def create_server(port: int = 8765, assistant: AssistantService | None = None) -> AutoFlowHTTPServer:
    root = Path(__file__).with_name("webui")
    service = assistant or AssistantService()
    try:
        return AutoFlowHTTPServer(("127.0.0.1", port), service, root)
    except OSError:
        return AutoFlowHTTPServer(("127.0.0.1", 0), service, root)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    server = create_server(int(os.environ.get("AUTOFLOW_PORT", "8765")))
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"AutoFlow 已启动：{url}")
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
