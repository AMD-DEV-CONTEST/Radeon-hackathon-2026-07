"""Content Studio 桌面入口：后台起 FastAPI 服务 + PyWebView 原生窗口，关窗即退。"""
from __future__ import annotations

import threading
import time
import urllib.request

import uvicorn
import webview

from content_studio.web.app import app

HOST = "127.0.0.1"
PORT = 8765  # 用不常用端口，避免和 8000 冲突


def _wait_ready(timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://{HOST}:{PORT}/", timeout=1)
            return True
        except Exception:
            time.sleep(0.2)
    return False


def main() -> None:
    config = uvicorn.Config(app, host=HOST, port=PORT, log_level="warning")
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()

    if not _wait_ready():
        raise RuntimeError("后端服务启动失败")

    webview.create_window("Content Studio", f"http://{HOST}:{PORT}/demo", width=1100, height=780)
    webview.start()
    # 关窗后 start() 返回 -> main 结束 -> 进程退出，daemon 服务线程随之结束（关窗即退）


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        from pathlib import Path
        log = Path.home() / ".content_studio" / "desktop_error.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(traceback.format_exc(), encoding="utf-8")
        raise
