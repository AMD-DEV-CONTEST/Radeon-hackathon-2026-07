import logging
import signal
import sys
import threading

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

from src.config import LLM_BASE_URL, LLM_API_KEY, LLM_MODEL, DB_PATH
from src.llm_client import LLMClient
from src.db import Store
from src.orchestrator import Orchestrator
from src.tools import set_store

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")


def run_web(store):
    """Run FastAPI web console in child thread"""
    import uvicorn
    from src.web.app import create_app
    app = create_app(store)
    # 绑定 127.0.0.1: rc-tunnel 要求 + 安全 (不裸暴露)
    # 生产模式: 前端静态文件由 FastAPI 同端口托管
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info",
                ws="wsproto")


def main():
    logger.info(f"LLM: {LLM_BASE_URL} | Model: {LLM_MODEL}")
    logger.info(f"DB: {DB_PATH}")

    llm = LLMClient(LLM_BASE_URL, LLM_API_KEY, LLM_MODEL)
    store = Store(DB_PATH)
    set_store(store)

    # Start web console (background thread)
    web_thread = threading.Thread(
        target=run_web, args=(store,), daemon=True)
    web_thread.start()
    logger.info("Web console: http://localhost:8000")

    # Main thread: Orchestrator inspection loop
    orch = Orchestrator(llm, store, inspect_interval=15)

    # Graceful shutdown
    stop_requested = [False]

    def _shutdown(signum, frame):
        if not stop_requested[0]:
            stop_requested[0] = True
            logger.info(f"Signal {signum} received, shutting down...")
            orch.stop()
        else:
            logger.info("Force exit")
            if orch.master_sid:
                store.finish_session(orch.master_sid, summary="interrupted", status="done")
            raise SystemExit(1)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    orch.run()

    # Print session tree on exit
    logger.info("Session tree:")
    with store.lock:
        rows = store.conn.execute(
            "SELECT id, parent_id, type, status FROM sessions ORDER BY started_at"
        ).fetchall()
    for row in rows:
        prefix = "  └─" if row[1] else "  ├─"
        print(f"{prefix} [{row[2]}] {row[0]} status={row[3]} parent={row[1] or '-'}")


if __name__ == "__main__":
    main()
