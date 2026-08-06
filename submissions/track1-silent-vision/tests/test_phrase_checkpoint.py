from __future__ import annotations

import math
import sys
from hashlib import sha256
from types import SimpleNamespace

import numpy as np
import pytest

import command.checkpoint as checkpoint_module
from command.catalog import PhraseCatalog, catalog_sha256
from command.checkpoint import validate_phrase_checkpoint_schema

DECISION_POLICY = {
    "languageSelectionRequired": True,
    "probabilityNormalization": "selected-language-softmax",
}
MANIFEST_HASHES = {
    "train.jsonl": "1" * 64,
    "calibration-known.jsonl": "2" * 64,
    "calibration-unknown.jsonl": "3" * 64,
    "evaluation-known.jsonl": "4" * 64,
    "evaluation-unknown.jsonl": "5" * 64,
}


def metadata_payload() -> dict:
    payload = {
        "schemaVersion": "silent-vision.fixed-phrase.v2",
        "modelState": {},
        "phraseIds": [
            "zh_light_on_hello",
            "zh_chat_meal",
            "en_light_on_hello",
            "en_chat_meal",
        ],
        "phraseCatalog": [
            {
                "phraseId": "zh_light_on_hello",
                "text": "你好，请帮我打开灯",
                "language": "zh",
                "intent": "LIGHT_ON",
                "enabled": True,
            },
            {
                "phraseId": "zh_chat_meal",
                "text": "你吃饭了吗？",
                "language": "zh",
                "intent": "CHAT_OTHER",
                "enabled": True,
            },
            {
                "phraseId": "en_light_on_hello",
                "text": "Hello, please turn on the light.",
                "language": "en",
                "intent": "LIGHT_ON",
                "enabled": True,
            },
            {
                "phraseId": "en_chat_meal",
                "text": "Have you eaten?",
                "language": "en",
                "intent": "CHAT_OTHER",
                "enabled": True,
            },
        ],
        "featureConfig": {
            "fps": 25,
            "frames": 125,
            "height": 96,
            "width": 96,
            "downsample": 16,
        },
        "modelConfig": {"embeddingDim": 64, "parameterCap": 150000},
        "decisionThresholds": {
            "minProbability": 0.80,
            "maxCosineDistance": {
                "zh_light_on_hello": 0.20,
                "zh_chat_meal": 0.20,
                "en_light_on_hello": 0.20,
                "en_chat_meal": 0.20,
            },
        },
        "decisionPolicy": DECISION_POLICY,
        "classCentroids": np.tile(np.eye(1, 64, dtype=np.float32), (4, 1)),
        "evidenceLineage": {
            "inventorySha256": "a" * 64,
            "catalogSha256": "b" * 64,
            "seed": 17,
            "manifestSha256": dict(MANIFEST_HASHES),
            "evidentiary": False,
        },
        "trainingSummary": {
            "seed": 17,
            "evidentiary": False,
            "torchVersion": "2.2.2",
            "hipVersion": None,
            "device": "cpu",
            "deviceName": "local CPU test fixture",
        },
    }
    payload["evidenceLineage"]["catalogSha256"] = catalog_sha256(
        PhraseCatalog.from_records(payload["phraseCatalog"])
    )
    return payload


def test_checkpoint_schema_validation_runs_without_torch():
    validated = validate_phrase_checkpoint_schema(metadata_payload())
    assert validated.phrase_ids == (
        "zh_light_on_hello",
        "zh_chat_meal",
        "en_light_on_hello",
        "en_chat_meal",
    )
    assert tuple(validated.centroids.shape) == (4, 64)
    payload = metadata_payload()
    assert payload["schemaVersion"] == "silent-vision.fixed-phrase.v2"
    assert payload["decisionPolicy"] == {
        "languageSelectionRequired": True,
        "probabilityNormalization": "selected-language-softmax",
    }


