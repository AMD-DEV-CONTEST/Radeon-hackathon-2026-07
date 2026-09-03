import importlib.util
from pathlib import Path


PATH = Path(__file__).parents[1] / "run_vllm_jsonl.py"
SPEC = importlib.util.spec_from_file_location("run_vllm_jsonl", PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(module)


def test_messages_remove_reference_answer():
    row = {"messages": [
        {"role": "system", "content": "bounded"},
        {"role": "user", "content": "question"},
        {"role": "assistant", "content": "reference"},
    ]}
    assert module.messages_for(row) == row["messages"][:2]


def test_case_id_prefers_explicit_and_percentile_is_nearest_rank():
    assert module.case_id({"caseId": "x", "metadata": {"id": "y"}}, 1) == "x"
    assert module.percentile([1, 2, 3, 4], .95) == 4


def test_structure_prompt_matches_trained_runtime_protocol():
    messages = module.messages_for({
        "suite": "structure_safety",
        "input": {"target": "comparison", "question": "比较两手。"},
    })

    assert messages[0] == {
        "role": "system", "content": "你是弈鉴工具规划器，只输出严格JSON。",
    }
    assert messages[1]["role"] == "user"
    assert "schemaVersion固定agent-plan-v1" in messages[1]["content"]
    assert "服务端已确定问题目标：comparison" in messages[1]["content"]
    assert "只能写comparison" in messages[1]["content"]
    assert "只能选一至四项" in messages[1]["content"]
    assert '"questionTarget":"comparison"' in messages[1]["content"]
    assert messages[1]["content"].endswith("用户问题：比较两手。")
