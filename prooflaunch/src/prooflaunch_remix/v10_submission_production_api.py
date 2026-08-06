from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import time
from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, BinaryIO, Callable, Mapping
from urllib.parse import parse_qs, urlparse

from .gtm_blind_review_service import (
    BlindReviewAuthorizationError,
    BlindReviewConflictError,
    BlindReviewService,
    BlindReviewServiceError,
)
from .gtm_portfolio_blind_review_service import PortfolioBlindReviewService
from .campaign_pack_blind_review import (
    CampaignPackBlindReviewAuthorizationError,
    CampaignPackBlindReviewConflictError,
    CampaignPackBlindReviewError,
    CampaignPackBlindReviewService,
)
from .gtm_judge_calibration import (
    JudgeCalibrationAuthorizationError,
    JudgeCalibrationConflictError,
    JudgeCalibrationError,
    JudgeCalibrationService,
)
from .gtm_platform_generation_quality import (
    verify_platform_generation_quality_audit,
)
from .gtm_platform_native_challenger import (
    verify_platform_native_challenger_plan,
    verify_platform_native_receipt,
)
from .gtm_codex_integrated_campaign import (
    verify_codex_integrated_campaign_portfolio,
)
from .gtm_codex_campaign_work_order import (
    verify_codex_campaign_adaptation_matrix,
)
from .gtm_codex_lighthouse_portfolio import (
    verify_lighthouse_portfolio,
    verify_lighthouse_quality_portfolio,
)
from .social_collection import connector_registry, plan_social_collection
from .files import atomic_write_text
from .gtm_frontier_cloud_agent import FrontierGTMAgentError, execute_frontier_gtm_agent
from .inference_gateway import OpenAICompatibleThirdPartyClient, load_third_party_provider_specs
from .realtime_preset_campaign import (
    RealtimePresetCampaignError,
    compile_realtime_preset_campaign,
)
from .production_guardrails import (
    GuardrailBlockedError,
    GuardrailTelemetryLedger,
    POLICY_VERSION as GUARDRAIL_POLICY_VERSION,
    evaluate_guardrails,
)
from .production_trace_ledger import ProductionTraceLedger
from .launch_proof_control import (
    LaunchProofControlError,
    compile_launch_proof_control,
)

from .v10_submission_runtime import (
    ProductionAgencyService,
    ProductionRuntimeError,
)
from .v10_submission_store import (
    ConflictError,
    IdempotencyConflict,
    IntegrityError,
    SubmissionStoreError,
)


_RUN_ID = r"run-[0-9a-f]{24}"
_SHA256 = r"[0-9a-f]{64}"
_ASSET_ID = r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}"
_TENANT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_MAX_JSON_BYTES = 1_000_000
_MAX_PNG_BYTES = 20_000_000
_MAX_WAV_BYTES = 100_000_000
_MAX_MP4_BYTES = 500_000_000
_MAX_UPLOAD_BYTES = max(_MAX_PNG_BYTES, _MAX_WAV_BYTES, _MAX_MP4_BYTES)
_TERMINAL_PUBLIC = frozenset({"delivered", "blocked", "failed", "rejected", "cancelled"})


class TenantAuthenticationError(PermissionError):
    """No configured tenant principal authenticated the request."""


class _LimitedReader:
    def __init__(self, source: BinaryIO, length: int) -> None:
        self.source = source
        self.remaining = length

    def read(self, size: int = -1) -> bytes:
        if self.remaining <= 0:
            return b""
        requested = self.remaining if size < 0 else min(size, self.remaining)
        chunk = self.source.read(requested)
        self.remaining -= len(chunk)
        return chunk


def _public_status(status: str) -> str:
    return "delivered" if status == "bundle_ready" else status


def _json_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _validate_uploaded_media_signature(path: Path, media_type: str) -> None:
    with path.open("rb") as handle:
        header = handle.read(32)
    valid = (
        media_type == "image/png" and header.startswith(b"\x89PNG\r\n\x1a\n")
    ) or (
        media_type == "audio/wav"
        and header.startswith(b"RIFF")
        and header[8:12] == b"WAVE"
    ) or (
        media_type == "video/mp4" and len(header) >= 12 and header[4:8] == b"ftyp"
    ) or media_type == "application/json"
    if not valid:
        raise ProductionRuntimeError(
            "artifact content signature disagrees with its declared media type"
        )


def load_verified_synthetic_lifecycle_demo(project_root: Path) -> dict[str, Any]:
    """Load the sealed two-device lifecycle demo without granting live authority."""

    root = project_root.resolve(strict=True)
    receipt_path = root / "evidence/v10/gtm-revenue-memory-demo.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if (
        receipt.get("schema") != "ProofLaunchRevenueMemoryEndToEndDemoV1"
        or receipt.get("data_class") != "synthetic"
        or receipt.get("external_api_calls") != 0
        or receipt.get("external_publish_executed") is not False
        or receipt.get("paid_media_spend_usd") != 0
        or not isinstance(receipt.get("artifacts"), list)
        or not isinstance(receipt.get("gates"), Mapping)
    ):
        raise IntegrityError("synthetic lifecycle demo receipt is malformed")
    unsigned_receipt = dict(receipt)
    supplied_receipt_digest = unsigned_receipt.pop("content_sha256", None)
    if supplied_receipt_digest != hashlib.sha256(
        _json_bytes(unsigned_receipt)
    ).hexdigest():
        raise IntegrityError("synthetic lifecycle demo receipt digest is invalid")
    gates = receipt["gates"]
    required_false_gates = (
        "automatic_strategy_mutation_executed",
        "automatic_budget_activation_executed",
        "automatic_external_action_executed",
        "synthetic_revenue_is_production_evidence",
        "four_a_effect_claim_eligible",
    )
    if any(gates.get(name) is not False for name in required_false_gates):
        raise IntegrityError("synthetic lifecycle demo authority boundary is invalid")
    device_b_receipt = receipt.get("device_b")
    if (
        not isinstance(device_b_receipt, Mapping)
        or device_b_receipt.get("next_cycle_eligible_memory_count") != 1
        or device_b_receipt.get("next_cycle_memory_conflict_count") != 0
        or device_b_receipt.get("next_cycle_memory_application_status")
        != "eligible_pending_human_application"
        or device_b_receipt.get("next_cycle_memory_human_application_required")
        is not True
        or not re.fullmatch(
            _SHA256,
            str(device_b_receipt.get("next_cycle_memory_decision_sha256", "")),
        )
    ):
        raise IntegrityError("synthetic lifecycle memory arbitration is invalid")

    verified_artifacts: dict[str, Path] = {}
    for item in receipt["artifacts"]:
        if not isinstance(item, Mapping):
            raise IntegrityError("synthetic lifecycle demo artifact is malformed")
        relative = item.get("path")
        expected_sha256 = item.get("sha256")
        expected_bytes = item.get("bytes")
        if (
            not isinstance(relative, str)
            or not relative.startswith("artifacts/gtm-revenue-memory-demo-v1/")
            or not re.fullmatch(_SHA256, str(expected_sha256))
            or type(expected_bytes) is not int
            or expected_bytes < 1
        ):
            raise IntegrityError("synthetic lifecycle demo artifact binding is invalid")
        candidate = (root / relative).resolve(strict=True)
        try:
            candidate.relative_to(root / "artifacts/gtm-revenue-memory-demo-v1")
        except ValueError as error:
            raise IntegrityError(
                "synthetic lifecycle demo artifact escaped its root"
            ) from error
        if candidate.is_symlink() or not candidate.is_file():
            raise IntegrityError("synthetic lifecycle demo artifact is not regular")
        body = candidate.read_bytes()
        if (
            len(body) != expected_bytes
            or hashlib.sha256(body).hexdigest() != expected_sha256
        ):
            raise IntegrityError("synthetic lifecycle demo artifact failed verification")
        verified_artifacts[candidate.name] = candidate

    cockpits: dict[str, dict[str, Any]] = {}
    for device, filename in (
        ("device_a", "device-a-final-gtm-cockpit.json"),
        ("device_b", "device-b-next-cycle-gtm-cockpit.json"),
    ):
        path = verified_artifacts.get(filename)
        if path is None:
            raise IntegrityError("synthetic lifecycle demo cockpit is missing")
        cockpit = json.loads(path.read_text(encoding="utf-8"))
        unsigned_cockpit = dict(cockpit)
        supplied_cockpit_digest = unsigned_cockpit.pop("content_sha256", None)
        if (
            cockpit.get("schema") != "ProofLaunchGTMCockpitV1"
            or supplied_cockpit_digest
            != hashlib.sha256(_json_bytes(unsigned_cockpit)).hexdigest()
            or cockpit.get("four_a_effect_claim_eligible") is not False
            or cockpit.get("top1_claim_eligible") is not False
            or cockpit.get("human_boundary", {}).get("automatic_publish_enabled")
            is not False
            or cockpit.get("human_boundary", {}).get("automatic_send_enabled")
            is not False
            or cockpit.get("human_boundary", {}).get("automatic_spend_enabled")
            is not False
            or cockpit.get("human_boundary", {}).get(
                "automatic_strategy_mutation_enabled"
            )
            is not False
            or cockpit.get("cross_device_memory", {}).get(
                "automatic_strategy_mutation_executed"
            )
            is not False
            or cockpit.get("cross_device_memory", {}).get(
                "automatic_schedule_mutation_executed"
            )
            is not False
            or cockpit.get("cross_device_memory", {}).get(
                "automatic_budget_activation_executed"
            )
            is not False
            or cockpit.get("cross_device_memory", {}).get(
                "human_application_required"
            )
            is not True
            or cockpit.get("cross_device_memory", {}).get("source_run_mutated")
            is not False
            or cockpit.get("cross_device_memory", {}).get(
                "future_resolution_recorded"
            )
            is not False
            or cockpit.get("cross_device_memory", {}).get(
                "future_resolution_complete"
            )
            is not False
            or cockpit.get("cross_device_memory", {}).get(
                "future_resolution_remaining_channels"
            )
            != []
            or not isinstance(
                cockpit.get("cross_device_memory", {}).get("conflicts"), list
            )
            or not isinstance(
                cockpit.get("cross_device_memory", {}).get(
                    "unresolved_conflict_channels"
                ),
                list,
            )
            or not isinstance(
                cockpit.get("cross_device_memory", {}).get("selected_directives"),
                list,
            )
            or not re.fullmatch(
                r"[0-9a-f]{64}",
                str(
                    cockpit.get("cross_device_memory", {}).get(
                        "application_sha256", ""
                    )
                ),
            )
            or not re.fullmatch(
                r"[0-9a-f]{64}",
                str(
                    cockpit.get("cross_device_memory", {}).get(
                        "resolution_context_sha256", ""
                    )
                ),
            )
        ):
            raise IntegrityError("synthetic lifecycle demo cockpit is invalid")
        cockpits[device] = cockpit

    if (
        cockpits["device_b"]["cross_device_memory"].get("eligible_memory_count")
        != 1
        or cockpits["device_b"]["cross_device_memory"].get("conflict_count") != 0
        or cockpits["device_b"]["cross_device_memory"].get("application_status")
        != "eligible_pending_human_application"
        or cockpits["device_b"]["cross_device_memory"].get("decision_sha256")
        != device_b_receipt["next_cycle_memory_decision_sha256"]
        or cockpits["device_b"]["cross_device_memory"].get(
            "effective_application_status"
        )
        != "eligible_pending_named_human_application"
        or len(
            cockpits["device_b"]["cross_device_memory"].get(
                "selected_directives", []
            )
        )
        != 1
        or cockpits["device_a"]["cross_device_memory"].get(
            "effective_application_status"
        )
        != "no_applicable_human_memory"
    ):
        raise IntegrityError("synthetic lifecycle device-B decision is inconsistent")

    envelope: dict[str, Any] = {
        "schema": "ProofLaunchSyntheticLifecycleDemoV1",
        "evidence_class": "synthetic_mechanics_only",
        "receipt_content_sha256": supplied_receipt_digest,
        "device_a": cockpits["device_a"],
        "device_b": cockpits["device_b"],
        "external_api_calls": 0,
        "external_publish_executed": False,
        "paid_media_spend_usd": 0,
        "production_effect_proven": False,
        "four_a_effect_claim_eligible": False,
        "truth_boundary": receipt["truth_boundary"],
    }
    envelope["content_sha256"] = hashlib.sha256(_json_bytes(envelope)).hexdigest()
    return envelope


def load_verified_platform_capability_showcase(project_root: Path) -> dict[str, Any]:
    """Expose clean-room B2B/B2C craft references without release authority."""

    root = project_root.resolve(strict=True)
    bundle_specs = (
        (
            "b2b",
            root
            / "artifacts/gtm-last-mile-pk-v1/platform-native-challengers-v6/b2b-plan.json",
            root
            / "artifacts/gtm-last-mile-pk-v1/platform-native-challengers-v13/b2b-codex-capability-reference-v2-receipt.json",
            root
            / "evidence/v10/gtm-platform-codex-capability-reference-quality-audit-v2.json",
        ),
        (
            "b2c",
            root
            / "artifacts/gtm-last-mile-pk-v1/platform-native-challengers-v6/b2c-plan.json",
            root
            / "artifacts/gtm-last-mile-pk-v1/platform-native-challengers-v14/b2c-codex-reference-v1-receipt.json",
            root
            / "evidence/v10/gtm-platform-b2c-codex-reference-quality-audit-v1.json",
        ),
    )
    public_bundles: list[dict[str, Any]] = []
    for business_model, plan_path, receipt_path, audit_path in bundle_specs:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        verify_platform_native_challenger_plan(plan)
        verify_platform_native_receipt(receipt, plan=plan)
        verify_platform_generation_quality_audit(audit)
        rows = {str(row["surface_id"]): row for row in audit["rows"]}
        b2c_capability = business_model == "b2c"
        if (
            plan.get("business_model") != business_model
            or receipt.get("business_model") != business_model
            or receipt.get("model", {}).get("provider")
            != "codex_workspace_clean_room_reference_authoring"
            or receipt.get("model", {}).get("reference_only") is not True
            or receipt.get("accepted_surface_count") != 13
            or audit.get("plan_sha256") != plan.get("content_sha256")
            or audit.get("receipt_sha256") != receipt.get("content_sha256")
            or audit.get("pre_human_quality_pass_count") != 13
            or audit.get("blocked_count") != 0
            or audit.get("cross_surface_duplicate_pairs")
            or audit.get("human_craft_review_completed_count") != 0
            or audit.get("production_effect_observed") is not False
            or audit.get("four_a_claim_eligible") is not False
            or audit.get("top1_claim_eligible") is not False
            or (audit.get("capability_reference_only") is True) != b2c_capability
            or (
                b2c_capability
                and (
                    audit.get("mechanically_publication_ready_count") != 0
                    or audit.get("publication_blocked_count") != 13
                )
            )
        ):
            raise IntegrityError("platform capability showcase binding is invalid")
        candidates: list[dict[str, Any]] = []
        for candidate in receipt["accepted_candidates"]:
            surface_id = str(candidate["surface_id"])
            row = rows.get(surface_id)
            if row is None or row.get("pre_human_quality_pass") is not True:
                raise IntegrityError("platform capability showcase row is invalid")
            candidates.append(
                {
                    "surface_id": surface_id,
                    "campaign_platform": candidate["campaign_platform"],
                    "hook": candidate["hook"],
                    "progression": list(candidate["progression"]),
                    "body": list(candidate["body"]),
                    "cta": candidate["cta"],
                    "participation_mechanism": candidate[
                        "participation_mechanism"
                    ],
                    "proof_integration": candidate["proof_integration"],
                    "falsifier": candidate["falsifier"],
                    "candidate_sha256": candidate["content_sha256"],
                    "capability_quality_pass": True,
                    "release_eligible": False,
                    "publication_state": (
                        "blocked_synthetic_benchmark"
                        if b2c_capability
                        else "reference_only_pending_human_review"
                    ),
                }
            )
        public_bundles.append(
            {
                "business_model": business_model,
                "brief": {
                    key: plan["brief"][key]
                    for key in (
                        "brief_id",
                        "product_name",
                        "audience",
                        "problem",
                        "offer",
                    )
                },
                "surface_count": 13,
                "pre_human_quality_pass_count": 13,
                "release_eligible_count": 0,
                "human_review_completed_count": 0,
                "production_effect_observed": False,
                "named_product_baseline": False,
                "publication_policy_state": (
                    "permanently_blocked_synthetic_benchmark"
                    if b2c_capability
                    else "reference_only_pending_human_review"
                ),
                "source_receipt_sha256": receipt["content_sha256"],
                "source_quality_audit_sha256": audit["content_sha256"],
                "candidates": candidates,
            }
        )
    payload: dict[str, Any] = {
        "schema": "ProofLaunchPlatformCapabilityShowcasePublicV1",
        "business_model_count": 2,
        "surface_count_per_business_model": 13,
        "candidate_count": 26,
        "pre_human_quality_pass_count": 26,
        "release_eligible_count": 0,
        "human_review_completed_count": 0,
        "production_effect_observed": False,
        "named_product_baseline_count": 0,
        "four_a_claim_eligible": False,
        "top1_claim_eligible": False,
        "automatic_publish_enabled": False,
        "bundles": public_bundles,
        "truth_boundary": (
            "These are Codex-authored clean-room capability references. B2B remains reference-only pending human review; "
            "B2C is a permanently unpublishable synthetic benchmark. Neither is named-product, preference, effect, revenue, 4A or Top-1 evidence."
        ),
    }
    payload["content_sha256"] = hashlib.sha256(_json_bytes(payload)).hexdigest()
    return payload


def load_verified_codex_integrated_campaign_portfolio(
    project_root: Path,
) -> dict[str, Any]:
    """Expose sealed B2B/B2C campaign systems without granting release authority."""

    root = project_root.resolve(strict=True)
    path = root / "evidence/v10/gtm-codex-integrated-campaign-portfolio-v1.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    verify_codex_integrated_campaign_portfolio(payload)
    if (
        payload.get("release_eligible_count") != 0
        or payload.get("human_review_completed_count") != 0
        or payload.get("production_effect_observed") is not False
        or payload.get("causal_effect_claim_allowed") is not False
        or payload.get("external_publish_executed") is not False
        or payload.get("automatic_send_spend_or_strategy_mutation") is not False
        or payload.get("paid_media_spend_usd") != 0
    ):
        raise IntegrityError("Codex integrated campaign portfolio gained false authority")
    return payload


def load_verified_codex_campaign_adaptation_summary(
    project_root: Path,
) -> dict[str, Any]:
    """Expose a compact verified view of the 456 Codex-ready scenario contracts."""

    root = project_root.resolve(strict=True)
    path = root / "evidence/v10/gtm-codex-campaign-adaptation-matrix-v1.json"
    matrix = json.loads(path.read_text(encoding="utf-8"))
    verify_codex_campaign_adaptation_matrix(matrix)
    if (
        matrix.get("model_call_count") != 0
        or matrix.get("candidate_output_count") != 0
        or matrix.get("human_review_completed_count") != 0
        or matrix.get("release_eligible_count") != 0
        or matrix.get("external_publish_executed_count") != 0
        or matrix.get("production_effect_observed_count") != 0
        or matrix.get("causal_effect_claim_allowed_count") != 0
    ):
        raise IntegrityError("Codex campaign adaptation matrix gained false authority")

    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for work_order in matrix["work_orders"]:
        archetype = str(work_order["immutable_brief"]["industry_archetype"])
        grouped.setdefault(archetype, []).append(work_order)
    archetypes: list[dict[str, Any]] = []
    for archetype, rows in sorted(grouped.items()):
        operating = rows[0]["industry_operating_contract"]
        archetypes.append(
            {
                "industry_archetype": archetype,
                "work_order_count": len(rows),
                "business_models": sorted(
                    {str(row["immutable_brief"]["business_model"]) for row in rows}
                ),
                "lifecycles": sorted(
                    {str(row["immutable_brief"]["lifecycle"]) for row in rows}
                ),
                "budgets": sorted(
                    {str(row["immutable_brief"]["budget"]) for row in rows}
                ),
                "primary_channels": sorted(
                    {str(row["strategy_contract"]["primary_channel"]) for row in rows}
                ),
                "conversion_unit": operating["conversion_unit"],
                "buying_motion": operating["buying_motion"],
                "zero_budget_growth_engine": operating["zero_budget_growth_engine"],
                "human_classification_confirmation_required": any(
                    bool(
                        row["industry_operating_contract"][
                            "human_classification_confirmation_required"
                        ]
                    )
                    for row in rows
                ),
            }
        )
    protocol = matrix["generation_protocol"]
    output = protocol["required_output_contract"]
    summary: dict[str, Any] = {
        "schema": "ProofLaunchCodexCampaignAdaptationSummaryPublicV1",
        "source_matrix_sha256": matrix["content_sha256"],
        "autonomy_level": protocol["autonomy_level"],
        "graph_stage_count": len(protocol["graph"]),
        "named_failure_mode_count": len(protocol["named_failure_modes"]),
        "maximum_generation_attempts": protocol["termination_conditions"][
            "maximum_generation_attempts"
        ],
        "maximum_critic_repair_rounds": protocol["termination_conditions"][
            "maximum_critic_repair_rounds"
        ],
        "industry_archetype_count": matrix["industry_archetype_count"],
        "business_model_count": matrix["business_model_count"],
        "lifecycle_count": matrix["lifecycle_count"],
        "budget_count": matrix["budget_count"],
        "case_count": matrix["case_count"],
        "zero_budget_work_order_count": matrix["zero_budget_work_order_count"],
        "regulated_work_order_count": matrix["regulated_work_order_count"],
        "human_classification_confirmation_required_count": matrix[
            "human_classification_confirmation_required_count"
        ],
        "distinct_primary_channel_count": matrix["distinct_primary_channel_count"],
        "overlapping_platform_work_order_count": matrix[
            "overlapping_platform_work_order_count"
        ],
        "fully_overlapping_channel_surface_work_order_count": matrix[
            "fully_overlapping_channel_surface_work_order_count"
        ],
        "empty_secondary_platform_surface_work_order_count": matrix[
            "empty_secondary_platform_surface_work_order_count"
        ],
        "output_contract": {
            "platform_native_asset_count": output["platform_native_assets"]["count"],
            "lifecycle_phase_count": output["lifecycle_phases"]["count"],
            "email_count": output["email_sequence"]["count"],
            "multimodal_direction_count": output["production_directions"]["count"],
            "search_geo_node_count": output["search_geo_nodes"]["count"],
            "flight_slot_count": output["seven_day_flight"]["count"],
            "experiment_count": output["experiment_registry"]["count"],
        },
        "model_call_count": 0,
        "candidate_output_count": 0,
        "human_review_completed_count": 0,
        "release_eligible_count": 0,
        "external_publish_executed_count": 0,
        "production_effect_observed_count": 0,
        "causal_effect_claim_allowed_count": 0,
        "archetypes": archetypes,
        "truth_boundary": matrix["truth_boundary"],
    }
    summary["content_sha256"] = hashlib.sha256(_json_bytes(summary)).hexdigest()
    return summary