@pytest.mark.parametrize(
    ("schema_version", "decision_policy", "message"),
    [
        (
            "silent-vision.fixed-phrase.v1",
            DECISION_POLICY,
            "unsupported checkpoint schema",
        ),
        (
            "silent-vision.fixed-phrase.v2",
            None,
            "checkpoint missing required keys: decisionPolicy",
        ),
        (
            "silent-vision.fixed-phrase.v2",
            {
                "languageSelectionRequired": False,
                "probabilityNormalization": "selected-language-softmax",
            },
            "languageSelectionRequired",
        ),
        (
            "silent-vision.fixed-phrase.v2",
            {
                "languageSelectionRequired": True,
                "probabilityNormalization": "global-softmax",
            },
            "probabilityNormalization",
        ),
    ],
)
def test_checkpoint_rejects_invalid_version_or_policy_before_model_loading(
    monkeypatch, schema_version, decision_policy, message
):
    payload = metadata_payload()
    payload["schemaVersion"] = schema_version
    if decision_policy is None:
        payload.pop("decisionPolicy")
    else:
        payload["decisionPolicy"] = decision_policy
    monkeypatch.setitem(
        sys.modules, "torch", SimpleNamespace(load=lambda path, map_location: payload)
    )
    monkeypatch.setattr(
        checkpoint_module,
        "_build_validated_model",
        lambda payload, validated: pytest.fail("model construction must not run"),
    )

    with pytest.raises(ValueError, match=message):
        checkpoint_module.load_phrase_checkpoint("ignored.pt", "cpu")


def test_checkpoint_phrase_ids_must_match_enabled_catalog_order():
    payload = metadata_payload()
    payload["phraseIds"].reverse()
    with pytest.raises(ValueError, match="enabled catalog order"):
        validate_phrase_checkpoint_schema(payload)


@pytest.mark.parametrize("frames", [None, 0, 124, 126, "125"])
def test_checkpoint_requires_fixed_temporal_frame_count(frames):
    payload = metadata_payload()
    if frames is None:
        payload["featureConfig"].pop("frames")
    else:
        payload["featureConfig"]["frames"] = frames

    with pytest.raises(ValueError, match="featureConfig frames must be 125"):
        validate_phrase_checkpoint_schema(payload)


def test_checkpoint_rejects_unknown_as_a_trained_phrase_class():
    payload = metadata_payload()
    payload["phraseCatalog"][0]["intent"] = "UNKNOWN"
    with pytest.raises(ValueError, match="UNKNOWN"):
        validate_phrase_checkpoint_schema(payload)


def test_checkpoint_thresholds_must_be_finite():
    payload = metadata_payload()
    payload["decisionThresholds"]["minProbability"] = math.nan
    with pytest.raises(ValueError, match="finite"):
        validate_phrase_checkpoint_schema(payload)


def test_checkpoint_thresholds_must_be_numeric():
    payload = metadata_payload()
    payload["decisionThresholds"]["minProbability"] = "0.80"
    with pytest.raises(ValueError, match="numeric"):
        validate_phrase_checkpoint_schema(payload)


@pytest.mark.parametrize(
    ("value", "message"),
    [
        (math.nan, "finite"),
        (math.inf, "finite"),
        (0.0, "non-zero"),
        (0.5, "unit-normalized"),
        (2.0, "unit-normalized"),
    ],
)
def test_checkpoint_rejects_corrupt_class_centroids(value, message):
    # Catches malformed centroids reaching cosine similarity and turning NaN into
    # an accepted distance through Python's min/max behavior.
    payload = metadata_payload()
    payload["classCentroids"][0] = 0.0
    payload["classCentroids"][0, 0] = value

    with pytest.raises(ValueError, match=message):
        validate_phrase_checkpoint_schema(payload)


def test_checkpoint_requires_fixed_parameter_cap():
    payload = metadata_payload()
    payload["modelConfig"]["parameterCap"] = 1_000_000
    with pytest.raises(ValueError, match="150000"):
        validate_phrase_checkpoint_schema(payload)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda lineage: lineage.pop("inventorySha256"), "inventorySha256"),
        (
            lambda lineage: lineage["manifestSha256"].pop("evaluation-known.jsonl"),
            "all five manifest roles",
        ),
        (lambda lineage: lineage.__setitem__("evidentiary", "yes"), "boolean"),
    ],
)
def test_checkpoint_requires_complete_explicit_evidence_lineage(mutation, message):
    payload = metadata_payload()
    mutation(payload["evidenceLineage"])

    with pytest.raises(ValueError, match=message):
        validate_phrase_checkpoint_schema(payload)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda summary: summary.pop("torchVersion"),
            "trainingSummary missing required keys: torchVersion",
        ),
        (
            lambda summary: summary.pop("hipVersion"),
            "trainingSummary missing required keys: hipVersion",
        ),
        (
            lambda summary: summary.pop("device"),
            "trainingSummary missing required keys: device",
        ),
        (
            lambda summary: summary.pop("deviceName"),
            "trainingSummary missing required keys: deviceName",
        ),
        (lambda summary: summary.__setitem__("torchVersion", ""), "torchVersion"),
        (lambda summary: summary.__setitem__("hipVersion", ""), "hipVersion"),
        (lambda summary: summary.__setitem__("device", "mps"), "device"),
        (lambda summary: summary.__setitem__("deviceName", 123), "deviceName"),
    ],
)
def test_checkpoint_rejects_missing_or_malformed_accelerator_provenance(
    mutation, message
):
    payload = metadata_payload()
    mutation(payload["trainingSummary"])

    with pytest.raises(ValueError, match=message):
        validate_phrase_checkpoint_schema(payload)


