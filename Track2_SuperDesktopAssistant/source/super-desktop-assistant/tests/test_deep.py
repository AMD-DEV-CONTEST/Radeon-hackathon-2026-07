"""深度回归测试 —— 覆盖 CLI 核心路径和边缘情况。"""
import os, sys, json

# 使用相对路径，适配任意机器
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_SCRIPT_DIR)  # 仓库根目录（tests 上一级）
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

from src.agents.planner import _clean_json, parse_and_validate
from src.agents.shared_memory import get_shared_memory
from src.orchestration.dag import TaskDAG, DAGNode, NodeType, NodeStatus
from src.agents.tools import execute_tool

errors = 0
passed = 0

def check(name, condition, detail=""):
    global errors, passed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        errors += 1
        print(f"  FAIL: {name} {detail}")

# === Test 6: Planner JSON cleaning robustness ===
print("=== Test 6: Planner JSON cleaning ===")
cleaning_cases = [
    # (input, should_be_valid_json_after_cleaning)
    ('{"task_id": "t", "description": "d", "nodes": []}', True, "empty nodes"),
    ('```json\n{"task_id": "t", "description": "d", "nodes": [{"id":"a","type":"llm","prompt":""}]}\n```', True, "json code block"),
    ('   {"task_id": "t", "description": "d", "nodes": [{"id":"a","type":"llm","prompt":""}]}   ', True, "whitespace"),
    ('Some text before\n{"task_id": "t", "description": "d", "nodes": [{"id":"a","type":"llm","prompt":""}]}\nSome text after', False, "extra text (should fail, expected)"),
    ('```\n{"task_id": "t", "description": "d", "nodes": [{"id":"a","type":"llm","prompt":""}]}\n```', True, "plain code block"),
]
for inp, should_parse, desc in cleaning_cases:
    cleaned = _clean_json(inp)
    try:
        json.loads(cleaned)
        parsed = True
    except:
        parsed = False
    check(f"clean '{desc}'", parsed == should_parse, f"got parsed={parsed}")

# === Test 7: DAG cycle detection ===
print("\n=== Test 7: DAG cycle detection ===")
cycle_cases = [
    ('[{"id":"a","type":"llm","prompt":"","depends_on":["b"]},{"id":"b","type":"llm","prompt":"","depends_on":["a"]}]', True, "a<->b cycle"),
    ('[{"id":"a","type":"llm","prompt":"","depends_on":["a"]}]', True, "self-loop"),
    ('[{"id":"a","type":"llm","prompt":""},{"id":"b","type":"llm","prompt":"","depends_on":["a"]},{"id":"c","type":"llm","prompt":"","depends_on":["b"]}]', False, "linear"),
    ('[{"id":"a","type":"llm","prompt":""},{"id":"b","type":"llm","prompt":""},{"id":"c","type":"llm","prompt":"","depends_on":["a","b"]}]', False, "diamond"),
]
for nodes_json, should_cycle, desc in cycle_cases:
    wrapper = '{"task_id":"t","description":"d","nodes":' + nodes_json + '}'
    result = parse_and_validate(wrapper)
    has_error = "error" in result
    check(f"cycle '{desc}'", has_error == should_cycle,
          f"error={result.get('error','')[:60]}" if has_error else "no error")

# === Test 8: DAG execution states ===
print("\n=== Test 8: DAG execution states ===")
dag = TaskDAG(
    task_id="test",
    description="test dag",
    nodes=[
        DAGNode(id="a", type=NodeType.LLM, prompt="task a"),
        DAGNode(id="b", type=NodeType.LLM, prompt="task b", depends_on=["a"]),
        DAGNode(id="c", type=NodeType.LLM, prompt="task c", depends_on=["a"]),
    ],
)
check("initial ready nodes = 1", len(dag.get_ready_nodes()) == 1)
check("first ready is 'a'", dag.get_ready_nodes()[0].id == "a")

# Mark 'a' done → b, c should be ready
dag.node_by_id("a").status = NodeStatus.DONE
ready = dag.get_ready_nodes()
check("after 'a' done, 2 ready", len(ready) == 2)
check("ready nodes are b,c", {n.id for n in ready} == {"b", "c"})

