"""E2E Test 1: Visual novel game generation."""
import os, sys, asyncio, time

# 相对路径，适配任意机器
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_SCRIPT_DIR)  # 仓库根目录（tests 上一级）
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from src.main import get_engine
from src.config import get_config


def sp(msg=""):
    """Safe print via UTF-8 binary stdout."""
    sys.stdout.buffer.write((str(msg) + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()


# 注意：此测试需要 ComfyUI 在本地运行，如果未配置则会使用 API 生图
TEST_PROMPT = """帮我做一个游戏，视觉小说，html驱动的，关于蔚蓝档案星野，游戏名叫星野的一天，其他细节自行补充，要有插画"""


async def main():
    sp("=" * 60)
    sp("  Test 1: Visual Novel Game")
    sp(f"  Prompt: {TEST_PROMPT[:80]}...")
    sp("=" * 60)

    engine = get_engine()
    t0 = time.time()

    try:
        result = await engine.process(
            user_message=TEST_PROMPT,
            conversation_history=[],
        )
    except Exception as e:
        elapsed = time.time() - t0
        sp(f"\n[ERROR] Exception ({elapsed:.1f}s): {e}")
        import traceback
        traceback.print_exc()
        return

    elapsed = time.time() - t0

    dag = result.get("dag", {})
    sp(f"\n[DAG] {dag.get('description', 'N/A')}")
    sp(f"  Nodes: {len(dag.get('nodes', []))}")
    for n in dag.get("nodes", []):
        sp(f"    [{n['id']}] {n['type']}: {n.get('prompt','')[:80]}...")

    sp(f"\n[Results] ({len(result.get('results',{}))}):")
    for nid, val in result.get("results", {}).items():
        v = str(val)[:200].replace("\n", "\\n")
        sp(f"    [{nid}] OK: {v}")

    if result.get("errors"):
        sp(f"\n[Errors] ({len(result['errors'])}):")
        for nid, err in result["errors"].items():
            sp(f"    [{nid}] {err[:300]}")

    sp(f"\n[Time] Total: {elapsed:.1f}s | DAG: {result.get('total_time_ms',0)/1000:.1f}s")
    sp(f"  Outputs: {result.get('outputs',{})}")

    # Summary
    checks = []
    if dag.get("nodes"):
        checks.append(f"+ DAG generated {len(dag['nodes'])} nodes")
    else:
        checks.append("- DAG has no nodes")
    if result.get("results"):
        checks.append(f"+ {len(result['results'])} nodes succeeded")
    else:
        checks.append("~ No results")
    if result.get("errors"):
        checks.append(f"! {len(result['errors'])} nodes failed")
    else:
        checks.append("+ Zero failures")

    sp("\n" + "\n".join(checks))


if __name__ == "__main__":
    asyncio.run(main())
