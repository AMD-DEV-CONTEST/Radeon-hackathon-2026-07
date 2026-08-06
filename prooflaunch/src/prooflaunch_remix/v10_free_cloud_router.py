from __future__ import annotations

from collections.abc import Mapping, Sequence

from .v10_contracts import V10ContractError
from .v10_frontier_api_panel import request_ceiling


API_ROLE_ORDER = (
    "structured_agent_draft",
    "long_context_red_team",
    "multimodal_understanding",
    "safety_critic",
)

COMPUTE_ROUTE_ORDER = (
    "lightning_ai_studios",
    "modelscope_notebook",
    "modal_starter",
    "kaggle_notebooks",
    "google_colab_free",
    "huggingface_zerogpu",
    "nvidia_launchpad",
    "amazon_sagemaker_studio_lab_existing_accounts",
)

WEIGHT_TRAINING_ELIGIBLE = frozenset(
    {
        "kaggle_notebooks",
        "lightning_ai_studios",
        "modelscope_notebook",
        "modal_starter",
        "google_colab_free",
        "amazon_sagemaker_studio_lab_existing_accounts",
    }
)

SHORT_INFERENCE_ELIGIBLE = frozenset(
    {
        "kaggle_notebooks",
        "lightning_ai_studios",
        "modelscope_notebook",
        "modal_starter",
        "google_colab_free",
        "huggingface_zerogpu",
    }
)


def _credential_ready(
    candidate: Mapping[str, object],
    credential_state: Mapping[str, bool],
    auxiliary_state: Mapping[str, bool],
) -> bool:
    environment_name = str(candidate.get("api_key_env", "")).strip()
    if not environment_name or not credential_state.get(environment_name, False):
        return False
    provider = str(candidate.get("provider", ""))
    if provider == "cloudflare_workers_ai":
        return auxiliary_state.get("CLOUDFLARE_ACCOUNT_ID", False)
    if provider == "lightning_model_api":
        return auxiliary_state.get("LIGHTNING_FREE_ONLY_ACK", False)
    return True


def _select_independent_candidates(
    candidate_ids: Sequence[str],
    candidate_by_id: Mapping[str, Mapping[str, object]],
    credential_state: Mapping[str, bool],
    auxiliary_state: Mapping[str, bool],
    *,
    limit: int = 2,
) -> list[dict[str, object]]:
    selected: list[dict[str, object]] = []
    providers: set[str] = set()
    for candidate_id in candidate_ids:
        candidate = candidate_by_id.get(candidate_id)
        if candidate is None or candidate.get("access_class") != "zero_cost_rate_limited":
            continue
        if not _credential_ready(candidate, credential_state, auxiliary_state):
            continue
        provider = str(candidate["provider"])
        if provider in providers:
            continue
        selected.append(
            {
                "candidate_id": candidate_id,
                "provider": provider,
                "api_model": candidate["api_model"],
                "endpoint": candidate["endpoint"],
                "maximum_call_cost_usd": candidate["maximum_call_cost_usd"],
                "release_authority": False,
                "training_admission": "blocked_pending_model_specific_output_rights_review",
            }
        )
        providers.add(provider)
        if len(selected) == limit:
            break
    return selected


def _compute_readiness(
    compute_provider: str,
    session_state: Mapping[str, bool],
) -> tuple[bool, str]:
    if compute_provider == "kaggle_notebooks":
        ready = bool(
            session_state.get("KAGGLE_API_TOKEN")
            or (
                session_state.get("KAGGLE_USERNAME")
                and session_state.get("KAGGLE_KEY")
            )
            or session_state.get("KAGGLE_CONFIG_PRESENT")
        )
        return ready, "authenticated Kaggle API session required"
    if compute_provider == "lightning_ai_studios":
        ready = bool(session_state.get("LIGHTNING_API_KEY"))
        return ready, "verified Lightning account and API key required"
    if compute_provider == "modelscope_notebook":
        ready = bool(session_state.get("MODELSCOPE_NOTEBOOK_SESSION_READY"))
        return ready, "active authenticated ModelScope Notebook session required"
    if compute_provider == "modal_starter":
        ready = bool(
            (
                session_state.get("MODAL_TOKEN_ID")
                and session_state.get("MODAL_TOKEN_SECRET")
            )
            or session_state.get("MODAL_CONFIG_PRESENT")
        )
        return ready, "authenticated Modal Starter profile required"
    if compute_provider == "google_colab_free":
        return bool(
            session_state.get("GOOGLE_COLAB_SESSION_READY")
        ), "active authenticated Colab notebook session required"
    if compute_provider == "huggingface_zerogpu":
        ready = bool(
            session_state.get("HF_TOKEN")
            and session_state.get("HF_ZEROGPU_SPACE_READY")
        )
        return ready, "authenticated Hugging Face account and eligible ZeroGPU Space required"
    if compute_provider == "nvidia_launchpad":
        return bool(
            session_state.get("NVIDIA_LAUNCHPAD_SESSION_READY")
        ), "active NVIDIA LaunchPad lab session required"
    if compute_provider == "amazon_sagemaker_studio_lab_existing_accounts":
        return bool(session_state.get("SAGEMAKER_STUDIO_LAB_ACCOUNT_READY")), "pre-2026-07-30 account required"
    return False, "interactive or program-specific session required"


