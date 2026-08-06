from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .files import atomic_write_text, sha256_file
from .gtm_challenger_dossier import validate_challenger_admission
from .gtm_named_product_baseline import validate_kit_manifest
from .gtm_omnichannel_craft_os import (
    compile_craft_job_binding,
    compile_lane_craft_playbook,
)
from .gtm_unified_offline_review import seal, sha256_json


SCHEMA = "ProofLaunchGTMHybridQualityControlV1"
LEDGER_SCHEMA = "ProofLaunchConcreteProductEffectPKLedgerV1"
LOCAL_SCHEMA = "ProofLaunchLocalFirstModelResourceDiscoveryV1"
CLOUD_SCHEMA = "ProofLaunchFreeCloudExecutionPlanV2"


class HybridQualityControlError(ValueError):
    pass


LANE_CONTRACTS: dict[str, dict[str, object]] = {
    "cross_device_memory": {
        "required_local_roles": ["semantic_memory_and_retrieval", "structured_text_baseline"],
        "preferred_cloud_roles": ["long_context_red_team", "safety_critic"],
        "cloud_gpu_stage": "optional embedding/router training after rights and dataset admission",
        "output_contract": ["source-bound retrieval", "newer-fact conflict resolution", "tenant denial", "cross-device replay", "exact deletion tombstone"],
        "hard_gates": ["retrieved source id exact", "newer approved fact wins", "cross-tenant disclosures = 0", "post-delete retrieval results = 0", "event hash chain valid"],
        "failure_signals": ["stale fact survives conflict", "citation disappears", "tenant boundary leaks", "deletion is cosmetic"],
    },
    "data_strategy_intelligence": {
        "required_local_roles": ["structured_text_baseline", "semantic_memory_and_retrieval"],
        "preferred_cloud_roles": ["structured_agent_draft", "long_context_red_team"],
        "cloud_gpu_stage": "optional scenario-policy SFT only after leakage and temporal-split checks",
        "output_contract": ["lineage graph", "point-in-time cutoff", "uncertainty interval", "three scenarios", "reversible recommendation"],
        "hard_gates": ["every decision input has lineage", "future leakage = 0", "unknowns remain explicit", "at least three materially different scenarios", "causal claim disabled without experiment"],
        "failure_signals": ["dashboard without a decision", "single-point forecast", "invented causality", "irreversible recommendation"],
    },
    "content_scheduling_operations": {
        "required_local_roles": ["structured_text_baseline"],
        "preferred_cloud_roles": ["structured_agent_draft", "safety_critic"],
        "cloud_gpu_stage": "not required for product closure; use only for admitted ranking experiments",
        "output_contract": ["seven executable slots", "native format per channel", "timezone", "dependencies", "approval queue", "frequency cap", "missed-slot recovery"],
        "hard_gates": ["slot count = 7", "timezone explicit", "every external action approval-gated", "automatic publish = false", "automatic reschedule = false"],
        "failure_signals": ["generic calendar", "channel copy pasted unchanged", "fatigue ignored", "failed asset causes silent skip"],
    },
    "image_generation_editing": {
        "required_local_roles": ["image_generation", "image_editing", "document_ocr"],
        "preferred_cloud_roles": ["multimodal_understanding", "safety_critic"],
        "cloud_gpu_stage": "parallel source-visual challenger generation and high-resolution edit/render",
        "output_contract": ["3840x2160 hero", "1080x1350 social", "1920x1080 landing", "deterministic typography", "shared visual world", "claim-bound proof line"],
        "hard_gates": ["all three exact geometries", "generated gibberish text = 0", "visible anatomy defect = 0", "source digest preserved", "candidate identity hidden for review"],
        "failure_signals": ["generic AI aesthetic", "crop destroys idea", "text hierarchy collapses", "product mechanism absent", "format drift"],
    },
    "video_generation_production": {
        "required_local_roles": ["video_generation", "video_restoration", "speech_and_voice_design"],
        "preferred_cloud_roles": ["multimodal_understanding", "safety_critic"],
        "cloud_gpu_stage": "candidate motion generation, restoration and 4K mastering with resumable receipts",
        "output_contract": ["15-second three-beat film", "first-three-second hook", "stable identity", "legible proof", "timed voice", "4K master"],
        "hard_gates": ["duration 14-16 seconds", "master at least 3840x2160", "three audit beats", "voice and picture timing receipt", "continuity defect = 0"],
        "failure_signals": ["motion without an idea", "identity mutation", "proof unreadable", "audio detached from picture", "upscaled low-detail master"],
    },
    "audio_voice_music": {
        "required_local_roles": ["speech_and_voice_design", "audio_generation"],
        "preferred_cloud_roles": ["safety_critic", "multimodal_understanding"],
        "cloud_gpu_stage": "parallel voice/music challenger generation after voice-consent admission",
        "output_contract": ["three voice directions", "one frozen script", "48 kHz stereo 24-bit masters", "transcript alignment", "consent receipt"],
        "hard_gates": ["candidate count = 3", "sample rate = 48000", "channels = 2", "sample width = 24-bit", "identifiable-person imitation = false"],
        "failure_signals": ["semantic drift", "robotic prosody", "voice identity instability", "loudness mismatch", "unlicensed imitation"],
    },
    "text_content_generation": {
        "required_local_roles": ["structured_text_baseline", "semantic_memory_and_retrieval"],
        "preferred_cloud_roles": ["structured_agent_draft", "long_context_red_team", "safety_critic"],
        "cloud_gpu_stage": "optional preference/SFT training after human labels and output-rights admission",
        "output_contract": ["native LinkedIn post", "partner-community prompt", "landing hero", "lifecycle email", "one evidence-consistent organizing idea"],
        "hard_gates": ["every factual claim source-bound", "unsupported performance claim = 0", "channel-native markers present", "cross-channel contradiction = 0", "human release required"],
        "failure_signals": ["generic copy", "same copy pasted everywhere", "invented proof", "weak offer", "senior-editor rewrite required"],
    },
    "product_marketing_analytics": {
        "required_local_roles": ["structured_text_baseline", "semantic_memory_and_retrieval"],
        "preferred_cloud_roles": ["long_context_red_team", "safety_critic"],
        "cloud_gpu_stage": "optional causal/uplift model training only on admitted first-party data",
        "output_contract": ["identity-safe event contract", "funnel", "cohort", "randomized holdout", "stop rules", "net-revenue reconciliation"],
        "hard_gates": ["PII prohibited fields absent", "primary metric preregistered", "holdout explicit", "revenue reconciliation equation complete", "causal claim disabled before observation"],
        "failure_signals": ["vanity dashboard", "identity leakage", "attribution presented as incrementality", "metric changes after result", "gross revenue only"],
    },
    "geo_ai_visibility": {
        "required_local_roles": ["structured_text_baseline", "semantic_memory_and_retrieval"],
        "preferred_cloud_roles": ["long_context_red_team", "multimodal_understanding"],
        "cloud_gpu_stage": "optional embedding reranker training on rights-cleared answer/citation pairs",
        "output_contract": ["direct answer", "explicit entity", "source-ready evidence", "citation structure", "reusable FAQ objects"],
        "hard_gates": ["at least four intent questions", "answer precedes elaboration", "every answer has evidence digest", "entity naming consistent", "unsupported superlative = 0"],
        "failure_signals": ["keyword padding", "citation theatre", "ambiguous entity", "answer buried", "unverifiable recommendation"],
    },
    "seo_operations": {
        "required_local_roles": ["structured_text_baseline", "document_ocr", "semantic_memory_and_retrieval"],
        "preferred_cloud_roles": ["long_context_red_team", "structured_agent_draft"],
        "cloud_gpu_stage": "not required for closure; optional semantic clustering/reranking experiment",
        "output_contract": ["intent map", "owned-page brief", "structured data", "internal-link graph", "crawl replay", "performance audit"],
        "hard_gates": ["canonical/indexability explicit", "structured data parseable", "internal links connected", "crawl contract replayable", "unobserved rank/traffic delta remains null"],
        "failure_signals": ["search-volume list without page value", "duplicate intent", "invalid schema", "orphan page", "ranking claim without observation"],
    },
    "employee_agent_platforms": {
        "required_local_roles": ["structured_text_baseline", "semantic_memory_and_retrieval"],
        "preferred_cloud_roles": ["structured_agent_draft", "long_context_red_team", "safety_critic"],
        "cloud_gpu_stage": "trajectory SFT/RL only after executable environment, trace and rights admission",
        "output_contract": ["durable Graph", "bounded node Loops", "global Harness", "forced failure recovery", "approval denial", "immutable trace"],
        "hard_gates": ["forced failure observed", "bounded recovery observed", "approval denial preserved", "hash chain valid", "external action executed = false"],
        "failure_signals": ["open-ended loop", "silent tool failure", "authority escalation", "non-replayable state", "model output treated as execution"],
    },
    "advertising_activation": {
        "required_local_roles": ["structured_text_baseline", "image_generation", "image_editing"],
        "preferred_cloud_roles": ["structured_agent_draft", "multimodal_understanding", "safety_critic"],
        "cloud_gpu_stage": "parallel creative generation and admitted response/uplift modeling; never direct activation",
        "output_contract": ["three creative routes", "audience exclusions", "four platform formats", "budget bounds", "incrementality holdout", "brand safety"],
        "hard_gates": ["creative routes >= 3", "audience exclusions non-empty", "activation authorized = false", "spend executed = 0", "incrementality design explicit"],
        "failure_signals": ["one concept resized", "targeting too broad", "platform objective mismatch", "no holdout", "automatic spend"],
    },
    "gtm_lifecycle_orchestration": {
        "required_local_roles": ["structured_text_baseline", "semantic_memory_and_retrieval", "image_generation", "speech_and_voice_design", "video_generation"],
        "preferred_cloud_roles": ["structured_agent_draft", "long_context_red_team", "multimodal_understanding", "safety_critic"],
        "cloud_gpu_stage": "quality accelerator for admitted specialist models; checkpoint export mandatory",
        "output_contract": ["company-stage diagnosis", "strategy", "channel assets", "approval receipts", "experiment observation", "next-cycle recommendation", "cross-device memory"],
        "hard_gates": ["all lifecycle stages bound", "strategy-to-asset contradiction = 0", "approval present", "synthetic observation labeled", "next cycle cites observed evidence"],
        "failure_signals": ["strategy deck without execution", "asset without diagnosis", "observation not fed back", "budget/authority drift", "memory loses provenance"],
    },
}


