"""E2E Test 2: Analyze a codebase (generic, works without full-combo project)."""
import os, sys, asyncio, time

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_SCRIPT_DIR)  # 仓库根目录（tests 上一级）
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from src.main import get_engine


def sp(msg=""):
    sys.stdout.buffer.write((str(msg) + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()


# 分析本项目自身代码——不需要外部依赖
TEST_PROMPT = f"""分析 {_SCRIPT_DIR}\\src 目录下的核心代码架构，给出以下方面的建议：
1. 架构设计是否合理
2. 有哪些潜在的性能问题
3. 代码质量和可维护性如何
请读取关键文件进行分析，重点关注 src/main.py, src/config.py, src/orchestration/ 和 src/agents/ 目录。"""


async def main():
    sp("=" * 60)
    sp("  Test 2: Code Review")
    sp("=" * 60)

    engine = get_engine()
    t0 = time.time()

    try:
        result = await engine.process(user_message=TEST_PROMPT, conversation_history=[])
    except Exception as e:
        sp(f"\n[ERROR] ({time.time()-t0:.1f}s): {e}")
        import traceback; traceback.print_exc()
        return

    elapsed = time.time() - t0
    dag = result.get("dag", {})

    sp(f"\n[DAG] {dag.get('description','?')} | {len(dag.get('nodes',[]))} nodes")
    sp(f"[Results] {len(result.get('results',{}))} ok, {len(result.get('errors',{}))} err")
    sp(f"[Time] {elapsed:.1f}s | DAG: {result.get('total_time_ms',0)/1000:.1f}s")

    for nid, val in result.get("results", {}).items():
        v = str(val)[:1500].replace("\n", "\\n")
        sp(f"\n[{nid}]: {v}")

    if result.get("errors"):
        sp(f"\n[Errors]:")
        for nid, err in result["errors"].items():
            sp(f"  [{nid}] {err[:500]}")

    checks = (f"{len(dag.get('nodes',[]))} nodes, "
              f"{len(result.get('results',{}))} ok, "
              f"{len(result.get('errors',{}))} err")
    sp(f"\n{checks}")


if __name__ == "__main__":
    asyncio.run(main())
