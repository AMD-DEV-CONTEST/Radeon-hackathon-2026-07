"""
模拟用户输入的一次端到端测试：让助手制作一个 HTML 国际象棋小游戏。

用法：python tests/run_chess_test.py
输出：打印 status / plan_summary / DAG 节点 / 结果 / 错误 / 产出文件。
"""
import asyncio
import json
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_SCRIPT_DIR)  # 仓库根目录（tests 上一级）
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

from src.main import get_engine


async def main():
    user_input = (
        "帮我做一个 html 国际象棋小游戏，人机对战（玩家执白走白方，AI 执黑），"
        "要有棋盘绘制、棋子走法规则、简单 AI 和吃子，保存成 html 文件"
    )
    print(f"用户输入: {user_input}\n")
    engine = get_engine()
    result = await engine.process(
        user_message=user_input,
        conversation_history=[],
    )

    print("=" * 60)
    print(f"status       : {result.get('status')}")
    print(f"plan_summary : {result.get('plan_summary')}")
    if result.get("error"):
        print(f"error        : {result.get('error')}")

    dag = result.get("dag") or {}
    nodes = dag.get("nodes", [])
    print(f"DAG 节点数   : {len(nodes)}")
    for n in nodes:
        print(f"  - {n.get('id')} [{n.get('type')}] status={n.get('status')} "
              f"reset={n.get('reset_context')}")

    print("-" * 60)
    results = result.get("results", {})
    for nid, val in results.items():
        short = str(val)[:300]
        print(f"结果 [{nid}]: {short}")
        if short != str(val):
            print(f"        ... (总长 {len(str(val))})")

    errs = result.get("errors", {})
    for nid, e in errs.items():
        print(f"错误 [{nid}]: {e}")

    skipped = result.get("skipped", {})
    for nid in skipped:
        print(f"跳过 [{nid}]: skipped")

    outputs = result.get("outputs", {})
    print("-" * 60)
    print("产出文件:")
    print(json.dumps(outputs, ensure_ascii=False, indent=2))
    print(f"耗时: {result.get('total_time_ms', 0):.0f} ms")

    return result


if __name__ == "__main__":
    r = asyncio.run(main())
    ok = r.get("status") in ("ok", "partial")
    sys.exit(0 if ok else 1)