def load_verified_codex_lighthouse_portfolio(
    project_root: Path,
) -> dict[str, Any]:
    """Expose eight real Codex-workspace candidates and separate Level-1 receipts."""

    root = project_root.resolve(strict=True)
    portfolio = json.loads(
        (root / "evidence/v10/gtm-codex-lighthouse-portfolio-v1.json").read_text(
            encoding="utf-8"
        )
    )
    quality = json.loads(
        (root / "evidence/v10/gtm-codex-lighthouse-quality-audit-v1.json").read_text(
            encoding="utf-8"
        )
    )
    verify_lighthouse_portfolio(portfolio)
    verify_lighthouse_quality_portfolio(quality, portfolio=portfolio)
    if (
        quality.get("level_1_pass_count") != 8
        or quality.get("level_1_reject_count") != 0
        or quality.get("qualified_human_review_count") != 0
        or quality.get("release_eligible_count") != 0
        or quality.get("external_publish_executed_count") != 0
        or quality.get("external_action_count") != 0
        or quality.get("production_effect_observed_count") != 0
        or quality.get("causal_revenue_effect_proven_count") != 0
        or quality.get("four_a_quality_proven") is not False
        or quality.get("top1_claim_eligible") is not False
    ):
        raise IntegrityError("Codex lighthouse portfolio gained false authority")
    cases: list[dict[str, Any]] = []
    for candidate, receipt in zip(
        portfolio["candidates"], quality["audits"], strict=True
    ):
        cases.append(
            {
                "candidate_id": candidate["candidate_id"],
                "candidate_sha256": candidate["content_sha256"],
                "selector": candidate["selector"],
                "authorship": candidate["authorship"],
                "fixture": candidate["fixture"],
                "campaign_system": candidate["campaign_system"],
                "channel_decision": candidate["channel_decision"],
                "platform_assets": candidate["platform_assets"],
                "email": candidate["email"],
                "seo_page": candidate["seo_page"],
                "geo_answer": candidate["geo_answer"],
                "video_script": candidate["video_script"],
                "experiment": candidate["experiment"],
                "level_1_audit": {
                    "receipt_sha256": receipt["content_sha256"],
                    "passed": receipt["passed"],
                    "gate_count": receipt["level_1"]["gate_count"],
                    "critical_failure_count": receipt["failure_count"],
                    "status": receipt["status"],
                    "release_eligible": receipt["release_eligible"],
                    "human_preference_observed": receipt[
                        "human_preference_observed"
                    ],
                    "production_effect_observed": receipt[
                        "production_effect_observed"
                    ],
                },
                "truth_boundary": candidate["truth_boundary"],
            }
        )
    payload: dict[str, Any] = {
        "schema": "ProofLaunchCodexLighthousePortfolioPublicV1",
        "source_portfolio_sha256": portfolio["content_sha256"],
        "source_quality_sha256": quality["content_sha256"],
        "candidate_count": 8,
        "workspace_authored_candidate_count": 8,
        "flagship_api_inference_observed_count": 0,
        "business_model_count": 2,
        "industry_archetype_count": 8,
        "lifecycle_count_per_business_model": 4,
        "budget_tier_count": 3,
        "regulated_candidate_count": 2,
        "platform_asset_count": 16,
        "email_count": 8,
        "seo_page_count": 8,
        "geo_answer_count": 8,
        "video_script_count": 8,
        "experiment_count": 8,
        "level_1_audit_pass_count": 8,
        "calibrated_model_critic_pass_count": 0,
        "qualified_human_review_count": 0,
        "release_eligible_count": 0,
        "external_publish_executed_count": 0,
        "external_action_count": 0,
        "production_effect_observed_count": 0,
        "causal_revenue_effect_proven_count": 0,
        "named_product_pk_completed_count": 0,
        "four_a_quality_proven": False,
        "top1_claim_eligible": False,
        "cases": cases,
        "truth_boundary": (
            "These are eight real clean-room campaign candidates authored directly in the Codex workspace and bound to deterministic work orders. "
            "Their 8/8 Level-1 receipts prove mechanics only; no API telemetry, human preference, release, publication, production effect, revenue, 4A quality, Top-1 standing or named-product superiority is proven."
        ),
    }
    payload["content_sha256"] = hashlib.sha256(_json_bytes(payload)).hexdigest()
    return payload


class ProductionHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def production_handler_factory(
    service: ProductionAgencyService,
    web_root: Path,
    *,
    approval_token: str,
    approver_identity: str,
    tenant_tokens: Mapping[str, str],
    memory_capsule_secret: bytes,
    product_readiness_path: Path | None = None,
    public_signal_pilot_path: Path | None = None,
    platform_market_expansion_path: Path | None = None,
    social_oss_landscape_path: Path | None = None,
    blind_review_service: BlindReviewService | None = None,
    portfolio_blind_review_service: PortfolioBlindReviewService | None = None,
    judge_calibration_service: JudgeCalibrationService | None = None,
    campaign_pack_blind_review_service: CampaignPackBlindReviewService | None = None,
    guardrail_ledger: GuardrailTelemetryLedger | None = None,
    trace_ledger: ProductionTraceLedger | None = None,
    local_evaluation_session: tuple[str, str] | None = None,
) -> type[BaseHTTPRequestHandler]:
    root = web_root.resolve(strict=True)
    readiness_path = (
        product_readiness_path.resolve()
        if product_readiness_path is not None
        else root.parent / "evidence/v10/aug3-product-readiness.json"
    )
    signal_pilot_path = (
        public_signal_pilot_path.resolve()
        if public_signal_pilot_path is not None
        else root.parent / "artifacts/public-signal-gtm-pilot-v1/pilot-receipt.json"
    )
    platform_expansion_path = (
        platform_market_expansion_path.resolve()
        if platform_market_expansion_path is not None
        else root.parent / "evidence/v10/gtm-platform-market-expansion-queue-v6.json"
    )
    oss_landscape_path = (
        social_oss_landscape_path.resolve()
        if social_oss_landscape_path is not None
        else root.parent / "evidence/v10/gtm-social-oss-adapter-landscape-v5.json"
    )
    last_mile_quality_path = (
        root.parent / "evidence/v10/gtm-last-mile-production-quality-v1.json"
    )
    concrete_product_effect_pk_path = (
        root.parent / "evidence/v10/gtm-concrete-product-effect-pk-ledger-v1.json"
    )
    named_product_baseline_capture_kit_path = (
        root.parent
        / "artifacts/gtm-last-mile-pk-v1/named-product-baseline-capture-kit-v1/manifest.json"
    )
    named_product_pk_portfolio_path = (
        root.parent / "evidence/v10/named-product-pk-portfolio-v1.json"
    )
    named_product_challenger_admission_path = (
        root.parent
        / "artifacts/gtm-last-mile-pk-v1/named-product-challenger-dossiers-v1/manifest.json"
    )
    gtm_hybrid_quality_control_path = (
        root.parent / "evidence/v10/gtm-hybrid-quality-control-v1.json"
    )
    gtm_adaptive_capability_graph_path = (
        root.parent / "evidence/v10/gtm-adaptive-capability-graph-matrix-v1.json"
    )
    qualification_path = root.parent / "evidence/v10/local-multimodal-qualification.json"
    campaign_pack_root = (
        root.parent / "evidence/v10/local-campaign-pack-v1/delivery-v6"
    ).resolve()
    campaign_pack_manifest_path = campaign_pack_root / "campaign-pack-manifest.json"
    project_root = root.parent
    radeon_live_preflight_path = project_root / "evidence/v10/radeon-live-preflight.json"
    telemetry = guardrail_ledger or GuardrailTelemetryLedger(
        service.store.root / "guardrails",
        retention_days=90,
    )
    request_traces = trace_ledger or ProductionTraceLedger(
        service.store.root / "production-traces",
        retention_days=90,
    )
    qualification_assets = {
        "speech-master": ("speech_master", "audio/wav"),
        "video-one-stage": ("video_one_stage", "video/mp4"),
    }
    campaign_pack_assets = {
        "hero-4k": ("prooflaunch-hero-4k.png", "image/png"),
        "social-4x5": ("prooflaunch-social-1080x1350.png", "image/png"),
        "landing-1080p": ("prooflaunch-landing-1920x1080.png", "image/png"),
        "audio-master": ("prooflaunch-audio-master-48k-stereo-24bit.wav", "audio/wav"),
        "film-4k": ("prooflaunch-campaign-film-4k.mp4", "video/mp4"),
        "captions": ("prooflaunch-captions.vtt", "text/vtt; charset=utf-8"),
    }
    if not approval_token or len(approval_token) < 24:
        raise ValueError("approval token must contain at least 24 characters")
    if not approver_identity.strip():
        raise ValueError("approver identity must be named")
    if not isinstance(tenant_tokens, Mapping) or not tenant_tokens:
        raise ValueError("at least one tenant token must be configured")
    if not isinstance(memory_capsule_secret, bytes) or len(memory_capsule_secret) < 32:
        raise ValueError("memory capsule secret must contain at least 32 bytes")
    tenant_by_token: dict[str, str] = {}
    for tenant_id, token in tenant_tokens.items():
        if not isinstance(tenant_id, str) or not _TENANT_ID.fullmatch(tenant_id):
            raise ValueError("tenant IDs must be safe bounded identifiers")
        if not isinstance(token, str) or len(token) < 24 or len(token) > 512:
            raise ValueError("tenant tokens must contain between 24 and 512 characters")
        if token in tenant_by_token:
            raise ValueError("tenant tokens must be unique")
        tenant_by_token[token] = tenant_id

    class Handler(BaseHTTPRequestHandler):
        server_version = "ProofLaunchProductionAPI/1.0"

        def handle_one_request(self) -> None:
            # Prevent a keep-alive EOF from reusing the prior request identity.
            self.command = None
            self.path = None
            self._trace_id = secrets.token_hex(16)
            self._trace_started = time.perf_counter()
            self._trace_status_code = 0
            self._trace_response_bytes = 0
            self._trace_exception_observed = False
            self._trace_header_sent = False
            try:
                super().handle_one_request()
            except BaseException:
                self._trace_exception_observed = True
                raise
            finally:
                method = getattr(self, "command", None)
                raw_path = getattr(self, "path", None)
                if isinstance(method, str) and isinstance(raw_path, str):
                    content_length = getattr(self, "headers", {}).get(
                        "Content-Length", "0"
                    )
                    request_bytes = (
                        int(content_length)
                        if isinstance(content_length, str)
                        and content_length.isdigit()
                        and int(content_length) <= _MAX_UPLOAD_BYTES
                        else 0
                    )
                    request_traces.append(
                        method=method,
                        route=urlparse(raw_path).path,
                        status_code=self._trace_status_code,
                        duration_ms=(time.perf_counter() - self._trace_started) * 1000,
                        request_bytes=request_bytes,
                        response_bytes=self._trace_response_bytes,
                        tenant_id=self._observed_tenant_id(),
                        trace_id=self._trace_id,
                        exception_observed=self._trace_exception_observed,
                    )

        def send_response(self, code: int, message: str | None = None) -> None:
            self._trace_status_code = int(code)
            super().send_response(code, message)

        def send_header(self, keyword: str, value: str) -> None:
            if keyword.casefold() == "content-length" and value.isdigit():
                self._trace_response_bytes = int(value)
            super().send_header(keyword, value)

        def end_headers(self) -> None:
            if not getattr(self, "_trace_header_sent", False):
                self._trace_header_sent = True
                super().send_header("X-ProofLaunch-Trace-ID", self._trace_id)
            super().end_headers()

        def log_message(self, format: str, *args: object) -> None:
            return

        def _send_json(self, status: int, payload: object) -> None:
            self._send_json_bytes(status, _json_bytes(payload))

        def _send_json_bytes(self, status: int, body: bytes) -> None:
            route = urlparse(self.path).path
            try:
                payload = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                payload = {"invalid_json_response_sha256": hashlib.sha256(body).hexdigest()}
            decision = evaluate_guardrails(
                payload,
                direction="output",
                route=route,
                schema_valid=isinstance(payload, (Mapping, list)),
            )
            telemetry.append(decision, tenant_id=self._observed_tenant_id())
            if decision.blocked:
                status = HTTPStatus.INTERNAL_SERVER_ERROR
                body = _json_bytes(
                    {
                        "error": "response_blocked_by_guardrail",
                        "policy_version": GUARDRAIL_POLICY_VERSION,
                    }
                )
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header(
                "X-ProofLaunch-Guardrail-Policy", GUARDRAIL_POLICY_VERSION
            )
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _send_qualification_asset(self, public_id: str) -> None:
            binding = qualification_assets.get(public_id)
            if binding is None:
                raise KeyError("unknown qualification artifact")
            receipt = json.loads(qualification_path.read_text(encoding="utf-8"))
            artifacts = receipt.get("artifacts")
            if not isinstance(artifacts, Mapping):
                raise IntegrityError("qualification artifact registry is malformed")
            artifact = artifacts.get(binding[0])
            if not isinstance(artifact, Mapping):
                raise IntegrityError("qualification artifact binding is missing")
            relative = artifact.get("path")
            expected_sha256 = artifact.get("sha256")
            expected_size = artifact.get("size_bytes")
            if not isinstance(relative, str) or not re.fullmatch(
                r"artifacts/[A-Za-z0-9._/-]+", relative
            ):
                raise IntegrityError("qualification artifact path is invalid")
            candidate = (root.parent / relative).resolve(strict=True)
            try:
                candidate.relative_to(root.parent)
            except ValueError as error:
                raise IntegrityError("qualification artifact escaped the project") from error
            if candidate.is_symlink() or not candidate.is_file():
                raise IntegrityError("qualification artifact is not a regular file")
            body = candidate.read_bytes()
            observed = hashlib.sha256(body).hexdigest()
            if observed != expected_sha256 or len(body) != expected_size:
                raise IntegrityError("qualification artifact failed content verification")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", binding[1])
            self.send_header("Content-Length", str(len(body)))
            self.send_header("ETag", f'"sha256:{observed}"')
            self.send_header("Cache-Control", "no-store")
            self.send_header(
                "X-ProofLaunch-Evidence-Class", "local-qualification-not-product"
            )
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _campaign_pack_receipt(self) -> Mapping[str, Any]:
            receipt = json.loads(campaign_pack_manifest_path.read_text(encoding="utf-8"))
            if (
                receipt.get("schema") != "ProofLaunchLocalCampaignPackV1"
                or not isinstance(receipt.get("artifacts"), list)
                or not isinstance(receipt.get("quality_gates"), Mapping)
            ):
                raise IntegrityError("campaign pack manifest is malformed")
            return receipt

        def _send_campaign_pack_asset(self, public_id: str) -> None:
            binding = campaign_pack_assets.get(public_id)
            if binding is None:
                raise KeyError("unknown campaign pack artifact")
            receipt = self._campaign_pack_receipt()
            artifact = next(
                (
                    item
                    for item in receipt["artifacts"]
                    if isinstance(item, Mapping) and item.get("path") == binding[0]
                ),
                None,
            )
            if not isinstance(artifact, Mapping):
                raise IntegrityError("campaign pack artifact binding is missing")
            expected_sha256 = artifact.get("sha256")
            expected_size = artifact.get("bytes")
            expected_media_type = artifact.get("media_type")
            if (
                not re.fullmatch(_SHA256, str(expected_sha256))
                or type(expected_size) is not int
                or expected_size < 1
                or expected_media_type != binding[1].split(";", 1)[0]
            ):
                raise IntegrityError("campaign pack artifact metadata is invalid")
            candidate = (campaign_pack_root / binding[0]).resolve(strict=True)
            try:
                candidate.relative_to(campaign_pack_root)
            except ValueError as error:
                raise IntegrityError("campaign pack artifact escaped its delivery root") from error
            if candidate.is_symlink() or not candidate.is_file():
                raise IntegrityError("campaign pack artifact is not a regular file")
            body = candidate.read_bytes()
            observed = hashlib.sha256(body).hexdigest()
            if observed != expected_sha256 or len(body) != expected_size:
                raise IntegrityError("campaign pack artifact failed content verification")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", binding[1])
            self.send_header("Content-Length", str(len(body)))
            self.send_header("ETag", f'"sha256:{observed}"')
            self.send_header("Cache-Control", "no-store")
            self.send_header(
                "X-ProofLaunch-Evidence-Class",
                "local-campaign-pack-mechanical-not-product",
            )
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _send_campaign_pack_blind_review_asset(self, asset_alias: str) -> None:
            if campaign_pack_blind_review_service is None:
                self._send_json(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    {"error": "campaign_pack_blind_review_service_unavailable"},
                )
                return
            candidate, media_type, observed = (
                campaign_pack_blind_review_service.asset_for_alias(asset_alias)
            )
            body = candidate.read_bytes()
            if hashlib.sha256(body).hexdigest() != observed:
                raise CampaignPackBlindReviewError(
                    "campaign-pack review asset changed after verification"
                )
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", media_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("ETag", f'"sha256:{observed}"')
            self.send_header("Cache-Control", "no-store")
            self.send_header(
                "X-ProofLaunch-Evidence-Class",
                "identity-hidden-human-review-candidate",
            )
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _send_campaign_pack_offline_review_kit(self, slot: int) -> None:
            if campaign_pack_blind_review_service is None:
                self._send_json(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    {"error": "campaign_pack_blind_review_service_unavailable"},
                )
                return
            body, observed, filename = (
                campaign_pack_blind_review_service.offline_kit_for_slot(
                    slot,
                    reviewer_token=self.headers.get(
                        "X-ProofLaunch-Reviewer-Token", ""
                    ),
                )
            )
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/zip")
            self.send_header(
                "Content-Disposition",
                f'attachment; filename="{filename}"',
            )
            self.send_header("Content-Length", str(len(body)))
            self.send_header("ETag", f'"sha256:{observed}"')
            self.send_header("Cache-Control", "no-store")
            self.send_header(
                "X-ProofLaunch-Evidence-Class",
                "identity-hidden-offline-human-review-kit",
            )
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _content_length(self, maximum: int) -> int:
            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError as error:
                raise ProductionRuntimeError("Content-Length is invalid") from error
            if length <= 0 or length > maximum:
                raise ProductionRuntimeError("request body length is outside its bound")
            return length

        def _raw_body(self, maximum: int = _MAX_JSON_BYTES) -> bytes:
            length = self._content_length(maximum)
            body = self.rfile.read(length)
            if len(body) != length:
                raise ProductionRuntimeError("request body ended before Content-Length")
            return body

        def _observed_tenant_id(self) -> str | None:
            authorization = self.headers.get("Authorization", "")
            if not authorization.startswith("Bearer "):
                return None
            supplied = authorization[7:]
            for token, tenant_id in tenant_by_token.items():
                if secrets.compare_digest(supplied, token):
                    return tenant_id
            return None

        def _mapping(self, body: bytes) -> Mapping[str, Any]:
            route = urlparse(self.path).path
            try:
                value = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                decision = evaluate_guardrails(
                    {"invalid_json_body_sha256": hashlib.sha256(body).hexdigest()},
                    direction="input",
                    route=route,
                    schema_valid=False,
                )
                telemetry.append(decision, tenant_id=self._observed_tenant_id())
                raise ProductionRuntimeError("request body must be valid UTF-8 JSON") from error
            if not isinstance(value, Mapping):
                decision = evaluate_guardrails(
                    value,
                    direction="input",
                    route=route,
                    schema_valid=False,
                )
                telemetry.append(decision, tenant_id=self._observed_tenant_id())
                raise ProductionRuntimeError("request JSON must be an object")
            decision = evaluate_guardrails(
                value,
                direction="input",
                route=route,
                schema_valid=True,
            )
            telemetry.append(decision, tenant_id=self._observed_tenant_id())
            if decision.blocked:
                raise GuardrailBlockedError(
                    "request blocked by guardrail categories: "
                    + ", ".join(decision.blocked_categories)
                )
            return value

        def _approval_authorized(self) -> bool:
            supplied = self.headers.get("X-ProofLaunch-Approval-Token", "")
            return bool(supplied) and secrets.compare_digest(supplied, approval_token)

        def _tenant_id(self) -> str:
            authorization = self.headers.get("Authorization", "")
            if not authorization.startswith("Bearer "):
                raise TenantAuthenticationError("tenant bearer token is required")
            supplied = authorization[7:]
            if not supplied or len(supplied) > 512:
                raise TenantAuthenticationError("tenant bearer token is invalid")
            for token, tenant_id in tenant_by_token.items():
                if secrets.compare_digest(supplied, token):
                    return tenant_id
            raise TenantAuthenticationError("tenant bearer token is invalid")

        def _require_run_tenant(self, run_id: str, tenant_id: str) -> None:
            service.store.require_run_tenant(run_id, tenant_id)

        @staticmethod
        def _tenant_launch_payload(
            payload: Mapping[str, Any], tenant_id: str
        ) -> dict[str, Any]:
            normalized = dict(payload)
            raw_strategy = normalized.get("strategy", {})
            if not isinstance(raw_strategy, Mapping):
                raise ProductionRuntimeError("strategy must be an object")
            strategy = dict(raw_strategy)
            supplied = strategy.get("org_id")
            if supplied is not None and supplied != tenant_id:
                raise ProductionRuntimeError(
                    "strategy org_id disagrees with the authenticated tenant"
                )
            strategy["org_id"] = tenant_id
            normalized["strategy"] = strategy
            return normalized

        @staticmethod
        def _input_artifact_digests(payload: Mapping[str, Any]) -> tuple[str, ...]:
            artifacts = payload.get("input_artifacts")
            if not isinstance(artifacts, Mapping):
                raise ProductionRuntimeError("input_artifacts must be an object")
            digests = tuple(str(value) for value in artifacts.values())
            if not digests:
                raise ProductionRuntimeError("at least one input artifact is required")
            return digests

        def _idempotent_json(
            self,
            *,
            namespace: str,
            key: str,
            request_body: bytes,
            operation: Callable[[], tuple[int, object]],
            tenant_id: str,
        ) -> None:
            if not key:
                raise ProductionRuntimeError("an idempotency key is required")
            tenant_scope = hashlib.sha256(tenant_id.encode("utf-8")).hexdigest()[:16]
            scoped_namespace = f"tenant:{tenant_scope}:{namespace}"
            disposition = service.store.begin_idempotent_command(
                scoped_namespace,
                key,
                request_body,
            )
            if disposition.is_replay:
                self._send_json_bytes(
                    int(disposition.response_code or HTTPStatus.OK),
                    disposition.response_body or b"{}",
                )
                return
            status, payload = operation()
            response = _json_bytes(payload)
            service.store.complete_idempotent_command(
                scoped_namespace,
                key,
                request_body,
                response_code=status,
                response_body=response,
            )
            self._send_json_bytes(status, response)

        def do_HEAD(self) -> None:
            path = urlparse(self.path).path
            match = re.fullmatch(rf"/v1/artifacts/({_SHA256})", path)
            if not match:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                return
            try:
                tenant_id = self._tenant_id()
                record = service.store.require_tenant_artifact(
                    tenant_id, match.group(1)
                )
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Length", str(record.byte_length))
                self.send_header("Content-Type", record.media_type)
                self.send_header("ETag", f'"sha256:{record.sha256}"')
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
            except KeyError:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "unknown_artifact"})
            except TenantAuthenticationError as error:
                self._send_json(HTTPStatus.UNAUTHORIZED, {"error": str(error)})
            except SubmissionStoreError as error:
                self._send_json(HTTPStatus.CONFLICT, {"error": str(error)})

        def do_PUT(self) -> None:
            path = urlparse(self.path).path
            match = re.fullmatch(rf"/v1/artifacts/({_SHA256})", path)
            if not match:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                return
            try:
                tenant_id = self._tenant_id()
                media_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip()
                if media_type == "image/png":
                    maximum_bytes = _MAX_PNG_BYTES
                elif media_type == "application/json":
                    maximum_bytes = _MAX_JSON_BYTES
                elif media_type == "audio/wav":
                    maximum_bytes = _MAX_WAV_BYTES
                elif media_type == "video/mp4":
                    maximum_bytes = _MAX_MP4_BYTES
                else:
                    raise ProductionRuntimeError(
                        "the production slice accepts image/png, application/json, audio/wav or video/mp4 only"
                    )
                length = self._content_length(maximum_bytes)
                source = _LimitedReader(self.rfile, length)
                record = service.store.artifacts.put(
                    source,
                    expected_sha256=match.group(1),
                    media_type=media_type,
                )
                if source.remaining != 0:
                    raise ProductionRuntimeError("artifact upload ended early")
                _validate_uploaded_media_signature(
                    service.store.artifacts.resolve_server_path(record.sha256),
                    media_type,
                )
                service.store.grant_artifact_to_tenant(tenant_id, record.sha256)
                self._send_json(
                    HTTPStatus.CREATED,
                    {
                        "schema": "ProofLaunchArtifactReceiptV1",
                        "sha256": record.sha256,
                        "bytes": record.byte_length,
                        "media_type": record.media_type,
                    },
                )
            except (ProductionRuntimeError, IntegrityError, ValueError, TypeError) as error:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
            except TenantAuthenticationError as error:
                self._send_json(HTTPStatus.UNAUTHORIZED, {"error": str(error)})
            except ConflictError as error:
                self._send_json(HTTPStatus.CONFLICT, {"error": str(error)})

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            try:
                if path == "/v1/realtime-preset-campaigns":
                    tenant_id = self._tenant_id()
                    raw = self._raw_body()
                    payload = self._mapping(raw)
                    idempotency_key = self.headers.get("Idempotency-Key", "")

                    def execute_realtime_preset() -> tuple[int, object]:
                        raw_brief = payload.get("brief")
                        if not isinstance(raw_brief, Mapping):
                            return HTTPStatus.BAD_REQUEST, {"error": "brief must be an object"}
                        tenant_scope = hashlib.sha256(tenant_id.encode("utf-8")).hexdigest()[:16]
                        run_root = service.store.root / "realtime-preset-campaigns" / tenant_scope
                        try:
                            result = compile_realtime_preset_campaign(raw_brief, run_root)
                            media = dict(result["rendered_media"])
                            published_assets: list[dict[str, Any]] = []
                            media_root = run_root / result["content_sha256"]
                            for artifact in media["assets"]:
                                source = media_root / str(artifact["filename"])
                                digest = str(artifact["content_sha256"])
                                media_type = str(artifact["media_type"])
                                with source.open("rb") as handle:
                                    service.store.artifacts.put(
                                        handle,
                                        expected_sha256=digest,
                                        media_type=media_type,
                                    )
                                service.store.grant_artifact_to_tenant(tenant_id, digest)
                                published_assets.append(
                                    {
                                        **artifact,
                                        "url": f"/v1/artifacts/{digest}",
                                        "tenant_authenticated": True,
                                    }
                                )
                            media["assets"] = published_assets
                            media.pop("content_sha256", None)
                            media["content_sha256"] = hashlib.sha256(_json_bytes(media)).hexdigest()
                            result["rendered_media"] = media
                            result["envelope_sha256"] = hashlib.sha256(
                                _json_bytes({key: value for key, value in result.items() if key != "envelope_sha256"})
                            ).hexdigest()
                        except (OSError, RealtimePresetCampaignError, ValueError, TypeError) as error:
                            return HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(error)}
                        output_path = run_root / f"{result['content_sha256']}.json"
                        atomic_write_text(
                            output_path,
                            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                        )
                        return HTTPStatus.CREATED, result

                    self._idempotent_json(
                        namespace="realtime-preset-campaign",
                        key=idempotency_key,
                        request_body=raw,
                        operation=execute_realtime_preset,
                        tenant_id=tenant_id,
                    )
                    return
                if path == "/v1/frontier-gtm/runs":
                    tenant_id = self._tenant_id()
                    raw = self._raw_body()
                    payload = self._mapping(raw)
                    idempotency_key = self.headers.get("Idempotency-Key", "")

                    def execute_frontier() -> tuple[int, object]:
                        raw_brief = payload.get("brief")
                        if not isinstance(raw_brief, Mapping):
                            return HTTPStatus.BAD_REQUEST, {"error": "brief must be an object"}
                        requested_provider = payload.get("provider")
                        if requested_provider is not None and (
                            not isinstance(requested_provider, str)
                            or not requested_provider.strip()
                            or len(requested_provider) > 120
                        ):
                            return HTTPStatus.BAD_REQUEST, {"error": "provider id is invalid"}
                        config_root = project_root / "config"
                        provider_config = config_root / "frontier-gtm-provider.json"
                        if not provider_config.is_file():
                            provider_config = config_root / "frontier-gtm-provider.example.json"
                        try:
                            specs = load_third_party_provider_specs(provider_config)
                            ready = [spec for spec in specs if os.environ.get(spec.api_key_env)]
                            if requested_provider is not None:
                                ready = [spec for spec in ready if spec.provider == requested_provider]
                            if not ready:
                                return HTTPStatus.SERVICE_UNAVAILABLE, {
                                    "schema": "ProofLaunchFrontierGTMAvailabilityV1",
                                    "status": "cloud_credential_unavailable",
                                    "error": "cloud_credential_unavailable",
                                    "local_fallback_attempted": False,
                                    "external_action_executed": False,
                                }
                            distillation = json.loads(
                                (project_root / "evidence/v10/gtm-named-capability-distillation-v1.json").read_text(encoding="utf-8")
                            )
                            human_kernel = json.loads(
                                (project_root / "evidence/v10/gtm-human-capability-kernel-v2.json").read_text(encoding="utf-8")
                            )
                            signal_pack_path = project_root / "evidence/v10/gtm-recent-organic-signal-pack-v5.json"
                            if not signal_pack_path.is_file():
                                signal_pack_path = project_root / "evidence/v10/gtm-recent-organic-signal-pack-v4.json"
                            if not signal_pack_path.is_file():
                                signal_pack_path = project_root / "evidence/v10/gtm-recent-organic-signal-pack-v3.json"
                            if not signal_pack_path.is_file():
                                signal_pack_path = project_root / "evidence/v10/gtm-recent-organic-signal-pack-v2.json"
                            signal_pack = json.loads(signal_pack_path.read_text(encoding="utf-8"))
                            learning_memory_path = project_root / "evidence/v10/gtm-genome-learning-memory-v1.json"
                            learning_memory = (
                                json.loads(learning_memory_path.read_text(encoding="utf-8"))
                                if learning_memory_path.is_file() else None
                            )
                            result = execute_frontier_gtm_agent(
                                raw_brief,
                                OpenAICompatibleThirdPartyClient(ready[0]),
                                named_capability_distillation=distillation,
                                human_capability_kernel=human_kernel,
                                recent_signal_pack=signal_pack,
                                learning_memory=learning_memory,
                            )
                        except (OSError, UnicodeError, json.JSONDecodeError, ValueError, FrontierGTMAgentError) as error:
                            return HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(error)}
                        tenant_scope = hashlib.sha256(tenant_id.encode("utf-8")).hexdigest()[:16]
                        run_root = service.store.root / "frontier-gtm-runs" / tenant_scope
                        run_root.mkdir(parents=True, exist_ok=True, mode=0o700)
                        output_path = run_root / f"{result['content_sha256']}.json"
                        atomic_write_text(
                            output_path,
                            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                        )
                        return HTTPStatus.CREATED, result

                    self._idempotent_json(
                        namespace="frontier-gtm-run",
                        key=idempotency_key,
                        request_body=raw,
                        operation=execute_frontier,
                        tenant_id=tenant_id,
                    )
                    return
                if path == "/v1/social-collection/plan":
                    raw = self._raw_body()
                    payload = self._mapping(raw)
                    self._send_json(HTTPStatus.OK, plan_social_collection(payload))
                    return
                if path == "/v1/blind-review/reviews":
                    if blind_review_service is None:
                        self._send_json(
                            HTTPStatus.SERVICE_UNAVAILABLE,
                            {"error": "blind_review_service_unavailable"},
                        )
                        return
                    raw = self._raw_body()
                    payload = self._mapping(raw)
                    acknowledgement = blind_review_service.submit(
                        payload,
                        reviewer_token=self.headers.get(
                            "X-ProofLaunch-Reviewer-Token", ""
                        ),
                    )
                    self._send_json(HTTPStatus.CREATED, acknowledgement)
                    return
                if path == "/v1/portfolio-blind-review/reviews":
                    if portfolio_blind_review_service is None:
                        self._send_json(
                            HTTPStatus.SERVICE_UNAVAILABLE,
                            {"error": "portfolio_blind_review_service_unavailable"},
                        )
                        return
                    raw = self._raw_body()
                    payload = self._mapping(raw)
                    acknowledgement = portfolio_blind_review_service.submit(
                        payload,
                        reviewer_token=self.headers.get(
                            "X-ProofLaunch-Reviewer-Token", ""
                        ),
                    )
                    self._send_json(HTTPStatus.CREATED, acknowledgement)
                    return
                if path == "/v1/campaign-pack-blind-review/reviews":
                    if campaign_pack_blind_review_service is None:
                        self._send_json(
                            HTTPStatus.SERVICE_UNAVAILABLE,
                            {"error": "campaign_pack_blind_review_service_unavailable"},
                        )
                        return
                    raw = self._raw_body()
                    payload = self._mapping(raw)
                    acknowledgement = campaign_pack_blind_review_service.submit(
                        payload,
                        reviewer_token=self.headers.get(
                            "X-ProofLaunch-Reviewer-Token", ""
                        ),
                    )
                    self._send_json(HTTPStatus.CREATED, acknowledgement)
                    return
                if path == "/v1/judge-calibration/reviews":
                    if judge_calibration_service is None:
                        self._send_json(
                            HTTPStatus.SERVICE_UNAVAILABLE,
                            {"error": "judge_calibration_service_unavailable"},
                        )
                        return
                    raw = self._raw_body()
                    payload = self._mapping(raw)
                    acknowledgement = judge_calibration_service.submit(
                        payload,
                        reviewer_token=self.headers.get(
                            "X-ProofLaunch-Reviewer-Token", ""
                        ),
                    )
                    self._send_json(HTTPStatus.CREATED, acknowledgement)
                    return
                if path == "/v1/blind-review/selections":
                    if blind_review_service is None:
                        self._send_json(
                            HTTPStatus.SERVICE_UNAVAILABLE,
                            {"error": "blind_review_service_unavailable"},
                        )
                        return
                    self._tenant_id()
                    if not self._approval_authorized():
                        self._send_json(
                            HTTPStatus.FORBIDDEN,
                            {"error": "operator approval token is required"},
                        )
                        return
                    raw = self._raw_body()
                    payload = self._mapping(raw)
                    admission = blind_review_service.select_multimodal_seed(
                        payload,
                        authenticated_approver=approver_identity,
                    )
                    self._send_json(HTTPStatus.CREATED, admission)
                    return
                if path == "/v1/runs":
                    tenant_id = self._tenant_id()
                    raw = self._raw_body()
                    payload = self._tenant_launch_payload(
                        self._mapping(raw), tenant_id
                    )
                    for digest in self._input_artifact_digests(payload):
                        service.store.require_tenant_artifact(tenant_id, digest)
                    fallback_key = str(payload.get("request_id", ""))
                    key = self.headers.get("Idempotency-Key", fallback_key)
                    self._idempotent_json(
                        namespace="create_run",
                        key=key,
                        request_body=raw,
                        operation=lambda: (
                            HTTPStatus.ACCEPTED,
                            _public_snapshot(service.create_run(payload)),
                        ),
                        tenant_id=tenant_id,
                    )
                    return
                if path == "/v1/memory-capsules/export":
                    tenant_id = self._tenant_id()
                    payload = self._mapping(self._raw_body())
                    project_id = payload.get("project_id")
                    ttl_seconds = payload.get("ttl_seconds", 86_400)
                    if not isinstance(project_id, str):
                        raise ProductionRuntimeError("project_id must be a string")
                    if type(ttl_seconds) is not int:
                        raise ProductionRuntimeError("ttl_seconds must be an integer")
                    self._send_json(
                        HTTPStatus.CREATED,
                        service.export_memory_capsule(
                            org_id=tenant_id,
                            project_id=project_id,
                            signing_secret=memory_capsule_secret,
                            ttl_seconds=ttl_seconds,
                        ),
                    )
                    return
                if path == "/v1/memory-capsules/import":
                    tenant_id = self._tenant_id()
                    payload = self._mapping(self._raw_body())
                    capsule = payload.get("capsule")
                    expected_project_id = payload.get("project_id")
                    if expected_project_id is not None and not isinstance(
                        expected_project_id, str
                    ):
                        raise ProductionRuntimeError("project_id must be a string")
                    self._send_json(
                        HTTPStatus.CREATED,
                        service.import_memory_capsule(
                            capsule,
                            authenticated_tenant=tenant_id,
                            signing_secret=memory_capsule_secret,
                            expected_project_id=expected_project_id,
                        ),
                    )
                    return
                match = re.fullmatch(
                    rf"/v1/memory-capsules/({_ASSET_ID})/reviews",
                    path,
                )
                if match:
                    tenant_id = self._tenant_id()
                    if not self._approval_authorized():
                        self._send_json(
                            HTTPStatus.FORBIDDEN,
                            {"error": "operator approval token is required"},
                        )
                        return
                    payload = self._mapping(self._raw_body())
                    decision = payload.get("decision")
                    reason = payload.get("reason")
                    if not isinstance(decision, str) or not isinstance(reason, str):
                        raise ProductionRuntimeError("decision and reason must be strings")
                    self._send_json(
                        HTTPStatus.OK,
                        service.review_memory_capsule(
                            match.group(1),
                            authenticated_tenant=tenant_id,
                            authenticated_reviewer=approver_identity,
                            decision=decision,
                            reason=reason,
                        ),
                    )
                    return
                match = re.fullmatch(
                    rf"/v1/runs/({_RUN_ID})/strategy-memory-resolutions",
                    path,
                )
                if match:
                    tenant_id = self._tenant_id()
                    if not self._approval_authorized():
                        self._send_json(
                            HTTPStatus.FORBIDDEN,
                            {"error": "operator approval token is required"},
                        )
                        return
                    run_id = match.group(1)
                    self._require_run_tenant(run_id, tenant_id)
                    raw = self._raw_body()
                    payload = self._mapping(raw)
                    required = (
                        "base_decision_sha256",
                        "channel",
                        "winner_memory_id",
                        "reason",
                    )
                    if any(not isinstance(payload.get(key), str) for key in required):
                        raise ProductionRuntimeError(
                            "strategy memory resolution fields must be strings"
                        )
                    key = self.headers.get(
                        "Idempotency-Key",
                        (
                            f"{payload['base_decision_sha256'][:24]}:"
                            f"{payload['channel']}"
                        ),
                    )
                    self._idempotent_json(
                        namespace=f"strategy_memory_resolution:{run_id}",
                        key=key,
                        request_body=raw,
                        operation=lambda: (
                            HTTPStatus.CREATED,
                            service.resolve_strategy_memory_conflict(
                                run_id,
                                authenticated_resolver=approver_identity,
                                base_decision_sha256=payload[
                                    "base_decision_sha256"
                                ],
                                channel=payload["channel"],
                                winner_memory_id=payload["winner_memory_id"],
                                reason=payload["reason"],
                            ),
                        ),
                        tenant_id=tenant_id,
                    )
                    return
                match = re.fullmatch(
                    rf"/v1/runs/({_RUN_ID})/capability-deliverables",
                    path,
                )
                if match:
                    tenant_id = self._tenant_id()
                    if not self._approval_authorized():
                        self._send_json(
                            HTTPStatus.FORBIDDEN,
                            {"error": "operator approval token is required"},
                        )
                        return
                    raw = self._raw_body()
                    payload = self._mapping(raw)
                    run_id = match.group(1)
                    self._require_run_tenant(run_id, tenant_id)
                    key = self.headers.get(
                        "Idempotency-Key", str(payload.get("registration_id", ""))
                    )
                    self._idempotent_json(
                        namespace=f"capability_deliverable:{run_id}",
                        key=key,
                        request_body=raw,
                        operation=lambda: (
                            HTTPStatus.CREATED,
                            service.register_capability_deliverable(
                                run_id,
                                payload,
                                authenticated_tenant=tenant_id,
                                authenticated_operator=approver_identity,
                            ),
                        ),
                        tenant_id=tenant_id,
                    )
                    return
                match = re.fullmatch(
                    rf"/v1/runs/({_RUN_ID})/capability-deliverables/({_ASSET_ID})/reviews",
                    path,
                )
                if match:
                    tenant_id = self._tenant_id()
                    if not self._approval_authorized():
                        self._send_json(
                            HTTPStatus.FORBIDDEN,
                            {"error": "operator approval token is required"},
                        )
                        return
                    raw = self._raw_body()
                    payload = self._mapping(raw)
                    run_id, registration_id = match.groups()
                    self._require_run_tenant(run_id, tenant_id)
                    key = self.headers.get(
                        "Idempotency-Key", str(payload.get("review_id", ""))
                    )
                    self._idempotent_json(
                        namespace=f"capability_review:{run_id}:{registration_id}",
                        key=key,
                        request_body=raw,
                        operation=lambda: (
                            HTTPStatus.CREATED,
                            service.review_capability_deliverable(
                                run_id,
                                registration_id,
                                payload,
                                authenticated_tenant=tenant_id,
                                authenticated_reviewer=approver_identity,
                            ),
                        ),
                        tenant_id=tenant_id,
                    )
                    return
                match = re.fullmatch(
                    rf"/v1/runs/({_RUN_ID})/multimodal-deliverables",
                    path,
                )
                if match:
                    tenant_id = self._tenant_id()
                    if not self._approval_authorized():
                        self._send_json(
                            HTTPStatus.FORBIDDEN,
                            {"error": "operator approval token is required"},
                        )
                        return
                    raw = self._raw_body()
                    payload = self._mapping(raw)
                    run_id = match.group(1)
                    self._require_run_tenant(run_id, tenant_id)
                    key = self.headers.get(
                        "Idempotency-Key", str(payload.get("registration_id", ""))
                    )
                    self._idempotent_json(
                        namespace=f"multimodal_deliverable:{run_id}",
                        key=key,
                        request_body=raw,
                        operation=lambda: (
                            HTTPStatus.CREATED,
                            service.register_multimodal_deliverable(
                                run_id,
                                payload,
                                authenticated_tenant=tenant_id,
                                authenticated_operator=approver_identity,
                            ),
                        ),
                        tenant_id=tenant_id,
                    )
                    return
                match = re.fullmatch(
                    rf"/v1/runs/({_RUN_ID})/multimodal-deliverables/({_ASSET_ID})/reviews",
                    path,
                )
                if match:
                    tenant_id = self._tenant_id()
                    if not self._approval_authorized():
                        self._send_json(
                            HTTPStatus.FORBIDDEN,
                            {"error": "operator approval token is required"},
                        )
                        return
                    raw = self._raw_body()
                    payload = self._mapping(raw)
                    run_id, registration_id = match.groups()
                    self._require_run_tenant(run_id, tenant_id)
                    key = self.headers.get(
                        "Idempotency-Key", str(payload.get("review_id", ""))
                    )
                    self._idempotent_json(
                        namespace=f"multimodal_review:{run_id}:{registration_id}",
                        key=key,
                        request_body=raw,
                        operation=lambda: (
                            HTTPStatus.CREATED,
                            service.review_multimodal_deliverable(
                                run_id,
                                registration_id,
                                payload,
                                authenticated_tenant=tenant_id,
                                authenticated_reviewer=approver_identity,
                            ),
                        ),
                        tenant_id=tenant_id,
                    )
                    return
                match = re.fullmatch(rf"/v1/runs/({_RUN_ID})/outcomes", path)
                if match:
                    tenant_id = self._tenant_id()
                    if not self._approval_authorized():
                        self._send_json(
                            HTTPStatus.FORBIDDEN,
                            {"error": "operator approval token is required"},
                        )
                        return
                    raw = self._raw_body()
                    payload = self._mapping(raw)
                    key = self.headers.get(
                        "Idempotency-Key",
                        str(payload.get("observation_id", "")),
                    )
                    run_id = match.group(1)
                    self._require_run_tenant(run_id, tenant_id)
                    self._idempotent_json(
                        namespace=f"effect_observation:{run_id}",
                        key=key,
                        request_body=raw,
                        operation=lambda: (
                            HTTPStatus.CREATED,
                            service.record_effect_observation(run_id, payload),
                        ),
                        tenant_id=tenant_id,
                    )
                    return
                match = re.fullmatch(
                    rf"/v1/runs/({_RUN_ID})/publication-receipts",
                    path,
                )
                if match:
                    tenant_id = self._tenant_id()
                    if not self._approval_authorized():
                        self._send_json(
                            HTTPStatus.FORBIDDEN,
                            {"error": "operator approval token is required"},
                        )
                        return
                    raw = self._raw_body()
                    payload = self._mapping(raw)
                    key = self.headers.get(
                        "Idempotency-Key",
                        str(payload.get("receipt_id", "")),
                    )
                    run_id = match.group(1)
                    self._require_run_tenant(run_id, tenant_id)
                    self._idempotent_json(
                        namespace=f"manual_publication_receipt:{run_id}",
                        key=key,
                        request_body=raw,
                        operation=lambda: (
                            HTTPStatus.CREATED,
                            service.record_manual_publication_receipt(
                                run_id,
                                payload,
                                authenticated_operator=approver_identity,
                            ),
                        ),
                        tenant_id=tenant_id,
                    )
                    return
                match = re.fullmatch(
                    rf"/v1/runs/({_RUN_ID})/outcomes/({_ASSET_ID})/economics",
                    path,
                )
                if match:
                    tenant_id = self._tenant_id()
                    if not self._approval_authorized():
                        self._send_json(
                            HTTPStatus.FORBIDDEN,
                            {"error": "operator approval token is required"},
                        )
                        return
                    raw = self._raw_body()
                    payload = self._mapping(raw)
                    key = self.headers.get(
                        "Idempotency-Key",
                        str(payload.get("economics_id", "")),
                    )
                    run_id, observation_id = match.groups()
                    self._require_run_tenant(run_id, tenant_id)
                    self._idempotent_json(
                        namespace=f"revenue_economics:{run_id}:{observation_id}",
                        key=key,
                        request_body=raw,
                        operation=lambda: (
                            HTTPStatus.CREATED,
                            service.record_revenue_economics(
                                run_id,
                                observation_id,
                                payload,
                            ),
                        ),
                        tenant_id=tenant_id,
                    )
                    return
                match = re.fullmatch(
                    rf"/v1/runs/({_RUN_ID})/outcomes/({_ASSET_ID})/promotions",
                    path,
                )
                if match:
                    tenant_id = self._tenant_id()
                    if not self._approval_authorized():
                        self._send_json(
                            HTTPStatus.FORBIDDEN,
                            {"error": "operator approval token is required"},
                        )
                        return
                    raw = self._raw_body()
                    payload = self._mapping(raw)
                    reason = payload.get("reason")
                    if not isinstance(reason, str):
                        raise ProductionRuntimeError("promotion reason must be a string")
                    key = self.headers.get(
                        "Idempotency-Key",
                        str(payload.get("idempotency_key", "")),
                    )
                    run_id, observation_id = match.groups()
                    self._require_run_tenant(run_id, tenant_id)
                    self._idempotent_json(
                        namespace=f"learning_promotion:{run_id}:{observation_id}",
                        key=key,
                        request_body=raw,
                        operation=lambda: (
                            HTTPStatus.CREATED,
                            service.promote_effect_observation(
                                run_id,
                                observation_id,
                                reason=reason,
                                authenticated_approver=approver_identity,
                            ),
                        ),
                        tenant_id=tenant_id,
                    )
                    return
                match = re.fullmatch(rf"/v1/runs/({_RUN_ID})/approvals", path)
                if match:
                    tenant_id = self._tenant_id()
                    if not self._approval_authorized():
                        self._send_json(
                            HTTPStatus.FORBIDDEN,
                            {"error": "operator approval token is required"},
                        )
                        return
                    raw = self._raw_body()
                    payload = self._mapping(raw)
                    key = self.headers.get(
                        "Idempotency-Key",
                        str(payload.get("idempotency_key", "")),
                    )
                    decision = payload.get("decision")
                    reason = payload.get("reason")
                    if not isinstance(decision, str) or not isinstance(reason, str):
                        raise ProductionRuntimeError("decision and reason must be strings")
                    run_id = match.group(1)
                    self._require_run_tenant(run_id, tenant_id)
                    self._idempotent_json(
                        namespace=f"release:{run_id}",
                        key=key,
                        request_body=raw,
                        operation=lambda: (
                            HTTPStatus.ACCEPTED,
                            _public_snapshot(
                                service.queue_release(
                                    run_id,
                                    decision=decision,
                                    reason=reason,
                                    authenticated_approver=approver_identity,
                                )
                            ),
                        ),
                        tenant_id=tenant_id,
                    )
                    return
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            except KeyError:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "unknown_resource"})
            except TenantAuthenticationError as error:
                self._send_json(HTTPStatus.UNAUTHORIZED, {"error": str(error)})
            except BlindReviewAuthorizationError as error:
                self._send_json(HTTPStatus.FORBIDDEN, {"error": str(error)})
            except BlindReviewConflictError as error:
                self._send_json(HTTPStatus.CONFLICT, {"error": str(error)})
            except BlindReviewServiceError as error:
                self._send_json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(error)})
            except CampaignPackBlindReviewAuthorizationError as error:
                self._send_json(HTTPStatus.FORBIDDEN, {"error": str(error)})
            except CampaignPackBlindReviewConflictError as error:
                self._send_json(HTTPStatus.CONFLICT, {"error": str(error)})
            except CampaignPackBlindReviewError as error:
                self._send_json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(error)})
            except JudgeCalibrationAuthorizationError as error:
                self._send_json(HTTPStatus.FORBIDDEN, {"error": str(error)})
            except JudgeCalibrationConflictError as error:
                self._send_json(HTTPStatus.CONFLICT, {"error": str(error)})
            except JudgeCalibrationError as error:
                self._send_json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(error)})
            except IdempotencyConflict as error:
                self._send_json(HTTPStatus.CONFLICT, {"error": str(error)})
            except ConflictError as error:
                self._send_json(HTTPStatus.CONFLICT, {"error": str(error)})
            except (ProductionRuntimeError, ValueError, TypeError) as error:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path
            try:
                if path == "/v1/local-evaluation-session":
                    if local_evaluation_session is None:
                        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                        return
                    tenant_id, tenant_token = local_evaluation_session
                    self._send_json(
                        HTTPStatus.OK,
                        {
                            "schema": "ProofLaunchLoopbackEvaluationSessionV1",
                            "tenant_id": tenant_id,
                            "tenant_token": tenant_token,
                            "scope": "loopback_evaluation_only",
                            "production_default_enabled": False,
                        },
                    )
                    return
                match = re.fullmatch(rf"/v1/artifacts/({_SHA256})", path)
                if match:
                    tenant_id = self._tenant_id()
                    record = service.store.require_tenant_artifact(tenant_id, match.group(1))
                    candidate = service.store.artifacts.resolve_server_path(record.sha256)
                    body = candidate.read_bytes()
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", record.media_type)
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("ETag", f'"sha256:{record.sha256}"')
                    self.send_header("Cache-Control", "private, no-store")
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if path == "/v1/launch-proof/status":
                    tenant_id = self._tenant_id()
                    try:
                        readiness = json.loads(
                            readiness_path.read_text(encoding="utf-8")
                        )
                        if not isinstance(readiness, Mapping):
                            raise ValueError("product readiness is not an object")
                        radeon_receipt: Mapping[str, Any] | None = None
                        if radeon_live_preflight_path.is_file():
                            loaded_radeon = json.loads(
                                radeon_live_preflight_path.read_text(encoding="utf-8")
                            )
                            if isinstance(loaded_radeon, Mapping):
                                radeon_receipt = loaded_radeon
                        portfolio_status = (
                            portfolio_blind_review_service.status()
                            if portfolio_blind_review_service is not None
                            else {
                                "schema": "ProofLaunchPortfolioBlindReviewQueueStatusV1",
                                "submitted_review_count": 0,
                                "expected_review_count": 270,
                                "review_complete": False,
                                "portfolio_promotion_passed": False,
                                "human_preference_observed": False,
                            }
                        )
                        judge_status = (
                            judge_calibration_service.status()
                            if judge_calibration_service is not None
                            else {
                                "schema": "ProofLaunchJudgeCalibrationStatusV1",
                                "submitted_review_count": 0,
                                "expected_review_count": 300,
                                "review_complete": False,
                                "judge_calibrated": False,
                            }
                        )
                        control = compile_launch_proof_control(
                            product_readiness=readiness,
                            portfolio_status=portfolio_status,
                            judge_status=judge_status,
                            guardrail_status=telemetry.status(tenant_id=tenant_id),
                            trace_status=request_traces.status(tenant_id=tenant_id),
                            radeon_receipt=radeon_receipt,
                        )
                    except (
                        OSError,
                        UnicodeError,
                        json.JSONDecodeError,
                        LaunchProofControlError,
                        ValueError,
                        TypeError,
                    ) as error:
                        self._send_json(
                            HTTPStatus.SERVICE_UNAVAILABLE,
                            {
                                "schema": "ProofLaunchLaunchProofControlUnavailableV1",
                                "error": "launch_proof_control_unavailable",
                                "detail": str(error),
                            },
                        )
                        return
                    self._send_json(HTTPStatus.OK, control)
                    return
                if path == "/v1/guardrails/status":
                    tenant_id = self._tenant_id()
                    self._send_json(
                        HTTPStatus.OK,
                        telemetry.status(tenant_id=tenant_id),
                    )
                    return
                if path == "/v1/traces/status":
                    tenant_id = self._tenant_id()
                    self._send_json(
                        HTTPStatus.OK,
                        request_traces.status(tenant_id=tenant_id),
                    )
                    return
                if path == "/v1/health":
                    self._send_json(
                        HTTPStatus.OK,
                        {
                            "schema": "ProofLaunchProductionHealthV1",
                            "api_connected": True,
                            "durable_store_connected": True,
                            "agent_worker_connected": bool(
                                service.worker._thread is not None
                                and service.worker._thread.is_alive()
                            ),
                            "request_trace_ledger_connected": True,
                            "request_trace_retention_days": request_traces.retention_days,
                            "execution_mode": "deterministic_agent_vertical_slice",
                            "external_release_enabled": False,
                            "radeon_connected": False,
                            "radeon_metrics_observed": False,
                            "model_inference_observed": False,
                        },
                    )
                    return
                if path == "/v1/demo/synthetic-lifecycle":
                    try:
                        self._send_json(
                            HTTPStatus.OK,
                            load_verified_synthetic_lifecycle_demo(project_root),
                        )
                    except (
                        OSError,
                        UnicodeError,
                        json.JSONDecodeError,
                        KeyError,
                        TypeError,
                        IntegrityError,
                    ):
                        self._send_json(
                            HTTPStatus.SERVICE_UNAVAILABLE,
                            {"error": "synthetic_lifecycle_demo_unavailable"},
                        )
                    return
                if path == "/v1/blind-review/status":
                    if blind_review_service is None:
                        self._send_json(
                            HTTPStatus.SERVICE_UNAVAILABLE,
                            {"error": "blind_review_service_unavailable"},
                        )
                    else:
                        self._send_json(HTTPStatus.OK, blind_review_service.status())
                    return
                if path == "/v1/portfolio-blind-review/status":
                    if portfolio_blind_review_service is None:
                        self._send_json(
                            HTTPStatus.SERVICE_UNAVAILABLE,
                            {"error": "portfolio_blind_review_service_unavailable"},
                        )
                    else:
                        self._send_json(
                            HTTPStatus.OK,
                            portfolio_blind_review_service.status(),
                        )
                    return
                if path == "/v1/campaign-pack-blind-review/status":
                    if campaign_pack_blind_review_service is None:
                        self._send_json(
                            HTTPStatus.SERVICE_UNAVAILABLE,
                            {"error": "campaign_pack_blind_review_service_unavailable"},
                        )
                    else:
                        self._send_json(
                            HTTPStatus.OK,
                            campaign_pack_blind_review_service.status(),
                        )
                    return
                if path == "/v1/campaign-pack-blind-review/tasks":
                    if campaign_pack_blind_review_service is None:
                        self._send_json(
                            HTTPStatus.SERVICE_UNAVAILABLE,
                            {"error": "campaign_pack_blind_review_service_unavailable"},
                        )
                        return
                    raw_slot = parse_qs(parsed.query).get("slot", [""])[0]
                    try:
                        slot = int(raw_slot)
                    except ValueError as error:
                        raise CampaignPackBlindReviewError(
                            "reviewer slot must be an integer in [1, 5]"
                        ) from error
                    self._send_json(
                        HTTPStatus.OK,
                        campaign_pack_blind_review_service.tasks_for_slot(
                            slot,
                            reviewer_token=self.headers.get(
                                "X-ProofLaunch-Reviewer-Token", ""
                            ),
                        ),
                    )
                    return
                if path == "/v1/campaign-pack-blind-review/aggregate":
                    if campaign_pack_blind_review_service is None:
                        self._send_json(
                            HTTPStatus.SERVICE_UNAVAILABLE,
                            {"error": "campaign_pack_blind_review_service_unavailable"},
                        )
                    else:
                        self._send_json(
                            HTTPStatus.OK,
                            campaign_pack_blind_review_service.aggregate(),
                        )
                    return
                if path == "/v1/campaign-pack-blind-review/offline-kit":
                    raw_slot = parse_qs(parsed.query).get("slot", [""])[0]
                    try:
                        slot = int(raw_slot)
                    except ValueError as error:
                        raise CampaignPackBlindReviewError(
                            "reviewer slot must be an integer in [1, 5]"
                        ) from error
                    self._send_campaign_pack_offline_review_kit(slot)
                    return
                if path == "/v1/judge-calibration/status":
                    if judge_calibration_service is None:
                        self._send_json(
                            HTTPStatus.SERVICE_UNAVAILABLE,
                            {"error": "judge_calibration_service_unavailable"},
                        )
                    else:
                        self._send_json(
                            HTTPStatus.OK,
                            judge_calibration_service.status(),
                        )
                    return
                if path == "/v1/judge-calibration/tasks":
                    if judge_calibration_service is None:
                        self._send_json(
                            HTTPStatus.SERVICE_UNAVAILABLE,
                            {"error": "judge_calibration_service_unavailable"},
                        )
                        return
                    raw_slot = parse_qs(parsed.query).get("slot", [""])[0]
                    try:
                        slot = int(raw_slot)
                    except ValueError as error:
                        raise JudgeCalibrationError(
                            "reviewer slot must be an integer in [1, 5]"
                        ) from error
                    self._send_json(
                        HTTPStatus.OK,
                        judge_calibration_service.tasks_for_slot(
                            slot,
                            reviewer_token=self.headers.get(
                                "X-ProofLaunch-Reviewer-Token", ""
                            ),
                        ),
                    )
                    return
                if path == "/v1/portfolio-blind-review/tasks":
                    if portfolio_blind_review_service is None:
                        self._send_json(
                            HTTPStatus.SERVICE_UNAVAILABLE,
                            {"error": "portfolio_blind_review_service_unavailable"},
                        )
                        return
                    raw_slot = parse_qs(parsed.query).get("slot", [""])[0]
                    try:
                        slot = int(raw_slot)
                    except ValueError as error:
                        raise BlindReviewServiceError(
                            "reviewer slot must be an integer in [1, 5]"
                        ) from error
                    self._send_json(
                        HTTPStatus.OK,
                        portfolio_blind_review_service.tasks_for_slot(
                            slot,
                            reviewer_token=self.headers.get(
                                "X-ProofLaunch-Reviewer-Token", ""
                            ),
                        ),
                    )
                    return
                if path == "/v1/portfolio-blind-review/aggregate":
                    if portfolio_blind_review_service is None:
                        self._send_json(
                            HTTPStatus.SERVICE_UNAVAILABLE,
                            {"error": "portfolio_blind_review_service_unavailable"},
                        )
                    else:
                        self._send_json(
                            HTTPStatus.OK,
                            portfolio_blind_review_service.aggregate(),
                        )
                    return
                if path == "/v1/blind-review/tasks":
                    if blind_review_service is None:
                        self._send_json(
                            HTTPStatus.SERVICE_UNAVAILABLE,
                            {"error": "blind_review_service_unavailable"},
                        )
                        return
                    raw_slot = parse_qs(parsed.query).get("slot", [""])[0]
                    try:
                        slot = int(raw_slot)
                    except ValueError as error:
                        raise BlindReviewServiceError(
                            "reviewer slot must be an integer in [1, 5]"
                        ) from error
                    self._send_json(
                        HTTPStatus.OK,
                        blind_review_service.tasks_for_slot(
                            slot,
                            reviewer_token=self.headers.get(
                                "X-ProofLaunch-Reviewer-Token", ""
                            ),
                        ),
                    )
                    return
                if path == "/v1/blind-review/aggregate":
                    if blind_review_service is None:
                        self._send_json(
                            HTTPStatus.SERVICE_UNAVAILABLE,
                            {"error": "blind_review_service_unavailable"},
                        )
                    else:
                        self._send_json(
                            HTTPStatus.OK,
                            blind_review_service.aggregate(),
                        )
                    return
                if path == "/v1/blind-review/activation":
                    if blind_review_service is None:
                        self._send_json(
                            HTTPStatus.SERVICE_UNAVAILABLE,
                            {"error": "blind_review_service_unavailable"},
                        )
                        return
                    self._tenant_id()
                    self._send_json(
                        HTTPStatus.OK,
                        blind_review_service.omnichannel_activation(),
                    )
                    return
                if path == "/v1/product-readiness":
                    try:
                        readiness = json.loads(readiness_path.read_text(encoding="utf-8"))
                        self._send_json(
                            HTTPStatus.OK,
                            _public_product_readiness(readiness),
                        )
                    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
                        self._send_json(
                            HTTPStatus.SERVICE_UNAVAILABLE,
                            {
                                "schema": "ProofLaunchProductReadinessPublicV1",
                                "status": "unavailable",
                                "error": "product_readiness_unavailable",
                            },
                        )
                    return
                if path == "/v1/public-signal-pilot":
                    try:
                        pilot = json.loads(
                            signal_pilot_path.read_text(encoding="utf-8")
                        )
                        self._send_json(
                            HTTPStatus.OK,
                            _public_signal_pilot(pilot),
                        )
                    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
                        self._send_json(
                            HTTPStatus.SERVICE_UNAVAILABLE,
                            {
                                "schema": "ProofLaunchPublicSignalGTMPilotPublicV1",
                                "status": "unavailable",
                                "error": "public_signal_pilot_unavailable",
                            },
                        )
                    return
                if path == "/v1/platform-market-expansion":
                    try:
                        expansion = json.loads(
                            platform_expansion_path.read_text(encoding="utf-8")
                        )
                        self._send_json(
                            HTTPStatus.OK,
                            _public_platform_market_expansion(expansion),
                        )
                    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
                        self._send_json(
                            HTTPStatus.SERVICE_UNAVAILABLE,
                            {
                                "schema": "ProofLaunchPlatformMarketExpansionPublicV1",
                                "status": "unavailable",
                                "error": "platform_market_expansion_unavailable",
                            },
                        )
                    return
                if path == "/v1/social-oss-landscape":
                    try:
                        landscape = json.loads(
                            oss_landscape_path.read_text(encoding="utf-8")
                        )
                        self._send_json(
                            HTTPStatus.OK,
                            _public_social_oss_landscape(landscape),
                        )
                    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
                        self._send_json(
                            HTTPStatus.SERVICE_UNAVAILABLE,
                            {
                                "schema": "ProofLaunchSocialOSSAdapterLandscapePublicV1",
                                "status": "unavailable",
                                "error": "social_oss_landscape_unavailable",
                            },
                        )
                    return
                if path == "/v1/last-mile-production-quality":
                    try:
                        quality = json.loads(
                            last_mile_quality_path.read_text(encoding="utf-8")
                        )
                        self._send_json(
                            HTTPStatus.OK,
                            _public_last_mile_production_quality(quality),
                        )
                    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
                        self._send_json(
                            HTTPStatus.SERVICE_UNAVAILABLE,
                            {
                                "schema": "ProofLaunchGTMLastMileProductionQualityPublicV1",
                                "status": "unavailable",
                                "error": "last_mile_production_quality_unavailable",
                            },
                        )
                    return
                if path == "/v1/platform-capability-showcase":
                    try:
                        self._send_json(
                            HTTPStatus.OK,
                            load_verified_platform_capability_showcase(project_root),
                        )
                    except (
                        OSError,
                        UnicodeError,
                        json.JSONDecodeError,
                        ValueError,
                    ):
                        self._send_json(
                            HTTPStatus.SERVICE_UNAVAILABLE,
                            {
                                "schema": "ProofLaunchPlatformCapabilityShowcasePublicV1",
                                "status": "unavailable",
                                "error": "platform_capability_showcase_unavailable",
                            },
                        )
                    return
                if path == "/v1/codex-integrated-campaign-portfolio":
                    try:
                        self._send_json(
                            HTTPStatus.OK,
                            load_verified_codex_integrated_campaign_portfolio(
                                project_root
                            ),
                        )
                    except (
                        OSError,
                        UnicodeError,
                        json.JSONDecodeError,
                        ValueError,
                    ):
                        self._send_json(
                            HTTPStatus.SERVICE_UNAVAILABLE,
                            {
                                "schema": "ProofLaunchCodexIntegratedCampaignPortfolioV1",
                                "status": "unavailable",
                                "error": "codex_integrated_campaign_portfolio_unavailable",
                            },
                        )
                    return
                if path == "/v1/codex-campaign-adaptation-summary":
                    try:
                        self._send_json(
                            HTTPStatus.OK,
                            load_verified_codex_campaign_adaptation_summary(
                                project_root
                            ),
                        )
                    except (
                        OSError,
                        UnicodeError,
                        json.JSONDecodeError,
                        ValueError,
                    ):
                        self._send_json(
                            HTTPStatus.SERVICE_UNAVAILABLE,
                            {
                                "schema": "ProofLaunchCodexCampaignAdaptationSummaryPublicV1",
                                "status": "unavailable",
                                "error": "codex_campaign_adaptation_summary_unavailable",
                            },
                        )
                    return
                if path == "/v1/codex-lighthouse-portfolio":
                    try:
                        self._send_json(
                            HTTPStatus.OK,
                            load_verified_codex_lighthouse_portfolio(project_root),
                        )
                    except (
                        OSError,
                        UnicodeError,
                        json.JSONDecodeError,
                        ValueError,
                    ):
                        self._send_json(
                            HTTPStatus.SERVICE_UNAVAILABLE,
                            {
                                "schema": "ProofLaunchCodexLighthousePortfolioPublicV1",
                                "status": "unavailable",
                                "error": "codex_lighthouse_portfolio_unavailable",
                            },
                        )
                    return
                if path == "/v1/concrete-product-effect-pk":
                    try:
                        ledger = json.loads(
                            concrete_product_effect_pk_path.read_text(encoding="utf-8")
                        )
                        self._send_json(
                            HTTPStatus.OK,
                            _public_concrete_product_effect_pk(ledger),
                        )
                    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
                        self._send_json(
                            HTTPStatus.SERVICE_UNAVAILABLE,
                            {
                                "schema": "ProofLaunchConcreteProductEffectPKLedgerPublicV1",
                                "status": "unavailable",
                                "error": "concrete_product_effect_pk_unavailable",
                            },
                        )
                    return
                if path == "/v1/named-product-baseline-capture-kit":
                    try:
                        capture_kit = json.loads(
                            named_product_baseline_capture_kit_path.read_text(
                                encoding="utf-8"
                            )
                        )
                        self._send_json(
                            HTTPStatus.OK,
                            _public_named_product_baseline_capture_kit(capture_kit),
                        )
                    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
                        self._send_json(
                            HTTPStatus.SERVICE_UNAVAILABLE,
                            {
                                "schema": "ProofLaunchNamedProductBaselineCaptureKitPublicV1",
                                "status": "unavailable",
                                "error": "named_product_baseline_capture_kit_unavailable",
                            },
                        )
                    return
                if path == "/v1/named-product-pk-portfolio":
                    try:
                        portfolio = json.loads(
                            named_product_pk_portfolio_path.read_text(encoding="utf-8")
                        )
                        self._send_json(
                            HTTPStatus.OK,
                            _public_named_product_pk_portfolio(portfolio),
                        )
                    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
                        self._send_json(
                            HTTPStatus.SERVICE_UNAVAILABLE,
                            {
                                "schema": "ProofLaunchNamedProductBlindPKPortfolioV1",
                                "status": "unavailable",
                                "error": "named_product_pk_portfolio_unavailable",
                            },
                        )
                    return
                if path == "/v1/named-product-challenger-admission":
                    try:
                        admission = json.loads(
                            named_product_challenger_admission_path.read_text(encoding="utf-8")
                        )
                        self._send_json(
                            HTTPStatus.OK,
                            _public_named_product_challenger_admission(admission),
                        )
                    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
                        self._send_json(
                            HTTPStatus.SERVICE_UNAVAILABLE,
                            {
                                "schema": "ProofLaunchNamedProductChallengerAdmissionPublicV1",
                                "status": "unavailable",
                                "error": "named_product_challenger_admission_unavailable",
                            },
                        )
                    return
                if path == "/v1/gtm-hybrid-quality-control":
                    try:
                        quality_control = json.loads(
                            gtm_hybrid_quality_control_path.read_text(encoding="utf-8")
                        )
                        self._send_json(
                            HTTPStatus.OK,
                            _public_gtm_hybrid_quality_control(quality_control),
                        )
                    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
                        self._send_json(
                            HTTPStatus.SERVICE_UNAVAILABLE,
                            {
                                "schema": "ProofLaunchGTMHybridQualityControlPublicV1",
                                "status": "unavailable",
                                "error": "gtm_hybrid_quality_control_unavailable",
                            },
                        )
                    return
                if path == "/v1/gtm-adaptive-capability-graph":
                    try:
                        adaptive_graph = json.loads(
                            gtm_adaptive_capability_graph_path.read_text(encoding="utf-8")
                        )
                        self._send_json(
                            HTTPStatus.OK,
                            _public_gtm_adaptive_capability_graph(
                                adaptive_graph,
                                parse_qs(parsed.query),
                            ),
                        )
                    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
                        self._send_json(
                            HTTPStatus.SERVICE_UNAVAILABLE,
                            {
                                "schema": "ProofLaunchGTMAdaptiveCapabilityGraphPublicV1",
                                "status": "unavailable",
                                "error": "gtm_adaptive_capability_graph_unavailable",
                            },
                        )
                    return
                if path == "/v1/local-multimodal-qualification":
                    try:
                        receipt = json.loads(
                            qualification_path.read_text(encoding="utf-8")
                        )
                        self._send_json(
                            HTTPStatus.OK,
                            {
                                "schema": receipt["schema"],
                                "content_sha256": receipt["content_sha256"],
                                "execution": receipt["execution"],
                                "models": receipt["models"],
                                "quality_gates": receipt["quality_gates"],
                                "campaign_binding": receipt["campaign_binding"],
                                "artifacts": {
                                    "speech_master": receipt["artifacts"]["speech_master"],
                                    "video_one_stage": receipt["artifacts"]["video_one_stage"],
                                },
                                "truth_boundary": receipt["truth_boundary"],
                            },
                        )
                    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError):
                        self._send_json(
                            HTTPStatus.SERVICE_UNAVAILABLE,
                            {"error": "local_multimodal_qualification_unavailable"},
                        )
                    return
                match = re.fullmatch(
                    rf"/v1/local-multimodal-qualification/assets/({_ASSET_ID})",
                    path,
                )
                if match:
                    self._send_qualification_asset(match.group(1))
                    return
                if path == "/v1/local-campaign-pack":
                    try:
                        receipt = self._campaign_pack_receipt()
                        public_artifacts = {
                            public_id: {
                                "url": f"/v1/local-campaign-pack/assets/{public_id}",
                                "media_type": binding[1],
                            }
                            for public_id, binding in campaign_pack_assets.items()
                        }
                        self._send_json(
                            HTTPStatus.OK,
                            {
                                "schema": receipt["schema"],
                                "campaign_id": receipt["campaign"]["campaign_id"],
                                "content_sha256": receipt["content_sha256"],
                                "source_generation": receipt["source_generation"],
                                "rejected_candidate_audit": receipt[
                                    "rejected_candidate_audit"
                                ],
                                "quality_gates": receipt["quality_gates"],
                                "artifacts": public_artifacts,
                                "external_publish_executed": receipt[
                                    "external_publish_executed"
                                ],
                                "truth_boundary": receipt["truth_boundary"],
                            },
                        )
                    except (
                        OSError,
                        UnicodeError,
                        json.JSONDecodeError,
                        KeyError,
                        TypeError,
                        IntegrityError,
                    ):
                        self._send_json(
                            HTTPStatus.SERVICE_UNAVAILABLE,
                            {"error": "local_campaign_pack_unavailable"},
                        )
                    return
                match = re.fullmatch(
                    rf"/v1/local-campaign-pack/assets/({_ASSET_ID})",
                    path,
                )
                if match:
                    self._send_campaign_pack_asset(match.group(1))
                    return
                if path == "/v1/model-cards":
                    try:
                        readiness = json.loads(readiness_path.read_text(encoding="utf-8"))
                        public = _public_product_readiness(readiness)
                        cards: list[dict[str, Any]] = []
                        route_head = public["local_models"]["route_head"]
                        generator = public["local_models"]["generator"]
                        if route_head["observed"]:
                            cards.append(
                                {
                                    "model_id": route_head["model_id"],
                                    "revision": route_head["digest"],
                                    "role": "14-node GTM Graph shadow router",
                                    "evidence_class": "local_training_frozen_test",
                                    "promotion_status": (
                                        "promoted"
                                        if route_head["promoted"]
                                        else "gate_passed_not_promoted"
                                    ),
                                    "training_observed": True,
                                    "automatic_external_action_enabled": False,
                                }
                            )
                        if generator["observed"]:
                            cards.append(
                                {
                                    "model_id": generator["model_id"],
                                    "revision": generator["digest"],
                                    "role": "bounded local GTM JSON generator",
                                    "evidence_class": "local_inference_contract_eval",
                                    "promotion_status": "baseline_not_training",
                                    "training_observed": generator["training_observed"],
                                    "automatic_external_action_enabled": False,
                                }
                            )
                        self._send_json(
                            HTTPStatus.OK,
                            {
                                "schema": "ProofLaunchLocalModelCardRegistryV1",
                                "model_cards": cards,
                                "external_publish_enabled": False,
                            },
                        )
                    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
                        self._send_json(
                            HTTPStatus.SERVICE_UNAVAILABLE,
                            {"error": "local_model_cards_unavailable"},
                        )
                    return
                if path == "/v1/evals/leaderboard":
                    try:
                        readiness = json.loads(readiness_path.read_text(encoding="utf-8"))
                        public = _public_product_readiness(readiness)
                        route_head = public["local_models"]["route_head"]
                        generator = public["local_models"]["generator"]
                        leaderboard: list[dict[str, Any]] = []
                        if route_head["observed"]:
                            leaderboard.append(
                                {
                                    "model_id": route_head["model_id"],
                                    "evidence_class": "frozen_local_test",
                                    "blinded": False,
                                    "case_count": route_head["test_examples"],
                                    "primary_metric": "macro_f1",
                                    "primary_value": route_head["macro_f1"],
                                    "accepted_coverage": route_head["accepted_coverage"],
                                    "accepted_accuracy": route_head["accepted_accuracy"],
                                }
                            )
                        if generator["observed"]:
                            leaderboard.append(
                                {
                                    "model_id": generator["model_id"],
                                    "evidence_class": "local_contract_eval",
                                    "blinded": False,
                                    "case_count": generator["case_count"],
                                    "primary_metric": "final_contract_pass_rate",
                                    "primary_value": generator["final_contract_pass_rate"],
                                    "first_pass_value": generator["first_pass_contract_rate"],
                                }
                            )
                        self._send_json(
                            HTTPStatus.OK,
                            {
                                "schema": "ProofLaunchLocalEvalLeaderboardV1",
                                "leaderboard": leaderboard,
                                "human_blind_quality_proven": False,
                            },
                        )
                    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
                        self._send_json(
                            HTTPStatus.SERVICE_UNAVAILABLE,
                            {"error": "local_eval_leaderboard_unavailable"},
                        )
                    return
                if path == "/v1/social-connectors":
                    connectors = list(connector_registry())
                    self._send_json(
                        HTTPStatus.OK,
                        {
                            "schema": "ProofLaunchOpenSourceConnectorRegistryV1",
                            "connectors": [asdict(item) for item in connectors],
                            "live_execution_admitted": sorted(
                                item.connector_id
                                for item in connectors
                                if item.live_execution_admitted
                            ),
                            "public_no_external_api_key_connector_ids": [
                                item.connector_id
                                for item in connectors
                                if not item.external_api_key_required
                            ],
                            "access_control_bypass_enabled": False,
                            "external_publish_enabled": False,
                        },
                    )
                    return
                if path == "/v1/memory-capsules":
                    tenant_id = self._tenant_id()
                    project_id = parse_qs(parsed.query).get("project_id", [""])[0]
                    if not project_id:
                        raise ProductionRuntimeError("project_id query parameter is required")
                    self._send_json(
                        HTTPStatus.OK,
                        service.memory_capsule_imports(tenant_id, project_id),
                    )
                    return
                if path == "/v1/strategy-memory-resolutions":
                    tenant_id = self._tenant_id()
                    project_id = parse_qs(parsed.query).get("project_id", [""])[0]
                    if not project_id:
                        raise ProductionRuntimeError(
                            "project_id query parameter is required"
                        )
                    self._send_json(
                        HTTPStatus.OK,
                        service.strategy_memory_resolutions(
                            tenant_id,
                            project_id,
                        ),
                    )
                    return
                match = re.fullmatch(rf"/v1/runs/({_RUN_ID})/gtm-cockpit", path)
                if match:
                    tenant_id = self._tenant_id()
                    self._require_run_tenant(match.group(1), tenant_id)
                    self._send_json(
                        HTTPStatus.OK,
                        service.gtm_cockpit(match.group(1)),
                    )
                    return
                match = re.fullmatch(
                    rf"/v1/runs/({_RUN_ID})/capability-deliverables", path
                )
                if match:
                    tenant_id = self._tenant_id()
                    run_id = match.group(1)
                    self._require_run_tenant(run_id, tenant_id)
                    records = service.store.list_capability_deliverables(run_id)
                    reviews = service.store.list_capability_deliverable_reviews(run_id)
                    self._send_json(
                        HTTPStatus.OK,
                        {
                            "schema": "ProofLaunchRunBoundCapabilityDeliverableCollectionV1",
                            "run_id": run_id,
                            "deliverable_count": len(records),
                            "review_count": len(reviews),
                            "deliverables": [asdict(item) for item in records],
                            "reviews": [asdict(item) for item in reviews],
                            "production_effect_proven": False,
                            "four_a_quality_proven": False,
                        },
                    )
                    return
                match = re.fullmatch(rf"/v1/runs/({_RUN_ID})/outcomes", path)
                if match:
                    tenant_id = self._tenant_id()
                    self._require_run_tenant(match.group(1), tenant_id)
                    self._send_json(
                        HTTPStatus.OK,
                        service.effect_observations(match.group(1)),
                    )
                    return
                match = re.fullmatch(
                    rf"/v1/runs/({_RUN_ID})/publication-receipts",
                    path,
                )
                if match:
                    tenant_id = self._tenant_id()
                    self._require_run_tenant(match.group(1), tenant_id)
                    self._send_json(
                        HTTPStatus.OK,
                        service.manual_publication_receipts(match.group(1)),
                    )
                    return
                match = re.fullmatch(
                    rf"/v1/runs/({_RUN_ID})/production-observation-kit",
                    path,
                )
                if match:
                    tenant_id = self._tenant_id()
                    run_id = match.group(1)
                    self._require_run_tenant(run_id, tenant_id)
                    if not self._approval_authorized():
                        self._send_json(
                            HTTPStatus.FORBIDDEN,
                            {"error": "operator approval token is required"},
                        )
                        return
                    body, observed, filename = (
                        service.production_observation_field_kit(run_id)
                    )
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "application/zip")
                    self.send_header(
                        "Content-Disposition",
                        f'attachment; filename="{filename}"',
                    )
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("ETag", f'"sha256:{observed}"')
                    self.send_header("Cache-Control", "no-store")
                    self.send_header(
                        "X-ProofLaunch-Evidence-Class",
                        "approved-experiment-empty-production-observation-kit",
                    )
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.end_headers()
                    if self.command != "HEAD":
                        self.wfile.write(body)
                    return
                match = re.fullmatch(rf"/v1/runs/({_RUN_ID})/economics", path)
                if match:
                    tenant_id = self._tenant_id()
                    self._require_run_tenant(match.group(1), tenant_id)
                    self._send_json(
                        HTTPStatus.OK,
                        service.revenue_economics(match.group(1)),
                    )
                    return
                match = re.fullmatch(rf"/v1/runs/({_RUN_ID})/learning-memories", path)
                if match:
                    tenant_id = self._tenant_id()
                    self._require_run_tenant(match.group(1), tenant_id)
                    self._send_json(
                        HTTPStatus.OK,
                        service.learning_memories_for_run(match.group(1)),
                    )
                    return
                match = re.fullmatch(rf"/v1/runs/({_RUN_ID})/events", path)
                if match:
                    tenant_id = self._tenant_id()
                    self._require_run_tenant(match.group(1), tenant_id)
                    if "application/json" in self.headers.get("Accept", ""):
                        self._send_event_batch(match.group(1))
                    else:
                        self._stream_events(
                            match.group(1),
                            follow=parse_qs(parsed.query).get("follow", ["0"])[0] == "1",
                        )
                    return
                match = re.fullmatch(rf"/v1/runs/({_RUN_ID})/preview", path)
                if match:
                    tenant_id = self._tenant_id()
                    self._require_run_tenant(match.group(1), tenant_id)
                    self._send_json(HTTPStatus.OK, service.preview(match.group(1)))
                    return
                match = re.fullmatch(
                    rf"/v1/runs/({_RUN_ID})/preview/({_ASSET_ID})/(creative|product_layer|background)",
                    path,
                )
                if match:
                    tenant_id = self._tenant_id()
                    self._require_run_tenant(match.group(1), tenant_id)
                    candidate = service.preview_asset(
                        match.group(1), match.group(2), match.group(3)
                    )
                    body = candidate.read_bytes()
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.end_headers()
                    self.wfile.write(body)
                    return
                match = re.fullmatch(rf"/v1/runs/({_RUN_ID})/bundle", path)
                if match:
                    tenant_id = self._tenant_id()
                    self._require_run_tenant(match.group(1), tenant_id)
                    bundle = service.bundle_path(match.group(1))
                    body = bundle.read_bytes()
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "application/zip")
                    self.send_header(
                        "Content-Disposition",
                        f'attachment; filename="{match.group(1)}.zip"',
                    )
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.end_headers()
                    self.wfile.write(body)
                    return
                match = re.fullmatch(rf"/v1/runs/({_RUN_ID})", path)
                if match:
                    tenant_id = self._tenant_id()
                    self._require_run_tenant(match.group(1), tenant_id)
                    self._send_json(
                        HTTPStatus.OK,
                        _public_snapshot(service.snapshot(match.group(1))),
                    )
                    return
                match = re.fullmatch(
                    r"/v1/campaign-pack-blind-review/assets/(asset-[0-9a-f]{24})",
                    path,
                )
                if match:
                    self._send_campaign_pack_blind_review_asset(match.group(1))
                    return
                if self._serve_static(path):
                    return
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            except KeyError:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "unknown_resource"})
            except TenantAuthenticationError as error:
                self._send_json(HTTPStatus.UNAUTHORIZED, {"error": str(error)})
            except BlindReviewAuthorizationError as error:
                self._send_json(HTTPStatus.FORBIDDEN, {"error": str(error)})
            except BlindReviewConflictError as error:
                self._send_json(HTTPStatus.CONFLICT, {"error": str(error)})
            except BlindReviewServiceError as error:
                self._send_json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(error)})
            except CampaignPackBlindReviewAuthorizationError as error:
                self._send_json(HTTPStatus.FORBIDDEN, {"error": str(error)})
            except CampaignPackBlindReviewConflictError as error:
                self._send_json(HTTPStatus.CONFLICT, {"error": str(error)})
            except CampaignPackBlindReviewError as error:
                self._send_json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(error)})
            except JudgeCalibrationAuthorizationError as error:
                self._send_json(HTTPStatus.FORBIDDEN, {"error": str(error)})
            except JudgeCalibrationConflictError as error:
                self._send_json(HTTPStatus.CONFLICT, {"error": str(error)})
            except JudgeCalibrationError as error:
                self._send_json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(error)})
            except ConflictError as error:
                self._send_json(HTTPStatus.CONFLICT, {"error": str(error)})
            except (ProductionRuntimeError, SubmissionStoreError) as error:
                self._send_json(HTTPStatus.CONFLICT, {"error": str(error)})

        def _stream_events(self, run_id: str, *, follow: bool) -> None:
            service.store.get_run(run_id)
            raw_last = self.headers.get("Last-Event-ID", "0")
            try:
                last_event_id = int(raw_last)
            except ValueError as error:
                raise ProductionRuntimeError("Last-Event-ID must be an integer") from error
            if last_event_id < 0:
                raise ProductionRuntimeError("Last-Event-ID must be non-negative")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "keep-alive" if follow else "close")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            heartbeat_at = time.monotonic() + 15.0
            try:
                while True:
                    events = service.store.events_after(run_id, last_event_id)
                    for event in events:
                        snapshot = _public_snapshot(service.snapshot(run_id))
                        public = _public_event(event, snapshot["status"])
                        frame = (
                            f"id: {event.event_id}\n"
                            f"event: {event.event_type}\n"
                            f"data: {_json_bytes(public).decode('utf-8')}\n\n"
                        ).encode("utf-8")
                        self.wfile.write(frame)
                        self.wfile.flush()
                        last_event_id = event.event_id
                    status = _public_status(service.store.get_run(run_id).status)
                    if not follow or status in _TERMINAL_PUBLIC:
                        self.close_connection = True
                        return
                    if time.monotonic() >= heartbeat_at:
                        self.wfile.write(b": heartbeat\n\n")
                        self.wfile.flush()
                        heartbeat_at = time.monotonic() + 15.0
                    time.sleep(0.25)
            except (BrokenPipeError, ConnectionResetError):
                return

        def _send_event_batch(self, run_id: str) -> None:
            raw_last = self.headers.get("Last-Event-ID", "0")
            try:
                last_event_id = int(raw_last)
            except ValueError as error:
                raise ProductionRuntimeError("Last-Event-ID must be an integer") from error
            if last_event_id < 0:
                raise ProductionRuntimeError("Last-Event-ID must be non-negative")
            snapshot = _public_snapshot(service.snapshot(run_id))
            events = [
                _public_event(event, snapshot["status"])
                for event in service.store.events_after(run_id, last_event_id)
            ]
            self._send_json(
                HTTPStatus.OK,
                {
                    "schema": "ProofLaunchRunEventBatchV1",
                    "run_id": run_id,
                    "current_status": snapshot["status"],
                    "terminal": snapshot["status"] in _TERMINAL_PUBLIC,
                    "events": events,
                },
            )

        def _serve_static(self, path: str) -> bool:
            static_files = {
                "/styles.css": ("styles.css", "text/css; charset=utf-8"),
                "/styles.min.css": ("styles.min.css", "text/css; charset=utf-8"),
                "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                "/app.min.js": ("app.min.js", "text/javascript; charset=utf-8"),
                "/judge-manifest.json": ("judge-manifest.json", "application/json; charset=utf-8"),
                "/llms.txt": ("llms.txt", "text/plain; charset=utf-8"),
            }
            if path in static_files:
                filename, content_type = static_files[path]
                return self._write_static(filename, content_type)
            if path.startswith("/assets/"):
                content_types = {
                    ".png": "image/png",
                    ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg",
                    ".webp": "image/webp",
                    ".svg": "image/svg+xml",
                    ".mp4": "video/mp4",
                }
                content_type = content_types.get(Path(path).suffix.lower())
                if content_type is None:
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": "web_asset_type_not_allowed"})
                    return True
                return self._write_static(path.removeprefix("/"), content_type)
            spa_route = path in {
                "/",
                "/index.html",
                "/datasets",
                "/models",
                "/spec",
                "/rocm",
                "/PDF",
            } or path.startswith(
                ("/workspace/", "/front/", "/control/", "/admin/", "/datasets/", "/models/")
            )
            if spa_route:
                return self._write_static("index.html", "text/html; charset=utf-8")
            return False

        def _write_static(self, filename: str, content_type: str) -> bool:
            candidate = (root / filename).resolve()
            try:
                candidate.relative_to(root)
            except ValueError:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "web_asset_outside_root"})
                return True
            if not candidate.is_file():
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "web_asset_missing"})
                return True
            body = candidate.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)
            return True

    return Handler


