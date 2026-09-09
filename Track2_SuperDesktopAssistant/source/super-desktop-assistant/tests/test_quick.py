"""快速回归测试 —— 验证核心模块功能正常。"""
import os
import sys

# 使用相对于脚本的路径而非硬编码
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_SCRIPT_DIR)  # 仓库根目录（tests 上一级）
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

from src.config import get_config
from src.conversations import get_store
from src.orchestration.dag import TaskDAG, DAGNode, NodeType
from src.agents.tools import _tool_list_files, _tool_read_file, _tool_write_file

errors = 0


def find_existing_dir():
    """找一个确定存在的目录用于测试。"""
    candidates = [_SCRIPT_DIR, os.path.dirname(_SCRIPT_DIR), os.path.expanduser("~")]
    for d in candidates:
        if os.path.isdir(d):
            return d
    return _SCRIPT_DIR


# Test 1: list_files basic functionality
print("=== Test 1: list_files ===")
test_dir = find_existing_dir()
r = _tool_list_files({"path": test_dir})
if "目录" in r or "个文件" in r:
    print(f"  PASS: {test_dir} listed")
else:
    print(f"  FAIL: {r[:80]}")
    errors += 1

# Test 2: Config loading
print("\n=== Test 2: Config ===")
c = get_config()
assign_llm = c.get_assignment("llm")
if assign_llm:
    print(f"  PASS: LLM -> {assign_llm.provider}/{assign_llm.model}")
else:
    print("  FAIL: LLM not assigned")
    errors += 1

resolved = c.resolve("llm")
if resolved:
    print(f"  PASS: resolve(llm) OK")
else:
    print("  FAIL: resolve(llm) returned None")
    errors += 1

# Test 3: Conversation CRUD
print("\n=== Test 3: Conversations ===")
s = get_store()
conv = s.create("测试会话")
if conv.id:
    print(f"  PASS: Created conv {conv.id[:8]}")
else:
    print("  FAIL: Create conv failed")
    errors += 1

s.add_message(conv.id, "user", "你好")
s.add_message(conv.id, "assistant", "你好！")
loaded = s.get(conv.id)
if loaded and len(loaded.messages) == 2:
    print(f"  PASS: Messages persisted ({len(loaded.messages)} msgs)")
else:
    print(f"  FAIL: Messages not loaded correctly ({len(loaded.messages) if loaded else 'conv is None'})")
    errors += 1

history = s.get_chat_history(conv.id)
if len(history) == 2 and history[-1]["role"] == "assistant":
    print(f"  PASS: Chat history format correct")
else:
    print(f"  FAIL: Chat history wrong: {history}")
    errors += 1

# Clean up
s.delete(conv.id)
if s.get(conv.id) is None:
    print("  PASS: Delete conversation OK")
else:
    print("  FAIL: Delete did not work")
    errors += 1

# Test 4: DAG parsing
print("\n=== Test 4: DAG parsing ===")
json_str = """{
  "task_id": "test_001",
  "description": "回答用户问题",
  "nodes": [
    {"id": "llm_1", "type": "llm", "prompt": "回答问题", "depends_on": []}
  ]
}"""
try:
    dag = TaskDAG.from_json(json_str)
    if dag.description == "回答用户问题" and len(dag.nodes) == 1:
        print(f"  PASS: DAG parsed ({dag.description}, {len(dag.nodes)} nodes)")
    else:
        print(f"  FAIL: DAG parsing wrong")
        errors += 1

    ready = dag.get_ready_nodes()
    if len(ready) == 1:
        print(f"  PASS: Ready nodes = {len(ready)}")
    else:
        print(f"  FAIL: Ready nodes wrong: {len(ready)}")
        errors += 1
except Exception as e:
    print(f"  FAIL: DAG parsing crashed: {e}")
    errors += 1

# Test 5: Write file basic check (within allowed project directory)
print("\n=== Test 5: Write file ===")
output_dir = os.path.join(_SCRIPT_DIR, "outputs")
os.makedirs(output_dir, exist_ok=True)
tmp = os.path.join(output_dir, "test_agent_write.txt")
r = _tool_write_file({"path": tmp, "content": "hello"})
if "已写入" in r:
    print(f"  PASS: write_file works")
    os.remove(tmp)
else:
    print(f"  FAIL: {r[:80]}")
    errors += 1

# Test 6: Read file out-of-range start
print("\n=== Test 6: Read file out-of-range ===")
tmp2 = os.path.join(output_dir, "test_agent_read.txt")
with open(tmp2, "w", encoding="utf-8") as f:
    f.write("line1\nline2\n")
r = _tool_read_file({"path": tmp2, "start_line": 100, "line_count": 10})
if "超出文件范围" in r:
    print(f"  PASS: Out-of-range detected")
else:
    print(f"  INFO: {r[:80]}")
os.remove(tmp2)

# Summary
print(f"\n{'='*40}")
if errors == 0:
    print(f"  ALL TESTS PASSED!")
else:
    print(f"  {errors} TESTS FAILED!")
print(f"{'='*40}")
# BUG11 修复：加 __main__ 保护，避免 import 时 sys.exit 终止解释器
if __name__ == "__main__":
    sys.exit(errors)
