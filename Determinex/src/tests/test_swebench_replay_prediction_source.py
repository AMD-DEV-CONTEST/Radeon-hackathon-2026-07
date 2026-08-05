from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "scripts"))

from determinex_swebench_run import (  # noqa: E402
    build_replay_prediction,
    load_flywheel_exact_patches,
)


def test_dataset_gold_prediction_copies_patch_exactly() -> None:
    instance = {
        "instance_id": "repo__issue-1",
        "patch": "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-old\n+new\n",
    }

    pred = build_replay_prediction(
        instance,
        run_id="tiny-corpus-replay",
        prediction_source="dataset-gold",
    )

    assert pred == {
        "instance_id": "repo__issue-1",
        "model_patch": instance["patch"],
        "model_name_or_path": "tiny-corpus-replay",
    }


def test_flywheel_exact_prediction_uses_matching_instance_only(tmp_path: Path) -> None:
    flywheel = tmp_path / "auto_curriculum.jsonl"
    matching_patch = "diff --git a/b.py b/b.py\n--- a/b.py\n+++ b/b.py\n"
    flywheel.write_text(
        "\n".join(
            [
                json.dumps({"instance_id": "repo__other", "output": "wrong"}),
                json.dumps({"instance_id": "repo__issue-2", "output": matching_patch}),
                json.dumps({"instance_id": "repo__issue-3", "patch": "also-supported"}),
                "{not json",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    exact = load_flywheel_exact_patches(flywheel)
    pred = build_replay_prediction(
        {"instance_id": "repo__issue-2"},
        run_id="flywheel-exact",
        prediction_source="flywheel-exact",
        flywheel_exact=exact,
    )
    missing = build_replay_prediction(
        {"instance_id": "repo__missing"},
        run_id="flywheel-exact",
        prediction_source="flywheel-exact",
        flywheel_exact=exact,
    )

    assert exact["repo__issue-2"] == matching_patch
    assert exact["repo__issue-3"] == "also-supported"
    assert pred["model_patch"] == matching_patch
    assert missing["model_patch"] == ""


def test_agent_prediction_source_is_not_replay() -> None:
    assert (
        build_replay_prediction(
            {"instance_id": "repo__issue-4", "patch": "diff --git\n"},
            run_id="agent-run",
            prediction_source="agent",
        )
        is None
    )
