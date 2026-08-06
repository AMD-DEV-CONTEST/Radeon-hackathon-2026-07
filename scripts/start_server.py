"""Start the Insurance RAG Agent Web service.

Usage::

    python scripts/start_server.py

After starting, visit http://localhost:8080 to view the Web interface.

Bind to 127.0.0.1 for compatibility with the competition rc-tunnel requirements:
  - rc-tunnel only supports HTTP/WebSocket services listening on 127.0.0.1
  - To access via SSH tunnel, you can add the --host 0.0.0.0 parameter to override
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure the project root is on the Python path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import uvicorn

from src.api.server import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Start the Insurance RAG Agent Web service")
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind address (default 127.0.0.1, compatible with rc-tunnel)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Listen port (default 8080)",
    )
    args = parser.parse_args()

    app = create_app()
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
