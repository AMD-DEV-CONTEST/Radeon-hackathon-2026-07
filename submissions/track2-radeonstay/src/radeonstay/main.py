from __future__ import annotations

import hmac
import json
import math
import re
import stat
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import gradio as gr
import uvicorn
from fastapi import FastAPI

from .api import create_api, readiness_report, startup_security_checks_ok
from .auth import IdentityError, LocalIdentityProvider
from .cloud_model_client import RadeonCloudFreeModelClient
from .config import Settings, load_env_file
from .domain import HotelService, HotelStore, build_tool_registry
from .model_client import LocalModelClient, ModelClient
from .orchestrator import RadeonStayService
from .planning import DeterministicPlanner, LocalLLMPlanner
from .retrieval import PolicyRetriever, validate_policy_directory
from .ui import build_ui

_RUNTIME_PROOF_FIELDS = frozenset(
    {
        "schema_version",
        "status",
        "run_id",
        "captured_at_utc",
        "rocm_version",
        "hip_version",
        "gpu_name",
        "gpu_arch",
        "compute_units",
        "vram_bytes",
        "offloaded_layers",
        "total_layers",
        "model_alias",
        "model_sha256",
        "llama_server_sha256",
        "binding_valid",
        "telemetry_active",
        "c2_commit",
        "reference_label",
        "winner_label",
        "winner_assessment_accepted",
        "winner_report_sha256",
        "winner_core_metric",
        "winner_core_improvement_percent",
        "request_configuration_sha256",
        "service_configuration_sha256",
        "candidate_source_index_sha256",
        "quality_qualified_candidate_count",
        "quality_negative_label",
        "quality_negative_manifest_sha256",
        "stability_report_sha256",
        "stability_run_count",
        "stability_run_ids_sha256",
        "soak_report_sha256",
        "soak_run_id",
        "soak_duration_seconds",
        "final_evidence_accepted",
    }
)
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_GIT_COMMIT_RE = re.compile(r"^[a-f0-9]{40}(?:[a-f0-9]{24})?$")
_EXPECTED_OFFLOADED_MODEL_LAYERS = 41


def _reject_nonstandard_json_constant(value: str) -> Any:
    raise ValueError(f"Non-standard JSON constant is forbidden: {value}")


def _is_safe_proof_scalar(value: Any) -> bool:
    return bool(
        value is None
        or isinstance(value, (str, int, bool))
        or (isinstance(value, float) and math.isfinite(value))
    )


