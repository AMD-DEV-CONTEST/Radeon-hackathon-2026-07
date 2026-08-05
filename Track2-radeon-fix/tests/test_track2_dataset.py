from track2_dataset import _prompt, _public_task


def test_public_task_excludes_gold_fields_from_export():
    row = {
        "instance_id": "demo__repo-1",
        "repo": "demo/repo",
        "base_commit": "abc123",
        "problem_statement": "Fix the parser",
        "patch": "SECRET GOLD PATCH",
        "test_patch": "SECRET TEST PATCH",
        "FAIL_TO_PASS": ["test_secret"],
    }
    exported = _public_task(row)
    assert exported["instance_id"] == "demo__repo-1"
    assert "patch" not in exported
    assert "test_patch" not in exported
    assert "FAIL_TO_PASS" not in exported


def test_prompt_contains_issue_and_checkout_without_gold_patch():
    prompt = _prompt(
        {
            "instance_id": "demo__repo-1",
            "repo": "demo/repo",
            "base_commit": "abc123",
            "problem_statement": "Fix the parser",
        }
    )
    assert "demo__repo-1" in prompt
    assert "abc123" in prompt
    assert "Fix the parser" in prompt
    assert "GOLD PATCH" not in prompt
