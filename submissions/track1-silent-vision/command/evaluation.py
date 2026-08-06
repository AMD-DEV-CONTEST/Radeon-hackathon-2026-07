from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from command.dataset import ValidatedDatasetBundle, validate_dataset_bundle
from command.language import validate_recognition_language

UNKNOWN_PHRASE_ID = "UNKNOWN"


@dataclass(frozen=True)
class EvaluationRecord:
    expected_phrase_id: str | None
    predicted_phrase_id: str
    accepted: bool
    confidence: float
    distance: float


def build_evaluation_report(
    known_records: Sequence[EvaluationRecord],
    unknown_records: Sequence[EvaluationRecord],
    phrase_intents: Mapping[str, str],
    provenance: Mapping[str, Any],
) -> dict[str, Any]:
    known_total = len(known_records)
    unknown_total = len(unknown_records)
    phrase_correct = 0
    mapped_intent_correct = 0
    known_accepted = 0
    accepted_known_correct = 0
    unknown_accepted = 0
    per_phrase = {
        phrase_id: {
            "knownTotal": 0,
            "top1Correct": 0,
            "mappedIntentCorrect": 0,
            "accepted": 0,
            "acceptedCorrect": 0,
            "rejected": 0,
        }
        for phrase_id in phrase_intents
    }
    confusion: dict[str, Counter[str]] = {}

    for record in known_records:
        expected = record.expected_phrase_id
        if expected is None:
            raise ValueError("known evaluation records require expected_phrase_id")
        try:
            expected_intent = phrase_intents[expected]
        except KeyError as exc:
            raise ValueError(
                f"known phrase is missing from phrase_intents: {expected!r}"
            ) from exc
        if expected not in per_phrase:
            per_phrase[expected] = {
                "knownTotal": 0,
                "top1Correct": 0,
                "mappedIntentCorrect": 0,
                "accepted": 0,
                "acceptedCorrect": 0,
                "rejected": 0,
            }
        phrase_counts = per_phrase[expected]
        phrase_counts["knownTotal"] += 1

        is_phrase_correct = record.predicted_phrase_id == expected
        phrase_correct += int(is_phrase_correct)
        phrase_counts["top1Correct"] += int(is_phrase_correct)

        is_intent_correct = (
            phrase_intents.get(record.predicted_phrase_id) == expected_intent
        )
        mapped_intent_correct += int(is_intent_correct)
        phrase_counts["mappedIntentCorrect"] += int(is_intent_correct)

        known_accepted += int(record.accepted)
        phrase_counts["accepted"] += int(record.accepted)
        phrase_counts["rejected"] += int(not record.accepted)
        is_accepted_correct = record.accepted and is_phrase_correct
        accepted_known_correct += int(is_accepted_correct)
        phrase_counts["acceptedCorrect"] += int(is_accepted_correct)

        displayed_prediction = (
            record.predicted_phrase_id if record.accepted else UNKNOWN_PHRASE_ID
        )
        confusion.setdefault(expected, Counter())[displayed_prediction] += 1

    for record in unknown_records:
        if record.expected_phrase_id is not None:
            raise ValueError(
                "unknown evaluation records must not have expected_phrase_id"
            )
        unknown_accepted += int(record.accepted)
        displayed_prediction = (
            record.predicted_phrase_id if record.accepted else UNKNOWN_PHRASE_ID
        )
        confusion.setdefault(UNKNOWN_PHRASE_ID, Counter())[displayed_prediction] += 1

    unknown_rejected = unknown_total - unknown_accepted
    rate_counts = {
        "phraseAccuracy": _count(phrase_correct, known_total),
        "mappedIntentAccuracy": _count(mapped_intent_correct, known_total),
        "knownAcceptanceRate": _count(known_accepted, known_total),
        "acceptedPhraseAccuracy": _count(accepted_known_correct, known_accepted),
        "acceptedPrecision": _count(
            accepted_known_correct, known_accepted + unknown_accepted
        ),
        "unknownFalseAcceptRate": _count(unknown_accepted, unknown_total),
        "unknownRejectionRate": _count(unknown_rejected, unknown_total),
    }
    report = {
        name: _rate(counts["numerator"], counts["denominator"])
        for name, counts in rate_counts.items()
    }
    report.update(
        {
            "rawCounts": rate_counts,
            "perPhrase": per_phrase,
            "confusionMatrix": {
                expected: dict(predictions)
                for expected, predictions in confusion.items()
            },
            **dict(provenance),
        }
    )
    return report


