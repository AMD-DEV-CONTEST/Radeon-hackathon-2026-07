from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from colorgraph.agent.creative_contracts import canonical_sha256
from colorgraph.agent.creative_corpus import load_creative_knowledge_corpus
from colorgraph.agent.creative_provider import ProviderBoundary
from colorgraph.agent.creative_shadow import ProviderShadowRunReport
from colorgraph.evaluation.creative_agent import (
    CreativeAgentEvaluationBundle,
    CreativeAgentEvaluationReport,
    CreativeEvidenceClass,
    evaluate_creative_agent,
)
from colorgraph.evaluation.creative_critic_calibration import (
    LoadedCreativeCriticCalibration,
    load_creative_critic_calibration,
)
from colorgraph.evaluation.creative_intake import (
    CreativeProductionEvidenceAudit,
    verify_creative_production_manifest,
)
from colorgraph.evaluation.models import StrictEvaluationModel

CREATIVE_AGENT_READINESS_VERSION = "colorgraph.creative-agent-readiness/v1"

CREATIVE_AGENT_TASK_IDS = (
    "CG-AGENT-012",
    "CG-CREATIVE-010",
    "CG-RAG-010",
    "CG-CRITIC-010",
    "CG-AGENT-EVAL-010",
)

CreativeAgentTaskId = Literal[
    "CG-AGENT-012",
    "CG-CREATIVE-010",
    "CG-RAG-010",
    "CG-CRITIC-010",
    "CG-AGENT-EVAL-010",
]


class CreativeRuntimeSafetySnapshot(StrictEvaluationModel):
    """Secret-free runtime state captured when the readiness audit is run."""

    network_enabled: bool
    provider_feature_enabled: bool
    provider_model_configured: bool
    provider_image_input_declared: bool
    provider_strict_output_declared: bool
    provider_maximum_context_tokens: int = Field(ge=0)
    provider_maximum_images: int = Field(ge=0)
    credential_present: bool
    knowledge_corpus_feature_enabled: bool
    knowledge_corpus_path_configured: bool
    critic_calibration_feature_enabled: bool
    critic_calibration_path_configured: bool
    current_runtime_fail_closed: bool

    @model_validator(mode="after")
    def validate_fail_closed_state(self) -> CreativeRuntimeSafetySnapshot:
        expected = not self.network_enabled and not self.provider_feature_enabled
        if self.current_runtime_fail_closed != expected:
            raise ValueError(
                "current_runtime_fail_closed must match the runtime feature flags"
            )
        return self


class CreativeTaskReadinessGate(StrictEvaluationModel):
    task_id: CreativeAgentTaskId
    required_checks: list[str] = Field(min_length=1)
    blockers: list[str]
    eligible_to_archive: bool


