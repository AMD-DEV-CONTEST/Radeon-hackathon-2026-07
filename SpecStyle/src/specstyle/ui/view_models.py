"""UI view models — pure data for presenters."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SpecEditorView:
    schema_version: str
    spec_id: str
    compile_ok: bool
    errors: tuple[str, ...]
    compiled_hash: str | None


@dataclass(frozen=True, slots=True)
class JobStatusView:
    job_id: str
    status: str
    message: str
    can_cancel: bool
    profile_label: str  # "preview" | "production" | ""


@dataclass(frozen=True, slots=True)
class QaRuleView:
    rule_id: str
    status: (
        str  # PASS|FAIL|WARNING|UNVERIFIABLE — never mapped to green PASS if not PASS
    )
    score: float | None
    display_class: str  # css/semantic: pass|fail|warning|unverifiable


@dataclass(frozen=True, slots=True)
class ExportView:
    bundle_name: str
    approved_count: int
    rejected_count: int
    manual_review_count: int
    bundle_sha256: str | None


@dataclass(frozen=True, slots=True)
class RepairStepView:
    artifact_id: str
    rounds: int
    stop_reason: str | None


@dataclass(frozen=True, slots=True)
class ReplayView:
    status: str  # EXACT|COMPATIBLE|REJECTED
    mode: str
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProductionRunUiView:
    job_id: str
    status: str
    message: str
    profile_label: str
    bundle_name: str
    bundle_sha256: str | None
    approved_images: tuple[str, ...]
    rejected_images: tuple[str, ...]
    qa_table: str


@dataclass(frozen=True, slots=True)
class ProductionBatchItemUiView:
    item_index: int
    requested_variation_index: int
    initial_seed: int | None
    final_variation_index: int | None
    final_seed: int | None
    run: ProductionRunUiView
    cleanup_error: str | None


@dataclass(frozen=True, slots=True)
class ProductionBatchUiView:
    status: str
    message: str
    profile_label: str
    items: tuple[ProductionBatchItemUiView, ...]
    final_seed_collision: bool
    diversity_evidence: bool
    approved_images: tuple[str, ...]
    rejected_images: tuple[str, ...]
    evidence_tsv: str


@dataclass(frozen=True, slots=True)
class PreviewReadinessUiView:
    status: str
    message: str


@dataclass(frozen=True, slots=True)
class PreviewRunUiView:
    run_id: str
    status: str
    message: str
    profile_label: str
    display_images: tuple[str, ...]
    execution_fingerprint: str | None
    verification: str
    repair: str
    export: str


@dataclass(frozen=True, slots=True)
class PreviewWallItemUiView:
    variation_index: int
    attempted: bool
    run_id: str
    status: str
    reason_code: str
    seed: int | None
    content_sha256: str | None
    execution_fingerprint: str | None
    display_image: str | None


@dataclass(frozen=True, slots=True)
class PreviewWallUiView:
    wall_id: str
    status: str
    message: str
    profile_label: str
    evidence_class: str
    items: tuple[PreviewWallItemUiView, ...]
    display_images: tuple[str, ...]
    evidence_tsv: str
    verification: str
    repair: str
    export: str