def load_runtime_proof(settings: Settings) -> dict[str, Any]:
    """Load a bounded, display-safe target manifest without exposing its path."""

    path = settings.runtime_proof_path
    if path is None:
        return {
            "status": (
                "missing_required_proof"
                if settings.runtime_proof_required
                else "not_bound"
            ),
            "required": settings.runtime_proof_required,
            "evidence_eligible": False,
        }
    if path.is_symlink() or not path.is_file():
        raise ValueError("Runtime proof must be a regular non-symlink JSON file")
    if path.stat().st_size > 1024 * 1024:
        raise ValueError("Runtime proof exceeds the 1 MiB safety limit")
    try:
        raw = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=_reject_nonstandard_json_constant,
        )
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError("Runtime proof is not valid UTF-8 JSON") from exc
    if not isinstance(raw, dict):
        raise ValueError("Runtime proof must be a JSON object")
    proof: dict[str, Any] = {
        str(key): value
        for key, value in raw.items()
        if str(key) in _RUNTIME_PROOF_FIELDS
        and _is_safe_proof_scalar(value)
    }
    observation = raw.get("single_request_rocm_observation")
    observation = observation if isinstance(observation, dict) else {}
    inference = raw.get("inference_identity")
    inference = inference if isinstance(inference, dict) else {}
    nested_fields = {
        "rocm_version": observation.get("rocm_version"),
        "gpu_name": observation.get("reported_product_string"),
        "gpu_arch": observation.get("gfx_target"),
        "compute_units": observation.get("compute_units"),
        "vram_bytes": observation.get("vram_total_bytes"),
        "model_alias": inference.get("model_alias"),
        "model_sha256": inference.get("model_file_sha256"),
        "llama_server_sha256": inference.get("llama_server_sha256"),
    }
    for key, value in nested_fields.items():
        if key not in proof and _is_safe_proof_scalar(value):
            proof[key] = value
    offload = observation.get("offloaded_model_layers")
    if (
        "offloaded_layers" not in proof
        and "total_layers" not in proof
        and isinstance(offload, str)
    ):
        match = re.fullmatch(r"\s*([0-9]+)\s*/\s*([0-9]+)\s*", offload)
        if match is not None:
            proof["offloaded_layers"] = int(match.group(1))
            proof["total_layers"] = int(match.group(2))
    proof["status"] = str(proof.get("status", "bound"))[:40]
    proof["status_eligible"] = proof["status"] in {
        "accepted",
        "accepted_final",
        "verified",
        "verified_final",
    }
    proof["required"] = True
    offloaded_layers = proof.get("offloaded_layers")
    total_layers = proof.get("total_layers")
    model_sha256 = proof.get("model_sha256")
    llama_server_sha256 = proof.get("llama_server_sha256")
    model_alias = proof.get("model_alias")
    proof["model_alias_matches_config"] = bool(
        isinstance(model_alias, str) and model_alias == settings.model_name
    )
    c2_commit = proof.get("c2_commit")
    reference_label = proof.get("reference_label")
    winner_label = proof.get("winner_label")
    winner_report_sha256 = proof.get("winner_report_sha256")
    winner_core_metric = proof.get("winner_core_metric")
    winner_core_improvement = proof.get("winner_core_improvement_percent")
    request_configuration_sha256 = proof.get("request_configuration_sha256")
    service_configuration_sha256 = proof.get("service_configuration_sha256")
    candidate_source_index_sha256 = proof.get("candidate_source_index_sha256")
    quality_qualified_candidate_count = proof.get(
        "quality_qualified_candidate_count"
    )
    quality_negative_label = proof.get("quality_negative_label")
    quality_negative_manifest_sha256 = proof.get(
        "quality_negative_manifest_sha256"
    )
    stability_report_sha256 = proof.get("stability_report_sha256")
    stability_run_count = proof.get("stability_run_count")
    stability_run_ids_sha256 = proof.get("stability_run_ids_sha256")
    soak_report_sha256 = proof.get("soak_report_sha256")
    soak_run_id = proof.get("soak_run_id")
    soak_duration_seconds = proof.get("soak_duration_seconds")
    proof["request_configuration_matches_config"] = bool(
        isinstance(request_configuration_sha256, str)
        and _SHA256_RE.fullmatch(request_configuration_sha256) is not None
        and hmac.compare_digest(
            request_configuration_sha256,
            settings.request_configuration_sha256,
        )
    )
    proof["release_metadata_valid"] = bool(
        isinstance(c2_commit, str)
        and _GIT_COMMIT_RE.fullmatch(c2_commit) is not None
        and isinstance(reference_label, str)
        and reference_label in {"A", "B"}
        and isinstance(winner_label, str)
        and winner_label in tuple("BCDEFGH")
        and winner_label > reference_label
        and proof.get("winner_assessment_accepted") is True
        and isinstance(winner_report_sha256, str)
        and _SHA256_RE.fullmatch(winner_report_sha256) is not None
        and isinstance(winner_core_metric, str)
        and 1 <= len(winner_core_metric) <= 80
        and isinstance(winner_core_improvement, (int, float))
        and not isinstance(winner_core_improvement, bool)
        and math.isfinite(float(winner_core_improvement))
        and float(winner_core_improvement) >= 5.0
        and isinstance(request_configuration_sha256, str)
        and _SHA256_RE.fullmatch(request_configuration_sha256) is not None
        and proof["request_configuration_matches_config"] is True
        and isinstance(service_configuration_sha256, str)
        and _SHA256_RE.fullmatch(service_configuration_sha256) is not None
    )
    expected_candidate_count = 8 if reference_label == "A" else 7
    expected_negative_label = "none" if reference_label == "A" else "A"
    negative_source_valid = bool(
        quality_negative_manifest_sha256 is None
        if reference_label == "A"
        else isinstance(quality_negative_manifest_sha256, str)
        and _SHA256_RE.fullmatch(quality_negative_manifest_sha256) is not None
    )
    proof["final_evidence_valid"] = bool(
        proof.get("schema_version") == 2
        and proof.get("final_evidence_accepted") is True
        and isinstance(candidate_source_index_sha256, str)
        and _SHA256_RE.fullmatch(candidate_source_index_sha256) is not None
        and type(quality_qualified_candidate_count) is int
        and quality_qualified_candidate_count == expected_candidate_count
        and quality_negative_label == expected_negative_label
        and negative_source_valid
        and isinstance(stability_report_sha256, str)
        and _SHA256_RE.fullmatch(stability_report_sha256) is not None
        and type(stability_run_count) is int
        and stability_run_count == 5
        and isinstance(stability_run_ids_sha256, str)
        and _SHA256_RE.fullmatch(stability_run_ids_sha256) is not None
        and isinstance(soak_report_sha256, str)
        and _SHA256_RE.fullmatch(soak_report_sha256) is not None
        and isinstance(soak_run_id, str)
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,47}", soak_run_id)
        is not None
        and soak_run_id != proof.get("run_id")
        and isinstance(soak_duration_seconds, (int, float))
        and not isinstance(soak_duration_seconds, bool)
        and math.isfinite(float(soak_duration_seconds))
        and float(soak_duration_seconds) >= 1800.0
    )
    accepted_status = proof["status"] in {"accepted", "accepted_final"}
    final_status = proof["status"] == "accepted_final"
    proof["evidence_eligible"] = bool(
        proof.get("binding_valid") is True
        and proof.get("telemetry_active") is True
        and type(offloaded_layers) is int
        and type(total_layers) is int
        and offloaded_layers
        == total_layers
        == _EXPECTED_OFFLOADED_MODEL_LAYERS
        and isinstance(proof.get("gpu_arch"), str)
        and str(proof["gpu_arch"]).startswith("gfx")
        and isinstance(proof.get("rocm_version"), str)
        and bool(str(proof["rocm_version"]).strip())
        and type(proof.get("compute_units")) is int
        and int(proof["compute_units"]) > 0
        and isinstance(model_sha256, str)
        and _SHA256_RE.fullmatch(model_sha256) is not None
        and isinstance(llama_server_sha256, str)
        and _SHA256_RE.fullmatch(llama_server_sha256) is not None
        and isinstance(service_configuration_sha256, str)
        and _SHA256_RE.fullmatch(service_configuration_sha256) is not None
        and proof["request_configuration_matches_config"] is True
        and proof["model_alias_matches_config"] is True
        and proof["status_eligible"] is True
        and (not accepted_status or proof["release_metadata_valid"] is True)
        and (not final_status or proof["final_evidence_valid"] is True)
    )
    return proof