class CreativeAgentReadinessReport(StrictEvaluationModel):
    schema_version: Literal["colorgraph.creative-agent-readiness/v1"] = (
        CREATIVE_AGENT_READINESS_VERSION
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    runtime: CreativeRuntimeSafetySnapshot
    runtime_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_sha256: dict[str, str]
    evidence_details: dict[str, str]
    checks: dict[str, bool]
    task_gates: dict[CreativeAgentTaskId, CreativeTaskReadinessGate]
    blockers: list[str]
    all_tasks_eligible_to_archive: bool
    formal_release_gates_passed: bool
    configuration_changed: Literal[False] = False

    @model_validator(mode="after")
    def validate_derived_status(self) -> CreativeAgentReadinessReport:
        if set(self.task_gates) != set(CREATIVE_AGENT_TASK_IDS):
            raise ValueError("readiness report must include all five Agent task gates")
        expected = all(
            gate.eligible_to_archive for gate in self.task_gates.values()
        )
        if (
            self.all_tasks_eligible_to_archive != expected
            or self.formal_release_gates_passed != expected
        ):
            raise ValueError("readiness aggregate status differs from task gates")
        return self


_CHECK_LABELS = {
    "current_runtime_fail_closed": (
        "current runtime is not reset to the fail-closed offline default"
    ),
    "provider_shadow_supplied": "real-provider shadow report is missing",
    "provider_shadow_completed": "no completed real-provider shadow run is evidenced",
    "provider_real_adapter": (
        "no shadow evidence is bound to the real provider adapter"
    ),
    "provider_multimodal_capability": (
        "no usable provider image-input capability is evidenced"
    ),
    "provider_strict_schema_capability": (
        "no strict provider structured-output capability is evidenced"
    ),
    "provider_image_exercised": (
        "no content-hashed provider image input is evidenced"
    ),
    "provider_cloud_consent": (
        "no explicit consent for uploaded provider image data is evidenced"
    ),
    "provider_audit_bound": (
        "no successful provider audit is bound to the shadow request"
    ),
    "provider_response_receipt": "no non-cache provider response receipt is evidenced",
    "provider_graph_unchanged": (
        "no provider shadow evidence proves that project state stayed unchanged"
    ),
    "provider_runtime_bound": (
        "no provider runtime configuration digest is evidenced"
    ),
    "corpus_supplied": "authorized creative corpus is missing",
    "corpus_audit_passed": (
        "creative corpus source, rights, review, or authorization audit failed"
    ),
    "corpus_index_built": "creative corpus was not admitted to the local RAG index",
    "evaluation_supplied": "frozen production expert evaluation bundle is missing",
    "evaluation_is_production": (
        "no production-class creative evaluation is evidenced"
    ),
    "evaluation_manifest_passed": (
        "creative production manifest or raw expert evidence audit failed"
    ),
    "evaluation_all_release_gates": (
        "no creative expert evaluation passes every formal release gate"
    ),
    "evaluation_eligible_default": (
        "no creative expert evaluation is eligible_default"
    ),
    "critic_calibration_supplied": (
        "content-bound Critic calibration source is missing"
    ),
    "critic_calibration_integrity": (
        "no Critic calibration evidence passes the integrity audit"
    ),
    "critic_calibration_authorized": (
        "no Critic expert-correlation and bias gate is authorized"
    ),
    "critic_calibration_evaluation_bound": (
        "Critic calibration is not bound to the same frozen expert evaluation"
    ),
}

_TASK_REQUIREMENTS: dict[CreativeAgentTaskId, tuple[str, ...]] = {
    "CG-AGENT-012": (
        "current_runtime_fail_closed",
        "provider_shadow_supplied",
        "provider_shadow_completed",
        "provider_real_adapter",
        "provider_multimodal_capability",
        "provider_strict_schema_capability",
        "provider_image_exercised",
        "provider_cloud_consent",
        "provider_audit_bound",
        "provider_response_receipt",
        "provider_graph_unchanged",
        "provider_runtime_bound",
    ),
    "CG-CREATIVE-010": (
        "provider_shadow_completed",
        "provider_real_adapter",
        "evaluation_is_production",
        "evaluation_manifest_passed",
        "evaluation_all_release_gates",
        "evaluation_eligible_default",
    ),
    "CG-RAG-010": (
        "corpus_supplied",
        "corpus_audit_passed",
        "corpus_index_built",
        "evaluation_is_production",
        "evaluation_manifest_passed",
        "evaluation_all_release_gates",
        "evaluation_eligible_default",
    ),
    "CG-CRITIC-010": (
        "provider_shadow_completed",
        "provider_real_adapter",
        "critic_calibration_supplied",
        "critic_calibration_integrity",
        "critic_calibration_authorized",
        "critic_calibration_evaluation_bound",
        "evaluation_manifest_passed",
        "evaluation_eligible_default",
    ),
    "CG-AGENT-EVAL-010": (
        "evaluation_supplied",
        "evaluation_is_production",
        "evaluation_manifest_passed",
        "evaluation_all_release_gates",
        "evaluation_eligible_default",
    ),
}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _provided_file(
    value: str | Path | None,
    *,
    evidence_key: str,
    supplied_check: str,
    checks: dict[str, bool],
    evidence_sha256: dict[str, str],
    issues: list[str],
) -> Path | None:
    if value is None or not str(value).strip():
        issues.append(_CHECK_LABELS[supplied_check])
        return None
    path = Path(value).resolve()
    if not path.is_file():
        issues.append(f"{evidence_key} is not a file: {path}")
        return None
    checks[supplied_check] = True
    evidence_sha256[evidence_key] = _sha256_file(path)
    return path


def _audit_provider_shadow(
    path_value: str | Path | None,
    *,
    checks: dict[str, bool],
    evidence_sha256: dict[str, str],
    details: dict[str, str],
    issues: list[str],
) -> ProviderShadowRunReport | None:
    path = _provided_file(
        path_value,
        evidence_key="provider_shadow",
        supplied_check="provider_shadow_supplied",
        checks=checks,
        evidence_sha256=evidence_sha256,
        issues=issues,
    )
    if path is None:
        return None
    try:
        report = ProviderShadowRunReport.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as exc:
        issues.append(f"provider shadow report is invalid: {exc}")
        return None

    details["provider_shadow_status"] = report.status
    details["provider_shadow_role"] = report.role.value
    details["provider_shadow_provider"] = report.provider_id
    details["provider_shadow_model"] = (
        f"{report.model_id}@{report.model_revision}"
    )
    checks["provider_shadow_completed"] = report.status == "completed"
    checks["provider_real_adapter"] = (
        (
            report.provider_id == "openai-responses"
            and report.provider_boundary
            in {ProviderBoundary.OPENAI, ProviderBoundary.OPENAI_COMPATIBLE}
        )
        or (
            report.provider_id
            in {
                "ollama-chat-local",
                "ollama-chat-structural-local",
                "ollama-generate-structural-local",
                "ollama-responses-local",
                "ollama-responses-structural-local",
            }
            and report.provider_boundary == ProviderBoundary.LOCAL
            and report.model_revision.startswith("ollama-")
            and "/sha256:" in report.model_revision
        )
    )
    checks["provider_multimodal_capability"] = (
        report.provider_capabilities.image_input
        and report.provider_capabilities.maximum_images > 0
    )
    checks["provider_strict_schema_capability"] = (
        report.provider_capabilities.strict_structured_output
    )
    checks["provider_image_exercised"] = bool(report.image_digests)
    checks["provider_cloud_consent"] = (
        not report.image_digests
        or report.provider_boundary == ProviderBoundary.LOCAL
        or report.cloud_upload_consent
    )
    checks["provider_graph_unchanged"] = not report.project_state_mutated
    checks["provider_runtime_bound"] = bool(report.runtime_configuration_digest)
    audit = report.audit
    checks["provider_audit_bound"] = (
        report.status == "completed"
        and audit is not None
        and audit.success
        and audit.request_digest == report.request_digest
        and audit.provider_id == report.provider_id
        and audit.model_id == report.model_id
        and audit.model_revision == report.model_revision
    )
    checks["provider_response_receipt"] = bool(
        audit is not None and audit.response_id
    )
    return report


def _audit_corpus(
    path_value: str | Path | None,
    *,
    checks: dict[str, bool],
    evidence_sha256: dict[str, str],
    details: dict[str, str],
    issues: list[str],
) -> None:
    path = _provided_file(
        path_value,
        evidence_key="creative_corpus",
        supplied_check="corpus_supplied",
        checks=checks,
        evidence_sha256=evidence_sha256,
        issues=issues,
    )
    if path is None:
        return
    try:
        loaded = load_creative_knowledge_corpus(path)
    except (OSError, ValueError) as exc:
        issues.append(f"creative corpus is invalid: {exc}")
        return
    details["creative_corpus"] = (
        f"{loaded.corpus.corpus_id}@{loaded.corpus.corpus_version}"
    )
    checks["corpus_audit_passed"] = loaded.audit.passed
    checks["corpus_index_built"] = loaded.index is not None
    issues.extend(
        f"creative corpus: {issue}" for issue in loaded.audit.issues
    )


def _audit_evaluation(
    path_value: str | Path | None,
    *,
    checks: dict[str, bool],
    evidence_sha256: dict[str, str],
    details: dict[str, str],
    issues: list[str],
) -> tuple[
    CreativeAgentEvaluationReport | None,
    CreativeProductionEvidenceAudit | None,
]:
    path = _provided_file(
        path_value,
        evidence_key="creative_evaluation_bundle",
        supplied_check="evaluation_supplied",
        checks=checks,
        evidence_sha256=evidence_sha256,
        issues=issues,
    )
    if path is None:
        return None, None
    try:
        bundle = CreativeAgentEvaluationBundle.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as exc:
        issues.append(f"creative evaluation bundle is invalid: {exc}")
        return None, None

    production_audit = None
    if bundle.production_manifest is not None:
        root = path.parent.resolve()
        manifest_path = (
            root / bundle.production_manifest.relative_path
        ).resolve()
        if not manifest_path.is_relative_to(root):
            issues.append("creative production manifest escapes the evaluation root")
        else:
            production_audit = verify_creative_production_manifest(
                bundle,
                manifest_path,
                expected_manifest_sha256=bundle.production_manifest.sha256,
            )
            issues.extend(
                f"creative production evidence: {issue}"
                for issue in production_audit.issues
            )
    report = evaluate_creative_agent(
        bundle,
        production_evidence_audit=production_audit,
    )
    details["creative_evaluation_id"] = report.evaluation_id
    details["creative_evaluation_dataset"] = report.dataset_version
    details["creative_evaluation_status"] = report.release_status
    checks["evaluation_is_production"] = (
        report.evidence_class == CreativeEvidenceClass.PRODUCTION
    )
    checks["evaluation_manifest_passed"] = bool(
        production_audit is not None and production_audit.passed
    )
    checks["evaluation_all_release_gates"] = bool(
        report.gates and all(report.gates.values())
    )
    checks["evaluation_eligible_default"] = (
        report.release_status == "eligible_default"
    )
    return report, production_audit


def _audit_critic_calibration(
    path_value: str | Path | None,
    *,
    checks: dict[str, bool],
    evidence_sha256: dict[str, str],
    details: dict[str, str],
    issues: list[str],
) -> LoadedCreativeCriticCalibration | None:
    path = _provided_file(
        path_value,
        evidence_key="critic_calibration",
        supplied_check="critic_calibration_supplied",
        checks=checks,
        evidence_sha256=evidence_sha256,
        issues=issues,
    )
    if path is None:
        return None
    try:
        loaded = load_creative_critic_calibration(path)
    except (OSError, ValueError) as exc:
        issues.append(f"Critic calibration source is invalid: {exc}")
        return None
    details["critic_calibration_id"] = loaded.source.calibration_id
    details["critic_calibration_status"] = (
        "authorized" if loaded.audit.calibration_authorized else "blocked"
    )
    checks["critic_calibration_integrity"] = (
        loaded.audit.evidence_integrity_passed
    )
    checks["critic_calibration_authorized"] = (
        loaded.audit.calibration_authorized
        and loaded.gate is not None
        and loaded.gate.authorized
    )
    issues.extend(
        f"Critic calibration: {issue}" for issue in loaded.audit.issues
    )
    return loaded


def _build_task_gates(
    checks: dict[str, bool],
) -> dict[CreativeAgentTaskId, CreativeTaskReadinessGate]:
    gates: dict[CreativeAgentTaskId, CreativeTaskReadinessGate] = {}
    for task_id, required_checks in _TASK_REQUIREMENTS.items():
        blockers = [
            _CHECK_LABELS[check]
            for check in required_checks
            if not checks.get(check, False)
        ]
        gates[task_id] = CreativeTaskReadinessGate(
            task_id=task_id,
            required_checks=list(required_checks),
            blockers=blockers,
            eligible_to_archive=not blockers,
        )
    return gates


def audit_creative_agent_readiness(
    *,
    runtime: CreativeRuntimeSafetySnapshot,
    provider_shadow_path: str | Path | None = None,
    corpus_path: str | Path | None = None,
    critic_calibration_path: str | Path | None = None,
    evaluation_bundle_path: str | Path | None = None,
) -> CreativeAgentReadinessReport:
    checks = {label: False for label in _CHECK_LABELS}
    checks["current_runtime_fail_closed"] = runtime.current_runtime_fail_closed
    evidence_sha256: dict[str, str] = {}
    details: dict[str, str] = {}
    issues: list[str] = []

    _audit_provider_shadow(
        provider_shadow_path,
        checks=checks,
        evidence_sha256=evidence_sha256,
        details=details,
        issues=issues,
    )
    _audit_corpus(
        corpus_path,
        checks=checks,
        evidence_sha256=evidence_sha256,
        details=details,
        issues=issues,
    )
    evaluation, _ = _audit_evaluation(
        evaluation_bundle_path,
        checks=checks,
        evidence_sha256=evidence_sha256,
        details=details,
        issues=issues,
    )
    calibration = _audit_critic_calibration(
        critic_calibration_path,
        checks=checks,
        evidence_sha256=evidence_sha256,
        details=details,
        issues=issues,
    )
    checks["critic_calibration_evaluation_bound"] = bool(
        calibration is not None
        and evaluation is not None
        and calibration.audit.evaluation_id == evaluation.evaluation_id
        and calibration.audit.dataset_version == evaluation.dataset_version
    )

    task_gates = _build_task_gates(checks)
    all_ready = all(gate.eligible_to_archive for gate in task_gates.values())
    blockers = list(dict.fromkeys(
        [
            *issues,
            *(
                blocker
                for gate in task_gates.values()
                for blocker in gate.blockers
            ),
        ]
    ))
    return CreativeAgentReadinessReport(
        runtime=runtime,
        runtime_snapshot_sha256=canonical_sha256(runtime),
        evidence_sha256=evidence_sha256,
        evidence_details=details,
        checks=checks,
        task_gates=task_gates,
        blockers=blockers,
        all_tasks_eligible_to_archive=all_ready,
        formal_release_gates_passed=all_ready,
    )


def audit_creative_agent_readiness_file(
    *,
    output_path: str | Path,
    runtime: CreativeRuntimeSafetySnapshot,
    provider_shadow_path: str | Path | None = None,
    corpus_path: str | Path | None = None,
    critic_calibration_path: str | Path | None = None,
    evaluation_bundle_path: str | Path | None = None,
) -> CreativeAgentReadinessReport:
    report = audit_creative_agent_readiness(
        runtime=runtime,
        provider_shadow_path=provider_shadow_path,
        corpus_path=corpus_path,
        critic_calibration_path=critic_calibration_path,
        evaluation_bundle_path=evaluation_bundle_path,
    )
    destination = Path(output_path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    temporary.replace(destination)
    return report
