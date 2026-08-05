import json
import subprocess

from track2_swebench_harness import (
    ALLOWED_HARNESSES,
    FORBIDDEN_AGENT_FIELDS,
    agent_task,
    compact_instance_report,
    localization_diagnostics,
    prepare_workspace,
    write_predictions,
)


def test_official_runner_exposes_clean_json_retry_variant():
    assert "mini-json-retry" in ALLOWED_HARNESSES
    assert "qwen-code" in ALLOWED_HARNESSES


def test_agent_task_drops_every_evaluator_only_field():
    record = {
        "repo": "owner/repo",
        "instance_id": "owner__repo-1",
        "base_commit": "abc",
        "problem_statement": "Fix the parser.",
        "patch": "GOLD",
        "test_patch": "HIDDEN TEST",
        "FAIL_TO_PASS": ["secret_test"],
        "PASS_TO_PASS": ["regression_test"],
        "hints_text": "gold hint",
    }

    public = agent_task(record)

    assert FORBIDDEN_AGENT_FIELDS.isdisjoint(public)
    serialized = json.dumps(public)
    assert "GOLD" not in serialized
    assert "HIDDEN TEST" not in serialized
    assert "secret_test" not in serialized
    assert public["problem_statement"] in public["prompt"]


def test_predictions_contain_only_frozen_candidate_patches(tmp_path):
    patch = tmp_path / "candidate.patch"
    patch.write_text("diff --git a/a.py b/a.py\n")
    results = [
        {
            "harness": "mini-original",
            "repeat": 1,
            "task_id": "owner__repo-1",
            "patch_path": str(patch),
        }
    ]

    paths = write_predictions(tmp_path, results, ["mini-original"], 1)
    rows = json.loads(paths[("mini-original", 1)].read_text())

    assert rows == [
        {
            "instance_id": "owner__repo-1",
            "model_patch": "diff --git a/a.py b/a.py\n",
            "model_name_or_path": "mini-original",
        }
    ]


def test_prepare_workspace_materializes_a_clean_target_commit(tmp_path):
    cache = tmp_path / "cache" / "owner__repo"
    cache.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=cache, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=cache, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=cache, check=True)
    (cache / "target.py").write_text("VALUE = 1\n")
    subprocess.run(["git", "add", "target.py"], cwd=cache, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=cache, check=True)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=cache, check=True, text=True, capture_output=True
    ).stdout.strip()

    workspace = tmp_path / "workspace"
    prepare_workspace(
        {"repo": "owner/repo", "base_commit": commit},
        workspace,
        tmp_path / "cache",
    )

    assert (workspace / "target.py").read_text() == "VALUE = 1\n"
    status = subprocess.run(
        ["git", "status", "--short"], cwd=workspace, check=True, text=True, capture_output=True
    )
    assert status.stdout == ""


def test_localization_metrics_do_not_return_gold_filenames():
    gold = "diff --git a/src/parser.py b/src/parser.py\n"
    trajectory = [
        {"role": "user", "content": "Issue mentions src/parser.py"},
        {"role": "assistant", "content": "Inspect src/parser.py"},
    ]

    result = localization_diagnostics(trajectory, gold)

    assert result["gold_file_recall"] == 1.0
    assert result["first_gold_reference_event"] == 1
    assert "parser.py" not in json.dumps(result)


def test_compact_official_report_drops_hidden_test_ids(tmp_path):
    path = tmp_path / "report.json"
    path.write_text(
        json.dumps(
            {
                "owner__repo-1": {
                    "patch_exists": True,
                    "patch_successfully_applied": True,
                    "resolved": False,
                    "tests_status": {
                        "FAIL_TO_PASS": {"success": ["hidden_a"], "failure": ["hidden_b"]},
                        "PASS_TO_PASS": {"success": ["regression_a"], "failure": []},
                    },
                }
            }
        )
    )

    result = compact_instance_report(path, "owner__repo-1")

    assert result["resolution_status"] == "PARTIAL"
    assert result["fail_to_pass_success"] == 1
    assert result["fail_to_pass_total"] == 2
    assert "hidden_a" not in json.dumps(result)