def load_settings(project_root: Path | None = None) -> Settings:
    root = (project_root or Path(__file__).resolve().parents[2]).resolve()
    load_env_file(root / ".env")
    settings = Settings.from_env(root)
    settings.validate_runtime_security()
    return settings


def build_service(settings: Settings) -> RadeonStayService:
    settings.ensure_runtime_dirs()
    settings.secure_runtime_files()
    store = HotelStore(
        settings.database_path,
        audit_secret=settings.audit_secret,
    )
    model: ModelClient | None = None
    try:
        store.initialize(seed=True)
        settings.secure_runtime_files()
        hotel = HotelService(store)
        registry = build_tool_registry(hotel)
        default_policy_dir = settings.project_root / "data" / "policies"
        policy_dir = (
            validate_policy_directory(
                settings.policy_dir,
                project_root=settings.project_root,
            )
            if settings.policy_dir == default_policy_dir
            else validate_policy_directory(settings.policy_dir)
        )
        retriever = PolicyRetriever.from_directory(policy_dir)
        identity_provider = LocalIdentityProvider(settings.identity_secret)
        runtime_proof = (
            {
                "status": "not_applicable_cloud_bonus",
                "required": False,
                "evidence_eligible": False,
                "local_only": False,
                "provider": settings.inference_provider,
                "competition_path": "radeon-cloud-public-free-bonus",
            }
            if settings.uses_radeon_cloud_free
            else load_runtime_proof(settings)
        )
        if settings.deterministic_mode:
            planner = DeterministicPlanner()
        elif settings.uses_radeon_cloud_free:
            model = RadeonCloudFreeModelClient(settings)
            planner = LocalLLMPlanner(model)
        else:
            model = LocalModelClient(
                settings,
                runtime_proof=runtime_proof,
            )
            runtime_proof.update(
                model.runtime_binding_result().public_report()
            )
            planner = LocalLLMPlanner(model)
        return RadeonStayService(
            identity_provider=identity_provider,
            registry=registry,
            retriever=retriever,
            planner=planner,
            audit_secret=settings.audit_secret,
            answer_model=model,
            runtime_proof=runtime_proof,
        )
    except Exception:
        try:
            if model is not None:
                model.close()
        finally:
            try:
                settings.secure_runtime_files()
            finally:
                store.close()
        raise