def compile_free_cloud_execution_plan(
    panel: Mapping[str, object],
    *,
    credential_state: Mapping[str, bool],
    auxiliary_state: Mapping[str, bool],
    compute_session_state: Mapping[str, bool],
    observed_at: str,
) -> dict[str, object]:
    candidates = panel.get("candidates")
    policy = panel.get("selection_policy")
    compute_matrix = panel.get("free_compute_matrix")
    if not isinstance(candidates, list) or not isinstance(policy, Mapping):
        raise V10ContractError("frontier panel is missing candidates or selection policy")
    if not isinstance(compute_matrix, list):
        raise V10ContractError("frontier panel is missing the free compute matrix")
    if not observed_at.strip():
        raise V10ContractError("free cloud plan requires an observation date")

    candidate_by_id = {
        str(row["candidate_id"]): row
        for row in candidates
        if isinstance(row, Mapping) and str(row.get("candidate_id", "")).strip()
    }
    assignments = policy.get("workload_assignment")
    if not isinstance(assignments, Mapping):
        raise V10ContractError("frontier panel is missing workload assignments")

    api_roles: dict[str, object] = {}
    selected_ids: list[str] = []
    for role in API_ROLE_ORDER:
        ids = assignments.get(role)
        if not isinstance(ids, list):
            raise V10ContractError(f"frontier panel is missing {role} candidates")
        selected = _select_independent_candidates(
            [str(value) for value in ids],
            candidate_by_id,
            credential_state,
            auxiliary_state,
        )
        selected_ids.extend(str(row["candidate_id"]) for row in selected)
        api_roles[role] = {
            "status": "ready" if selected else "blocked_missing_credential",
            "routes": selected,
            "minimum_independent_providers_target": 2,
            "independent_provider_target_met": len(selected) >= 2,
        }

    unique_selected_ids = list(dict.fromkeys(selected_ids))
    call_ceiling = request_ceiling(len(unique_selected_ids)) if unique_selected_ids else 0
    global_limit = int(policy.get("free_route_daily_request_limit", 0))
    if call_ceiling > global_limit:
        raise V10ContractError("selected free API plan exceeds the frozen daily request limit")

    compute_routes: list[dict[str, object]] = []
    compute_by_provider = {
        str(row["provider"]): row
        for row in compute_matrix
        if isinstance(row, Mapping) and str(row.get("provider", "")).strip()
    }
    for provider in COMPUTE_ROUTE_ORDER:
        row = compute_by_provider.get(provider)
        if row is None:
            raise V10ContractError(f"free compute matrix is missing {provider}")
        ready, blocker = _compute_readiness(provider, compute_session_state)
        compute_routes.append(
            {
                **dict(row),
                "session_ready": ready,
                "status": "ready" if ready else "blocked_missing_authenticated_session",
                "blocker": None if ready else blocker,
                "checkpoint_export_required_before_stop": True,
                "weight_training_eligible": provider in WEIGHT_TRAINING_ELIGIBLE,
                "short_inference_eligible": provider in SHORT_INFERENCE_ELIGIBLE,
            }
        )
    selected_training_route = next(
        (
            str(row["provider"])
            for row in compute_routes
            if row["session_ready"] and row["weight_training_eligible"]
        ),
        None,
    )
    selected_short_inference_route = next(
        (
            str(row["provider"])
            for row in compute_routes
            if row["session_ready"] and row["short_inference_eligible"]
        ),
        None,
    )

    ready_role_count = sum(
        role["status"] == "ready" for role in api_roles.values() if isinstance(role, Mapping)
    )
    return {
        "schema": "ProofLaunchFreeCloudExecutionPlanV2",
        "observed_at": observed_at,
        "local_first": True,
        "api_roles": api_roles,
        "selected_api_candidate_ids": unique_selected_ids,
        "selected_api_candidate_count": len(unique_selected_ids),
        "ready_api_role_count": ready_role_count,
        "possible_api_role_count": len(API_ROLE_ORDER),
        "qualification_request_ceiling": call_ceiling,
        "free_route_daily_request_limit": global_limit,
        "paid_fallback_enabled": False,
        "recommended_activation": {
            "minimum_api_bundle": [
                {
                    "provider": "groq",
                    "required_environment": ["GROQ_API_KEY"],
                    "roles": ["structured_agent_draft"],
                    "reason": "explicit free-plan limits and fast OpenAI-compatible structured inference",
                },
                {
                    "provider": "google_ai_studio",
                    "required_environment": ["GEMINI_API_KEY"],
                    "roles": ["multimodal_understanding"],
                    "reason": "free-tier multimodal challenger with project-specific live limits",
                },
                {
                    "provider": "openrouter",
                    "required_environment": ["OPENROUTER_API_KEY"],
                    "roles": ["long_context_red_team", "safety_critic"],
                    "reason": "free fixed-model fallbacks plus a separately gated dynamic exploration route",
                },
            ],
            "resilience_api_bundle": [
                {
                    "provider": "cloudflare_workers_ai",
                    "required_environment": [
                        "CLOUDFLARE_API_TOKEN",
                        "CLOUDFLARE_ACCOUNT_ID",
                    ],
                    "reason": "independent daily free allocation shared across text and multimodal models",
                },
                {
                    "provider": "sambanova",
                    "required_environment": ["SAMBANOVA_API_KEY"],
                    "reason": "no-payment-method Free Tier with per-model request and token limits",
                },
            ],
            "weight_training_bundle": [
                {
                    "provider": "lightning_ai_studios",
                    "required_environment": ["LIGHTNING_API_KEY"],
                    "priority": 1,
                },
                {
                    "provider": "modelscope_notebook",
                    "required_environment": ["MODELSCOPE_NOTEBOOK_SESSION_READY"],
                    "priority": 2,
                },
                {
                    "provider": "modal_starter",
                    "required_environment": [
                        "MODAL_TOKEN_ID",
                        "MODAL_TOKEN_SECRET",
                    ],
                    "priority": 3,
                },
                {
                    "provider": "kaggle_notebooks",
                    "required_environment": ["KAGGLE_API_TOKEN"],
                    "priority": 4,
                },
            ],
            "inference_is_weight_training": False,
            "secret_values_may_be_persisted": False,
        },
        "external_output_release_authority": False,
        "external_output_training_admission": "blocked_pending_model_specific_output_rights_review",
        "free_compute_priority": compute_routes,
        "selected_weight_training_route": selected_training_route,
        "selected_short_inference_route": selected_short_inference_route,
        "weight_training_status": (
            "ready_checkpointed_free_gpu"
            if selected_training_route
            else "blocked_missing_authenticated_free_gpu_session"
        ),
        "execution_order": [
            "reuse_local_models_and_prepare_frozen_public_or_synthetic_cases",
            "run_same_input_free_api_qualification_with_successive_halving",
            "retain_only_schema_and_effect_gate_winners_as_advisory_outputs",
            "run_checkpointed_adapter_training_on_one_free_gpu_provider",
            "export_checkpoint_metrics_environment_lock_and_sha256_before_stop",
            "run_local_frozen_regression_and_prepare_separate_radeon_handoff",
        ],
        "status": (
            "cloud_api_and_training_ready"
            if ready_role_count and selected_training_route
            else "cloud_api_ready_training_blocked"
            if ready_role_count
            else "cloud_blocked_local_pipeline_remains_ready"
        ),
        "truth_boundary": (
            "This plan proves route discovery and deterministic quota-safe selection only. "
            "It does not prove account approval, live API success, GPU allocation, model training, "
            "provider-output training rights, Radeon execution, or product-quality lift."
        ),
    }
