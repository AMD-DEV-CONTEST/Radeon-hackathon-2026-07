"""SparkFencer 教练 Agent 对话入口(完全本地)。

用法:
  python agent_chat.py --ask "对比两场比赛双方的打法"     # 单问
  python agent_chat.py                                    # 交互多轮
环境变量: VLM_BASE_URL(默认 http://127.0.0.1:11434/v1)、AGENT_MODEL(默认 qwen3:32b)
"""

import argparse

from fencing_analysis.agents.orchestrator import CoachChat


def main():
    parser = argparse.ArgumentParser(description="SparkFencer 教练 Agent")
    parser.add_argument("--ask", default=None, help="单个问题(非交互)")
    parser.add_argument("--model", default=None, help="本地模型名(默认 qwen3:32b)")
    args = parser.parse_args()

    chat = CoachChat(model=args.model)

    if args.ask:
        print("\n=== 回答 ===\n" + chat.ask(args.ask))
        return

    print("SparkFencer 教练 Agent(输入 exit 退出)")
    while True:
        try:
            question = input("\n你: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not question or question.lower() in ("exit", "quit"):
            break
        print("\n教练: " + chat.ask(question))


if __name__ == "__main__":
    main()
