"""Regression tests: the approval gate. A dataset build must not start
in the same user turn that drafted the spec — the 4B agent blew through
the prompt-level gate twice on Aug 5 and ran a full unapproved build."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from foundry.tools import ToolBox

SPEC = {
    "name": "gate-test",
    "description": "test task",
    "example_noun": "claim",
    "input_field": "claim",
    "input_length": [10, 200],
    "seed_docs": ["seeds/expense_policy.md"],
    "output_schema": {"kind": {"type": "enum", "values": ["a", "b"]}},
    "balance_field": "kind",
    "datagen_guidance": "",
    "facets": {},
}


def make_toolbox(tmp_path):
    return ToolBox({"run": {"out_root": str(tmp_path)},
                    "datagen": {"n_train": 4, "n_holdout": 2}}, "cfg.toml",
                   teacher_ctl=None)


def test_generate_blocked_in_spec_turn(tmp_path):
    tb = make_toolbox(tmp_path)
    tb.user_turns = 1  # agent loop increments per user turn
    tb.dispatch("save_task_spec", {"spec": SPEC})
    result = tb.dispatch("generate_dataset", {})
    assert "approval gate" in result["error"]


def test_generate_allowed_after_user_replies(tmp_path):
    tb = make_toolbox(tmp_path)
    tb.user_turns = 1
    tb.dispatch("save_task_spec", {"spec": SPEC})
    tb.user_turns = 2  # the user replied (approval turn)
    result = tb.dispatch("generate_dataset", {})
    # The gate must not fire; the call proceeds into real datagen and
    # fails on the absent teacher instead.
    assert "approval gate" not in result.get("error", "")


def test_resumed_build_not_gated(tmp_path):
    tb = make_toolbox(tmp_path)
    tb.user_turns = 3  # spec loaded via resume_build, never saved this session
    from foundry.spec import TaskSpec
    tb.spec = TaskSpec(SPEC)
    tb.run_dir = tmp_path
    result = tb.dispatch("generate_dataset", {})
    assert "approval gate" not in result.get("error", "")
