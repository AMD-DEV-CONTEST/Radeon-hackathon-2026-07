from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, HttpUrl

from . import __version__
from .config import Settings
from .service import OpenAlphaService


class GitHubDiscoveryRequest(BaseModel):
    query: str = Field(min_length=2, max_length=250)
    limit: int = Field(default=5, ge=1, le=25)


class RSSIngestionRequest(BaseModel):
    url: HttpUrl


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    session_id: str | None = Field(default=None, max_length=120)


class WatchRuleRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: str
    config: dict[str, Any]
    interval_minutes: int = Field(default=360, ge=5, le=43_200)


class OfflineModeRequest(BaseModel):
    enabled: bool


class DomainGrantRequest(BaseModel):
    domain: str = Field(min_length=3, max_length=253)


def _raise_api_error(exc: Exception) -> None:
    if isinstance(exc, PermissionError):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if isinstance(exc, (ValueError, FileNotFoundError)):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    raise HTTPException(status_code=502, detail=str(exc)) from exc


def create_app(settings: Settings | None = None) -> FastAPI:
    service = OpenAlphaService(settings)
    app = FastAPI(
        title="OpenAlpha Sentinel",
        version=__version__,
        description="Local-first open-source strategy intelligence agent.",
    )
    app.state.service = service
    web_dir = Path(__file__).with_name("web")
    app.mount("/static", StaticFiles(directory=web_dir), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(web_dir / "index.html")

    @app.get("/app.js", include_in_schema=False)
    def app_javascript() -> FileResponse:
        return FileResponse(web_dir / "app.js", media_type="application/javascript")

    @app.get("/styles.css", include_in_schema=False)
    def app_styles() -> FileResponse:
        return FileResponse(web_dir / "styles.css", media_type="text/css")

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "version": __version__,
            "llm_backend": service.models.name,
            "offline": service.permissions.is_offline(),
        }

    @app.get("/api/dashboard")
    def dashboard() -> dict[str, Any]:
        return service.dashboard().model_dump()

    @app.get("/api/cards")
    def cards(limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)) -> list[dict[str, Any]]:
        return service.database.list_cards(limit=limit, offset=offset)

    @app.get("/api/cards/{card_id}")
    def card(card_id: str) -> dict[str, Any]:
        value = service.database.get_card(card_id)
        if value is None:
            raise HTTPException(status_code=404, detail="Strategy card not found")
        return value

    @app.get("/api/sources")
    def sources(limit: int = Query(100, ge=1, le=500)) -> list[dict[str, Any]]:
        return service.database.list_sources(limit)

    @app.get("/api/jobs")
    def jobs(limit: int = Query(50, ge=1, le=500)) -> list[dict[str, Any]]:
        return service.database.list_jobs(limit)

    @app.get("/api/notifications")
    def notifications(limit: int = Query(50, ge=1, le=500)) -> list[dict[str, Any]]:
        return service.database.list_notifications(limit)

    @app.get("/api/audit")
    def audit(limit: int = Query(100, ge=1, le=500)) -> list[dict[str, Any]]:
        return service.database.list_audit_events(limit)

    @app.get("/api/tools")
    def tools() -> list[dict[str, str]]:
        return service.agent.tools.descriptions()

    @app.post("/api/demo/seed")
    def seed_demo() -> dict[str, Any]:
        try:
            return service.seed_demo().model_dump()
        except Exception as exc:
            _raise_api_error(exc)

    @app.post("/api/discover/github")
    def discover_github(payload: GitHubDiscoveryRequest) -> dict[str, Any]:
        try:
            return service.discover_github(payload.query, payload.limit).model_dump()
        except Exception as exc:
            _raise_api_error(exc)

    @app.post("/api/ingest/rss")
    def ingest_rss(payload: RSSIngestionRequest) -> dict[str, Any]:
        try:
            return service.ingest_rss(str(payload.url)).model_dump()
        except Exception as exc:
            _raise_api_error(exc)

    @app.post("/api/chat")
    def chat(payload: ChatRequest) -> dict[str, Any]:
        try:
            return service.ask(payload.question, payload.session_id).model_dump()
        except Exception as exc:
            _raise_api_error(exc)

    @app.get("/api/watch-rules")
    def watch_rules() -> list[dict[str, Any]]:
        return service.database.list_watch_rules()

    @app.post("/api/watch-rules")
    def create_watch_rule(payload: WatchRuleRequest) -> dict[str, Any]:
        try:
            return service.create_watch_rule(
                payload.name, payload.kind, payload.config, payload.interval_minutes
            )
        except Exception as exc:
            _raise_api_error(exc)

    @app.post("/api/watch-rules/{rule_id}/run")
    def run_watch_rule(rule_id: str) -> dict[str, Any]:
        rule = service.database.get_watch_rule(rule_id)
        if rule is None:
            raise HTTPException(status_code=404, detail="Watch rule not found")
        try:
            return service.run_watch_rule(rule).model_dump()
        except Exception as exc:
            _raise_api_error(exc)

    @app.get("/api/permissions")
    def permissions() -> dict[str, Any]:
        return {
            "offline": service.permissions.is_offline(),
            "allowed_domains": service.permissions.allowed_domains(),
        }

    @app.post("/api/permissions/offline")
    def set_offline(payload: OfflineModeRequest) -> dict[str, Any]:
        service.permissions.set_offline(payload.enabled)
        return permissions()

    @app.post("/api/permissions/domains")
    def grant_domain(payload: DomainGrantRequest) -> dict[str, Any]:
        service.permissions.grant_domain(payload.domain)
        return permissions()

    @app.get("/api/memory")
    def memory() -> dict[str, Any]:
        return {
            "preferences": service.database.preferences(),
            "conversations": service.database.list_conversations(),
        }

    @app.delete("/api/memory/sessions/{session_id}")
    def delete_session(session_id: str) -> dict[str, bool]:
        deleted = service.database.delete_conversation(session_id)
        service.database.audit("conversation_deleted", {"session_id": session_id, "deleted": deleted})
        return {"deleted": deleted}

    @app.delete("/api/memory/preferences/{key}")
    def delete_preference(key: str) -> dict[str, bool]:
        deleted = service.database.delete_preference(key)
        service.database.audit("preference_deleted", {"key": key, "deleted": deleted})
        return {"deleted": deleted}

    return app


app = create_app()
