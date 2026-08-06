import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
LOG = ROOT / "acceptance/remote/match_20260804_115349.json"
EXPECTED_SHA = "9a494e2f00cc751df2090339c2f7b2e3e99c75333fd6a3f2f4e8d6ef598ac2be"
SPEC = importlib.util.spec_from_file_location("match_analysis", ROOT / "scripts/analyze_match_log.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _with_authority(data, client="client_0"):
    for key, identity in data["identities"].items():
        identity["ball_authority"] = key == client
    return data


def test_final_identities_and_explicit_events():
    data, digest = MODULE.load_and_validate(LOG)
    result = MODULE.analyze(data, str(LOG.relative_to(ROOT)), digest)
    assert digest == EXPECTED_SHA
    assert result["clients"]["client_0"]["team"] == "A"
    assert result["clients"]["client_0"]["role"] == "attacker"
    assert result["clients"]["client_1"]["team"] == "A"
    assert result["clients"]["client_5"]["controller"] == "Rule"
    assert result["validation"]["observed_steps"] == 20
    assert result["match_events"]["fall_event_count"] == 1
    assert result["match_events"]["score_event_count"] == 0
    assert result["match_events"]["goal_boundary_inference_used"] is False
    assert result["match_events"]["ball_authority_client"] == "client_0"


def test_rising_edges_not_true_frame_count():
    log = [{"events": {"client_0": {"fallen": v}}} for v in (False, True, True, False, True)]
    assert MODULE._rising_edges(log, "client_0", "fallen") == [1, 4]


def test_only_ball_authority_score_edges_create_goal():
    data = _with_authority(json.loads(LOG.read_text()), "client_0")
    data["log"][8]["events"]["client_1"]["scored"] = True
    data["log"][8]["robots"]["client_1"]["scored"] = True
    result = MODULE.analyze(data, "fixture", "0" * 64)
    assert result["clients"]["client_1"]["explicit_events"]["score_event_count"] == 1
    assert result["match_events"]["score_event_count"] == 0
    assert result["match_events"]["goal_scored"] is False


@pytest.mark.parametrize("mutation", ["identities", "steps", "events", "ball_missing", "ball_nonfinite", "event_mismatch", "authority", "team_size", "roles", "controller", "model_sha"])
def test_validation_fails_closed(tmp_path, mutation):
    data = _with_authority(json.loads(LOG.read_text()))
    if mutation == "identities": data["identities"].pop("client_5")
    elif mutation == "steps": data["steps"] += 1
    elif mutation == "events": data["log"][0]["events"].pop("client_5")
    elif mutation == "ball_missing": data["log"][0]["ball"].pop("vz")
    elif mutation == "ball_nonfinite": data["log"][0]["ball"]["vx"] = float("nan")
    else:
        if mutation == "event_mismatch":
            data["log"][6]["robots"]["client_0"]["fallen"] = True
            data["log"][6]["events"]["client_0"]["fallen"] = False
        elif mutation == "authority": data["identities"]["client_1"]["ball_authority"] = True
        elif mutation == "team_size": data["identities"]["client_2"]["team"] = "A"
        elif mutation == "roles": data["identities"]["client_0"]["role"] = "keeper"
        elif mutation == "controller": data["identities"]["client_2"]["controller"] = "ONNX"
        elif mutation == "model_sha": data["identities"]["client_0"]["model_sha"] = "not-a-sha"
    path = tmp_path / "bad.json"; path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="fail-closed"):
        MODULE.load_and_validate(path)


def test_generated_artifact_is_bound_to_final_source():
    artifact = json.loads((ROOT / "acceptance/evaluation/metrics.json").read_text())
    assert artifact["source"] == "acceptance/remote/match_20260804_115349.json"
    assert artifact["source_sha256"] == EXPECTED_SHA
