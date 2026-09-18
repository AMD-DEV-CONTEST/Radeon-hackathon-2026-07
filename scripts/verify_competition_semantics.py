"""Validate resolved competition policy and emit a redacted snapshot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlparse

from buildguard.config import load_settings
from buildguard.exceptions import EndpointSecurityError
from buildguard.security.network_guard import NetworkGuard


def verify(config: Path) -> dict[str, object]:
    settings = load_settings(config)
    endpoint = str(settings.llm.endpoint)
    host = urlparse(endpoint).hostname
    enabled_models = [model for model in settings.vision.models if model.enabled]
    guard = NetworkGuard([endpoint], settings.permissions.allowed_lan_cidrs)
    remote_rejected = False
    try:
        guard.validate("https://api.openai.com/v1/chat/completions")
    except EndpointSecurityError:
        remote_rejected = True
    checks = {
        "llm_loopback": host in {"localhost", "127.0.0.1", "::1"},
        "mock_disabled": (
            settings.llm.mode != "mock"
            and settings.rag.embedding_mode != "mock"
            and settings.rag.reranker_mode != "mock"
            and all(model.backend != "mock" for model in enabled_models)
        ),
        "offline_only": settings.competition.offline_only,
        "require_rocm": settings.competition.require_rocm,
        "allow_cpu_fallback_false": (
            not settings.monitoring.scheduler.allow_cpu_fallback
        ),
        "embedding_local_files_only": settings.rag.embedding_local_files_only,
        "reranker_local_files_only": settings.rag.reranker_local_files_only,
        "ppe_local_model": bool(enabled_models)
        and all(model.backend == "local" and model.model_path for model in enabled_models),
        "remote_inference_rejected": remote_rejected,
    }
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "resolved_config": settings.safe_dump(),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/competition/app.yaml"),
    )
    arguments = parser.parse_args()
    report = verify(arguments.config)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["status"] == "PASS" else 2)
