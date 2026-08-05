"""FrameForge 主程序入口.

启动流程:
  1. 确保输出目录存在
  2. 构建 Gradio UI
  3. 启动 Web 服务 (默认 0.0.0.0:7860)

需先启动 ComfyUI 后端 (默认 127.0.0.1:8188)。
"""
from __future__ import annotations

import sys
from pathlib import Path

# 把项目根加入 sys.path, 保证 `python app.py` 时包导入正常
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config
from ui import components, handlers


def main():
    config.ensure_dirs()
    demo = components.build_ui(handlers)
    server_port = int(_env("FRAMEFORGE_PORT", "7860"))
    server_name = _env("FRAMEFORGE_HOST", "0.0.0.0")
    print("=" * 60)
    print("  FrameForge — AI 视频关键帧微调工坊")
    print(f"  ComfyUI 后端: {config.COMFYUI_URL}")
    print(f"  输出目录:      {config.OUTPUT_DIR}")
    print(f"  Web UI:        http://{server_name}:{server_port}")
    print("=" * 60)
    try:
        demo.queue(default_concurrency_limit=1).launch(
            server_name=server_name,
            server_port=server_port,
            share=True,
            show_error=True,
            theme=components._THEME,
            css=components._CSS,
        )
    except Exception:
        demo.queue(default_concurrency_limit=1).launch(
            server_name=server_name,
            server_port=server_port,
            share=True,
            show_error=True,
            theme=components._THEME,
            css=components._CSS,
        )


def _env(key: str, default: str) -> str:
    import os
    return os.environ.get(key, default)


if __name__ == "__main__":
    main()
