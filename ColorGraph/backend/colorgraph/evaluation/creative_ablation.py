from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from colorgraph.evaluation.creative_agent import (
    CREATIVE_ABLATION_EXECUTION_VERSION,
    CreativePipelineStage,
    CreativePipelineVariant,
    CreativeVariantExecution,
)
from colorgraph.evaluation.creative_intake import (
    CreativeArtifactReference,
    sha256_file,
)
from colorgraph.evaluation.models import StrictEvaluationModel

CREATIVE_ABLATION_SEED_VERSION = "colorgraph.creative-ablation-seed/v2"
CREATIVE_ABLATION_SEED_AUDIT_VERSION = (
    "colorgraph.creative-ablation-seed-audit/v2"
)
CREATIVE_ABLATION_MATRIX_VERSION = "colorgraph.creative-ablation-matrix/v1"
CREATIVE_ABLATION_MATRIX_AUDIT_VERSION = (
    "colorgraph.creative-ablation-matrix-audit/v1"
)


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


class CreativeAblationProviderEvidence(StrictEvaluationModel):
    provider_id: str = Field(min_length=1)
    runtime_version: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    model_revision: str = Field(min_length=1)
    successful_calls: int = Field(ge=0)
    total_calls: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_calls(self) -> CreativeAblationProviderEvidence:
        if self.successful_calls > self.total_calls:
            raise ValueError("successful ablation calls exceed total calls")
        return self


class CreativeDirectionDistanceEvidence(StrictEvaluationModel):
    metric: Literal["colorgraph.mean-rgb-l1/v1"]
    definition: str = Field(min_length=1)
    pair_order: list[str]
    values: list[float]
    mean: float = Field(ge=0, le=1)
    formal_full_pipeline_threshold: float = Field(ge=0, le=1)
    formal_full_pipeline_gate_passed: bool

    @model_validator(mode="after")
    def validate_summary(self) -> CreativeDirectionDistanceEvidence:
        if len(self.pair_order) != len(self.values):
            raise ValueError("direction distance labels and values differ")
        if len(self.pair_order) != len(set(self.pair_order)):
            raise ValueError("direction distance pair labels must be unique")
        if any(
            not math.isfinite(value) or not 0 <= value <= 1
            for value in self.values
        ):
            raise ValueError("direction distances must be finite values in [0, 1]")
        observed_mean = sum(self.values) / len(self.values) if self.values else 0
        if not math.isclose(self.mean, observed_mean, abs_tol=1e-12):
            raise ValueError("direction distance mean is stale")
        if self.formal_full_pipeline_gate_passed != (
            self.mean >= self.formal_full_pipeline_threshold
        ):
            raise ValueError("direction diversity gate result is stale")
        return self


class CreativeAblationEvaluationCoverage(StrictEvaluationModel):
    test_items_present: int = Field(ge=1)
    minimum_rule_baseline_pairs: int = Field(ge=10)
    rule_baseline_pairs_present: int = Field(ge=0)
    variants_present: list[CreativePipelineVariant] = Field(min_length=1)
    missing_variants: list[CreativePipelineVariant]
    production_candidate_observation_ready: Literal[False] = False

    @model_validator(mode="after")
    def validate_variants(self) -> CreativeAblationEvaluationCoverage:
        if len(self.variants_present) != len(set(self.variants_present)):
            raise ValueError("present ablation variants must be unique")
        if len(self.missing_variants) != len(set(self.missing_variants)):
            raise ValueError("missing ablation variants must be unique")
        expected_missing = [
            variant
            for variant in CreativePipelineVariant
            if variant not in self.variants_present
        ]
        if self.missing_variants != expected_missing:
            raise ValueError("ablation coverage missing-variant list is stale")
        return self