def evaluate_checkpoint(
    checkpoint_path: Path,
    catalog_path: Path,
    inventory_path: Path,
    train_manifest: Path,
    calibration_known_manifest: Path,
    calibration_unknown_manifest: Path,
    known_manifest: Path,
    unknown_manifest: Path,
    output_path: Path,
    probability_override: float | None,
    distance_override: float | None,
) -> dict[str, Any]:
    checkpoint_path = Path(checkpoint_path)
    known_manifest = Path(known_manifest)
    unknown_manifest = Path(unknown_manifest)
    output_path = Path(output_path)
    _require_final_partition(known_manifest, "evaluation-known.jsonl")
    _require_final_partition(unknown_manifest, "evaluation-unknown.jsonl")

    bundle = validate_dataset_bundle(
        Path(catalog_path),
        Path(inventory_path),
        {
            "train.jsonl": Path(train_manifest),
            "calibration-known.jsonl": Path(calibration_known_manifest),
            "calibration-unknown.jsonl": Path(calibration_unknown_manifest),
            "evaluation-known.jsonl": known_manifest,
            "evaluation-unknown.jsonl": unknown_manifest,
        },
        require_evidentiary=True,
    )

    from backend.config import Settings
    from command.checkpoint import load_phrase_checkpoint
    from command.inference import TorchCommandClassifierBackend
    from command.training import (
        ManifestDataset,
        _sha256_file,
        _write_json_atomic,
        accelerator_provenance,
    )

    validated_checkpoint = load_phrase_checkpoint(checkpoint_path, "cpu")
    _validate_checkpoint_lineage(validated_checkpoint.evidence_lineage, bundle)

    backend = TorchCommandClassifierBackend(
        Settings(
            command_backend="torch",
            command_classifier_checkpoint=checkpoint_path,
            command_phrase_probability_override=probability_override,
            command_phrase_distance_override=distance_override,
        )
    )
    phrase_intents = {
        entry.phrase_id: entry.intent.value
        for entry in backend.loaded_checkpoint.catalog.entries
    }
    phrase_index = {
        phrase_id: index
        for index, phrase_id in enumerate(backend.loaded_checkpoint.phrase_ids)
    }
    known_dataset = ManifestDataset(known_manifest, phrase_index)
    unknown_dataset = ManifestDataset(unknown_manifest, phrase_index)
    _validate_partition_records(known_dataset.records, known=True)
    _validate_partition_records(unknown_dataset.records, known=False)

    known_records = _evaluate_dataset(backend, known_dataset, known_manifest)
    unknown_records = _evaluate_dataset(backend, unknown_dataset, unknown_manifest)
    provenance_keys = ("torchVersion", "hipVersion", "device", "deviceName")
    provenance = {
        "backend": "torch",
        "device": str(backend.device),
        "trainingAccelerator": {
            key: backend.loaded_checkpoint.training_summary[key]
            for key in provenance_keys
        },
        "evaluationAccelerator": accelerator_provenance(backend.torch, backend.device),
        "checkpointSha256": _sha256_file(checkpoint_path),
        "inventorySha256": bundle.inventory_sha256,
        "manifestSha256": dict(bundle.manifest_sha256),
        "thresholdSource": backend.thresholds.source,
        "effectiveThresholds": {
            "minProbability": backend.thresholds.min_probability,
            "maxCosineDistance": dict(backend.thresholds.max_cosine_distance),
        },
        "evidenceStatus": {
            "evidentiary": backend.thresholds.source == "checkpoint",
            "datasetEvidentiary": bundle.evidentiary,
            "checkpointEvidentiary": True,
            "lineageVerified": True,
            "thresholdsFrozen": backend.thresholds.source == "checkpoint",
        },
    }
    report = build_evaluation_report(
        known_records,
        unknown_records,
        phrase_intents,
        provenance,
    )
    _write_json_atomic(output_path, report)
    return report


def _validate_checkpoint_lineage(
    checkpoint_lineage: Mapping[str, Any], bundle: ValidatedDatasetBundle
) -> None:
    if checkpoint_lineage.get("evidentiary") is not True:
        raise ValueError("final evidence rejects a non-evidentiary checkpoint")
    if dict(checkpoint_lineage) != bundle.checkpoint_lineage():
        raise ValueError(
            "checkpoint evidence lineage does not match inventory and manifests"
        )


def _require_final_partition(path: Path, expected_name: str) -> None:
    if path.name != expected_name:
        raise ValueError(
            f"{expected_name} argument must reference a file named {expected_name}, "
            f"got {path.name}"
        )


def _validate_partition_records(
    records: Sequence[dict[str, Any]], *, known: bool
) -> None:
    for record in records:
        phrase_id = record.get("phrase_id")
        validate_recognition_language(record.get("language"))
        if known and (not isinstance(phrase_id, str) or not phrase_id):
            raise ValueError("evaluation-known.jsonl records require phrase_id")
        if not known and phrase_id is not None:
            raise ValueError("evaluation-unknown.jsonl records require phrase_id null")


def _evaluate_dataset(backend, dataset, manifest_path: Path) -> list[EvaluationRecord]:
    records: list[EvaluationRecord] = []
    for index, manifest_record in enumerate(dataset.records):
        frames, _ = dataset[index]
        language = validate_recognition_language(manifest_record.get("language"))
        decision = backend.predict(
            frames.numpy(),
            language,
            {
                "manifest": str(manifest_path),
                "sampleId": manifest_record.get("sample_id"),
            },
        )
        metadata = decision.metadata
        records.append(
            EvaluationRecord(
                expected_phrase_id=manifest_record.get("phrase_id"),
                predicted_phrase_id=str(metadata["predictedPhraseId"]),
                accepted=decision.accepted,
                confidence=decision.confidence,
                distance=float(metadata["openSetDistance"]),
            )
        )
    return records


def _count(numerator: int, denominator: int) -> dict[str, int]:
    return {"numerator": int(numerator), "denominator": int(denominator)}


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None