def _public_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(snapshot)
    result["status"] = _public_status(str(result.get("status", "unknown")))
    return result


def _public_event(event: Any, current_status: str) -> dict[str, Any]:
    event_status = event.payload.get(
        "status",
        event.payload.get("to", event.payload.get("stage", current_status)),
    )
    return {
        "sequence": event.sequence,
        "event_id": event.event_id,
        "type": event.event_type,
        "status": _public_status(str(event_status)),
        "current_status": current_status,
        "payload": dict(event.payload),
        "event_hash": event.event_hash,
    }


def _public_last_mile_production_quality(payload: object) -> dict[str, Any]:
    if (
        not isinstance(payload, Mapping)
        or payload.get("schema")
        != "ProofLaunchGTMLastMileProductionQualityBenchmarkV1"
    ):
        raise ValueError("last-mile quality schema is unsupported")
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if not isinstance(supplied, str) or hashlib.sha256(_json_bytes(unsigned)).hexdigest() != supplied:
        raise ValueError("last-mile quality digest is invalid")
    lanes = payload.get("lanes")
    portfolio = payload.get("portfolio")
    effect_definition = payload.get("effect_definition")
    quality_ladder = payload.get("quality_ladder")
    if (
        not isinstance(lanes, list)
        or payload.get("lane_count") != 14
        or len(lanes) != 14
        or not isinstance(portfolio, Mapping)
        or not isinstance(effect_definition, Mapping)
        or not isinstance(quality_ladder, Mapping)
        or effect_definition.get("primary")
        != "last_mile_generated_execution_quality"
        or quality_ladder.get("schema")
        != "ProofLaunchGTMProductionQualityEvaluationV1"
        or quality_ladder.get("current_state") != "mechanically_ready"
        or quality_ladder.get("promotion_allowed") is not False
        or quality_ladder.get("automatic_release_allowed") is not False
        or quality_ladder.get("automatic_learning_allowed") is not False
        or not isinstance(quality_ladder.get("gates"), Mapping)
        or quality_ladder["gates"].get("G0_contract", {}).get("passed") is not True
        or quality_ladder["gates"].get("G1_professional_editor", {}).get("passed") is not False
        or quality_ladder["gates"].get("G2_same_brief_blind_pk", {}).get("passed") is not False
        or quality_ladder["gates"].get("G3_production_effect", {}).get("passed") is not False
        or portfolio.get("last_mile_execution_quality_alignment_achieved")
        is not False
        or portfolio.get("business_outcome_observed") is not False
        or portfolio.get("four_a_quality_proven") is not False
        or portfolio.get("same_brief_internal_challenger_compiled_lane_count") != 14
        or not isinstance(payload.get("current_review_evidence"), Mapping)
        or payload["current_review_evidence"].get("unified_expected") != 80
        or payload["current_review_evidence"].get("unified_submitted") != 0
        or payload["current_review_evidence"].get("unified_top_product_baselines_present") is not False
    ):
        raise ValueError("last-mile quality contract is incomplete")
    for lane in lanes:
        if (
            not isinstance(lane, Mapping)
            or not isinstance(lane.get("lane_id"), str)
            or lane.get("last_mile_execution_quality_alignment_achieved") is not False
            or lane.get("business_outcome_observed") is not False
            or lane.get("same_brief_peer_comparison_completed") is not False
        ):
            raise ValueError("last-mile quality lane is invalid")
    return dict(payload)