class CreativeAblationSeedManifest(StrictEvaluationModel):
    schema_version: Literal["colorgraph.creative-ablation-seed/v2"] = (
        CREATIVE_ABLATION_SEED_VERSION
    )
    created_at: AwareDatetime
    project_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    item_id: str = Field(min_length=1)
    candidate_id: str = Field(min_length=1)
    variant: CreativePipelineVariant
    status: Literal["technical_ablation_seed"] = "technical_ablation_seed"
    formal_review_freeze: Literal[False] = False
    release_effect: Literal["none_shadow_only"] = "none_shadow_only"
    provider: CreativeAblationProviderEvidence
    execution: CreativeArtifactReference
    source_media: CreativeArtifactReference
    source_graph: CreativeArtifactReference
    run_request: CreativeArtifactReference
    pipeline_result: CreativeArtifactReference
    output: CreativeArtifactReference
    stage_evidence: dict[CreativePipelineStage, CreativeArtifactReference]
    direction_distance: CreativeDirectionDistanceEvidence
    evaluation_coverage: CreativeAblationEvaluationCoverage
    formal_blockers: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_seed(self) -> CreativeAblationSeedManifest:
        if self.evaluation_coverage.variants_present != [self.variant]:
            raise ValueError("technical seed must describe exactly its own variant")
        paths = [
            self.execution.relative_path,
            self.source_media.relative_path,
            self.source_graph.relative_path,
            self.run_request.relative_path,
            self.output.relative_path,
            *(
                reference.relative_path
                for reference in self.stage_evidence.values()
            ),
        ]
        if len(paths) != len(set(paths)):
            raise ValueError("ablation seed artifact paths must be unique")
        if (
            self.pipeline_result.relative_path
            in set(paths)
            and self.pipeline_result.relative_path
            not in {
                reference.relative_path
                for reference in self.stage_evidence.values()
            }
        ):
            raise ValueError(
                "pipeline result may only alias its matching stage evidence"
            )
        return self


class CreativeAblationSeedAudit(StrictEvaluationModel):
    schema_version: Literal[
        "colorgraph.creative-ablation-seed-audit/v2"
    ] = CREATIVE_ABLATION_SEED_AUDIT_VERSION
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    project_id: str
    run_id: str
    item_id: str
    candidate_id: str
    variant: CreativePipelineVariant
    checked_artifacts: int = Field(ge=0)
    execution_protocol_valid: bool
    formal_review_freeze: Literal[False] = False
    formal_release_eligible: Literal[False] = False
    issues: list[str]
    passed: bool


class CreativeAblationMatrixManifest(StrictEvaluationModel):
    schema_version: Literal["colorgraph.creative-ablation-matrix/v1"] = (
        CREATIVE_ABLATION_MATRIX_VERSION
    )
    evaluation_id: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    created_at: AwareDatetime
    required_test_items: Literal[10] = 10
    required_variants: list[CreativePipelineVariant] = Field(
        default_factory=lambda: list(CreativePipelineVariant)
    )
    seed_manifests: list[CreativeArtifactReference] = Field(min_length=1)
    formal_review_freeze: Literal[False] = False
    release_effect: Literal["none_shadow_only"] = "none_shadow_only"

    @model_validator(mode="after")
    def validate_matrix(self) -> CreativeAblationMatrixManifest:
        if self.required_variants != list(CreativePipelineVariant):
            raise ValueError(
                "creative ablation matrix must preserve the frozen eight-variant order"
            )
        paths = [item.relative_path for item in self.seed_manifests]
        digests = [item.sha256 for item in self.seed_manifests]
        if len(paths) != len(set(paths)):
            raise ValueError("creative ablation seed manifest paths must be unique")
        if len(digests) != len(set(digests)):
            raise ValueError("creative ablation seed manifests must be content-unique")
        return self


class CreativeAblationItemCoverage(StrictEvaluationModel):
    item_id: str = Field(min_length=1)
    source_media_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    source_graph_artifact_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    variants_present: list[CreativePipelineVariant]
    missing_variants: list[CreativePipelineVariant]
    full_pipeline_direction_diversity_passed: bool
    complete: bool
    issues: list[str]

    @model_validator(mode="after")
    def validate_coverage(self) -> CreativeAblationItemCoverage:
        if len(self.variants_present) != len(set(self.variants_present)):
            raise ValueError("item ablation variants must be unique")
        expected_missing = [
            variant
            for variant in CreativePipelineVariant
            if variant not in self.variants_present
        ]
        if self.missing_variants != expected_missing:
            raise ValueError("item missing-variant list is stale")
        expected_complete = (
            not expected_missing
            and self.full_pipeline_direction_diversity_passed
            and not self.issues
        )
        if self.complete != expected_complete:
            raise ValueError("item ablation completeness is stale")
        return self


