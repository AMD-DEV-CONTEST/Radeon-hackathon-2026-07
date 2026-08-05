import json

import pytest

from swe_experiments.actions import ActionParseError, parse_action_envelope, parse_json_object
from swe_experiments.structured_output import structured_output_extra_body


def test_action_parser_accepts_fenced_json_and_validates_payload():
    action = parse_action_envelope(
        "```json\n"
        '{"action":"execute","path":null,"query":null,"command":"pytest -q","patch":null,"reason":"run regression tests"}'
        "\n```"
    )
    assert action.action == "execute"
    assert action.command == "pytest -q"


def test_action_parser_rejects_unknown_fields_and_missing_payload():
    with pytest.raises(ActionParseError, match="unknown action fields"):
        parse_action_envelope({"action": "finish", "path": None, "query": None, "command": None, "patch": None, "reason": "done", "extra": 1})
    with pytest.raises(ActionParseError, match="requires command"):
        parse_action_envelope({"action": "execute", "reason": "run"})


def test_structured_output_modes_are_version_explicit():
    current = structured_output_extra_body("J3")
    assert "structured_outputs" in current
    assert current["structured_outputs"]["json"]["type"] == "object"

    legacy = structured_output_extra_body("J5")
    assert "guided_json" in legacy
    assert legacy["guided_decoding_backend"] == "lm-format-enforcer"

    assert structured_output_extra_body("J1") == {}


def test_action_round_trip_is_json_serializable():
    action = parse_action_envelope(
        {"action": "edit", "path": None, "query": None, "command": None, "patch": "diff --git a/a.py b/a.py", "reason": "fix bug"}
    )
    assert json.loads(json.dumps(action.to_dict()))["action"] == "edit"


def test_generic_json_parser_supports_verifier_reports():
    report = parse_json_object('```json\n{"verdict":"accept","confidence":0.8,"summary":"tests pass"}\n```')
    assert report["verdict"] == "accept"


def test_replace_action_requires_exact_payload_and_round_trips():
    action = parse_action_envelope(
        {
            "action": "replace",
            "path": "pkg/core.py",
            "query": None,
            "command": None,
            "patch": None,
            "old_text": "return old",
            "new_text": "return new",
            "reason": "fix the branch",
        }
    )
    assert action.action == "replace"
    assert action.to_dict()["old_text"] == "return old"
    with pytest.raises(ActionParseError, match="old_text"):
        parse_action_envelope(
            {
                "action": "replace",
                "path": "pkg/core.py",
                "query": None,
                "command": None,
                "patch": None,
                "old_text": "",
                "new_text": "return new",
                "reason": "invalid",
            }
        )