def _public_concrete_product_effect_pk(payload: object) -> dict[str, Any]:
    if (
        not isinstance(payload, Mapping)
        or payload.get("schema") != "ProofLaunchConcreteProductEffectPKLedgerV1"
    ):
        raise ValueError("concrete product-effect PK schema is unsupported")
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if not isinstance(supplied, str) or hashlib.sha256(_json_bytes(unsigned)).hexdigest() != supplied:
        raise ValueError("concrete product-effect PK digest is invalid")
    categories = payload.get("categories")
    rows = payload.get("product_pk_rows")
    portfolio = payload.get("portfolio")
    gate = payload.get("acceptance_gate")
    if (
        not isinstance(categories, list)
        or len(categories) != 13
        or payload.get("category_count") != 13
        or not isinstance(rows, list)
        or len(rows) != 130
        or payload.get("reference_product_row_count") != 130
        or not isinstance(portfolio, Mapping)
        or portfolio.get("completed_product_pk_rows") != 0
        or portfolio.get("effect_aligned_categories") != 0
        or portfolio.get("categories_with_internal_same_brief_opponent") != 13
        or portfolio.get("categories_with_named_product_baseline") != 0
        or not isinstance(gate, Mapping)
        or gate.get("product_integration_can_substitute_for_effect_pk") is not False
        or gate.get("model_judge_can_promote") is not False
    ):
        raise ValueError("concrete product-effect PK contract is incomplete")
    if any(
        not isinstance(row, Mapping)
        or row.get("comparison_status") != "not_completed"
        or row.get("qualified_human_review_count") != 0
        or row.get("effect_alignment_achieved") is not False
        for row in rows
    ):
        raise ValueError("concrete product-effect PK row overclaims evidence")
    return dict(payload)


