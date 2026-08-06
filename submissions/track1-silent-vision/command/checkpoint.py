from __future__ import annotations

import hashlib
import math
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from numbers import Real
from pathlib import Path
from typing import Any

from command.catalog import PhraseCatalog, catalog_sha256
from command.dataset import MANIFEST_ROLES
from command.model import FIXED_CLIP_FRAMES, PARAMETER_CAP

SCHEMA_VERSION = "silent-vision.fixed-phrase.v2"
DECISION_POLICY = {
    "languageSelectionRequired": True,
    "probabilityNormalization": "selected-language-softmax",
}
REQUIRED_KEYS = frozenset(
    {
        "schemaVersion",
        "modelState",
        "phraseIds",
        "phraseCatalog",
        "featureConfig",
        "modelConfig",
        "decisionPolicy",
        "decisionThresholds",
        "classCentroids",
        "evidenceLineage",
        "trainingSummary",
    }
)


@dataclass(frozen=True)
class ValidatedPhraseCheckpointSchema:
    catalog: PhraseCatalog
    phrase_ids: tuple[str, ...]
    centroids: Any
    embedding_dim: int
    parameter_cap: int
    decision_thresholds: dict[str, Any]
    evidence_lineage: dict[str, Any]
    training_summary: dict[str, Any]


@dataclass(frozen=True)
class LoadedPhraseCheckpoint:
    model: Any
    catalog: PhraseCatalog
    phrase_ids: tuple[str, ...]
    centroids: Any
    decision_thresholds: dict[str, Any]
    evidence_lineage: dict[str, Any]
    training_summary: dict[str, Any]


