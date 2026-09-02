from __future__ import annotations

import argparse

from app.ui.workbench import build_workbench


def main() -> None:
    parser = argparse.ArgumentParser(description="Start the ProjectPack Gradio workbench")
    parser.add_argument("--api-url", default="http://127.0.0.1:9000")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7860)
    args = parser.parse_args()
    build_workbench(args.api_url).launch(server_name=args.host, server_port=args.port)


if __name__ == "__main__":
    main()