def _public_named_product_baseline_capture_kit(payload: object) -> dict[str, Any]:
    if (
        not isinstance(payload, Mapping)
        or payload.get("schema") != "ProofLaunchNamedProductBaselineCaptureKitV1"
    ):
        raise ValueError("named-product baseline capture kit schema is unsupported")
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if not isinstance(supplied, str) or hashlib.sha256(_json_bytes(unsigned)).hexdigest() != supplied:
        raise ValueError("named-product baseline capture kit digest is invalid")
    slots = payload.get("capture_slots")
    briefs = payload.get("frozen_briefs")
    if (
        payload.get("category_count") != 13
        or payload.get("capture_slot_count") != 130
        or payload.get("authorized_baseline_count") != 0
        or not isinstance(slots, list)
        or len(slots) != 130
        or not isinstance(briefs, list)
        or len(briefs) != 13
        or payload.get("network_submission_enabled") is not False
        or payload.get("automatic_product_execution_enabled") is not False
        or payload.get("automatic_pairing_enabled") is not False
        or payload.get("automatic_pk_promotion_enabled") is not False
        or payload.get("human_review_required") is not True
    ):
        raise ValueError("named-product baseline capture kit contract is incomplete")
    slot_ids: set[str] = set()
    for slot in slots:
        if (
            not isinstance(slot, Mapping)
            or not isinstance(slot.get("capture_slot_id"), str)
            or slot["capture_slot_id"] in slot_ids
            or slot.get("status") != "awaiting_authorized_baseline"
            or not isinstance(slot.get("reference_product"), str)
            or not isinstance(slot.get("reference_product_url"), str)
            or not isinstance(slot.get("allowed_extensions"), list)
            or not isinstance(slot.get("maximum_artifact_bytes"), int)
        ):
            raise ValueError("named-product baseline capture slot is invalid")
        slot_ids.add(slot["capture_slot_id"])
    categories: dict[str, dict[str, Any]] = {}
    brief_by_category = {
        item.get("category_id"): item
        for item in briefs
        if isinstance(item, Mapping) and isinstance(item.get("category_id"), str)
    }
    for slot in slots:
        category_id = str(slot["category_id"])
        summary = categories.setdefault(
            category_id,
            {
                "category_id": category_id,
                "capture_slot_count": 0,
                "authorized_baseline_count": 0,
                "allowed_extensions": list(slot["allowed_extensions"]),
                "maximum_artifact_bytes": slot["maximum_artifact_bytes"],
                "frozen_brief_sha256": slot["frozen_brief_sha256"],
                "status": "awaiting_authorized_baselines",
            },
        )
        if (
            summary["allowed_extensions"] != slot["allowed_extensions"]
            or summary["maximum_artifact_bytes"] != slot["maximum_artifact_bytes"]
            or summary["frozen_brief_sha256"] != slot["frozen_brief_sha256"]
        ):
            raise ValueError("named-product capture category contract drifted")
        summary["capture_slot_count"] += 1
    if (
        len(categories) != 13
        or set(categories) != set(brief_by_category)
        or any(item["capture_slot_count"] != 10 for item in categories.values())
    ):
        raise ValueError("named-product capture category inventory drifted")
    public: dict[str, Any] = {
        "schema": "ProofLaunchNamedProductBaselineCaptureKitPublicV1",
        "source_manifest_content_sha256": supplied,
        "category_count": 13,
        "capture_slot_count": 130,
        "authorized_baseline_count": 0,
        "categories": [categories[key] for key in sorted(categories)],
        "network_submission_enabled": False,
        "automatic_product_execution_enabled": False,
        "automatic_pairing_enabled": False,
        "automatic_pk_promotion_enabled": False,
        "human_review_required": True,
        "truth_boundary": payload.get("truth_boundary"),
    }
    public["content_sha256"] = hashlib.sha256(_json_bytes(public)).hexdigest()
    return public


def _public_named_product_pk_portfolio(payload: object) -> dict[str, Any]:
    if (
        not isinstance(payload, Mapping)
        or payload.get("schema") != "ProofLaunchNamedProductBlindPKPortfolioV1"
    ):
        raise ValueError("named-product PK portfolio schema is unsupported")
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if not isinstance(supplied, str) or hashlib.sha256(_json_bytes(unsigned)).hexdigest() != supplied:
        raise ValueError("named-product PK portfolio digest is invalid")
    categories = payload.get("categories")
    completed = payload.get("completed_product_pk_rows")
    won = payload.get("candidate_won_product_pk_rows")
    aligned = payload.get("effect_aligned_category_count")
    global_alignment = completed == 130 and won == 130 and aligned == 13
    if (
        payload.get("category_count") != 13
        or payload.get("reference_product_row_count") != 130
        or type(completed) is not int or not 0 <= completed <= 130
        or type(won) is not int or not 0 <= won <= completed
        or payload.get("remaining_product_pk_rows") != 130 - completed
        or type(aligned) is not int or not 0 <= aligned <= 13
        or not isinstance(categories, list) or len(categories) != 13
        or payload.get("named_product_last_mile_alignment_achieved") is not global_alignment
        or payload.get("automatic_runtime_switch_enabled") is not False
        or payload.get("automatic_strategy_mutation_enabled") is not False
        or payload.get("automatic_publish_enabled") is not False
        or payload.get("four_a_quality_proven") is not False
        or payload.get("causal_business_effect_proven") is not False
    ):
        raise ValueError("named-product PK portfolio contract is incomplete")
    category_ids: set[str] = set()
    for category in categories:
        if not isinstance(category, Mapping):
            raise ValueError("named-product PK category is invalid")
        category_id = category.get("category_id")
        category_completed = category.get("completed_product_pk_rows")
        category_won = category.get("candidate_won_product_pk_rows")
        category_alignment = category_completed == 10 and category_won == 10
        if (
            not isinstance(category_id, str) or not category_id or category_id in category_ids
            or category.get("reference_product_count") != 10
            or type(category_completed) is not int or not 0 <= category_completed <= 10
            or type(category_won) is not int or not 0 <= category_won <= category_completed
            or category.get("remaining_product_pk_rows") != 10 - category_completed
            or category.get("category_named_product_last_mile_alignment_achieved") is not category_alignment
        ):
            raise ValueError("named-product PK category contract is inconsistent")
        category_ids.add(category_id)
    if sum(item["completed_product_pk_rows"] for item in categories) != completed or sum(
        item["candidate_won_product_pk_rows"] for item in categories
    ) != won or sum(
        1 for item in categories if item["category_named_product_last_mile_alignment_achieved"]
    ) != aligned:
        raise ValueError("named-product PK portfolio totals drifted")
    return dict(payload)


def _public_gtm_hybrid_quality_control(payload: object) -> dict[str, Any]:
    if (
        not isinstance(payload, Mapping)
        or payload.get("schema") != "ProofLaunchGTMHybridQualityControlV1"
    ):
        raise ValueError("GTM hybrid quality-control schema is unsupported")
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if (
        not isinstance(supplied, str)
        or hashlib.sha256(_json_bytes(unsigned)).hexdigest() != supplied
    ):
        raise ValueError("GTM hybrid quality-control digest is invalid")
    portfolio = payload.get("portfolio")
    invariants = payload.get("routing_invariants")
    lanes = payload.get("lanes")
    jobs = payload.get("jobs")
    if (
        not isinstance(portfolio, Mapping)
        or not isinstance(invariants, Mapping)
        or not isinstance(lanes, list)
        or not isinstance(jobs, list)
        or len(lanes) != 13
        or len(jobs) != 130
        or portfolio.get("category_count") != 13
        or portfolio.get("job_count") != 130
        or portfolio.get("local_ready_category_count") != 13
        or portfolio.get("challenger_dossier_count_admitted") != 13
        or portfolio.get("authorized_named_product_baseline_count") != 0
        or portfolio.get("completed_named_product_pk_count") != 0
        or portfolio.get("candidate_wins") != 0
        or portfolio.get("effect_aligned_categories") != 0
        or invariants.get("hardware_and_provider_are_replaceable") is not True
        or invariants.get("jobs_route_by_capability_not_vendor") is not True
        or invariants.get("local_pipeline_continues_without_cloud") is not True
        or invariants.get("cloud_gpu_is_quality_accelerator_not_product_runtime_dependency") is not True
        or invariants.get("radeon_required_for_product_closure") is not False
        or invariants.get("model_judge_can_promote") is not False
        or invariants.get("human_release_required") is not True
        or invariants.get("automatic_publish_send_spend_or_strategy_mutation") is not False
    ):
        raise ValueError("GTM hybrid quality-control contract is incomplete")
    category_ids: set[str] = set()
    public_lanes = []
    for lane in lanes:
        if not isinstance(lane, Mapping):
            raise ValueError("GTM hybrid quality lane is invalid")
        category_id = lane.get("category_id")
        if (
            not isinstance(category_id, str)
            or not category_id
            or category_id in category_ids
            or lane.get("local_route_ready") is not True
            or lane.get("challenger_dossier_admitted") is not True
            or lane.get("cloud_gpu_is_product_runtime_dependency") is not False
            or lane.get("model_judge_can_promote") is not False
            or lane.get("human_release_required") is not True
        ):
            raise ValueError("GTM hybrid quality lane contract is inconsistent")
        category_ids.add(category_id)
        public_lanes.append(
            {
                "category_id": category_id,
                "same_brief_task": lane.get("same_brief_task"),
                "effect_pk_question": lane.get("effect_pk_question"),
                "quality_axes": lane.get("quality_axes"),
                "output_contract": lane.get("output_contract"),
                "hard_gates": lane.get("hard_gates"),
                "failure_signals": lane.get("failure_signals"),
                "local_route_ready": True,
                "preferred_cloud_roles": lane.get("preferred_cloud_roles"),
                "cloud_quality_acceleration_ready": lane.get(
                    "cloud_quality_acceleration_ready"
                ),
                "cloud_gpu_is_product_runtime_dependency": False,
                "open_source_projects": [
                    {
                        "project_id": project.get("project_id"),
                        "revision": project.get("revision"),
                        "license": project.get("license"),
                        "decision": project.get("decision"),
                    }
                    for project in lane.get("open_source_reuse", [])
                    if isinstance(project, Mapping)
                ],
            }
        )
    public = {
        "schema": "ProofLaunchGTMHybridQualityControlPublicV1",
        "source_content_sha256": supplied,
        "portfolio": dict(portfolio),
        "routing_invariants": dict(invariants),
        "lanes": public_lanes,
        "four_hour_execution_order": payload.get("four_hour_execution_order"),
        "truth_boundary": payload.get("truth_boundary"),
    }
    public["content_sha256"] = hashlib.sha256(_json_bytes(public)).hexdigest()
    return public


def _public_gtm_adaptive_capability_graph(
    payload: object,
    query: Mapping[str, list[str]],
) -> dict[str, Any]:
    if (
        not isinstance(payload, Mapping)
        or payload.get("schema") != "ProofLaunchGTMAdaptiveCapabilityGraphMatrixV1"
    ):
        raise ValueError("GTM adaptive capability-graph schema is unsupported")
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if (
        not isinstance(supplied, str)
        or hashlib.sha256(_json_bytes(unsigned)).hexdigest() != supplied
    ):
        raise ValueError("GTM adaptive capability-graph digest is invalid")
    dimensions = payload.get("dimensions")
    coverage = payload.get("coverage")
    graph = payload.get("graph_loop_harness")
    lane_contracts = payload.get("lane_execution_contracts")
    shadows = payload.get("shadow_candidate_registry")
    executor = payload.get("executor_binding")
    contexts = payload.get("contexts")
    if (
        not isinstance(dimensions, Mapping)
        or not isinstance(coverage, Mapping)
        or not isinstance(graph, Mapping)
        or not isinstance(lane_contracts, Mapping)
        or len(lane_contracts) != 13
        or not isinstance(shadows, Mapping)
        or not isinstance(executor, Mapping)
        or not isinstance(contexts, list)
        or len(contexts) != 6912
        or coverage.get("context_count") != 6912
        or coverage.get("lane_count_per_context") != 13
        or coverage.get("lane_decision_count") != 89856
        or coverage.get("zero_budget_paid_activation_count") != 0
        or coverage.get("regulated_missing_specialist_gate_count") != 0
        or coverage.get("automatic_external_action_count") != 0
        or coverage.get("named_product_pk_jobs_preserved") != 130
        or coverage.get("named_product_pk_wins") != 0
        or executor.get("included_in_plan_identity") is not False
        or shadows.get("automatic_install_enabled") is not False
        or shadows.get("automatic_skill_script_execution_enabled") is not False
        or shadows.get("automatic_online_training_enabled") is not False
        or graph.get("global_harness", {}).get(
            "automatic_publish_send_spend_or_strategy_mutation"
        )
        is not False
    ):
        raise ValueError("GTM adaptive capability-graph contract is incomplete")
    seen: set[str] = set()
    for row in contexts:
        row_dimensions = row.get("dimensions") if isinstance(row, Mapping) else None
        lane_states = row.get("lane_states") if isinstance(row, Mapping) else None
        context_id = row.get("context_id") if isinstance(row, Mapping) else None
        if (
            not isinstance(context_id, str)
            or not context_id
            or context_id in seen
            or not isinstance(row_dimensions, Mapping)
            or not isinstance(lane_states, Mapping)
            or len(lane_states) != 13
            or sum(state == "FOCUS" for state in lane_states.values()) != 4
            or row.get("human_release_required") is not True
            or row.get("automatic_external_actions") != 0
            or row.get("node_loop_iteration_cap") not in {1, 2, 3}
            or (
                row_dimensions.get("budget") == "zero"
                and (
                    lane_states.get("advertising_activation") != "EXCLUDED"
                    or row.get("paid_activation_candidate_count") != 0
                )
            )
            or (
                row_dimensions.get("industry_risk") == "high_regulation"
                and row.get("specialist_approval_required") is not True
            )
        ):
            raise ValueError("GTM adaptive context contract is inconsistent")
        seen.add(context_id)

    query_to_dimension = {
        "business_model": "business_models",
        "lifecycle": "lifecycle_stages",
        "budget": "budget_tiers",
        "industry_risk": "industry_risk_tiers",
        "company_scale": "company_scales",
        "distribution_strength": "distribution_strengths",
        "content_capacity": "content_capacities",
        "sales_motion": "sales_motions",
    }
    defaults = {
        "business_model": "b2b",
        "lifecycle": "launch",
        "budget": "small",
        "industry_risk": "standard",
        "company_scale": "startup",
        "distribution_strength": "emerging",
        "content_capacity": "standard",
        "sales_motion": "hybrid",
    }
    selected_dimensions: dict[str, str] = {}
    for query_name, dimension_name in query_to_dimension.items():
        values = query.get(query_name, [])
        if len(values) > 1:
            raise ValueError("adaptive selector query value is ambiguous")
        value = values[0] if values else defaults[query_name]
        allowed = dimensions.get(dimension_name)
        if not isinstance(allowed, list) or value not in allowed:
            raise ValueError("adaptive selector query value is invalid")
        selected_dimensions[query_name] = value
    selected = next(
        (
            row
            for row in contexts
            if all(row["dimensions"].get(key) == value for key, value in selected_dimensions.items())
        ),
        None,
    )
    if selected is None:
        raise ValueError("adaptive selector context was not found")
    public = {
        "schema": "ProofLaunchGTMAdaptiveCapabilityGraphPublicV1",
        "source_content_sha256": supplied,
        "dimensions": dict(dimensions),
        "coverage": dict(coverage),
        "graph_loop_harness": dict(graph),
        "lane_execution_contracts": dict(lane_contracts),
        "shadow_candidate_registry": dict(shadows),
        "executor_binding": dict(executor),
        "selected_context": dict(selected),
        "truth_boundary": payload.get("truth_boundary"),
    }
    public["content_sha256"] = hashlib.sha256(_json_bytes(public)).hexdigest()
    return public


