"""Strict offline evidence preparation for held-out L2/L3 calibration studies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from specstyle.calibration.evidence_io import (
    _count,
    _exact,
    _float,
    _load_canonical,
    _pin,
    _sha,
    _text,
    canonical_json,
    evidence_sha256 as evidence_sha256,
)
from specstyle.calibration.splits import assign_split
from specstyle.calibration.threshold_search import (
    ScoredPair,
    binary_rates,
    freeze_threshold,
    select_threshold_on_calibration,
)
from specstyle.domain.identifiers import Sha256
from specstyle.errors import DomainError
from specstyle.observability.hashing import hash_bytes

_OUTPUT_PROFILES = ("xhs_grid", "talking_head_cover", "background_sequence")
_DOMAIN_PROFILES = {"product_instance", "face_identity", "structure_only"}
_SPLITS = ("calibration", "validation", "test")
_PROTOCOL_KEYS = {"schema_version", "protocol_id", "label_definition"}
_PLAN_KEYS = {
    "schema_version",
    "study_id",
    "layer",
    "style_pack_id",
    "domain_profile",
    "output_profiles",
    "metric",
    "verifier_pin",
    "preprocessor_pin",
    "targets",
    "split",
    "annotation_protocol_sha256",
}
_SAMPLE_KEYS = {
    "sample_id",
    "candidate_sha256",
    "source_sha256",
    "reference_sha256",
    "isolation_group_sha256",
    "split",
    "style_pack_id",
    "domain_profile",
    "output_profile",
    "annotation_record_sha256",
    "provenance_record_sha256",
}
_OBSERVATION_KEYS = {
    "sample_id",
    "candidate_sha256",
    "score",
    "label_positive",
    "annotation_record_sha256",
}
_PREPARED_KEYS = {
    "schema_version",
    "study_id",
    "layer",
    "style_pack_id",
    "domain_profile",
    "output_profiles",
    "metric",
    "verifier_pin",
    "preprocessor_pin",
    "targets",
    "study_plan_sha256",
    "sample_manifest_sha256",
    "annotation_protocol_sha256",
    "label_approval_receipt_sha256",
    "test_commitment_sha256",
    "sealed_test_observations_sha256",
    "test_sample_ids",
    "test_bindings_sha256",
    "test_positive_count",
    "test_negative_count",
    "status",
    "reasons",
    "threshold",
    "calibration",
    "validation",
    "test_held",
}


@dataclass(frozen=True, slots=True)
class _Study:
    raw: dict[str, Any]
    digest: Sha256


@dataclass(frozen=True, slots=True)
class _Manifest:
    raw: dict[str, Any]
    digest: Sha256
    by_split: dict[str, tuple[dict[str, Any], ...]]


@dataclass(frozen=True, slots=True)
class _ObservationSet:
    raw: dict[str, Any]
    digest: Sha256
    pairs: tuple[ScoredPair, ...]


def _load_study(data: bytes) -> _Study:
    raw = _exact(_load_canonical(data), _PLAN_KEYS, "study plan")
    if raw["schema_version"] != "specstyle.calibration.study_plan.v1":
        raise DomainError("invalid study plan schema")
    _text(raw["study_id"], "study id")
    if raw["layer"] not in {"L2", "L3"}:
        raise DomainError("invalid study layer")
    _text(raw["style_pack_id"], "style pack")
    if raw["domain_profile"] not in _DOMAIN_PROFILES:
        raise DomainError("invalid domain profile")
    outputs = raw["output_profiles"]
    if (
        type(outputs) is not list
        or not outputs
        or any(
            type(item) is not str or item not in _OUTPUT_PROFILES for item in outputs
        )
        or outputs != [item for item in _OUTPUT_PROFILES if item in outputs]
        or len(set(outputs)) != len(outputs)
    ):
        raise DomainError("invalid output profiles")
    if len(outputs) != 1:
        raise DomainError("study requires one output profile")
    metric = _exact(
        raw["metric"], {"metric_id", "operator", "implementation_pin"}, "metric"
    )
    _text(metric["metric_id"], "metric id")
    if metric["operator"] != "gte":
        raise DomainError("unsupported metric operator")
    _pin(metric["implementation_pin"], "metric implementation pin")
    _pin(raw["verifier_pin"], "verifier pin")
    _pin(raw["preprocessor_pin"], "preprocessor pin")
    targets = _exact(raw["targets"], {"min_tpr", "max_fpr"}, "targets")
    min_tpr = _float(targets["min_tpr"], "minimum tpr")
    max_fpr = _float(targets["max_fpr"], "maximum fpr")
    if not 0.0 <= min_tpr <= 1.0 or not 0.0 <= max_fpr <= 1.0:
        raise DomainError("invalid targets")
    split = _exact(
        raw["split"],
        {
            "algorithm",
            "salt",
            "minimum_positive_per_split",
            "minimum_negative_per_split",
        },
        "split plan",
    )
    if split["algorithm"] != "sha256_mod_60_20_20":
        raise DomainError("unsupported split algorithm")
    _text(split["salt"], "split salt")
    _count(split["minimum_positive_per_split"], "minimum positives", minimum=1)
    _count(split["minimum_negative_per_split"], "minimum negatives", minimum=1)
    _sha(raw["annotation_protocol_sha256"], "annotation protocol sha256")
    return _Study(raw, hash_bytes(data))


def _verify_annotation_protocol(data: bytes, study: _Study) -> None:
    raw = _exact(_load_canonical(data), _PROTOCOL_KEYS, "annotation protocol")
    if (
        raw["schema_version"] != "specstyle.annotation_protocol.v1"
        or hash_bytes(data).value != study.raw["annotation_protocol_sha256"]
    ):
        raise DomainError("annotation protocol mismatch")
    _text(raw["protocol_id"], "annotation protocol id")
    _text(raw["label_definition"], "annotation label definition")


def _load_manifest(data: bytes, study: _Study) -> _Manifest:
    raw = _exact(
        _load_canonical(data),
        {"schema_version", "study_plan_sha256", "samples"},
        "sample manifest",
    )
    if (
        raw["schema_version"] != "specstyle.calibration.sample_manifest.v1"
        or raw["study_plan_sha256"] != study.digest.value
        or type(raw["samples"]) is not list
        or not raw["samples"]
    ):
        raise DomainError("invalid sample manifest")
    by_split: dict[str, list[dict[str, Any]]] = {name: [] for name in _SPLITS}
    seen_ids: set[str] = set()
    seen_candidates: set[str] = set()
    group_splits: dict[str, str] = {}
    for value in raw["samples"]:
        sample = _exact(value, _SAMPLE_KEYS, "sample")
        sample_id = _text(sample["sample_id"], "sample id")
        candidate = _sha(sample["candidate_sha256"], "candidate sha256")
        for key in (
            "source_sha256",
            "reference_sha256",
            "annotation_record_sha256",
            "provenance_record_sha256",
        ):
            _sha(sample[key], key)
        group = _sha(sample["isolation_group_sha256"], "isolation group sha256")
        split = sample["split"]
        expected = assign_split(Sha256(group), study.raw["split"]["salt"])
        if split != expected:
            raise DomainError("sample split assignment mismatch")
        if group in group_splits and group_splits[group] != split:
            raise DomainError("isolation group split leakage")
        group_splits[group] = split
        if (
            sample["style_pack_id"] != study.raw["style_pack_id"]
            or sample["domain_profile"] != study.raw["domain_profile"]
            or sample["output_profile"] not in study.raw["output_profiles"]
        ):
            raise DomainError("sample study binding mismatch")
        if sample_id in seen_ids or candidate in seen_candidates:
            raise DomainError("duplicate calibration sample")
        seen_ids.add(sample_id)
        seen_candidates.add(candidate)
        by_split[split].append(sample)
    return _Manifest(
        raw,
        hash_bytes(data),
        {name: tuple(by_split[name]) for name in _SPLITS},
    )


def _load_observations(
    data: bytes, split: str, study: _Study, manifest: _Manifest
) -> _ObservationSet:
    raw = _exact(
        _load_canonical(data),
        {
            "schema_version",
            "study_plan_sha256",
            "sample_manifest_sha256",
            "split",
            "metric_id",
            "metric_implementation_pin",
            "verifier_pin",
            "preprocessor_pin",
            "observations",
        },
        "observations",
    )
    metric = study.raw["metric"]
    if (
        raw["schema_version"] != "specstyle.calibration.observations.v1"
        or raw["study_plan_sha256"] != study.digest.value
        or raw["sample_manifest_sha256"] != manifest.digest.value
        or raw["split"] != split
        or raw["metric_id"] != metric["metric_id"]
        or raw["metric_implementation_pin"] != metric["implementation_pin"]
        or raw["verifier_pin"] != study.raw["verifier_pin"]
        or raw["preprocessor_pin"] != study.raw["preprocessor_pin"]
        or type(raw["observations"]) is not list
    ):
        raise DomainError("observation binding mismatch")
    expected = manifest.by_split[split]
    if len(raw["observations"]) != len(expected):
        raise DomainError("observation coverage mismatch")
    pairs: list[ScoredPair] = []
    for value, sample in zip(raw["observations"], expected, strict=True):
        item = _exact(value, _OBSERVATION_KEYS, "observation")
        score = _float(item["score"], "observation score")
        if (
            item["sample_id"] != sample["sample_id"]
            or item["candidate_sha256"] != sample["candidate_sha256"]
            or item["annotation_record_sha256"] != sample["annotation_record_sha256"]
            or type(item["label_positive"]) is not bool
        ):
            raise DomainError("observation sample mismatch")
        pairs.append(ScoredPair(item["sample_id"], score, item["label_positive"]))
    return _ObservationSet(raw, hash_bytes(data), tuple(pairs))


def _load_commitment(data: bytes, study: _Study, manifest: _Manifest) -> dict[str, Any]:
    raw = _exact(
        _load_canonical(data),
        {
            "schema_version",
            "study_plan_sha256",
            "sample_manifest_sha256",
            "sealed_test_observations_sha256",
            "sample_ids",
            "positive_count",
            "negative_count",
        },
        "test commitment",
    )
    expected_ids = [sample["sample_id"] for sample in manifest.by_split["test"]]
    if (
        raw["schema_version"] != "specstyle.calibration.test_commitment.v1"
        or raw["study_plan_sha256"] != study.digest.value
        or raw["sample_manifest_sha256"] != manifest.digest.value
        or raw["sample_ids"] != expected_ids
    ):
        raise DomainError("test commitment mismatch")
    _sha(raw["sealed_test_observations_sha256"], "sealed test observations")
    _count(raw["positive_count"], "test positive count")
    _count(raw["negative_count"], "test negative count")
    if raw["positive_count"] + raw["negative_count"] != len(expected_ids):
        raise DomainError("test commitment counts mismatch")
    return raw


def _load_label_approval(
    data: bytes,
    study: _Study,
    manifest: _Manifest,
    observations: tuple[_ObservationSet, _ObservationSet],
    sealed_test_sha256: str,
) -> dict[str, Any]:
    raw = _exact(
        _load_canonical(data),
        {
            "schema_version",
            "receipt_id",
            "study_id",
            "approval_kind",
            "approved",
            "label_source",
            "study_plan_sha256",
            "sample_manifest_sha256",
            "annotation_protocol_sha256",
            "observation_sha256s",
            "approver_id",
            "issued_at",
        },
        "label approval receipt",
    )
    if (
        raw["schema_version"] != "specstyle.calibration.approval_receipt.v1"
        or raw["study_id"] != study.raw["study_id"]
        or raw["approval_kind"] != "HUMAN_LABELS"
        or type(raw["approved"]) is not bool
        or raw["label_source"] not in {"HUMAN_APPROVED", "SYNTHETIC"}
        or raw["study_plan_sha256"] != study.digest.value
        or raw["sample_manifest_sha256"] != manifest.digest.value
        or raw["annotation_protocol_sha256"] != study.raw["annotation_protocol_sha256"]
        or raw["observation_sha256s"]
        != [
            observations[0].digest.value,
            observations[1].digest.value,
            sealed_test_sha256,
        ]
    ):
        raise DomainError("label approval receipt mismatch")
    for key in ("receipt_id", "approver_id", "issued_at"):
        _text(raw[key], key)
    return raw


def _counts(pairs: tuple[ScoredPair, ...]) -> tuple[int, int]:
    positive = sum(1 for pair in pairs if pair.label_positive)
    return positive, len(pairs) - positive


def _confusion(pairs: tuple[ScoredPair, ...], threshold: float) -> dict[str, int]:
    tp = fp = tn = fn = 0
    for pair in pairs:
        predicted = pair.score >= threshold
        if pair.label_positive and predicted:
            tp += 1
        elif pair.label_positive:
            fn += 1
        elif predicted:
            fp += 1
        else:
            tn += 1
    return {"fn": fn, "fp": fp, "tn": tn, "tp": tp}


def _statistics(pairs: tuple[ScoredPair, ...], threshold: float) -> dict[str, Any]:
    tpr, fpr = binary_rates(pairs, threshold)
    positive, negative = _counts(pairs)
    return {
        "sample_count": len(pairs),
        "positive_count": positive,
        "negative_count": negative,
        "tpr": tpr,
        "fpr": fpr,
        "confusion": _confusion(pairs, threshold),
    }


def _test_bindings_sha256(items: object) -> str:
    if type(items) not in {list, tuple}:
        raise DomainError("invalid test bindings")
    keys = ("sample_id", "candidate_sha256", "annotation_record_sha256")
    return hash_bytes(
        canonical_json([{key: item[key] for key in keys} for item in items])
    ).value


def _blocked_report(
    study: _Study,
    manifest: _Manifest,
    commitment_data: bytes,
    commitment: dict[str, Any],
    approval_data: bytes,
    reason: str,
) -> bytes:
    return _prepared_report(
        study,
        manifest,
        commitment_data,
        commitment,
        approval_data,
        "BLOCKED",
        [reason],
        None,
        None,
        None,
    )


def _prepared_report(
    study: _Study,
    manifest: _Manifest,
    commitment_data: bytes,
    commitment: dict[str, Any],
    approval_data: bytes,
    status: str,
    reasons: list[str],
    threshold: float | None,
    calibration: dict[str, Any] | None,
    validation: dict[str, Any] | None,
) -> bytes:
    return canonical_json(
        {
            "schema_version": "specstyle.calibration.prepared_evidence.v1",
            "study_id": study.raw["study_id"],
            "layer": study.raw["layer"],
            "style_pack_id": study.raw["style_pack_id"],
            "domain_profile": study.raw["domain_profile"],
            "output_profiles": study.raw["output_profiles"],
            "metric": study.raw["metric"],
            "verifier_pin": study.raw["verifier_pin"],
            "preprocessor_pin": study.raw["preprocessor_pin"],
            "targets": study.raw["targets"],
            "study_plan_sha256": study.digest.value,
            "sample_manifest_sha256": manifest.digest.value,
            "annotation_protocol_sha256": study.raw["annotation_protocol_sha256"],
            "label_approval_receipt_sha256": hash_bytes(approval_data).value,
            "test_commitment_sha256": hash_bytes(commitment_data).value,
            "sealed_test_observations_sha256": commitment[
                "sealed_test_observations_sha256"
            ],
            "test_sample_ids": commitment["sample_ids"],
            "test_bindings_sha256": _test_bindings_sha256(manifest.by_split["test"]),
            "test_positive_count": commitment["positive_count"],
            "test_negative_count": commitment["negative_count"],
            "status": status,
            "reasons": reasons,
            "threshold": threshold,
            "calibration": calibration,
            "validation": validation,
            "test_held": True,
        }
    )


def prepare_evidence(
    study_plan: bytes,
    annotation_protocol: bytes,
    sample_manifest: bytes,
    calibration_observations: bytes,
    validation_observations: bytes,
    test_commitment: bytes,
    label_approval_receipt: bytes,
) -> bytes:
    """Freeze a threshold without reading test observations or editing Production."""
    study = _load_study(study_plan)
    _verify_annotation_protocol(annotation_protocol, study)
    manifest = _load_manifest(sample_manifest, study)
    calibration = _load_observations(
        calibration_observations, "calibration", study, manifest
    )
    validation = _load_observations(
        validation_observations, "validation", study, manifest
    )
    commitment = _load_commitment(test_commitment, study, manifest)
    approval = _load_label_approval(
        label_approval_receipt,
        study,
        manifest,
        (calibration, validation),
        commitment["sealed_test_observations_sha256"],
    )
    if approval["label_source"] == "SYNTHETIC":
        return _blocked_report(
            study,
            manifest,
            test_commitment,
            commitment,
            label_approval_receipt,
            "BLOCKED_SYNTHETIC_LABELS",
        )
    if not approval["approved"]:
        return _blocked_report(
            study,
            manifest,
            test_commitment,
            commitment,
            label_approval_receipt,
            "BLOCKED_MISSING_APPROVED_LABELS",
        )
    minimum_positive = study.raw["split"]["minimum_positive_per_split"]
    minimum_negative = study.raw["split"]["minimum_negative_per_split"]
    counts = (*_counts(calibration.pairs), *_counts(validation.pairs))
    test_counts = (commitment["positive_count"], commitment["negative_count"])
    if any(
        positive < minimum_positive or negative < minimum_negative
        for positive, negative in (
            counts[:2],
            counts[2:],
            test_counts,
        )
    ):
        return _blocked_report(
            study,
            manifest,
            test_commitment,
            commitment,
            label_approval_receipt,
            "BLOCKED_INSUFFICIENT_SPLIT_LABELS",
        )
    targets = study.raw["targets"]
    try:
        threshold = select_threshold_on_calibration(
            calibration.pairs,
            metric_id=study.raw["metric"]["metric_id"],
            max_fpr=targets["max_fpr"],
            min_tpr=targets["min_tpr"],
        )
    except DomainError as exc:
        if str(exc) != "no threshold meets calibration targets":
            raise
        return _prepared_report(
            study,
            manifest,
            test_commitment,
            commitment,
            label_approval_receipt,
            "REJECTED",
            ["CALIBRATION_TARGETS_NOT_MET"],
            None,
            None,
            None,
        )
    decision = freeze_threshold(
        metric_id=study.raw["metric"]["metric_id"],
        threshold=threshold,
        calibration=calibration.pairs,
        validation=validation.pairs,
        max_fpr=targets["max_fpr"],
        min_tpr=targets["min_tpr"],
    )
    status = decision.status
    reasons = [] if status == "VALIDATION_PASSED" else ["VALIDATION_TARGETS_NOT_MET"]
    return _prepared_report(
        study,
        manifest,
        test_commitment,
        commitment,
        label_approval_receipt,
        status,
        reasons,
        threshold,
        _statistics(calibration.pairs, threshold),
        _statistics(validation.pairs, threshold),
    )


def _load_reveal_receipt(
    data: bytes, prepared_data: bytes, prepared: dict[str, Any], test_sha256: Sha256
) -> dict[str, Any]:
    raw = _exact(
        _load_canonical(data),
        {
            "schema_version",
            "receipt_id",
            "study_id",
            "approval_kind",
            "approved",
            "validation_report_sha256",
            "sealed_test_observations_sha256",
            "approver_id",
            "issued_at",
        },
        "reveal receipt",
    )
    if (
        raw["schema_version"] != "specstyle.calibration.reveal_receipt.v1"
        or raw["study_id"] != prepared["study_id"]
        or raw["approval_kind"] != "REVEAL_TEST"
        or raw["approved"] is not True
        or raw["validation_report_sha256"] != hash_bytes(prepared_data).value
        or raw["sealed_test_observations_sha256"] != test_sha256.value
        or test_sha256.value != prepared["sealed_test_observations_sha256"]
    ):
        raise DomainError("reveal receipt mismatch")
    for key in ("receipt_id", "approver_id", "issued_at"):
        _text(raw[key], key)
    return raw


def _load_prepared(data: bytes) -> dict[str, Any]:
    raw = _exact(_load_canonical(data), _PREPARED_KEYS, "prepared evidence")
    if (
        raw["schema_version"] != "specstyle.calibration.prepared_evidence.v1"
        or raw["status"] != "VALIDATION_PASSED"
        or type(raw["threshold"]) is not float
        or raw["test_held"] is not True
        or type(raw["targets"]) is not dict
    ):
        raise DomainError("prepared evidence is not revealable")
    _sha(raw["sealed_test_observations_sha256"], "sealed test observations")
    return raw


def _pairs_from_revealed(
    raw: dict[str, Any], prepared: dict[str, Any]
) -> tuple[ScoredPair, ...]:
    if (
        raw.get("schema_version") != "specstyle.calibration.observations.v1"
        or raw.get("study_plan_sha256") != prepared["study_plan_sha256"]
        or raw.get("sample_manifest_sha256") != prepared["sample_manifest_sha256"]
        or raw.get("split") != "test"
        or raw.get("metric_id") != prepared["metric"]["metric_id"]
        or raw.get("metric_implementation_pin")
        != prepared["metric"]["implementation_pin"]
        or raw.get("verifier_pin") != prepared["verifier_pin"]
        or raw.get("preprocessor_pin") != prepared["preprocessor_pin"]
        or type(raw.get("observations")) is not list
    ):
        raise DomainError("revealed test binding mismatch")
    pairs: list[ScoredPair] = []
    seen: set[str] = set()
    for value in raw["observations"]:
        item = _exact(value, _OBSERVATION_KEYS, "test observation")
        sample_id = _text(item["sample_id"], "test sample id")
        if sample_id in seen or type(item["label_positive"]) is not bool:
            raise DomainError("invalid revealed test observations")
        seen.add(sample_id)
        _sha(item["candidate_sha256"], "test candidate sha256")
        _sha(item["annotation_record_sha256"], "test annotation record sha256")
        pairs.append(
            ScoredPair(
                sample_id,
                _float(item["score"], "test observation score"),
                item["label_positive"],
            )
        )
    if not pairs:
        raise DomainError("invalid revealed test observations")
    if (
        [pair.sample_id for pair in pairs] != prepared["test_sample_ids"]
        or _test_bindings_sha256(raw["observations"])
        != prepared["test_bindings_sha256"]
        or _counts(tuple(pairs))
        != (prepared["test_positive_count"], prepared["test_negative_count"])
    ):
        raise DomainError("revealed test commitment mismatch")
    return tuple(pairs)


def reveal_test(
    prepared_evidence: bytes,
    test_observations: bytes,
    reveal_authorization_receipt: bytes,
) -> bytes:
    """Reveal a committed test set without changing the frozen threshold."""
    prepared = _load_prepared(prepared_evidence)
    test_document = _load_canonical(test_observations)
    test_sha256 = hash_bytes(test_observations)
    receipt = _load_reveal_receipt(
        reveal_authorization_receipt, prepared_evidence, prepared, test_sha256
    )
    pairs = _pairs_from_revealed(test_document, prepared)
    threshold = prepared["threshold"]
    statistics = _statistics(pairs, threshold)
    targets = prepared["targets"]
    passed = (
        statistics["tpr"] >= targets["min_tpr"]
        and statistics["fpr"] <= targets["max_fpr"]
    )
    return canonical_json(
        {
            "schema_version": "specstyle.calibration.test_reveal.v1",
            "study_id": prepared["study_id"],
            "validation_report_sha256": hash_bytes(prepared_evidence).value,
            "test_observations_sha256": test_sha256.value,
            "reveal_receipt_sha256": hash_bytes(reveal_authorization_receipt).value,
            "status": (
                "TEST_PASSED_PENDING_PRODUCTION_APPROVAL" if passed else "REJECTED"
            ),
            "reasons": [] if passed else ["TEST_TARGETS_NOT_MET"],
            "metric": prepared["metric"],
            "threshold": threshold,
            "calibration": prepared["calibration"],
            "validation": prepared["validation"],
            "test": statistics,
            "eligible_context_status": "CALIBRATED" if passed else "DRAFT",
            "production_approval_required": True,
            "authorization_receipt_id": receipt["receipt_id"],
        }
    )


if __name__ == "__main__":
    from specstyle.calibration.evidence_cli import run

    run()
