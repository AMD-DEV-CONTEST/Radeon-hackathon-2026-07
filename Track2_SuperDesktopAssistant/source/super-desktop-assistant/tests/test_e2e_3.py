"""E2E Test 3: Simple Tetris game."""
import os, sys, asyncio, time

# 使用相对路径，适配任意机器
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_SCRIPT_DIR)  # 仓库根目录（tests 上一级）
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from src.main import get_engine


def sp(msg=""):
    sys.stdout.buffer.write((str(msg) + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()


TEST_PROMPT = "做一个简易俄罗斯方块"


async def main():
    sp("=" * 60)
    sp("  Test 3: Simple Tetris")
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
