#!/usr/bin/env python3
"""Retire the known legacy AMD smoke threshold without claiming validation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Mapping, Sequence

import specstyle.deployment.context_migration as engine
from specstyle.deployment.context_migration import (
    ContextMigrationPlan,
    ContextMigrationPolicyError,
    ContextSnapshot,
    LoaderExpectation,
    thaw_json,
)

_PLAN_ID = "retire-legacy-smoke-threshold"
_AUDIT_SCHEMA = "specstyle.legacy-smoke-threshold-retirement.v1"
_SOURCE_REJECTION = "VALIDATED threshold requires production context v3"
_PIN = {
    "id": "l2-profile",
    "revision": "r1",
    "sha256": "b" * 64,
}
_METRIC = {
    "metric_id": "reference_style_statistics_similarity",
    "operator": ">=",
    "value": 0.5,
}
_EVIDENCE = {
    "calibration_dataset_sha256": (
        "f2318b1927fe2a51d38b52aa0a9798007be35b2217e2694f048be79bf02890ca"
    ),
    "validation_dataset_sha256": (
        "48e44f5358f88e859ad7735b0bebc19e8405c37e827ad639295d3cb9f92b9a18"
    ),
    "annotation_protocol_sha256": (
        "fb07c5c128e528ea8b527e94aae81829b8086c91a2ca105b1457fdbf7acb75b2"
    ),
}


def _plain_mapping(value: object) -> dict[str, object]:
    thawed = thaw_json(value)
    if type(thawed) is not dict:
        raise ContextMigrationPolicyError("legacy smoke signature mismatch")
    return thawed


def _expected_threshold(status: str) -> dict[str, object]:
    return {
        "pin": dict(_PIN),
        "logical_name": "l2-product-instance",
        "status": status,
        "style_pack_id": "preset",
        "metric": dict(_METRIC),
        "evidence": dict(_EVIDENCE),
    }


def _recognize(snapshot: ContextSnapshot, status: str) -> None:
    document = _plain_mapping(snapshot.document)
    if document.get(
        "schema_version"
    ) != "specstyle.production.context.v1" or document.get(
        "l2_threshold_profile"
    ) != _expected_threshold(status):
        raise ContextMigrationPolicyError("legacy smoke signature mismatch")


def _recognize_source(snapshot: ContextSnapshot) -> None:
    _recognize(snapshot, "VALIDATED")
    if snapshot.loaded is not None or snapshot.loader_error != _SOURCE_REJECTION:
        raise ContextMigrationPolicyError("legacy source loader mismatch")


def _recognize_target(snapshot: ContextSnapshot) -> None:
    _recognize(snapshot, "DRAFT")
    loaded = snapshot.loaded
    threshold = getattr(loaded, "l2_threshold_profile", None)
    if (
        loaded is None
        or snapshot.loader_error is not None
        or getattr(loaded, "schema_version", None) != "specstyle.production.context.v1"
        or getattr(threshold, "status", None) != "DRAFT"
        or getattr(threshold, "production_binding", None) is not None
    ):
        raise ContextMigrationPolicyError("retired target loader mismatch")


def _transform(snapshot: ContextSnapshot) -> Mapping[str, object]:
    _recognize_source(snapshot)
    document = _plain_mapping(snapshot.document)
    threshold = document["l2_threshold_profile"]
    if type(threshold) is not dict:
        raise ContextMigrationPolicyError("legacy smoke signature mismatch")
    threshold["status"] = "DRAFT"
    return document


_PLAN = ContextMigrationPlan(
    plan_id=_PLAN_ID,
    audit_schema=_AUDIT_SCHEMA,
    source_loader=LoaderExpectation(
        "EXPECTED_EXACT_REJECTION", exact_error=_SOURCE_REJECTION
    ),
    target_loader=LoaderExpectation("PASS"),
    recognize_source=_recognize_source,
    recognize_target=_recognize_target,
    transform=_transform,
    applied_status="RETIRED",
    already_status="ALREADY_RETIRED",
    rollback_status="ROLLED_BACK_TO_KNOWN_INVALID_SOURCE",
)


def retire_legacy_smoke_threshold(
    *,
    config_root: Path,
    context_evidence_root: Path,
    audit_root: Path,
    expected_before_sha256: str,
    apply: bool,
) -> dict[str, object]:
    return engine.run_context_migration(
        config_root=config_root,
        context_evidence_root=context_evidence_root,
        audit_root=audit_root,
        expected_before_sha256=expected_before_sha256,
        apply=apply,
        plan=_PLAN,
    )


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Retire legacy AMD smoke threshold")
    parser.add_argument("--config-root", type=Path, required=True)
    parser.add_argument("--context-evidence-root", type=Path, required=True)
    parser.add_argument("--audit-root", type=Path, required=True)
    parser.add_argument("--expected-before-sha256", required=True)
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parse_args(argv)
    result = retire_legacy_smoke_threshold(
        config_root=arguments.config_root,
        context_evidence_root=arguments.context_evidence_root,
        audit_root=arguments.audit_root,
        expected_before_sha256=arguments.expected_before_sha256,
        apply=arguments.apply,
    )
    sys.stdout.write(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n")
    return 0 if result["status"] in {"RETIRED", "ALREADY_RETIRED"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
