#!/usr/bin/env python3
"""Explicitly enable audited LCM compiler capability in an AMD runtime context."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

import specstyle.deployment.context_migration as engine
from specstyle.deployment.context_migration import (
    ContextMigrationPlan,
    ContextMigrationPolicyError,
    ContextSnapshot,
    LoaderExpectation,
    thaw_json,
)
from specstyle.errors import DomainError
from specstyle.production.context_config import require_model_pipeline_support

_OLD_PIPELINES = ["sdxl_turbo", "sdxl_base"]
_LCM_PIPELINES = ["sdxl_turbo", "lcm", "sdxl_base"]
_ROLES = ("base", "ip_adapter", "controlnet")


def _document(snapshot: ContextSnapshot) -> dict[str, object]:
    value = thaw_json(snapshot.document)
    if type(value) is not dict:
        raise ContextMigrationPolicyError("model support refused")
    return value


def _support_state(document: dict[str, object], expected: list[str]) -> None:
    support = document.get("model_support")
    if type(support) is not list or len(support) != len(_ROLES):
        raise ContextMigrationPolicyError("model support refused")
    for item, role in zip(support, _ROLES, strict=True):
        if (
            type(item) is not dict
            or set(item) != {"role", "supported_pipelines"}
            or item["role"] != role
            or item["supported_pipelines"] != expected
        ):
            raise ContextMigrationPolicyError("model support refused")


def _recognize_source(snapshot: ContextSnapshot) -> None:
    if snapshot.loaded is None or snapshot.loader_error is not None:
        raise ContextMigrationPolicyError("source loader refused")
    _support_state(_document(snapshot), _OLD_PIPELINES)


def _recognize_target(snapshot: ContextSnapshot) -> None:
    if snapshot.loaded is None or snapshot.loader_error is not None:
        raise ContextMigrationPolicyError("target loader refused")
    _support_state(_document(snapshot), _LCM_PIPELINES)
    try:
        require_model_pipeline_support(snapshot.loaded, "lcm", _ROLES)
    except DomainError as exc:
        raise ContextMigrationPolicyError("LCM capability missing") from exc


def _transform(snapshot: ContextSnapshot) -> dict[str, object]:
    _recognize_source(snapshot)
    document = _document(snapshot)
    support = document["model_support"]
    if type(support) is not list:
        raise ContextMigrationPolicyError("model support refused")
    for item in support:
        if type(item) is not dict:
            raise ContextMigrationPolicyError("model support refused")
        item["supported_pipelines"] = list(_LCM_PIPELINES)
    return document


_PLAN = ContextMigrationPlan(
    plan_id="enable-preview-lcm",
    audit_schema="specstyle.preview-lcm-context-migration.v1",
    source_loader=LoaderExpectation("PASS"),
    target_loader=LoaderExpectation("PASS"),
    recognize_source=_recognize_source,
    recognize_target=_recognize_target,
    transform=_transform,
    applied_status="APPLIED",
    already_status="ALREADY_ENABLED",
    rollback_status="ROLLED_BACK",
)


def migrate_preview_lcm_context(
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
    parser = argparse.ArgumentParser(description="Enable audited Preview LCM context")
    parser.add_argument("--config-root", type=Path, required=True)
    parser.add_argument("--context-evidence-root", type=Path, required=True)
    parser.add_argument("--audit-root", type=Path, required=True)
    parser.add_argument("--expected-before-sha256", required=True)
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parse_args(argv)
    result = migrate_preview_lcm_context(
        config_root=arguments.config_root,
        context_evidence_root=arguments.context_evidence_root,
        audit_root=arguments.audit_root,
        expected_before_sha256=arguments.expected_before_sha256,
        apply=arguments.apply,
    )
    sys.stdout.write(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n")
    return 0 if result["status"] in {"APPLIED", "ALREADY_ENABLED"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