def _public_named_product_challenger_admission(payload: object) -> dict[str, Any]:
    if (
        not isinstance(payload, Mapping)
        or payload.get("schema") != "ProofLaunchNamedProductChallengerAdmissionV1"
    ):
        raise ValueError("named-product challenger admission schema is unsupported")
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if not isinstance(supplied, str) or hashlib.sha256(_json_bytes(unsigned)).hexdigest() != supplied:
        raise ValueError("named-product challenger admission digest is invalid")
    categories = payload.get("categories")
    admitted = payload.get("admitted_category_count")
    blocked = payload.get("blocked_category_count")
    if (
        payload.get("category_count") != 13
        or payload.get("reference_product_row_count") != 130
        or payload.get("dossier_count") != 13
        or type(admitted) is not int or type(blocked) is not int
        or admitted + blocked != 13
        or not isinstance(categories, list) or len(categories) != 13
        or payload.get("automatic_pairing_enabled") is not False
        or payload.get("automatic_product_execution_enabled") is not False
        or payload.get("automatic_pk_promotion_enabled") is not False
        or payload.get("four_a_quality_proven") is not False
    ):
        raise ValueError("named-product challenger admission contract is incomplete")
    public_categories: list[dict[str, Any]] = []
    category_ids: set[str] = set()
    for category in categories:
        if not isinstance(category, Mapping):
            raise ValueError("named-product challenger admission category is invalid")
        category_id = category.get("category_id")
        dossier = category.get("dossier")
        is_admitted = category.get("named_product_pk_preparation_admitted")
        gaps = category.get("blocking_gaps")
        gap_count = category.get("blocking_gap_count")
        if (
            not isinstance(category_id, str) or not category_id or category_id in category_ids
            or not isinstance(dossier, Mapping)
            or not isinstance(dossier.get("sha256"), str)
            or not isinstance(dossier.get("bytes"), int) or dossier["bytes"] < 1
            or type(is_admitted) is not bool
            or not isinstance(gaps, list) or any(not isinstance(item, str) or not item for item in gaps)
            or gap_count != len(gaps)
            or is_admitted is not (gap_count == 0)
            or category.get("dossier_compiled") is not True
            or category.get("same_brief_material_complete") is not is_admitted
        ):
            raise ValueError("named-product challenger admission category drifted")
        category_ids.add(category_id)
        public_categories.append(
            {
                "category_id": category_id,
                "dossier_sha256": dossier["sha256"],
                "dossier_bytes": dossier["bytes"],
                "source_artifact_count": category.get("source_artifact_count"),
                "named_product_pk_preparation_admitted": is_admitted,
                "blocking_gap_count": gap_count,
                "blocking_gaps": list(gaps),
                "repair_action": category.get("repair_action"),
            }
        )
    if sum(item["named_product_pk_preparation_admitted"] for item in public_categories) != admitted:
        raise ValueError("named-product challenger admission totals drifted")
    public: dict[str, Any] = {
        "schema": "ProofLaunchNamedProductChallengerAdmissionPublicV1",
        "source_manifest_content_sha256": supplied,
        "category_count": 13,
        "reference_product_row_count": 130,
        "dossier_count": 13,
        "admitted_category_count": admitted,
        "blocked_category_count": blocked,
        "categories": sorted(public_categories, key=lambda item: item["category_id"]),
        "automatic_pairing_enabled": False,
        "automatic_product_execution_enabled": False,
        "automatic_pk_promotion_enabled": False,
        "four_a_quality_proven": False,
        "truth_boundary": payload.get("truth_boundary"),
    }
    public["content_sha256"] = hashlib.sha256(_json_bytes(public)).hexdigest()
    return public


def _public_product_readiness(payload: object) -> dict[str, Any]:
    if not isinstance(payload, Mapping) or payload.get("schema") != "ProofLaunchAug3ProductReadinessV1":
        raise ValueError("product readiness schema is unsupported")
    verification = payload.get("verification")
    evidence = payload.get("evidence_status")
    tests = verification.get("product_critical_regression") if isinstance(verification, Mapping) else None
    if not isinstance(verification, Mapping) or not isinstance(evidence, Mapping) or not isinstance(tests, Mapping):
        raise ValueError("product readiness receipt is incomplete")
    boolean_fields = (
        "multi_route_multi_seed_candidate_batch_present",
        "candidate_batch_automatic_winner_selection_enabled",
        "blind_selected_progressive_multimodal_funnel_present",
        "progressive_multimodal_master_mux_enabled",
        "automatic_external_publish_enabled",
    )
    integer_fields = (
        "comfyui_admitted_backend_count",
        "official_comfyui_blueprint_capture_count",
        "official_comfyui_api_export_count",
    )
    if any(not isinstance(verification.get(field), bool) for field in boolean_fields):
        raise ValueError("product readiness capability flags are invalid")
    if any(type(verification.get(field)) is not int or verification[field] < 0 for field in integer_fields):
        raise ValueError("product readiness generation counts are invalid")
    gates = payload.get("remaining_proof_gates")
    if not isinstance(gates, list) or any(not isinstance(item, str) for item in gates):
        raise ValueError("product readiness remaining gates are invalid")
    route_observed = verification.get("local_route_head_training_observed") is True
    generator_case_count = verification.get("local_generative_baseline_case_count", 0)
    generator_observed = type(generator_case_count) is int and generator_case_count > 0
    route_model_id = verification.get("local_route_head_base_model")
    route_digest = verification.get("local_route_head_base_model_digest")
    generator_model_id = verification.get("local_generative_baseline_model")
    generator_digest = verification.get("local_generative_baseline_model_digest")
    strategy_challenger_accepted = (
        verification.get("local_gemma3_strategy_challenger_accepted") is True
    )
    strategy_challenger_model_id = verification.get(
        "local_gemma3_strategy_challenger_model"
    )
    strategy_challenger_revision = verification.get(
        "local_gemma3_strategy_challenger_revision"
    )
    strategy_challenger_manifest = verification.get(
        "local_gemma3_strategy_challenger_manifest_sha256"
    )
    strategy_challenger_candidate = verification.get(
        "local_gemma3_strategy_challenger_candidate_sha256"
    )
    strategy_portfolio_quality_passed = (
        verification.get("local_gemma3_strategy_portfolio_quality_gate_passed") is True
    )
    strategy_portfolio_receipt_sha256 = verification.get(
        "local_gemma3_strategy_portfolio_content_sha256"
    )
    mission_status = verification.get("local_gtm_mission_status")
    mission_observed = mission_status == "awaiting_named_human_blind_review"
    mission_model_id = verification.get("local_gtm_mission_model")
    mission_model_digest = verification.get("local_gtm_mission_model_digest")
    if route_observed and (
        not isinstance(route_model_id, str)
        or not re.fullmatch(_SHA256, str(route_digest))
    ):
        raise ValueError("local route-head identity is invalid")
    if generator_observed and (
        not isinstance(generator_model_id, str)
        or not re.fullmatch(_SHA256, str(generator_digest))
    ):
        raise ValueError("local generator identity is invalid")
    if strategy_challenger_accepted and (
        not isinstance(strategy_challenger_model_id, str)
        or not isinstance(strategy_challenger_revision, str)
        or not re.fullmatch(_SHA256, str(strategy_challenger_manifest))
        or not re.fullmatch(_SHA256, str(strategy_challenger_candidate))
        or verification.get("local_gemma3_strategy_challenger_attempt_count") not in (1, 2)
        or verification.get("local_gemma3_strategy_challenger_download_performed") is not False
        or verification.get("local_gemma3_strategy_challenger_cloud_api_calls") != 0
        or verification.get("local_gemma3_strategy_challenger_training_observed") is not False
        or verification.get("local_gemma3_strategy_challenger_radeon_observed") is not False
        or verification.get("local_gemma3_strategy_challenger_automatic_release_authority") is not False
    ):
        raise ValueError("local strategy challenger evidence is invalid")
    strategy_portfolio_distribution = verification.get(
        "local_gemma3_strategy_portfolio_channel_distribution"
    )
    strategy_portfolio_jaccard = verification.get(
        "local_gemma3_strategy_portfolio_maximum_pairwise_content_jaccard"
    )
    if strategy_portfolio_quality_passed and (
        not re.fullmatch(_SHA256, str(strategy_portfolio_receipt_sha256))
        or verification.get("local_gemma3_strategy_portfolio_status")
        != "completed_all_accepted"
        or verification.get("local_gemma3_strategy_portfolio_case_count") != 8
        or verification.get("local_gemma3_strategy_portfolio_accepted_case_count") != 8
        or verification.get("local_gemma3_strategy_portfolio_all_cases_accepted") is not True
        or verification.get("local_gemma3_strategy_portfolio_model_load_count") != 1
        or verification.get("local_gemma3_strategy_portfolio_download_performed") is not False
        or verification.get("local_gemma3_strategy_portfolio_cloud_api_calls") != 0
        or verification.get("local_gemma3_strategy_portfolio_training_observed") is not False
        or verification.get("local_gemma3_strategy_portfolio_radeon_observed") is not False
        or strategy_portfolio_distribution
        != {"LinkedIn": 2, "community": 2, "owned": 2, "partner": 2}
        or verification.get("local_gemma3_strategy_portfolio_unique_strategy_count") != 8
        or not isinstance(strategy_portfolio_jaccard, (int, float))
        or not 0 <= strategy_portfolio_jaccard <= 0.60
        or verification.get("local_gemma3_strategy_portfolio_human_preference_observed") is not False
        or verification.get("local_gemma3_strategy_portfolio_production_effect_observed") is not False
    ):
        raise ValueError("local strategy portfolio evidence is invalid")
    if mission_observed and (
        not isinstance(mission_model_id, str)
        or not re.fullmatch(_SHA256, str(mission_model_digest))
        or verification.get("local_gtm_mission_completed_model_calls") != 3
        or verification.get("local_gtm_mission_validated_candidate_count") != 3
        or verification.get("local_gtm_mission_blind_pair_count") != 6
        or verification.get("local_gtm_mission_empty_human_review_task_count") != 30
    ):
        raise ValueError("local GTM mission evidence is invalid")
    return {
        "schema": "ProofLaunchProductReadinessPublicV1",
        "status": "available",
        "generated_at": payload.get("generated_at"),
        "deadline": payload.get("deadline"),
        "launch_decision": payload.get("launch_decision"),
        "regression": {
            "passed": tests.get("passed") is True,
            "test_count": tests.get("test_count"),
        },
        "generation": {
            "official_blueprint_count": verification["official_comfyui_blueprint_capture_count"],
            "api_export_count": verification["official_comfyui_api_export_count"],
            "admitted_backend_count": verification["comfyui_admitted_backend_count"],
            "candidate_search_ready": verification["multi_route_multi_seed_candidate_batch_present"],
            "automatic_winner_selection": verification[
                "candidate_batch_automatic_winner_selection_enabled"
            ],
            "progressive_multimodal_funnel_ready": verification[
                "blind_selected_progressive_multimodal_funnel_present"
            ],
            "master_mux_enabled": verification["progressive_multimodal_master_mux_enabled"],
        },
        "local_campaign_pack": {
            "observed": isinstance(
                verification.get("local_campaign_pack_content_sha256"), str
            ),
            "content_sha256": verification.get(
                "local_campaign_pack_content_sha256"
            ),
            "source_model": verification.get("local_campaign_pack_source_model"),
            "source_accelerator": verification.get(
                "local_campaign_pack_source_accelerator"
            ),
            "artifact_count": verification.get(
                "local_campaign_pack_artifact_count", 0
            ),
            "true_4k_geometry": verification.get(
                "local_campaign_pack_true_4k_geometry"
            )
            is True,
            "mechanical_ready": verification.get(
                "local_campaign_pack_mechanical_ready"
            )
            is True,
            "named_human_review_passed": verification.get(
                "local_campaign_pack_named_human_review_passed"
            )
            is True,
            "four_a_preference_proven": verification.get(
                "local_campaign_pack_four_a_preference_proven"
            )
            is True,
            "product_admission_passed": verification.get(
                "local_campaign_pack_product_admission_passed"
            )
            is True,
            "external_publish_enabled": False,
        },
        "lifecycle_closure": {
            "observed": isinstance(
                verification.get("lifecycle_closure_content_sha256"), str
            ),
            "content_sha256": verification.get(
                "lifecycle_closure_content_sha256"
            ),
            "case_count": verification.get("lifecycle_closure_case_count", 0),
            "scenario_count": verification.get(
                "lifecycle_closure_scenario_count", 0
            ),
            "named_failure_mode_count": verification.get(
                "lifecycle_closure_named_failure_mode_count", 0
            ),
            "minimum_cases_per_failure_mode": verification.get(
                "lifecycle_closure_minimum_cases_per_failure_mode", 0
            ),
            "ten_capabilities_connected": verification.get(
                "lifecycle_closure_all_ten_capabilities_connected"
            )
            is True,
            "zero_budget_paid_channels_excluded": verification.get(
                "lifecycle_closure_zero_budget_paid_channels_excluded"
            )
            is True,
            "positive_paths_require_human_review": verification.get(
                "lifecycle_closure_positive_paths_require_human_review"
            )
            is True,
            "all_external_actions_disabled": verification.get(
                "lifecycle_closure_all_external_actions_disabled"
            )
            is True,
            "campaign_workspace_artifact_count": verification.get(
                "lifecycle_closure_campaign_workspace_artifact_count", 0
            ),
            "campaign_workspace_same_evidence_spine": verification.get(
                "lifecycle_closure_campaign_workspace_same_evidence_spine"
            )
            is True,
            "campaign_workspace_activations_disabled": verification.get(
                "lifecycle_closure_campaign_workspace_activations_disabled"
            )
            is True,
            "post_selection_omnichannel_lane_count": verification.get(
                "lifecycle_closure_post_selection_omnichannel_lane_count", 0
            ),
            "all_post_selection_campaign_identities_bound": verification.get(
                "lifecycle_closure_all_post_selection_campaign_identities_bound"
            )
            is True,
            "all_post_selection_creative_systems_connected": verification.get(
                "lifecycle_closure_all_post_selection_creative_systems_connected"
            )
            is True,
            "all_post_selection_evidence_spines_connected": verification.get(
                "lifecycle_closure_all_post_selection_evidence_spines_connected"
            )
            is True,
            "all_post_selection_external_actions_disabled": verification.get(
                "lifecycle_closure_all_post_selection_external_actions_disabled"
            )
            is True,
            "post_selection_human_observations": verification.get(
                "lifecycle_closure_post_selection_human_observations", 0
            ),
            "production_outcomes_observed": verification.get(
                "lifecycle_closure_production_outcomes_observed", 0
            ),
            "evidence_class": "synthetic_cross_capability_regression",
        },
        "observed": {
            "model_generated_multimodal": evidence.get("real_model_generated_multimodal_deliverable"),
            "comfyui_execution": evidence.get("comfyui_production_execution"),
            "human_blind_preference": evidence.get("real_named_human_blind_preference"),
            "production_outcome": evidence.get("real_production_business_outcome"),
            "radeon_local_inference": evidence.get("radeon_local_key_inference"),
            "four_a_effect_claim": evidence.get("four_a_effect_claim"),
        },
        "local_models": {
            "route_head": {
                "observed": route_observed,
                "model_id": route_model_id if route_observed else None,
                "digest": route_digest if route_observed else None,
                "training_records": verification.get("local_route_head_training_record_count") if route_observed else None,
                "test_examples": verification.get("local_route_head_final_test_count") if route_observed else None,
                "accuracy": verification.get("local_route_head_test_accuracy") if route_observed else None,
                "macro_f1": verification.get("local_route_head_test_macro_f1") if route_observed else None,
                "accepted_coverage": verification.get("local_route_head_test_accepted_coverage") if route_observed else None,
                "accepted_accuracy": verification.get("local_route_head_test_accepted_accuracy") if route_observed else None,
                "promotion_gate_passed": verification.get("local_route_head_promotion_gate_passed") is True,
                "promoted": verification.get("local_route_head_promoted") is True,
                "network_download_performed": verification.get("local_route_head_download_performed") is True,
                "cloud_api_calls": verification.get("local_route_head_cloud_api_calls", 0),
                "automatic_external_action_enabled": False,
            },
            "generator": {
                "observed": generator_observed,
                "model_id": generator_model_id if generator_observed else None,
                "digest": generator_digest if generator_observed else None,
                "case_count": generator_case_count if generator_observed else 0,
                "first_pass_contract_rate": verification.get("local_generative_baseline_first_pass_contract_rate") if generator_observed else None,
                "final_contract_pass_rate": verification.get("local_generative_baseline_final_contract_rate") if generator_observed else None,
                "repair_calls": verification.get("local_generative_baseline_repair_call_count", 0),
                "wrapper_normalizations": verification.get("local_generative_baseline_wrapper_normalization_count", 0),
                "training_observed": verification.get("local_generative_baseline_training_observed") is True,
                "network_download_performed": verification.get("local_generative_baseline_download_performed") is True,
                "cloud_api_calls": verification.get("local_generative_baseline_cloud_api_calls", 0),
                "automatic_external_action_enabled": False,
            },
            "strategy_challenger": {
                "observed": strategy_challenger_accepted,
                "accepted": strategy_challenger_accepted,
                "model_id": strategy_challenger_model_id if strategy_challenger_accepted else None,
                "revision": strategy_challenger_revision if strategy_challenger_accepted else None,
                "model_manifest_sha256": strategy_challenger_manifest if strategy_challenger_accepted else None,
                "candidate_sha256": strategy_challenger_candidate if strategy_challenger_accepted else None,
                "attempt_count": verification.get(
                    "local_gemma3_strategy_challenger_attempt_count", 0
                ),
                "training_observed": False,
                "radeon_local_inference_observed": False,
                "network_download_performed": False,
                "cloud_api_calls": 0,
                "automatic_release_authority": False,
                "human_preference_observed": False,
                "effect_observed": False,
            },
            "strategy_portfolio": {
                "observed": strategy_portfolio_quality_passed,
                "quality_gate_passed": strategy_portfolio_quality_passed,
                "receipt_sha256": (
                    strategy_portfolio_receipt_sha256
                    if strategy_portfolio_quality_passed
                    else None
                ),
                "case_count": verification.get(
                    "local_gemma3_strategy_portfolio_case_count", 0
                ),
                "accepted_case_count": verification.get(
                    "local_gemma3_strategy_portfolio_accepted_case_count", 0
                ),
                "channel_distribution": (
                    strategy_portfolio_distribution
                    if strategy_portfolio_quality_passed
                    else {}
                ),
                "unique_strategy_count": verification.get(
                    "local_gemma3_strategy_portfolio_unique_strategy_count", 0
                ),
                "maximum_pairwise_content_jaccard": (
                    strategy_portfolio_jaccard
                    if strategy_portfolio_quality_passed
                    else None
                ),
                "maximum_allowed_pairwise_content_jaccard": 0.60,
                "training_observed": False,
                "radeon_local_inference_observed": False,
                "human_preference_observed": False,
                "effect_observed": False,
                "any_industry_generalization_claim_eligible": False,
                "automatic_release_authority": False,
            },
        },
        "local_mission": {
            "observed": mission_observed,
            "status": mission_status if mission_observed else "not_observed",
            "run_id": verification.get("local_gtm_mission_run_id") if mission_observed else None,
            "model_id": mission_model_id if mission_observed else None,
            "model_digest": mission_model_digest if mission_observed else None,
            "graph_loop_harness_executed": verification.get(
                "local_gtm_mission_graph_loop_harness_executed"
            ) is True,
            "human_release_gate_reached": verification.get(
                "local_gtm_mission_human_release_gate_reached"
            ) is True,
            "completed_model_calls": verification.get(
                "local_gtm_mission_completed_model_calls", 0
            ),
            "validated_candidate_count": verification.get(
                "local_gtm_mission_validated_candidate_count", 0
            ),
            "blind_pair_count": verification.get(
                "local_gtm_mission_blind_pair_count", 0
            ),
            "empty_human_review_task_count": verification.get(
                "local_gtm_mission_empty_human_review_task_count", 0
            ),
            "human_review_completed": verification.get(
                "local_gtm_mission_human_review_completed"
            ) is True or verification.get(
                "local_gtm_mission_live_human_review_complete"
            ) is True,
            "live_human_review_submitted_count": verification.get(
                "local_gtm_mission_live_human_review_submitted_count", 0
            ),
            "winner_selected": verification.get(
                "local_gtm_mission_winner_selected"
            ) is True or verification.get(
                "local_gtm_mission_multimodal_production_entry_created"
            ) is True,
            "multimodal_production_entry_created": verification.get(
                "local_gtm_mission_multimodal_production_entry_created"
            ) is True,
            "post_selection_compiler_ready": verification.get(
                "local_gtm_mission_post_selection_compiler_ready"
            ) is True,
            "post_selection_compiler_lane_count": verification.get(
                "local_gtm_mission_post_selection_compiler_lane_count", 0
            ),
            "post_selection_compiler_automatic_gpu_execution_enabled": verification.get(
                "local_gtm_mission_post_selection_compiler_automatic_gpu_execution_enabled"
            ) is True,
            "omnichannel_compiler_ready": verification.get(
                "local_gtm_mission_omnichannel_compiler_ready"
            ) is True,
            "omnichannel_compiler_lane_count": verification.get(
                "local_gtm_mission_omnichannel_compiler_lane_count", 0
            ),
            "omnichannel_activation_observed": verification.get(
                "local_gtm_mission_omnichannel_activation_observed"
            ) is True,
            "omnichannel_automatic_external_action_enabled": verification.get(
                "local_gtm_mission_omnichannel_automatic_external_action_enabled"
            ) is True,
            "network_download_performed": verification.get(
                "local_gtm_mission_download_performed"
            ) is True,
            "cloud_api_calls": verification.get("local_gtm_mission_cloud_api_calls", 0),
            "radeon_local_inference_observed": False,
            "external_publish_enabled": False,
        },
        "local_creative_benchmark": {
            "status": verification.get(
                "local_creative_benchmark_status", "not_observed"
            ),
            "blocker": verification.get("local_creative_benchmark_blocker"),
            "active_case_id": verification.get(
                "local_creative_benchmark_active_case_id"
            ),
            "preflight_passed": verification.get(
                "local_creative_benchmark_preflight_passed"
            )
            is True,
            "planned_case_count": verification.get(
                "local_creative_benchmark_planned_case_count", 0
            ),
            "observed_case_count": verification.get(
                "local_creative_benchmark_observed_case_count", 0
            ),
            "completed_case_count": verification.get(
                "local_creative_benchmark_completed_case_count", 0
            ),
            "planned_model_call_count": verification.get(
                "local_creative_benchmark_planned_model_call_count", 0
            ),
            "completed_model_call_count": verification.get(
                "local_creative_benchmark_completed_model_call_count", 0
            ),
            "validated_candidate_count": verification.get(
                "local_creative_benchmark_validated_candidate_count", 0
            ),
            "training_observed": verification.get(
                "local_creative_benchmark_training_observed"
            )
            is True,
            "cloud_api_calls": verification.get(
                "local_creative_benchmark_cloud_api_calls", 0
            ),
            "radeon_local_inference_observed": verification.get(
                "local_creative_benchmark_radeon_local_inference_observed"
            )
            is True,
            "external_publish_enabled": False,
        },
        "portfolio_blind_review": {
            "status": verification.get(
                "local_portfolio_blind_review_status", "not_observed"
            ),
            "public_packet_sha256": verification.get(
                "local_portfolio_blind_review_public_packet_sha256"
            ),
            "case_count": verification.get(
                "local_portfolio_blind_review_case_count", 0
            ),
            "pair_count": verification.get(
                "local_portfolio_blind_review_pair_count", 0
            ),
            "reviewer_slot_count": verification.get(
                "local_portfolio_blind_review_reviewer_slot_count", 0
            ),
            "expected_review_count": verification.get(
                "local_portfolio_blind_review_expected_review_count", 0
            ),
            "submitted_review_count": verification.get(
                "local_portfolio_blind_review_submitted_review_count", 0
            ),
            "review_complete": verification.get(
                "local_portfolio_blind_review_complete"
            )
            is True,
            "portfolio_promotion_passed": verification.get(
                "local_portfolio_blind_review_promotion_passed"
            )
            is True,
            "human_preference_observed": verification.get(
                "local_portfolio_blind_review_human_preference_observed"
            )
            is True,
            "candidate_identity_exposed": False,
            "provider_identity_exposed": False,
            "automatic_scoring_executed": False,
            "winner_selected": False,
            "external_publish_enabled": False,
        },
        "cloud_upgrade": {
            "free_api_candidate_count": verification.get("frontier_free_api_candidate_count", 0),
            "live_calls_executed": verification.get("frontier_free_api_live_calls_executed", 0),
            "free_compute_route_count": verification.get("frontier_free_compute_route_count", 0),
            "competition_core_eligible": False,
        },
        "remaining_gates": gates,
        "external_publish_enabled": verification["automatic_external_publish_enabled"],
        "truth_boundary": payload.get("truth_boundary"),
    }