def build_startup_preflight(
    settings: Settings,
    service: RadeonStayService,
) -> dict[str, Any]:
    """Build the bounded startup evidence shown to judges and operators."""
    health = readiness_report(service)
    permissions = settings.runtime_security_report()
    env_path = settings.project_root / ".env"
    try:
        env_stat = env_path.lstat()
    except FileNotFoundError:
        env_stat = None
    env_present = env_stat is not None
    env_is_regular = bool(
        env_stat is not None and stat.S_ISREG(env_stat.st_mode)
    )
    env_mode = stat.S_IMODE(env_stat.st_mode) if env_is_regular else None
    environment_file = {
        "ok": not env_present or (env_is_regular and env_mode == 0o600),
        "present": env_present,
        "mode": f"{env_mode:04o}" if env_mode is not None else None,
    }
    policy_chunks = health.get("policy_chunks")
    tools = health.get("tools")
    policies = {
        "ok": isinstance(policy_chunks, int) and policy_chunks > 0,
        "chunk_count": policy_chunks if isinstance(policy_chunks, int) else 0,
    }
    tool_check = {
        "ok": isinstance(tools, list) and bool(tools),
        "count": len(tools) if isinstance(tools, list) else 0,
    }
    health_runtime_proof = health.get("runtime_proof")
    runtime_proof = dict(
        health_runtime_proof
        if isinstance(health_runtime_proof, Mapping)
        else getattr(
            service,
            "runtime_proof",
            {"status": "not_bound", "required": False, "evidence_eligible": False},
        )
    )
    runtime_proof["required"] = bool(
        settings.runtime_proof_required or runtime_proof.get("required")
    )
    runtime_proof["ok"] = bool(
        not runtime_proof.get("required")
        or runtime_proof.get("evidence_eligible") is True
    )
    expected_evidence_run_id = settings.evidence_run_id or settings.demo_run_id
    proof_run_matches = bool(
        expected_evidence_run_id
        and isinstance(runtime_proof.get("run_id"), str)
        and runtime_proof["run_id"] == expected_evidence_run_id
    )
    database_run_matches = settings.isolated_database_run_bound
    demo_isolation = {
        "ok": bool(
            not settings.isolated_demo
            or (
                settings.demo_run_id
                and settings.runtime_proof_path is not None
                and settings.runtime_instance_path is not None
                and runtime_proof.get("evidence_eligible") is True
                and proof_run_matches
                and database_run_matches
            )
        ),
        "enabled": settings.isolated_demo,
        "run_id": settings.demo_run_id,
        "evidence_run_id_bound": proof_run_matches,
        "database_reuse": (
            "same_deployment_secure_reopen"
            if settings.isolated_demo
            else "allowed"
        ),
        "new_deployment_requires_new_database": settings.isolated_demo,
        "runtime_proof_bound": bool(settings.runtime_proof_path is not None),
        "runtime_proof_run_match": proof_run_matches,
        "database_run_match": database_run_matches,
    }
    database_check = health.get("database")
    if not isinstance(database_check, Mapping):
        database_check = {
            "ok": health.get("ok") is True,
            "source": "readiness_aggregate",
        }
    checks = {
        "environment_file": environment_file,
        "runtime_permissions": permissions,
        "database": database_check,
        "inventory": health.get("inventory", {"ok": False}),
        "local_model": health.get("model", {"ok": False}),
        "inference_provider": {
            "ok": health.get("model", {}).get("ok") is True,
            "name": settings.inference_provider,
            "local_only": settings.local_only,
            "bonus_demo": settings.bonus_demo,
            "synthetic_only": settings.uses_radeon_cloud_free,
        },
        "policies": policies,
        "tools": tool_check,
        "runtime_proof": runtime_proof,
        "demo_isolation": demo_isolation,
    }
    ok = bool(
        environment_file["ok"]
        and permissions.get("ok")
        and checks["database"].get("ok") is True
        and checks["inventory"].get("ok") is True
        and policies["ok"]
        and tool_check["ok"]
        and runtime_proof["ok"]
        and demo_isolation["ok"]
    )
    return {
        "ok": ok,
        "status": "preflight_passed" if ok else "preflight_failed",
        "inference_provider": settings.inference_provider,
        "local_only": settings.local_only,
        "bonus_demo": settings.bonus_demo,
        "network_boundary": health.get("network_boundary"),
        "checks": checks,
        "readiness_endpoint": "/health/ready",
        "liveness_endpoint": "/health/live",
    }