class CreativeAblationMatrixAudit(StrictEvaluationModel):
    schema_version: Literal[
        "colorgraph.creative-ablation-matrix-audit/v1"
    ] = CREATIVE_ABLATION_MATRIX_AUDIT_VERSION
    evaluation_id: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    checked_seed_manifests: int = Field(ge=0)
    passed_seed_manifests: int = Field(ge=0)
    unique_test_items: int = Field(ge=0)
    required_test_items: Literal[10] = 10
    complete_test_items: int = Field(ge=0)
    item_coverage: list[CreativeAblationItemCoverage]
    technical_evidence_integrity_passed: bool
    technical_matrix_complete: bool
    formal_review_freeze: Literal[False] = False
    formal_release_eligible: Literal[False] = False
    blockers: list[str]
    passed: bool

    @model_validator(mode="after")
    def validate_audit(self) -> CreativeAblationMatrixAudit:
        if self.checked_seed_manifests < self.passed_seed_manifests:
            raise ValueError("passed seed count exceeds checked seed count")
        if self.unique_test_items != len(self.item_coverage):
            raise ValueError("ablation matrix item count is stale")
        if self.complete_test_items != sum(
            item.complete for item in self.item_coverage
        ):
            raise ValueError("ablation matrix complete-item count is stale")
        expected_complete = (
            self.technical_evidence_integrity_passed
            and self.unique_test_items >= self.required_test_items
            and self.complete_test_items == self.unique_test_items
        )
        if self.technical_matrix_complete != expected_complete:
            raise ValueError("ablation technical matrix result is stale")
        if self.passed != self.technical_matrix_complete:
            raise ValueError("ablation matrix pass result is stale")
        if self.passed == bool(self.blockers):
            raise ValueError("ablation matrix blockers and pass result disagree")
        return self


def _resolve_reference(
    root: Path,
    reference: CreativeArtifactReference,
) -> Path:
    resolved_root = root.resolve()
    path = (resolved_root / reference.relative_path).resolve()
    if not path.is_relative_to(resolved_root):
        raise ValueError(
            f"creative ablation artifact escapes its root: "
            f"{reference.relative_path!r}"
        )
    return path


def _verify_reference(
    root: Path,
    reference: CreativeArtifactReference,
    *,
    label: str,
    issues: list[str],
) -> Path | None:
    try:
        path = _resolve_reference(root, reference)
    except ValueError as exc:
        issues.append(str(exc))
        return None
    if not path.is_file():
        issues.append(f"{label} is missing: {reference.relative_path}")
        return None
    actual = sha256_file(path)
    if actual != reference.sha256:
        issues.append(
            f"{label} digest mismatch: expected {reference.sha256}, got {actual}"
        )
        return None
    return path