def validate_phrase_checkpoint_schema(
    payload: dict[str, Any],
) -> ValidatedPhraseCheckpointSchema:
    if not isinstance(payload, dict):
        raise ValueError("checkpoint payload must be a dictionary")  # noqa: TRY004
    missing = sorted(REQUIRED_KEYS - payload.keys())
    if missing:
        raise ValueError(f"checkpoint missing required keys: {', '.join(missing)}")
    if payload["schemaVersion"] != SCHEMA_VERSION:
        raise ValueError(f"unsupported checkpoint schema: {payload['schemaVersion']!r}")
    _validate_decision_policy(payload["decisionPolicy"])
    if not isinstance(payload["modelState"], Mapping):
        raise ValueError("modelState must be a mapping")  # noqa: TRY004

    phrase_ids_value = payload["phraseIds"]
    if not isinstance(phrase_ids_value, (list, tuple)) or not phrase_ids_value:
        raise ValueError("phraseIds must be a non-empty ordered sequence")
    phrase_ids = tuple(phrase_ids_value)
    if any(
        not isinstance(phrase_id, str) or not phrase_id.strip()
        for phrase_id in phrase_ids
    ):
        raise ValueError("phraseIds must contain non-blank strings")
    if len(set(phrase_ids)) != len(phrase_ids):
        raise ValueError("phraseIds must be unique")

    catalog_records = payload["phraseCatalog"]
    if not isinstance(catalog_records, list):
        raise ValueError("phraseCatalog must be a list")  # noqa: TRY004
    if any(
        record.get("enabled", True) and record.get("intent") == "UNKNOWN"
        for record in catalog_records
    ):
        raise ValueError("checkpoint phraseCatalog cannot train UNKNOWN")
    catalog = PhraseCatalog.from_records(catalog_records)
    catalog_phrase_ids = tuple(entry.phrase_id for entry in catalog.entries)
    if phrase_ids != catalog_phrase_ids:
        raise ValueError("phraseIds must match enabled catalog order")

    feature_config = _mapping(payload["featureConfig"], "featureConfig")
    _require_keys(
        feature_config, {"fps", "height", "width", "downsample"}, "featureConfig"
    )
    if feature_config["fps"] != 25:
        raise ValueError("featureConfig fps must be 25")
    if feature_config.get("frames") != FIXED_CLIP_FRAMES:
        raise ValueError(f"featureConfig frames must be {FIXED_CLIP_FRAMES}")
    expected_spatial_config = {"height": 96, "width": 96, "downsample": 16}
    for key, expected in expected_spatial_config.items():
        if feature_config[key] != expected:
            raise ValueError(f"featureConfig {key} must be {expected}")

    model_config = _mapping(payload["modelConfig"], "modelConfig")
    _require_keys(model_config, {"embeddingDim", "parameterCap"}, "modelConfig")
    embedding_dim = _positive_integer(
        model_config["embeddingDim"], "modelConfig embeddingDim"
    )
    parameter_cap = _positive_integer(
        model_config["parameterCap"], "modelConfig parameterCap"
    )
    if parameter_cap != PARAMETER_CAP:
        raise ValueError(f"modelConfig parameterCap must be {PARAMETER_CAP}")

    centroids = payload["classCentroids"]
    shape = getattr(centroids, "shape", None)
    if shape is None or tuple(shape) != (len(phrase_ids), embedding_dim):
        raise ValueError(
            "classCentroids shape must be "
            f"[{len(phrase_ids)}, {embedding_dim}], got {None if shape is None else list(shape)}"
        )
    _validate_centroid_values(centroids)

    thresholds = dict(_mapping(payload["decisionThresholds"], "decisionThresholds"))
    _require_keys(
        thresholds, {"minProbability", "maxCosineDistance"}, "decisionThresholds"
    )
    minimum_probability = _finite_number(thresholds["minProbability"], "minProbability")
    if not 0.0 <= minimum_probability <= 1.0:
        raise ValueError("minProbability must be between 0 and 1")
    thresholds["minProbability"] = minimum_probability
    distances = _mapping(thresholds["maxCosineDistance"], "maxCosineDistance")
    if set(distances) != set(phrase_ids):
        raise ValueError("maxCosineDistance keys must match phraseIds")
    normalized_distances: dict[str, float] = {}
    for phrase_id in phrase_ids:
        distance = _finite_number(
            distances[phrase_id], f"maxCosineDistance[{phrase_id!r}]"
        )
        if not 0.0 <= distance <= 2.0:
            raise ValueError("maxCosineDistance values must be between 0 and 2")
        normalized_distances[phrase_id] = distance
    thresholds["maxCosineDistance"] = normalized_distances

    evidence_lineage = _validate_evidence_lineage(payload["evidenceLineage"], catalog)
    training_summary = dict(_mapping(payload["trainingSummary"], "trainingSummary"))
    _require_keys(
        training_summary,
        {"torchVersion", "hipVersion", "device", "deviceName"},
        "trainingSummary",
    )
    training_summary["torchVersion"] = _non_blank_string(
        training_summary["torchVersion"], "trainingSummary torchVersion"
    )
    hip_version = training_summary["hipVersion"]
    if hip_version is not None:
        hip_version = _non_blank_string(
            hip_version, "trainingSummary hipVersion"
        )
    training_summary["hipVersion"] = hip_version
    device = _non_blank_string(training_summary["device"], "trainingSummary device")
    if device not in {"cpu", "cuda:0"}:
        raise ValueError("trainingSummary device must be cpu or cuda:0")
    training_summary["device"] = device
    if not isinstance(training_summary["deviceName"], str):
        raise ValueError(  # noqa: TRY004
            "trainingSummary deviceName must be a string"
        )
    if training_summary.get("seed") != evidence_lineage["seed"]:
        raise ValueError("trainingSummary seed must match evidenceLineage seed")
    if training_summary.get("evidentiary") is not evidence_lineage["evidentiary"]:
        raise ValueError(
            "trainingSummary evidentiary must match evidenceLineage evidentiary"
        )
    if evidence_lineage["evidentiary"] and (
        training_summary["hipVersion"] is None or training_summary["device"] != "cuda:0"
    ):
        raise ValueError(
            "evidentiary trainingSummary requires ROCm/HIP device cuda:0"
        )
    return ValidatedPhraseCheckpointSchema(
        catalog=catalog,
        phrase_ids=phrase_ids,
        centroids=centroids,
        embedding_dim=embedding_dim,
        parameter_cap=parameter_cap,
        decision_thresholds=thresholds,
        evidence_lineage=evidence_lineage,
        training_summary=training_summary,
    )


