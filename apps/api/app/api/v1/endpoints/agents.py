"""Local Agent registration + install script delivery (M27)."""
from __future__ import annotations

import os
from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from app.api.v1.endpoints.auth import get_current_user
from app.models.user import User

router = APIRouter()

_REPO_ROOT = Path(__file__).resolve().parents[6]
_INSTALLER = _REPO_ROOT / "scripts" / "install-botversex-agent.sh"
_LAB_SEATS = Path(__file__).resolve().parents[3] / "data" / "lab_seats.yaml"
_DEFAULT_API = os.environ.get("BOTVERSEX_PUBLIC_API", "https://botversex.feispace.me/api/v1")


class AgentRegisterRequest(BaseModel):
    hostname: str = Field(default="unknown")
    platform: str = Field(default="linux")
    agent_version: str | None = None


class AgentRegisterResponse(BaseModel):
    ok: bool
    message: str
    agent_id: str | None = None


@router.post("/register", response_model=AgentRegisterResponse)
async def register_agent(
    body: AgentRegisterRequest,
    user: User = Depends(get_current_user),
) -> AgentRegisterResponse:
    """Record that this user's machine installed the Local Agent."""
    agent_id = f"agent-{user.id}-{body.hostname[:32]}"
    return AgentRegisterResponse(
        ok=True,
        message="Agent registered",
        agent_id=agent_id,
    )


class LabSeatStatus(BaseModel):
    seat_id: str
    label: str
    role: str
    agent_url: str | None = None
    ok: bool | None = None
    error: str | None = None


class LabSeatsResponse(BaseModel):
    schema_version: str
    max_seats: int
    seats: list[LabSeatStatus]


def _load_lab_seats_template() -> dict:
    if not _LAB_SEATS.is_file():
        return {"schema_version": "botversex.lab_seats.v1", "max_seats": 5, "seats": []}
    return yaml.safe_load(_LAB_SEATS.read_text(encoding="utf-8")) or {}


@router.get("/lab/seats", response_model=LabSeatsResponse)
async def list_lab_seats(
    user: User = Depends(get_current_user),
) -> LabSeatsResponse:
    """Lab mode: seat template for up to 5 Local Agent workstations under one PI account."""
    template = _load_lab_seats_template()
    seats: list[LabSeatStatus] = []
    for seat in template.get("seats") or []:
        seats.append(
            LabSeatStatus(
                seat_id=str(seat.get("seat_id") or ""),
                label=str(seat.get("label") or seat.get("seat_id") or ""),
                role=str(seat.get("role") or "member"),
                agent_url=None,
                ok=None,
            )
        )
    return LabSeatsResponse(
        schema_version=str(template.get("schema_version") or "botversex.lab_seats.v1"),
        max_seats=int(template.get("max_seats") or 5),
        seats=seats,
    )


@router.get("/install.sh")
async def get_install_script(
    request: Request,
    token: str | None = Query(None, description="JWT for cloud registration"),
) -> PlainTextResponse:
    """Return the one-line curl installer with embedded API base + token."""
    if not _INSTALLER.is_file():
        raise HTTPException(status_code=404, detail="Installer script not found on server")

    base = str(request.base_url).rstrip("/")
    if base.endswith("/api/v1/agents"):
        api_base = base[: -len("/agents")]
    else:
        api_base = _DEFAULT_API

    script = _INSTALLER.read_text(encoding="utf-8")
    header = (
        f"# BotverseX installer — generated for {request.client.host if request.client else 'client'}\n"
        f"export BOTVERSEX_API='{api_base}'\n"
    )
    if token:
        header += f"export BOTVERSEX_INSTALL_TOKEN='{token}'\n"
        header += 'exec bash -s -- --token="$BOTVERSEX_INSTALL_TOKEN"\n<<<\'INSTALL_EOF\'\n'
        body = header + script + "\nINSTALL_EOF\n"
    else:
        body = header + script

    return PlainTextResponse(body, media_type="text/x-shellscript")