def audit_creative_ablation_seed(
    manifest_path: str | Path,
) -> CreativeAblationSeedAudit:
    source = Path(manifest_path).resolve()
    manifest = CreativeAblationSeedManifest.model_validate_json(
        source.read_text(encoding="utf-8")
    )
    root = source.parent
    issues: list[str] = []
    checked = 0
    references = [
        ("execution", manifest.execution),
        ("source media", manifest.source_media),
        ("source graph", manifest.source_graph),
        ("run request", manifest.run_request),
        ("pipeline result", manifest.pipeline_result),
        ("output", manifest.output),
        *(
            (f"{stage.value} stage", reference)
            for stage, reference in manifest.stage_evidence.items()
        ),
    ]
    verified: dict[str, Path] = {}
    for label, reference in references:
        path = _verify_reference(
            root,
            reference,
            label=label,
            issues=issues,
        )
        if path is not None:
            checked += 1
            verified[label] = path

    execution: CreativeVariantExecution | None = None
    execution_path = verified.get("execution")
    if execution_path is not None:
        try:
            execution = CreativeVariantExecution.model_validate_json(
                execution_path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as exc:
            issues.append(f"ablation execution manifest is invalid: {exc}")
    if execution is not None:
        if (
            execution.schema_version != CREATIVE_ABLATION_EXECUTION_VERSION
            or execution.candidate_id != manifest.candidate_id
            or execution.item_id != manifest.item_id
            or execution.variant != manifest.variant
        ):
            issues.append(
                "ablation execution identity does not match the seed manifest"
            )
        for label, expected, observed in (
            (
                "source media",
                execution.source_media_sha256,
                manifest.source_media.sha256,
            ),
            (
                "source graph",
                execution.source_graph_artifact_sha256,
                manifest.source_graph.sha256,
            ),
            (
                "run request",
                execution.run_request_sha256,
                manifest.run_request.sha256,
            ),
            (
                "pipeline result",
                execution.pipeline_result_sha256,
                manifest.pipeline_result.sha256,
            ),
            ("output", execution.output_sha256, manifest.output.sha256),
        ):
            if expected != observed:
                issues.append(
                    f"ablation {label} is not bound to the execution manifest"
                )
        expected_stage_evidence = {
            stage: digest
            for stage, digest in execution.stage_evidence_sha256.items()
        }
        observed_stage_evidence = {
            stage: reference.sha256
            for stage, reference in manifest.stage_evidence.items()
        }
        if observed_stage_evidence != expected_stage_evidence:
            issues.append(
                "ablation stage evidence is not bound to the execution manifest"
            )
        if (
            manifest.direction_distance.values
            != execution.direction_pairwise_distances
        ):
            issues.append(
                "direction distance evidence differs from the execution manifest"
            )
        pipeline_result_path = verified.get("pipeline result")
        if pipeline_result_path is not None:
            try:
                pipeline_result = json.loads(
                    pipeline_result_path.read_text(encoding="utf-8")
                )
            except (OSError, ValueError) as exc:
                issues.append(f"ablation pipeline result is invalid: {exc}")
            else:
                if pipeline_result.get("current_graph_unchanged") is not True:
                    issues.append(
                        "ablation pipeline result changed the current graph"
                    )
                reflection_executed = bool(
                    pipeline_result.get("reflection_stage_executed", False)
                )
                reflection_completed = bool(
                    pipeline_result.get("reflection_completed", False)
                )
                if (
                    manifest.variant == CreativePipelineVariant.FULL_PIPELINE
                    and (not reflection_executed or not reflection_completed)
                ):
                    issues.append(
                        "full_pipeline seed did not execute and complete Reflection"
                    )
                if (
                    manifest.variant == CreativePipelineVariant.NO_REFLECTION
                    and reflection_executed
                ):
                    issues.append(
                        "no_reflection seed unexpectedly executed Reflection"
                    )

    return CreativeAblationSeedAudit(
        manifest_sha256=sha256_file(source),
        project_id=manifest.project_id,
        run_id=manifest.run_id,
        item_id=manifest.item_id,
        candidate_id=manifest.candidate_id,
        variant=manifest.variant,
        checked_artifacts=checked,
        execution_protocol_valid=execution is not None,
        issues=issues,
        passed=not issues,
    )


def audit_creative_ablation_seed_file(
    manifest_path: str | Path,
    output_path: str | Path,
) -> CreativeAblationSeedAudit:
    audit = audit_creative_ablation_seed(manifest_path)
    destination = Path(output_path).resolve()
    _atomic_write(
        destination,
        json.dumps(
            audit.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
    )
    return audit


def audit_creative_ablation_matrix(
    manifest_path: str | Path,
) -> CreativeAblationMatrixAudit:
    source = Path(manifest_path).resolve()
    manifest = CreativeAblationMatrixManifest.model_validate_json(
        source.read_text(encoding="utf-8")
    )
    root = source.parent
    blockers: list[str] = []
    integrity_issues: list[str] = []
    checked = 0
    passed = 0
    seeds_by_item: dict[
        str,
        dict[CreativePipelineVariant, CreativeAblationSeedManifest],
    ] = defaultdict(dict)
    item_issues: dict[str, list[str]] = defaultdict(list)

    for reference in manifest.seed_manifests:
        reference_issues: list[str] = []
        seed_path = _verify_reference(
            root,
            reference,
            label="ablation seed manifest",
            issues=reference_issues,
        )
        blockers.extend(reference_issues)
        integrity_issues.extend(reference_issues)
        if seed_path is None:
            continue
        checked += 1
        try:
            seed = CreativeAblationSeedManifest.model_validate_json(
                seed_path.read_text(encoding="utf-8")
            )
            seed_audit = audit_creative_ablation_seed(seed_path)
        except (OSError, ValueError) as exc:
            issue = (
                f"ablation seed manifest is invalid: "
                f"{reference.relative_path}: {exc}"
            )
            blockers.append(issue)
            integrity_issues.append(issue)
            continue
        if not seed_audit.passed:
            issues = [
                f"{seed.item_id}/{seed.variant.value}: {issue}"
                for issue in seed_audit.issues
            ]
            blockers.extend(issues)
            integrity_issues.extend(issues)
            continue
        passed += 1
        existing = seeds_by_item[seed.item_id].get(seed.variant)
        if existing is not None:
            issue = (
                f"duplicate seed for {seed.item_id}/{seed.variant.value}"
            )
            blockers.append(issue)
            integrity_issues.append(issue)
            item_issues[seed.item_id].append(issue)
            continue
        seeds_by_item[seed.item_id][seed.variant] = seed

    coverage: list[CreativeAblationItemCoverage] = []
    for item_id in sorted(seeds_by_item):
        variants = seeds_by_item[item_id]
        media_digests = {
            seed.source_media.sha256 for seed in variants.values()
        }
        graph_digests = {
            seed.source_graph.sha256 for seed in variants.values()
        }
        if len(media_digests) != 1:
            issue = (
                f"{item_id} variants do not share one frozen source media digest"
            )
            blockers.append(issue)
            integrity_issues.append(issue)
            item_issues[item_id].append(issue)
        if len(graph_digests) != 1:
            issue = (
                f"{item_id} variants do not share one frozen source graph artifact"
            )
            blockers.append(issue)
            integrity_issues.append(issue)
            item_issues[item_id].append(issue)
        variants_present = [
            variant
            for variant in CreativePipelineVariant
            if variant in variants
        ]
        missing = [
            variant
            for variant in CreativePipelineVariant
            if variant not in variants
        ]
        if missing:
            issue = (
                f"{item_id} is missing variants: "
                + ", ".join(item.value for item in missing)
            )
            blockers.append(issue)
            item_issues[item_id].append(issue)
        full_pipeline = variants.get(CreativePipelineVariant.FULL_PIPELINE)
        diversity_passed = bool(
            full_pipeline is not None
            and full_pipeline.direction_distance.formal_full_pipeline_gate_passed
        )
        if full_pipeline is not None and not diversity_passed:
            issue = (
                f"{item_id} full_pipeline direction diversity did not pass"
            )
            blockers.append(issue)
            item_issues[item_id].append(issue)
        issues = list(dict.fromkeys(item_issues[item_id]))
        coverage.append(
            CreativeAblationItemCoverage(
                item_id=item_id,
                source_media_sha256=(
                    next(iter(media_digests))
                    if len(media_digests) == 1
                    else None
                ),
                source_graph_artifact_sha256=(
                    next(iter(graph_digests))
                    if len(graph_digests) == 1
                    else None
                ),
                variants_present=variants_present,
                missing_variants=missing,
                full_pipeline_direction_diversity_passed=diversity_passed,
                complete=not missing and diversity_passed and not issues,
                issues=issues,
            )
        )

    if len(coverage) < manifest.required_test_items:
        blockers.append(
            "creative ablation matrix requires at least "
            f"{manifest.required_test_items} frozen test items; found "
            f"{len(coverage)}"
        )
    integrity_passed = (
        checked == len(manifest.seed_manifests)
        and passed == checked
        and not integrity_issues
    )
    complete_items = sum(item.complete for item in coverage)
    matrix_complete = (
        integrity_passed
        and len(coverage) >= manifest.required_test_items
        and complete_items == len(coverage)
    )
    return CreativeAblationMatrixAudit(
        evaluation_id=manifest.evaluation_id,
        dataset_version=manifest.dataset_version,
        manifest_sha256=sha256_file(source),
        checked_seed_manifests=checked,
        passed_seed_manifests=passed,
        unique_test_items=len(coverage),
        complete_test_items=complete_items,
        item_coverage=coverage,
        technical_evidence_integrity_passed=integrity_passed,
        technical_matrix_complete=matrix_complete,
        blockers=list(dict.fromkeys(blockers)),
        passed=matrix_complete,
    )


def audit_creative_ablation_matrix_file(
    manifest_path: str | Path,
    output_path: str | Path,
) -> CreativeAblationMatrixAudit:
    audit = audit_creative_ablation_matrix(manifest_path)
    destination = Path(output_path).resolve()
    _atomic_write(
        destination,
        json.dumps(
            audit.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
    )
    return audit