def save_phrase_checkpoint(path: Path, payload: dict[str, Any]) -> str:
    import torch

    validated = validate_phrase_checkpoint_schema(payload)
    _validate_classifier_head(
        payload["modelState"], len(validated.phrase_ids), validated.embedding_dim
    )
    _build_validated_model(payload, validated)

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            torch.save(payload, temporary_file)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        temporary_path.replace(path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
    return _sha256(path)


def load_phrase_checkpoint(path: Path, device: str) -> LoadedPhraseCheckpoint:
    import torch

    payload = torch.load(Path(path), map_location=device)
    if (
        isinstance(payload, dict)
        and "schemaVersion" not in payload
        and {"model", "labels"} <= payload.keys()
    ):
        raise ValueError(
            "legacy intent-only checkpoint; retrain with the fixed phrase classifier"
        )
    if not isinstance(payload, dict):
        raise ValueError("checkpoint payload must be a dictionary")  # noqa: TRY004

    _validate_head_from_unvalidated_payload(payload)
    validated = validate_phrase_checkpoint_schema(payload)
    model = _build_validated_model(payload, validated)
    model.to(device)
    model.eval()
    return LoadedPhraseCheckpoint(
        model=model,
        catalog=validated.catalog,
        phrase_ids=validated.phrase_ids,
        centroids=validated.centroids,
        decision_thresholds=validated.decision_thresholds,
        evidence_lineage=validated.evidence_lineage,
        training_summary=validated.training_summary,
    )


def _validate_head_from_unvalidated_payload(payload: dict[str, Any]) -> None:
    missing = sorted({"modelState", "phraseIds", "modelConfig"} - payload.keys())
    if missing:
        return
    phrase_ids = payload["phraseIds"]
    model_config = payload["modelConfig"]
    if not isinstance(phrase_ids, (list, tuple)) or not isinstance(
        model_config, Mapping
    ):
        return
    embedding_dim = model_config.get("embeddingDim")
    if not isinstance(embedding_dim, int) or isinstance(embedding_dim, bool):
        return
    _validate_classifier_head(payload["modelState"], len(phrase_ids), embedding_dim)


def _validate_classifier_head(
    model_state: Any, class_count: int, embedding_dim: int
) -> None:
    if not isinstance(model_state, Mapping):
        return
    weight = model_state.get("classifier.weight")
    bias = model_state.get("classifier.bias")
    weight_shape = getattr(weight, "shape", None)
    bias_shape = getattr(bias, "shape", None)
    if weight_shape is not None and tuple(weight_shape) != (class_count, embedding_dim):
        raise ValueError(
            f"classifier head weight shape must be [{class_count}, {embedding_dim}], got {list(weight_shape)}"
        )
    if bias_shape is not None and tuple(bias_shape) != (class_count,):
        raise ValueError(
            f"classifier head bias shape must be [{class_count}], got {list(bias_shape)}"
        )


def _build_validated_model(
    payload: dict[str, Any], validated: ValidatedPhraseCheckpointSchema
) -> Any:
    from command.model import build_fixed_phrase_model, count_trainable_parameters

    model = build_fixed_phrase_model(len(validated.phrase_ids), validated.embedding_dim)
    parameter_count = count_trainable_parameters(model)
    if parameter_count >= PARAMETER_CAP:
        raise ValueError(
            f"model has {parameter_count} trainable parameters, violating cap {PARAMETER_CAP}"
        )
    try:
        model.load_state_dict(payload["modelState"], strict=True)
    except RuntimeError as exc:
        raise ValueError(
            f"checkpoint modelState is incompatible with the fixed phrase model: {exc}"
        ) from exc
    return model


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a mapping")  # noqa: TRY004
    return value


def _validate_decision_policy(value: Any) -> None:
    policy = _mapping(value, "decisionPolicy")
    if set(policy) != set(DECISION_POLICY):
        raise ValueError(
            "decisionPolicy must contain exactly languageSelectionRequired and probabilityNormalization"
        )
    if policy["languageSelectionRequired"] is not True:
        raise ValueError("decisionPolicy languageSelectionRequired must be True")
    if policy["probabilityNormalization"] != "selected-language-softmax":
        raise ValueError(
            "decisionPolicy probabilityNormalization must be selected-language-softmax"
        )


def _require_keys(mapping: Mapping[str, Any], keys: set[str], name: str) -> None:
    missing = sorted(keys - mapping.keys())
    if missing:
        raise ValueError(f"{name} missing required keys: {', '.join(missing)}")


def _positive_integer(value: Any, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _non_blank_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-blank string")
    return value.strip()


def _finite_number(value: Any, name: str) -> float:
    if not isinstance(value, Real) or isinstance(value, bool):
        raise ValueError(f"{name} must be numeric and finite")  # noqa: TRY004
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _validate_centroid_values(centroids: Any) -> None:
    if hasattr(centroids, "detach"):
        values = centroids.detach().to(dtype=getattr(centroids, "dtype", None))
        if not bool(values.isfinite().all().item()):
            raise ValueError("classCentroids must contain only finite values")
        norms = values.float().norm(dim=1)
        if bool((norms <= 1e-12).any().item()):
            raise ValueError("classCentroids rows must be non-zero")
        if bool(((norms - 1.0).abs() > 1e-4).any().item()):
            raise ValueError("classCentroids rows must be unit-normalized")
        return

    import numpy as np

    values = np.asarray(centroids, dtype=np.float64)
    if not np.isfinite(values).all():
        raise ValueError("classCentroids must contain only finite values")
    norms = np.linalg.norm(values, axis=1)
    if np.any(norms <= 1e-12):
        raise ValueError("classCentroids rows must be non-zero")
    if np.any(np.abs(norms - 1.0) > 1e-4):
        raise ValueError("classCentroids rows must be unit-normalized")


def _validate_evidence_lineage(value: Any, catalog: PhraseCatalog) -> dict[str, Any]:
    lineage = _mapping(value, "evidenceLineage")
    expected_keys = {
        "inventorySha256",
        "catalogSha256",
        "seed",
        "manifestSha256",
        "evidentiary",
    }
    if set(lineage) != expected_keys:
        missing = sorted(expected_keys - lineage.keys())
        detail = f": {', '.join(missing)}" if missing else ""
        raise ValueError(f"evidenceLineage has invalid keys{detail}")
    inventory_digest = _sha256_value(
        lineage["inventorySha256"], "evidenceLineage inventorySha256"
    )
    catalog_digest = _sha256_value(
        lineage["catalogSha256"], "evidenceLineage catalogSha256"
    )
    if catalog_digest != catalog_sha256(catalog):
        raise ValueError("evidenceLineage catalogSha256 does not match phraseCatalog")
    seed = lineage["seed"]
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError("evidenceLineage seed must be an integer")  # noqa: TRY004
    manifest_hashes = _mapping(
        lineage["manifestSha256"], "evidenceLineage manifestSha256"
    )
    if set(manifest_hashes) != set(MANIFEST_ROLES):
        raise ValueError(
            "evidenceLineage manifestSha256 must contain all five manifest roles"
        )
    normalized_hashes = {
        role: _sha256_value(
            manifest_hashes[role], f"evidenceLineage manifestSha256[{role!r}]"
        )
        for role in MANIFEST_ROLES
    }
    evidentiary = lineage["evidentiary"]
    if not isinstance(evidentiary, bool):
        raise ValueError(  # noqa: TRY004
            "evidenceLineage evidentiary must be a boolean"
        )
    return {
        "inventorySha256": inventory_digest,
        "catalogSha256": catalog_digest,
        "seed": seed,
        "manifestSha256": normalized_hashes,
        "evidentiary": evidentiary,
    }


def _sha256_value(value: Any, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError(f"{name} must be 64 hexadecimal characters")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(f"{name} must be 64 hexadecimal characters") from exc
    return value.lower()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as checkpoint_file:
        for chunk in iter(lambda: checkpoint_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
