from __future__ import annotations

from pathlib import Path

import gradio as gr
import uvicorn
from fastapi import FastAPI

from .api import create_api
from .auth import LocalIdentityProvider
from .config import Settings, load_env_file
from .domain import HotelService, HotelStore, build_tool_registry
from .model_client import LocalModelClient
from .orchestrator import RadeonStayService
from .planning import DeterministicPlanner, LocalLLMPlanner
from .retrieval import PolicyRetriever, validate_policy_directory
from .ui import build_ui


def load_settings(project_root: Path | None = None) -> Settings:
    root = (project_root or Path(__file__).resolve().parents[2]).resolve()
    load_env_file(root / ".env")
    settings = Settings.from_env(root)
    settings.validate_runtime_security()
    return settings


def build_service(settings: Settings) -> RadeonStayService:
    settings.ensure_runtime_dirs()
    store = HotelStore(settings.database_path)
    model: LocalModelClient | None = None
    try:
        store.initialize(seed=True)
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
        if settings.deterministic_mode:
            planner = DeterministicPlanner()
        else:
            model = LocalModelClient(settings)
            planner = LocalLLMPlanner(model)
        return RadeonStayService(
            identity_provider=identity_provider,
            registry=registry,
            retriever=retriever,
            planner=planner,
            audit_secret=settings.audit_secret,
            answer_model=model,
        )
    except Exception:
        if model is not None:
            model.close()
        store.close()
        raise


def create_application(settings: Settings | None = None) -> FastAPI:
    resolved = settings or load_settings()
    # Custom Settings instances are accepted by tests and embedded deployments,
    # but must never bypass the same fail-closed checks as environment settings.
    resolved.validate_runtime_security()
    service = build_service(resolved)
    try:
        api = create_api(service)
        public_bind = resolved.host not in {"127.0.0.1", "localhost", "::1"}
        tokens = service.identity_provider.demo_tokens(include_staff=not public_bind)
        ui = build_ui(service, tokens)
        auth = (
            (resolved.ui_username, resolved.ui_password)
            if public_bind
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
