"""CPU-only contract tests for the single-scene multi-robot evaluator."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "eval_shared_physics_3v3", ROOT / "scripts/eval_shared_physics_3v3.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_identity_map_is_six_fixed_roles_and_single_authority():
    identities = MODULE.identity_records(
        ROOT / "models/chase_v8_policy.onnx",
        ROOT / "models/pretrained/t1_walk.pt",
    )
    normalized = MODULE.validate_identities(identities)
    assert tuple(normalized) == MODULE.ROBOT_IDS
    assert {(item["team"], item["role"]) for item in normalized.values()} == {
        (team, role) for team in ("A", "B")
        for role in ("attacker", "defender", "keeper")
    }
    assert [name for name, item in normalized.items() if item["ball_authority"]] == ["A_attacker"]
    assert {item["controller"] for item in normalized.values() if item["team"] == "A"} == {"ONNX"}
    assert {item["controller"] for item in normalized.values() if item["team"] == "B"} == {"Rule"}


def test_identity_validation_rejects_duplicate_or_wrong_authority():
    identities = MODULE.identity_records(
        ROOT / "models/chase_v8_policy.onnx",
        ROOT / "models/pretrained/t1_walk.pt",
    )
    identities["B_keeper"]["ball_authority"] = True
    with pytest.raises(ValueError, match="authority"):
        MODULE.validate_identities(identities)


def test_parser_defaults_are_canonical_and_headless():
    args = MODULE.build_parser().parse_args([])
    assert args.steps == 100
    assert args.seed == 42
    assert args.backend == "gpu"
    assert args.viewer is False
    assert args.model == ROOT / "models/chase_v8_policy.onnx"
    assert args.walk_model == ROOT / "models/pretrained/t1_walk.pt"


def test_robot_rows_preserve_identity_and_emit_fall_state():
    identities = MODULE.identity_records(
        ROOT / "models/chase_v8_policy.onnx",
        ROOT / "models/pretrained/t1_walk.pt",
    )
    rows = MODULE._robot_rows(
        identities,
        [[0, 0, 0.1], [0, 0, 0.8], [0, 0, 0.8], [0, 0, 0.8], [0, 0, 0.8], [0, 0, 0.8]],
        [[1, 0, 0, 0]] * 6,
        [[0, 0, 0]] * 6,
        [[0, 0, 0]] * 6,
        fall_height=0.4,
        term_pitch=0.5,
        term_roll=0.5,
    )
    assert rows["A_attacker"]["fallen"] is True
    assert rows["A_attacker"]["model_sha"] == identities["A_attacker"]["model_sha"]
    assert rows["B_keeper"]["role"] == "keeper"