# Mark 'a' failed → b, c should NOT be ready (no deadlock yet)
dag.node_by_id("a").status = NodeStatus.FAILED
dag.node_by_id("b").status = NodeStatus.PENDING
dag.node_by_id("c").status = NodeStatus.PENDING
ready = dag.get_ready_nodes()
check("after 'a' failed, 0 ready", len(ready) == 0)
check("dag has failed", dag.any_failed())

# all_done when a=failed, b/c=pending
check("not all_done with pending", not dag.all_done())

# all skipped (a=failed means all_done=False -- correct: failure ≠ done)
dag.node_by_id("b").status = NodeStatus.SKIPPED
dag.node_by_id("c").status = NodeStatus.SKIPPED
# With a=FAILED, b/c=SKIPPED: not all_done because FAILED is a terminal state
# that the executor handles separately via any_failed()
check("all_done=False with failed node", not dag.all_done())
check("any_failed=True with failed node", dag.any_failed())

# All done (no failures)
dag.node_by_id("a").status = NodeStatus.DONE
dag.node_by_id("b").status = NodeStatus.DONE
dag.node_by_id("c").status = NodeStatus.DONE
check("all_done=True all done", dag.all_done())

# === Test 9: Shared memory slot limits ===
print("\n=== Test 9: Shared memory limits ===")
mem = get_shared_memory()
mem.clear()
# Register 5 LLM agents (max)
for i in range(5):
    slot = mem.register_agent(f"agent_{i}", "llm")
    check(f"register llm agent {i}", slot is not None)
# 6th should fail
slot6 = mem.register_agent("agent_6", "llm")
check("6th llm agent rejected", slot6 is None)
# Non-LLM agents shouldn't count
slot_img = mem.register_agent("img_1", "image_gen")
check("image_gen agent allowed", slot_img is not None)

mem.clear()

# === Test 10: _format_plan_error coverage ===
print("\n=== Test 10: Error formatting ===")
from src.main import _format_plan_error

error_cases = [
    (ValueError("供应商 xyz 不存在"), "不存在"),
    (RuntimeError("Error code: 401 - Unauthorized"), "API Key"),  # 401 → 友好的中文提示
    (RuntimeError("Insufficient quota, billing issue"), "余额"),
    (RuntimeError("Rate limit exceeded: 429"), "频率"),
    (RuntimeError("Connection refused"), "连接"),
    (RuntimeError("Model gpt-5 not found"), "模型不存在"),
    (RuntimeError("Some random error 12345"), "AI 服务调用失败"),
]
for exc, expected_keyword in error_cases:
    result = _format_plan_error(exc)
    check(f"format '{str(exc)[:40]}'", expected_keyword in result, f"got: {result[:60]}")

# === Test 11: Conversation Store lazy loading integrity ===
print("\n=== Test 11: Conversation lazy loading ===")
from src.conversations import get_store, Conversation

store = get_store()
conv = store.create("懒加载测试")

# Simulate fresh start: clear internal dict and reload index
store._convs.clear()
store._load_index()

# Verify lazy loading works
loaded = store.get(conv.id)
check("lazy loaded conv exists", loaded is not None)
check("lazy loaded messages", loaded.messages is not None)
check("messages is list", isinstance(loaded.messages, list))

# Add message to lazy-loaded conv
store.add_message(conv.id, "user", "test lazy")
store.add_message(conv.id, "assistant", "reply lazy")

# Simulate another fresh start
store._convs.clear()
store._load_index()
reloaded = store.get(conv.id)
check("reloaded has 2 messages", len(reloaded.messages) == 2)
check("reloaded last message is assistant", reloaded.messages[-1]["role"] == "assistant")
check("reloaded content intact", "reply lazy" in reloaded.messages[-1]["content"])

# Clean up
store.delete(conv.id)

# === Summary ===
print(f"\n{'='*50}")
total = passed + errors
print(f"  Results: {passed}/{total} passed, {errors} failed")
if errors == 0:
    print(f"  ALL TESTS PASSED!")
else:
    print(f"  {errors} TEST(S) FAILED!")
print(f"{'='*50}")
# BUG11 修复：加 __main__ 保护，避免 import 时 sys.exit 终止解释器
if __name__ == "__main__":
    sys.exit(errors)