def _load(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise HybridQualityControlError(f"unsafe or missing input: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise HybridQualityControlError(f"invalid JSON input: {path}") from error
    if not isinstance(value, dict):
        raise HybridQualityControlError(f"JSON input must be an object: {path}")
    return value


def _verify_seal(value: Mapping[str, Any], schema: str, label: str) -> dict[str, Any]:
    if value.get("schema") != schema:
        raise HybridQualityControlError(f"{label} schema is invalid")
    supplied = value.get("content_sha256")
    unsigned = dict(value)
    unsigned.pop("content_sha256", None)
    if supplied != sha256_json(unsigned):
        raise HybridQualityControlError(f"{label} digest is invalid")
    return dict(value)


def _render_markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# GTM hybrid quality control V1",
        "",
        "Hardware and model providers are replaceable executors. The stable product is the capability contract, Graph/Loop/Harness behavior, same-Brief artifact contract and effect PK evidence.",
        "",
        f"- Local capability lanes ready: **{payload['portfolio']['local_ready_category_count']}/13**",
        f"- Cloud API roles ready: **{payload['portfolio']['cloud_api_role_count_ready']}/4**",
        f"- Cloud GPU training route: **{payload['portfolio']['cloud_gpu_training_status']}**",
        f"- Challenger dossiers admitted: **{payload['portfolio']['challenger_dossier_count_admitted']}/13**",
        f"- Executable PK jobs: **{payload['portfolio']['job_count']}**; completed human PK rows: **0/130**",
        "",
        "| Lane | Product output contract | Hard gates | Local executors | Cloud accelerators | Current PK blocker |",
        "|---|---|---|---|---|---|",
    ]
    for lane in payload["lanes"]:
        lines.append(
            "| {lane} | {outputs} | {gates} | {local} | {cloud} | authorized named-product baseline + five independent reviews |".format(
                lane=lane["category_id"],
                outputs="; ".join(lane["output_contract"]),
                gates="; ".join(lane["hard_gates"]),
                local=", ".join(f"{key}={value}" for key, value in lane["local_route"].items()),
                cloud=", ".join(lane["preferred_cloud_roles"]),
            )
        )
    lines.extend([
        "",
        "## 130 same-Brief jobs",
        "",
        "Each row below is a real execution slot, not a victory claim. `READY_LOCAL_CANDIDATE` means the local capability path and challenger dossier exist; it remains blocked from comparison until an authorized named-product baseline and five independent human reviews exist.",
        "",
        "| Job | Lane | Named product | Frozen brief | Candidate | Baseline | Human review |",
        "|---|---|---|---|---|---|---|",
    ])
    for job in payload["jobs"]:
        lines.append(
            f"| {job['job_id']} | {job['category_id']} | {job['reference_product']} | `{job['frozen_brief_sha256'][:12]}` | {job['candidate_status']} | {job['baseline_status']} | 0/5 |"
        )
    lines.extend([
        "",
        "## Four-hour execution order",
        "",
    ])
    for item in payload["four_hour_execution_order"]:
        lines.append(f"{item['window']}. **{item['objective']}** — {item['exit_gate']}")
    lines.extend(["", f"> {payload['truth_boundary']}", ""])
    return "\n".join(lines)


def compile_hybrid_quality_control(
    *,
    project_root: Path,
    ledger_path: Path,
    challenger_admission_path: Path,
    capture_manifest_path: Path,
    local_discovery_path: Path,
    cloud_plan_path: Path,
    output_json: Path | None = None,
    output_markdown: Path | None = None,
) -> dict[str, Any]:
    root = project_root.resolve(strict=True)
    ledger = _verify_seal(_load(ledger_path), LEDGER_SCHEMA, "product-effect ledger")
    if ledger.get("category_count") != 13 or ledger.get("reference_product_row_count") != 130:
        raise HybridQualityControlError("product-effect ledger coverage drifted")
    challenger = validate_challenger_admission(
        _load(challenger_admission_path), ledger=ledger, project_root=root
    )
    capture = validate_kit_manifest(
        _load(capture_manifest_path), kit_root=capture_manifest_path.parent
    )
    if capture.get("source_ledger_sha256") != ledger["content_sha256"]:
        raise HybridQualityControlError("capture kit is not bound to the current ledger")
    local = _load(local_discovery_path)
    cloud = _load(cloud_plan_path)
    if local.get("schema") != LOCAL_SCHEMA or cloud.get("schema") != CLOUD_SCHEMA:
        raise HybridQualityControlError("local discovery or cloud execution plan schema is invalid")
    if local.get("secret_persisted") is not False or cloud.get("secret_values_persisted") is not False:
        raise HybridQualityControlError("secret persistence is forbidden")
    categories = {row["category_id"]: row for row in ledger["categories"]}
    dossier_by_category = {row["category_id"]: row for row in challenger["categories"]}
    slots = {
        (row["category_id"], row["reference_product"]): row
        for row in capture["capture_slots"]
    }
    local_roles = local.get("local_role_assignment")
    cloud_roles = cloud.get("api_roles")
    if not isinstance(local_roles, dict) or not isinstance(cloud_roles, dict):
        raise HybridQualityControlError("model role discovery is incomplete")
    if set(categories) != set(LANE_CONTRACTS) or set(dossier_by_category) != set(LANE_CONTRACTS):
        raise HybridQualityControlError("13-lane capability coverage drifted")

    lanes: list[dict[str, Any]] = []
    for category_id, contract in LANE_CONTRACTS.items():
        required = list(contract["required_local_roles"])
        resolved = {role: local_roles.get(role) for role in required}
        missing = [role for role, model in resolved.items() if not model]
        preferred = list(contract["preferred_cloud_roles"])
        selected_cloud = {
            role: [route["candidate_id"] for route in cloud_roles.get(role, {}).get("routes", [])]
            for role in preferred
        }
        dossier = dossier_by_category[category_id]
        craft_playbook = compile_lane_craft_playbook(
            category_id,
            same_brief_task=categories[category_id]["same_brief_task"],
            effect_pk_question=categories[category_id]["effect_pk_question"],
            quality_axes=categories[category_id]["quality_axes"],
            output_contract=contract["output_contract"],
            hard_gates=contract["hard_gates"],
            failure_signals=contract["failure_signals"],
        )
        lane = {
            "category_id": category_id,
            "same_brief_task": categories[category_id]["same_brief_task"],
            "effect_pk_question": categories[category_id]["effect_pk_question"],
            "quality_axes": categories[category_id]["quality_axes"],
            "output_contract": list(contract["output_contract"]),
            "hard_gates": list(contract["hard_gates"]),
            "failure_signals": list(contract["failure_signals"]),
            "local_route": resolved,
            "local_route_ready": not missing,
            "missing_local_roles": missing,
            "preferred_cloud_roles": preferred,
            "selected_cloud_routes": selected_cloud,
            "cloud_quality_acceleration_ready": any(selected_cloud.values()),
            "cloud_gpu_stage": contract["cloud_gpu_stage"],
            "selected_cloud_gpu_training_route": cloud.get("selected_weight_training_route"),
            "cloud_gpu_is_product_runtime_dependency": False,
            "challenger_dossier_sha256": dossier["dossier"]["sha256"],
            "challenger_dossier_admitted": dossier["named_product_pk_preparation_admitted"] is True,
            "open_source_reuse": categories[category_id]["open_source_projects"],
            "model_judge_can_promote": False,
            "human_release_required": True,
            "specialist_craft_playbook": craft_playbook,
        }
        lanes.append(lane)

    jobs: list[dict[str, Any]] = []
    lane_by_id = {row["category_id"]: row for row in lanes}
    for index, row in enumerate(ledger["product_pk_rows"], start=1):
        key = (row["category_id"], row["reference_product"])
        slot = slots.get(key)
        if slot is None:
            raise HybridQualityControlError(f"missing capture slot for {key}")
        lane = lane_by_id[row["category_id"]]
        job_core = {
            "category_id": row["category_id"],
            "reference_product": row["reference_product"],
            "capture_slot_id": slot["capture_slot_id"],
            "frozen_brief_sha256": slot["frozen_brief_sha256"],
        }
        job_id = f"effect-pk-{index:04d}-{sha256_json(job_core)[:10]}"
        craft_job_binding = compile_craft_job_binding(
            lane["specialist_craft_playbook"],
            job_id=job_id,
            reference_product=row["reference_product"],
            frozen_brief_sha256=slot["frozen_brief_sha256"],
            candidate_dossier_sha256=lane["challenger_dossier_sha256"],
        )
        jobs.append({
            "job_id": job_id,
            **job_core,
            "reference_capability": row["reference_capability"],
            "same_brief_task": row["same_brief_task"],
            "effect_pk_question": row["effect_pk_question"],
            "quality_axis_score_contract": [
                {"axis": axis, "scale": "1-5 per side", "minimum_candidate_target": 4, "human_only": True}
                for axis in row["quality_axes"]
            ],
            "candidate_status": "READY_LOCAL_CANDIDATE" if lane["local_route_ready"] and lane["challenger_dossier_admitted"] else "BLOCKED_CANDIDATE",
            "candidate_dossier_sha256": lane["challenger_dossier_sha256"],
            "baseline_status": "AWAITING_AUTHORIZED_BASELINE",
            "cloud_acceleration_status": "READY_OPTIONAL" if lane["cloud_quality_acceleration_ready"] else "UNAVAILABLE_OPTIONAL_LOCAL_CONTINUES",
            "human_review_status": "AWAITING_5_INDEPENDENT_REVIEWS",
            "specialist_craft_job_binding": craft_job_binding,
            "execution_steps": [
                "import rights-cleared named-product same-Brief output",
                "execute the content-bound specialist craft work orders",
                "replay or regenerate the admitted candidate through capability routes",
                "run three independent specialist reviews and repair only located failures once",
                "run all three specialist reviews again after any repair",
                "run deterministic lane hard gates and fail closed on remaining failures",
                "prepare source-hidden hash-bound pair",
                "collect five independent human reviews",
                "compile row result without automatic model/runtime/release mutation",
            ],
            "automatic_external_actions": 0,
        })

    payload = seal({
        "schema": SCHEMA,
        "source_bindings": {
            "ledger_file_sha256": sha256_file(ledger_path),
            "ledger_content_sha256": ledger["content_sha256"],
            "challenger_admission_file_sha256": sha256_file(challenger_admission_path),
            "challenger_admission_content_sha256": challenger["content_sha256"],
            "capture_manifest_file_sha256": sha256_file(capture_manifest_path),
            "capture_manifest_content_sha256": capture["content_sha256"],
            "local_discovery_file_sha256": sha256_file(local_discovery_path),
            "cloud_plan_file_sha256": sha256_file(cloud_plan_path),
        },
        "routing_invariants": {
            "hardware_and_provider_are_replaceable": True,
            "jobs_route_by_capability_not_vendor": True,
            "local_pipeline_continues_without_cloud": True,
            "cloud_models_are_generation_critique_or_ranking_challengers": True,
            "cloud_gpu_is_quality_accelerator_not_product_runtime_dependency": True,
            "inference_is_not_training": True,
            "training_requires_dataset_rights_and_checkpoint_receipt": True,
            "model_judge_can_promote": False,
            "human_release_required": True,
            "automatic_publish_send_spend_or_strategy_mutation": False,
            "radeon_required_for_product_closure": False,
            "radeon_role": "optional competition compatibility evidence",
        },
        "portfolio": {
            "category_count": 13,
            "job_count": 130,
            "local_ready_category_count": sum(row["local_route_ready"] for row in lanes),
            "challenger_dossier_count_admitted": sum(row["challenger_dossier_admitted"] for row in lanes),
            "cloud_api_role_count_ready": cloud.get("ready_api_role_count"),
            "cloud_gpu_training_status": cloud.get("weight_training_status"),
            "authorized_named_product_baseline_count": capture.get("authorized_baseline_count"),
            "completed_named_product_pk_count": 0,
            "candidate_wins": 0,
            "effect_aligned_categories": 0,
            "product_local_runtime_blocked_by_cloud": False,
        },
        "lanes": lanes,
        "jobs": jobs,
        "four_hour_execution_order": [
            {"window": "T+00–45 min", "objective": "freeze one evidence pack and replay all 13 deterministic lane gates", "exit_gate": "13/13 admitted candidate dossiers with exact source digests"},
            {"window": "T+45–135 min", "objective": "generate local challenger variants only for located last-mile failures", "exit_gate": "no format, claim, authority, provenance or continuity blocker"},
            {"window": "T+135–195 min", "objective": "add cloud model/GPU challengers where credentials and sessions are actually available", "exit_gate": "provider receipts, costs, revisions and rights boundaries sealed; local fallback still passes"},
            {"window": "T+195–240 min", "objective": "prepare authorized named-product pairs and hand off source-hidden review kits", "exit_gate": "never claim a win without five independent human reviews per row"},
        ],
        "truth_boundary": (
            "This control plane proves capability-based routing, 13-lane local readiness, explicit "
            "cloud/GPU optionality and 130 executable same-Brief PK slots. It does not provide the "
            "missing authorized product baselines or human votes and therefore proves zero named-product "
            "wins, zero 4A alignment, zero production lift and zero causal revenue effect."
        ),
    })
    if output_json is not None:
        output_json.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(output_json, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    if output_markdown is not None:
        output_markdown.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(output_markdown, _render_markdown(payload))
    return payload
