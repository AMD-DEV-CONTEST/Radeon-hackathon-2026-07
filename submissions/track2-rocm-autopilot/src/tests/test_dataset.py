from autopilot.dataset import load_prompts


def test_load_prompts_returns_nonempty_strings():
    prompts = load_prompts("datasets/confidential_drafting.jsonl")
    assert len(prompts) >= 30
    assert all(isinstance(p, str) and len(p) > 200 for p in prompts)