_PLATFORM_MARKET_PRIORITY = (
    "linkedin",
    "tiktok",
    "instagram",
    "reddit",
    "x",
    "facebook",
    "pinterest",
    "bluesky",
    "mastodon",
)


def _public_social_oss_landscape(payload: object) -> dict[str, Any]:
    if (
        not isinstance(payload, Mapping)
        or payload.get("schema") != "ProofLaunchSocialOSSAdapterLandscapeV1"
    ):
        raise ValueError("social OSS landscape schema is unsupported")
    unsigned = dict(payload)
    source_digest = unsigned.pop("content_sha256", None)
    if (
        not isinstance(source_digest, str)
        or not re.fullmatch(_SHA256, source_digest)
        or hashlib.sha256(_json_bytes(unsigned)).hexdigest() != source_digest
    ):
        raise ValueError("social OSS landscape digest is invalid")
    candidates = payload.get("candidates")
    platform_counts = payload.get("platform_candidate_counts")
    access_mode_counts = payload.get("access_mode_counts")
    integration_role_counts = payload.get("integration_role_counts")
    runtime_proven_count = payload.get("runtime_proven_count")
    if (
        not isinstance(candidates, list)
        or len(candidates) != payload.get("candidate_count")
        or not isinstance(platform_counts, Mapping)
        or set(platform_counts) != set(_PLATFORM_MARKET_PRIORITY)
        or not isinstance(access_mode_counts, Mapping)
        or not isinstance(integration_role_counts, Mapping)
        or type(runtime_proven_count) is not int
    ):
        raise ValueError("social OSS landscape coverage is invalid")
    public_candidates: list[dict[str, Any]] = []
    resolved_count = 0
    production_admitted_count = 0
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            raise ValueError("social OSS candidate is invalid")
        repository = candidate.get("repository")
        platforms = candidate.get("platforms")
        decision = candidate.get("admission_decision")
        resolved = candidate.get("resolved")
        revision = candidate.get("revision")
        access_mode = candidate.get("access_mode")
        signal_surfaces = candidate.get("signal_surfaces")
        freshness_mode = candidate.get("freshness_mode")
        integration_role = candidate.get("integration_role")
        login_or_api_requirement = candidate.get("login_or_api_requirement")
        runtime_proven = candidate.get("runtime_proven")
        if (
            not isinstance(repository, str)
            or not repository.startswith("https://github.com/")
            or not isinstance(platforms, list)
            or not platforms
            or any(platform not in _PLATFORM_MARKET_PRIORITY for platform in platforms)
            or not isinstance(decision, str)
            or type(resolved) is not bool
            or not isinstance(access_mode, str)
            or not isinstance(signal_surfaces, list)
            or not signal_surfaces
            or any(not isinstance(item, str) for item in signal_surfaces)
            or not isinstance(freshness_mode, str)
            or not isinstance(integration_role, str)
            or type(login_or_api_requirement) is not bool
            or type(runtime_proven) is not bool
            or runtime_proven != (decision == "production_admitted")
            or (resolved and (not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision)))
        ):
            raise ValueError("social OSS candidate contract is invalid")
        resolved_count += int(resolved)
        production_admitted_count += int(decision == "production_admitted")
        public_candidates.append(
            {
                "repository": repository,
                "platforms": list(platforms),
                "capability": candidate.get("capability"),
                "resolved": resolved,
                "revision": revision,
                "license_spdx": candidate.get("license_spdx"),
                "admission_decision": decision,
                "archived": candidate.get("archived"),
                "audit_note": candidate.get("audit_note"),
                "access_mode": access_mode,
                "signal_surfaces": list(signal_surfaces),
                "freshness_mode": freshness_mode,
                "integration_role": integration_role,
                "login_or_api_requirement": login_or_api_requirement,
                "runtime_proven": runtime_proven,
            }
        )
    if (
        resolved_count != payload.get("resolved_count")
        or production_admitted_count != payload.get("production_admitted_count")
        or runtime_proven_count != production_admitted_count
        or dict(access_mode_counts) != {
            mode: sum(candidate["access_mode"] == mode for candidate in public_candidates)
            for mode in sorted({candidate["access_mode"] for candidate in public_candidates})
        }
        or dict(integration_role_counts) != {
            role: sum(candidate["integration_role"] == role for candidate in public_candidates)
            for role in sorted({candidate["integration_role"] for candidate in public_candidates})
        }
        or any(
            platform_counts.get(platform)
            != sum(platform in candidate["platforms"] for candidate in public_candidates)
            for platform in _PLATFORM_MARKET_PRIORITY
        )
    ):
        raise ValueError("social OSS landscape aggregates drifted")
    public: dict[str, Any] = {
        "schema": "ProofLaunchSocialOSSAdapterLandscapePublicV1",
        "status": "audited_candidate_registry",
        "source_content_sha256": source_digest,
        "candidate_count": len(public_candidates),
        "resolved_count": resolved_count,
        "production_admitted_count": production_admitted_count,
        "platform_candidate_counts": dict(platform_counts),
        "access_mode_counts": dict(access_mode_counts),
        "integration_role_counts": dict(integration_role_counts),
        "runtime_proven_count": runtime_proven_count,
        "candidates": public_candidates,
        "selection_gate": payload.get("selection_gate"),
        "repository_discovery_is_not_runtime_admission": True,
        "authentication_or_captcha_bypass_enabled": False,
        "external_publish_enabled": False,
        "truth_boundary": payload.get("truth_boundary"),
    }
    public["content_sha256"] = hashlib.sha256(_json_bytes(public)).hexdigest()
    return public


def _public_platform_market_expansion(payload: object) -> dict[str, Any]:
    """Return a digest-bound view that never equates discovery with coverage."""

    if (
        not isinstance(payload, Mapping)
        or payload.get("schema") != "ProofLaunchPlatformMarketExpansionQueueV1"
    ):
        raise ValueError("platform-market expansion schema is unsupported")
    unsigned = dict(payload)
    source_digest = unsigned.pop("content_sha256", None)
    if (
        not isinstance(source_digest, str)
        or not re.fullmatch(_SHA256, source_digest)
        or hashlib.sha256(_json_bytes(unsigned)).hexdigest() != source_digest
    ):
        raise ValueError("platform-market expansion digest is invalid")

    platforms = payload.get("priority_platforms")
    lanes = payload.get("lanes")
    if platforms != list(_PLATFORM_MARKET_PRIORITY):
        raise ValueError("platform-market priority contract drifted")
    if not isinstance(lanes, list) or len(lanes) != 126:
        raise ValueError("platform-market lane contract is incomplete")
    if (
        payload.get("target_lane_count") != len(lanes)
        or payload.get("automatic_external_publish_count") != 0
        or payload.get("automatic_learning_memory_write_count") != 0
    ):
        raise ValueError("platform-market authority boundary is invalid")

    totals = {
        "candidate_source_slot_count": 0,
        "discovered_candidate_slot_count": 0,
        "executed_candidate_slot_count": 0,
        "recent_candidate_slot_count": 0,
        "stale_or_undated_candidate_slot_count": 0,
        "handoff_candidate_slot_count": 0,
    }
    seen_lane_ids: set[str] = set()
    platform_rows: dict[str, dict[str, Any]] = {
        platform: {
            "platform": platform,
            "target_lane_count": 0,
            "observed_lane_count": 0,
            "verified_recent_lane_count": 0,
            "discovered_candidate_slot_count": 0,
            "executed_candidate_slot_count": 0,
            "recent_candidate_slot_count": 0,
            "stale_or_undated_candidate_slot_count": 0,
            "handoff_candidate_slot_count": 0,
        }
        for platform in _PLATFORM_MARKET_PRIORITY
    }
    lane_statuses: list[dict[str, Any]] = []
    for lane in lanes:
        if not isinstance(lane, Mapping):
            raise ValueError("platform-market lane is invalid")
        lane_id = lane.get("lane_id")
        platform = lane.get("platform")
        slots = lane.get("source_slots")
        if (
            not isinstance(lane_id, str)
            or lane_id in seen_lane_ids
            or platform not in platform_rows
            or not isinstance(slots, list)
            or len(slots) != int(lane.get("remaining_distinct_sources", -1))
        ):
            raise ValueError("platform-market lane identity or slots are invalid")
        seen_lane_ids.add(lane_id)
        row = platform_rows[str(platform)]
        row["target_lane_count"] += 1
        observed_sources = int(lane.get("observed_distinct_source_count", 0))
        observed_recent = int(lane.get("observed_recent_item_count", 0))
        if observed_sources < 0 or observed_recent < 0:
            raise ValueError("platform-market observations are invalid")
        if observed_sources > 0:
            row["observed_lane_count"] += 1
        if observed_sources >= 3 and observed_recent >= 60:
            row["verified_recent_lane_count"] += 1

        lane_counts = {
            "discovered": sum(slot.get("source_url") is not None for slot in slots),
            "executed": sum(
                str(slot.get("status", "")).startswith("executed_") for slot in slots
            ),
            "recent": sum(
                slot.get("status") == "executed_recent_public_metadata" for slot in slots
            ),
            "stale": sum(
                slot.get("status") == "executed_stale_or_undated_public_metadata"
                for slot in slots
            ),
            "handoff": sum(
                slot.get("status") == "executed_human_handoff_required" for slot in slots
            ),
        }
        totals["candidate_source_slot_count"] += len(slots)
        totals["discovered_candidate_slot_count"] += lane_counts["discovered"]
        totals["executed_candidate_slot_count"] += lane_counts["executed"]
        totals["recent_candidate_slot_count"] += lane_counts["recent"]
        totals["stale_or_undated_candidate_slot_count"] += lane_counts["stale"]
        totals["handoff_candidate_slot_count"] += lane_counts["handoff"]
        row["discovered_candidate_slot_count"] += lane_counts["discovered"]
        row["executed_candidate_slot_count"] += lane_counts["executed"]
        row["recent_candidate_slot_count"] += lane_counts["recent"]
        row["stale_or_undated_candidate_slot_count"] += lane_counts["stale"]
        row["handoff_candidate_slot_count"] += lane_counts["handoff"]
        lane_statuses.append(
            {
                "lane_id": lane_id,
                "platform": platform,
                "business_model": lane.get("business_model"),
                "market": lane.get("market"),
                "observed_distinct_source_count": observed_sources,
                "observed_recent_item_count": observed_recent,
                "discovered_candidate_count": lane_counts["discovered"],
                "recent_candidate_count": lane_counts["recent"],
                "handoff_candidate_count": lane_counts["handoff"],
                "verified_recent": observed_sources >= 3 and observed_recent >= 60,
            }
        )

    for field, computed in totals.items():
        if payload.get(field) != computed:
            raise ValueError(f"platform-market aggregate drifted: {field}")
    recent_qualified = sum(
        int(row["verified_recent_lane_count"]) for row in platform_rows.values()
    )
    public: dict[str, Any] = {
        "schema": "ProofLaunchPlatformMarketExpansionPublicV1",
        "status": "recent_coverage_verified" if recent_qualified == 126 else "execution_gap",
        "source_content_sha256": source_digest,
        "sampling_standard_sha256": payload.get("sampling_standard_sha256"),
        "coverage_receipt_sha256": payload.get("coverage_receipt_sha256"),
        "source_registry_sha256": payload.get("source_registry_sha256"),
        "priority_platforms": list(platforms),
        "target_lane_count": 126,
        **totals,
        "verified_recent_lane_count": recent_qualified,
        "remaining_verified_recent_lane_count": 126 - recent_qualified,
        "platforms": list(platform_rows.values()),
        "lanes": lane_statuses,
        "discovery_is_not_coverage": True,
        "automatic_external_publish_count": 0,
        "automatic_learning_memory_write_count": 0,
        "truth_boundary": payload.get("truth_boundary"),
    }
    public["content_sha256"] = hashlib.sha256(_json_bytes(public)).hexdigest()
    return public


def _public_signal_pilot(payload: object) -> dict[str, Any]:
    if not isinstance(payload, Mapping) or payload.get("schema") != (
        "ProofLaunchPublicSignalGTMPilotV1"
    ):
        raise ValueError("public signal pilot schema is unsupported")
    source_digest = payload.get("content_sha256")
    unsigned = dict(payload)
    unsigned.pop("content_sha256", None)
    if (
        not isinstance(source_digest, str)
        or not re.fullmatch(_SHA256, source_digest)
        or hashlib.sha256(_json_bytes(unsigned)).hexdigest() != source_digest
    ):
        raise ValueError("public signal pilot digest is invalid")
    run_id = payload.get("run_id")
    signal_count = payload.get("signal_count")
    hypothesis_count = payload.get("hypothesis_count")
    platform_counts = payload.get("platform_counts")
    hypothesis_ids = payload.get("hypothesis_ids")
    if not isinstance(run_id, str) or not re.fullmatch(_RUN_ID, run_id):
        raise ValueError("public signal pilot run ID is invalid")
    if type(signal_count) is not int or signal_count <= 0:
        raise ValueError("public signal pilot count is invalid")
    if type(hypothesis_count) is not int or hypothesis_count <= 0:
        raise ValueError("public signal hypothesis count is invalid")
    if (
        not isinstance(platform_counts, Mapping)
        or not platform_counts
        or any(
            not isinstance(key, str) or type(value) is not int or value < 0
            for key, value in platform_counts.items()
        )
        or sum(platform_counts.values()) != signal_count
    ):
        raise ValueError("public signal platform counts are invalid")
    if (
        not isinstance(hypothesis_ids, list)
        or len(hypothesis_ids) != hypothesis_count
        or any(not isinstance(item, str) or not item for item in hypothesis_ids)
    ):
        raise ValueError("public signal hypothesis identities are invalid")
    required_hashes = (
        "collection_receipt_sha256",
        "collection_plan_sha256",
        "content_calendar_sha256",
    )
    if any(
        not isinstance(payload.get(field), str)
        or not re.fullmatch(_SHA256, str(payload.get(field)))
        for field in required_hashes
    ):
        raise ValueError("public signal evidence hashes are invalid")
    if (
        payload.get("status") != "awaiting_human_release"
        or payload.get("run_data_class") != "internal"
        or payload.get("creative_signal_data_class") != "public"
        or payload.get("automatic_strategy_mutation_executed") is not False
        or payload.get("automatic_schedule_mutation_executed") is not False
        or payload.get("external_release_executed") is not False
        or payload.get("human_release_required") is not True
    ):
        raise ValueError("public signal authority boundary is invalid")
    public: dict[str, Any] = {
        "schema": "ProofLaunchPublicSignalGTMPilotPublicV1",
        "status": payload["status"],
        "run_id": run_id,
        "run_data_class": payload["run_data_class"],
        "creative_signal_data_class": payload["creative_signal_data_class"],
        "signal_count": signal_count,
        "platform_counts": dict(platform_counts),
        "hypothesis_count": hypothesis_count,
        "hypothesis_ids": list(hypothesis_ids),
        "collection_receipt_sha256": payload["collection_receipt_sha256"],
        "collection_plan_sha256": payload["collection_plan_sha256"],
        "content_calendar_sha256": payload["content_calendar_sha256"],
        "source_content_sha256": source_digest,
        "automatic_strategy_mutation_executed": False,
        "automatic_schedule_mutation_executed": False,
        "external_release_executed": False,
        "human_release_required": True,
        "truth_boundary": payload.get("truth_boundary"),
    }
    public["content_sha256"] = hashlib.sha256(_json_bytes(public)).hexdigest()
    return public


def make_production_server(
    host: str,
    port: int,
    *,
    service: ProductionAgencyService,
    web_root: Path,
    approval_token: str,
    approver_identity: str,
    tenant_tokens: Mapping[str, str],
    memory_capsule_secret: bytes,
    product_readiness_path: Path | None = None,
    public_signal_pilot_path: Path | None = None,
    platform_market_expansion_path: Path | None = None,
    social_oss_landscape_path: Path | None = None,
    blind_review_service: BlindReviewService | None = None,
    portfolio_blind_review_service: PortfolioBlindReviewService | None = None,
    judge_calibration_service: JudgeCalibrationService | None = None,
    campaign_pack_blind_review_service: CampaignPackBlindReviewService | None = None,
    guardrail_ledger: GuardrailTelemetryLedger | None = None,
    trace_ledger: ProductionTraceLedger | None = None,
    local_evaluation_session: tuple[str, str] | None = None,
) -> ProductionHTTPServer:
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("production submission API binds loopback only")
    if not 0 <= port <= 65535:
        raise ValueError("port is outside [0, 65535]")
    return ProductionHTTPServer(
        (host, port),
        production_handler_factory(
            service,
            web_root,
            approval_token=approval_token,
            approver_identity=approver_identity,
            tenant_tokens=tenant_tokens,
            memory_capsule_secret=memory_capsule_secret,
            product_readiness_path=product_readiness_path,
            public_signal_pilot_path=public_signal_pilot_path,
            platform_market_expansion_path=platform_market_expansion_path,
            social_oss_landscape_path=social_oss_landscape_path,
            blind_review_service=blind_review_service,
            portfolio_blind_review_service=portfolio_blind_review_service,
            judge_calibration_service=judge_calibration_service,
            campaign_pack_blind_review_service=campaign_pack_blind_review_service,
            guardrail_ledger=guardrail_ledger,
            trace_ledger=trace_ledger,
            local_evaluation_session=local_evaluation_session,
        ),
    )


__all__ = [
    "ProductionHTTPServer",
    "TenantAuthenticationError",
    "make_production_server",
    "production_handler_factory",
]
