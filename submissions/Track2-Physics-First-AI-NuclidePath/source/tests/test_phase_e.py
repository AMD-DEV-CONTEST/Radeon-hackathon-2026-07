import json
from pathlib import Path

import pytest

from nuclear_agent.contracts import EvidenceRecord, ValidationError
from nuclear_agent.model_selection import ModelCandidate, ModelSelectionAgent
from nuclear_agent.replay import ReplayBundle, ReplayVerificationError, verify_bundle


def test_evidence_record_requires_exactly_value_or_range_and_is_immutable():
    record = EvidenceRecord.from_dict({
        "parameter": "half_life", "value": 30.0, "unit": "year",
        "source": "https://example.test/a", "location": "table 1",
        "hash": "a" * 64, "class": "primary", "applicability": "Cs-137",
        "caveat": "rounded",
    })
    assert record.parameter == "half_life"
    with pytest.raises((AttributeError, TypeError)):
        record.parameter = "other"
    with pytest.raises(ValidationError):
        EvidenceRecord.from_dict({"parameter": "x", "value": 1, "value_range": [1, 2]})
    with pytest.raises(ValidationError):
        EvidenceRecord(parameter="x", value=1)
    with pytest.raises(ValidationError):
        EvidenceRecord.from_dict({
            "parameter":"x", "value": float("nan"), "unit":"m", "source":"s",
            "location":"p1", "hash":"a"*64, "class":"primary", "applicability":"a",
            "caveat":"",
        })


def test_model_selection_is_rule_driven_and_fail_closed():
    agent = ModelSelectionAgent(required_capabilities=("decay",))
    result = agent.select({"radionuclide": "Cs-137", "capabilities": ["decay"]}, [
        ModelCandidate("good", capabilities=("decay",), applicability=("Cs-137",), priority=1),
        ModelCandidate("missing", capabilities=(), applicability=("Cs-137",), priority=2),
        ModelCandidate("unknown", capabilities=("decay",), applicability=(), priority=3),
    ])
    assert result.selected == ("good",)
    assert result.rejected["missing"]
    assert result.rejected["unknown"]
    assert ModelSelectionAgent().select({}, []).selected == ()
    with pytest.raises((TypeError, AttributeError)):
        result.rejected["x"] = ()
    with pytest.raises(ValueError):
        ModelCandidate("", capabilities=("x",), applicability=("Cs-137",))


def test_replay_bundle_manifest_and_tamper_detection(tmp_path):
    path = tmp_path / "bundle"
    ReplayBundle.write(path, {"b": 2, "a": 1}, {"source": "x"}, {"answer": 3}, tool_trace=[{"tool": "x"}])
    assert verify_bundle(path).valid
    (path / "results.json").write_text('{"answer":4}\n')
    with pytest.raises(ReplayVerificationError):
        verify_bundle(path)


def test_replay_bundle_can_be_rewritten_in_place(tmp_path):
    path = tmp_path / "bundle"
    ReplayBundle.write(path, {"a": 1}, {"source": "x"}, {"answer": 3})
    ReplayBundle.write(path, {"a": 2}, {"source": "y"}, {"answer": 4})
    assert verify_bundle(path).valid
    assert json.loads((path / "normalized_input.json").read_text()) == {"a": 2}


def test_replay_bundle_rejects_non_finite_json_and_symbolic_links(tmp_path):
    with pytest.raises(ValueError, match="JSON"):
        ReplayBundle.write(tmp_path / "non-finite", {"value": float("nan")}, {}, {})

    outside = tmp_path / "outside.json"
    outside.write_text("do not overwrite")
    path = tmp_path / "bundle"
    path.mkdir()
    (path / "normalized_input.json").symlink_to(outside)
    with pytest.raises(ReplayVerificationError, match="symbolic link"):
        ReplayBundle.write(path, {"a": 1}, {}, {})
    assert outside.read_text() == "do not overwrite"


def test_replay_manifest_rejects_unknown_files_and_path_traversal(tmp_path):
    path = tmp_path / "bundle"
    ReplayBundle.write(path, {"a":1}, {"source":"x"}, {"answer":3})
    (path / "extra.json").write_text("{}")
    with pytest.raises(ReplayVerificationError):
        verify_bundle(path)
    (path / "extra.json").unlink()
    manifest = json.loads((path / "manifest.json").read_text())
    manifest["files"]["../outside.json"] = "a" * 64
    (path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ReplayVerificationError):
        verify_bundle(path)