def test_evidentiary_checkpoint_requires_rocm_accelerator_provenance():
    payload = metadata_payload()
    payload["evidenceLineage"]["evidentiary"] = True
    payload["trainingSummary"]["evidentiary"] = True

    with pytest.raises(ValueError, match="ROCm/HIP"):
        validate_phrase_checkpoint_schema(payload)


def valid_payload(model):
    torch = pytest.importorskip("torch")
    payload = metadata_payload()
    payload["modelState"] = model.state_dict()
    payload["classCentroids"] = torch.nn.functional.normalize(torch.rand(4, 64), dim=1)
    return payload


def test_checkpoint_builds_dynamic_four_phrase_head(tmp_path):
    pytest.importorskip("torch")
    from command.checkpoint import load_phrase_checkpoint, save_phrase_checkpoint
    from command.model import build_fixed_phrase_model

    model = build_fixed_phrase_model(4)
    path = tmp_path / "phrase.pt"
    payload = valid_payload(model)
    digest = save_phrase_checkpoint(path, payload)
    loaded = load_phrase_checkpoint(path, "cpu")
    assert digest == sha256(path.read_bytes()).hexdigest()
    assert loaded.phrase_ids == (
        "zh_light_on_hello",
        "zh_chat_meal",
        "en_light_on_hello",
        "en_chat_meal",
    )
    assert loaded.centroids.shape == (4, 64)
    assert loaded.model.classifier.out_features == 4


def test_checkpoint_creation_preserves_empty_rocm_device_name(tmp_path):
    pytest.importorskip("torch")
    from command.checkpoint import load_phrase_checkpoint, save_phrase_checkpoint
    from command.model import build_fixed_phrase_model
    from command.training import accelerator_provenance

    rocm_torch = SimpleNamespace(
        __version__="2.7.1+rocm6.3",
        version=SimpleNamespace(hip="6.3"),
        cuda=SimpleNamespace(get_device_name=lambda index: ""),
    )
    payload = valid_payload(build_fixed_phrase_model(4))
    payload["evidenceLineage"]["evidentiary"] = True
    payload["trainingSummary"].update(
        {
            "evidentiary": True,
            **accelerator_provenance(rocm_torch, "cuda:0"),
        }
    )
    path = tmp_path / "empty-device-name.pt"

    save_phrase_checkpoint(path, payload)
    loaded = load_phrase_checkpoint(path, "cpu")

    assert loaded.training_summary["deviceName"] == ""


def test_legacy_intent_checkpoint_has_migration_error(tmp_path):
    torch = pytest.importorskip("torch")
    from command.checkpoint import load_phrase_checkpoint

    path = tmp_path / "legacy.pt"
    torch.save({"model": {}, "labels": ["LIGHT_ON", "LIGHT_OFF"]}, path)
    with pytest.raises(ValueError, match="legacy intent-only checkpoint"):
        load_phrase_checkpoint(path, "cpu")


def test_head_shape_mismatch_is_rejected(tmp_path):
    torch = pytest.importorskip("torch")
    from command.checkpoint import load_phrase_checkpoint
    from command.model import build_fixed_phrase_model

    payload = valid_payload(build_fixed_phrase_model(4))
    payload["phraseIds"].append("third")
    torch.save(payload, tmp_path / "bad.pt")
    with pytest.raises(ValueError, match="classifier head"):
        load_phrase_checkpoint(tmp_path / "bad.pt", "cpu")


def test_save_rejects_incomplete_state_without_replacing_existing_file(tmp_path):
    pytest.importorskip("torch")
    from command.checkpoint import save_phrase_checkpoint
    from command.model import build_fixed_phrase_model

    path = tmp_path / "phrase.pt"
    path.write_bytes(b"existing checkpoint")
    payload = valid_payload(build_fixed_phrase_model(4))
    payload["modelState"].pop("projection.weight")
    with pytest.raises(ValueError, match="modelState"):
        save_phrase_checkpoint(path, payload)
    assert path.read_bytes() == b"existing checkpoint"