def create_application(settings: Settings | None = None) -> FastAPI:
    resolved = settings or load_settings()
    # Custom Settings instances are accepted by tests and embedded deployments,
    # but must never bypass the same fail-closed checks as environment settings.
    resolved.validate_runtime_security()
    service = build_service(resolved)
    try:
        preflight = build_startup_preflight(resolved, service)
        operations_enabled = bool(
            not resolved.isolated_demo
            or startup_security_checks_ok(preflight)
        )
        api = create_api(
            service,
            startup_preflight=preflight,
            operations_enabled=operations_enabled,
        )
        api.state.startup_preflight = preflight
        api.state.operations_enabled = operations_enabled
        if not operations_enabled:
            return api
        public_bind = resolved.host not in {"127.0.0.1", "localhost", "::1"}
        public_access = public_bind or resolved.public_demo_enabled
        tokens = service.identity_provider.demo_tokens(include_staff=not public_access)

        def refresh_demo_identity(label: str, session_id: str) -> str:
            if not session_id or len(session_id) > 120:
                raise IdentityError("A valid demo session is required")
            return service.identity_provider.issue_demo_token(
                label,
                include_staff=not public_access,
                session_scope=session_id if public_access else None,
            )

        ui = build_ui(
            service,
            tokens,
            identity_token_refresher=refresh_demo_identity,
            initial_health=preflight,
        )
        auth = (
            (resolved.ui_username, resolved.ui_password)
            if public_access
            else None
        )
        return gr.mount_gradio_app(api, ui, path="/", auth=auth)
    except Exception:
        service.close()
        raise


def main() -> None:
    settings = load_settings()
    application = create_application(settings)
    uvicorn.run(
        application,
        host=settings.host,
        port=settings.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
