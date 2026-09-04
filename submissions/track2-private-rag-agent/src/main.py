# -*- coding: utf-8 -*-
"""私有 RAG Agent —— 命令行入口

用法：
  python main.py ingest docs/           # 导入文档
  python main.py ingest docs/a.pdf      # 导入单个文档
  python main.py ask "问题"             # 提问
  python main.py ui                     # 启动网页版
  python main.py bench                  # AMD GPU 基准测试
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent.agent import Agent


def main():
    args = sys.argv[1:]
    agent = Agent()

    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return
    if args[0] == "ingest":
        n = agent.ingest_dir(args[1]) if os.path.isdir(args[1]) else agent.ingest(args[1])
        print(f"导入完成，新增 {n} 个片段")
    elif args[0] == "ask":
        q = " ".join(args[1:])
        print(agent.ask(q))
        if agent.verification:
            print(f"\n[引用校验] grounding={agent.verification['grounding']}")
    elif args[0] == "ui":
        from ui.server import launch
        launch(agent)
    elif args[0] == "bench":
        from benchmarks.bench_amd import main as bench
        bench()
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
