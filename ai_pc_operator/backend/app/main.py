"""FastAPI main application for AI PC Operator.

This is the entry point for the local PC agent server.
It receives commands from the mobile remote, processes them through
the agent brain, and executes tools with proper approval flow.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, HTTPException, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional

from app.db.database import init_db, db_session, close_db
from app.agent.router import AgentRouter
from app.security.pairing import PairingManager
from app.security.pairing_v2 import PairingManagerV2
from app.approvals.manager import ApprovalManager
from app.tools.system_tools import SystemTools
from app.tools.file_tools import FileTools
from app.tools.browser_tools import BrowserTools
from app.tools.auth_tools import AuthTools
from app.tools.screen_tools import ScreenTools
from app.logs.redactor import LogRedactor

# Paths
ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = ROOT / "ai_pc_operator" / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


class RedactingFilter(logging.Filter):
    """Redact secrets before records reach file/console handlers."""

    def __init__(self) -> None:
        super().__init__()
        self.redactor = LogRedactor()

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self.redactor.redact(str(record.msg))
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    key: self.redactor.redact(value) if isinstance(value, str) else value
                    for key, value in record.args.items()
                }
            else:
                record.args = tuple(
                    self.redactor.redact(arg) if isinstance(arg, str) else arg
                    for arg in record.args
                )
        return True

# Setup logging with redaction
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(DATA_DIR / "agent.log"),
        logging.StreamHandler(),
    ],
)
for handler in logging.getLogger().handlers:
    handler.addFilter(RedactingFilter())
logger = logging.getLogger("ai_pc_operator")

# Global state
agent_router: Optional[AgentRouter] = None
pairing_manager: Optional[PairingManager] = None
pairing_manager_v2: Optional[PairingManagerV2] = None
approval_manager: Optional[ApprovalManager] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    global agent_router, pairing_manager, pairing_manager_v2, approval_manager

    logger.info("Starting AI PC Operator...")

    # Initialize database
    await init_db()

    # Initialize managers
    pairing_manager = PairingManager()
    pairing_manager_v2 = PairingManagerV2()
    approval_manager = ApprovalManager()

    # Initialize agent router
    agent_router = AgentRouter(
        approval_manager=approval_manager,
        system_tools=SystemTools(),
        file_tools=FileTools(),
        browser_tools=BrowserTools(),
        auth_tools=AuthTools(),
        screen_tools=ScreenTools(),
    )

    logger.info("AI PC Operator started successfully")

    # Seed MVP skill pack on first boot
    try:
        seeded = await agent_router.ensure_skills_seeded()
        if seeded:
            logger.info("Seeded %d MVP skills", seeded)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Skill seeding failed: %s", exc)

    yield

    logger.info("Shutting down AI PC Operator...")
    if agent_router:
        await agent_router.shutdown()
    await close_db()


# Create FastAPI app
app = FastAPI(
    title="AI PC Operator",
    description="Local AI PC Operator with mobile approval",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS for mobile web remote
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Pydantic models
class CommandRequest(BaseModel):
    """Command request from mobile remote."""
    text: str
    device_id: Optional[str] = None


class PlanPreviewRequest(BaseModel):
    """Plan-preview request from mobile remote."""
    text: str
    device_id: Optional[str] = None


class CommandResponse(BaseModel):
    """Command response to mobile remote."""
    command_id: int
    status: str
    result: Optional[str] = None
    requires_approval: bool = False
    approval_id: Optional[int] = None


class ApprovalRequest(BaseModel):
    """Approval request from mobile."""
    approval_id: int
    approved: bool
    master_key: Optional[str] = None  # For vault unlock


class PairingRequest(BaseModel):
    """Pairing code from mobile."""
    code: str
    device_name: str


class QRPairingCompleteRequest(BaseModel):
    """Complete QR pairing after phone scans code."""
    pairing_id: str
    device_public_key: str
    device_name: str
    trust_device: bool = False


class TrustedRePairRequest(BaseModel):
    """Auto re-pair a trusted device."""
    device_id: str
    device_public_key: str


class TokenRotateRequest(BaseModel):
    """Rotate session token."""
    device_id: str
    old_token: str


class BiometricChallengeRequest(BaseModel):
    """Request a biometric challenge."""
    device_id: str


class BiometricVerifyRequest(BaseModel):
    """Verify a biometric challenge response."""
    challenge_id: str
    response: str


# ============================================================
# New spec models (ag.md §3-§7)
# ============================================================


class SkillExecuteRequest(BaseModel):
    """Execute a registered skill by id."""
    skill_id: str
    inputs: dict = {}
    command_id: Optional[int] = None


class TaskNodeSpec(BaseModel):
    """A single node in a task graph."""
    id: Optional[str] = None
    node_type: str = "act"  # observe | decide | act | verify | rollback | ask_user | summarize
    skill_id: Optional[str] = None
    depends_on: list = []
    inputs: dict = {}


class TaskRunRequest(BaseModel):
    """Create and run a task graph."""
    name: str
    nodes: list  # list[TaskNodeSpec]
    command_id: Optional[int] = None


class MemoryRememberRequest(BaseModel):
    """Save a memory entry."""
    kind: str
    key: str
    value: str
    confidence: float = 1.0
    source: str = "user"


class WorkflowTemplateRequest(BaseModel):
    """Save a workflow template."""
    template_id: str
    name: str
    plan: list
    description: str = ""
    trigger_text: str = ""


# REST API endpoints
def bearer_token(authorization: Optional[str]) -> str:
    """Extract a Bearer token from an Authorization header."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    return authorization.split(" ", 1)[1].strip()


async def require_device_auth(
    device_id: Optional[str],
    authorization: Optional[str],
) -> None:
    """Verify a paired mobile device against its token."""
    if not device_id:
        raise HTTPException(status_code=401, detail="Missing device id")
    if not pairing_manager:
        raise HTTPException(status_code=503, detail="Server not ready")
    token = bearer_token(authorization)
    if not await pairing_manager.verify_device(device_id, token):
        raise HTTPException(status_code=401, detail="Device not paired")


@app.get("/")
async def root():
    """Root endpoint - serves mobile web remote."""
    return {
        "name": "AI PC Operator",
        "version": "0.1.0",
        "status": "running",
        "pc_pairing_page": "/remote/pair.html",
        "mobile_remote": "/remote/index.html",
        "pairing_code_api": "/pair/code",
        "pairing_qr_api": "/pair/qr",
    }


@app.get("/status")
async def status():
    """System status endpoint."""
    system_tools = SystemTools()
    return await system_tools.get_status()


@app.get("/runtime")
async def runtime_status():
    """Runtime budget, lazy model status, telemetry, and strategy data."""
    if not agent_router:
        raise HTTPException(status_code=503, detail="Server not ready")

    budget = agent_router.resource_budget.measure()
    ssd_plan = agent_router.ssd_tier.plan(
        budget,
        agent_router.artifacts,
        agent_router.resource_budget.reserve_mb,
    )
    return {
        "memory": {
            "available_mb": budget.available_mb,
            "model_budget_mb": budget.model_budget_mb,
            "mode": budget.mode,
            "allow_ocr": budget.allow_ocr,
            "allow_detector": budget.allow_detector,
            "allow_llm": budget.allow_llm,
        },
        "models": agent_router.model_registry.status(),
        "model_insights": agent_router.model_insights.summary(),
        "ssd_tier": ssd_plan.to_dict(),
        "ssd_usage": agent_router.ssd_tier.status(),
        "artifacts": agent_router.artifacts.inventory(),
        "screen_cache": agent_router.screen_cache.stats(),
        "telemetry": agent_router.telemetry.get_live_dashboard(),
        "strategy": agent_router.strategy.status(),
        "native_core": {
            "available": _check_native_core(),
        },
    }


def _check_native_core() -> bool:
    """Check if the native C core is available."""
    try:
        from app.runtime.native_bridge import C_AVAILABLE
        return C_AVAILABLE
    except Exception:
        return False


@app.post("/pair")
async def pair(request: PairingRequest):
    """Pair a new device with pairing code."""
    if not pairing_manager:
        raise HTTPException(status_code=503, detail="Server not ready")

    device = await pairing_manager.pair_device(
        code=request.code,
        device_name=request.device_name,
    )

    if not device:
        raise HTTPException(status_code=401, detail="Invalid pairing code")

    return {
        "device_id": device["id"],
        "token": device["token"],
        "paired_at": device["paired_at"],
    }


@app.get("/pair/code")
async def get_pairing_code():
    """Get current pairing code (shown on PC)."""
    if not pairing_manager:
        raise HTTPException(status_code=503, detail="Server not ready")

    code = await pairing_manager.generate_code()
    return {"code": code, "expires_in": 300}  # 5 minutes


# ============================================================
# Enhanced Pairing Endpoints (QR + Trust + Rotation + Biometric)
# These are additive - the 6-digit code flow still works.
# ============================================================

@app.get("/pair/qr")
async def create_qr_pairing():
    """Create a new QR code pairing session.

    Returns QR data that the phone can scan for instant pairing
    (no typing required). Falls back to 6-digit code if QR not used.
    """
    if not pairing_manager_v2:
        raise HTTPException(status_code=503, detail="Server not ready")

    pairing = await pairing_manager_v2.create_qr_pairing()
    return pairing


@app.post("/pair/qr/complete")
async def complete_qr_pairing(request: QRPairingCompleteRequest):
    """Complete QR pairing after phone scans the code.

    Phone sends its X25519 public key. PC derives shared secret,
    encrypts the session token, and returns it.
    """
    if not pairing_manager_v2:
        raise HTTPException(status_code=503, detail="Server not ready")

    result = await pairing_manager_v2.complete_qr_pairing(
        pairing_id=request.pairing_id,
        device_public_key=request.device_public_key,
        device_name=request.device_name,
        trust_device=request.trust_device,
    )

    if not result:
        raise HTTPException(status_code=401, detail="Invalid or expired pairing")

    return result


@app.post("/pair/trust")
async def trust_device(device_id: str, days: int = 30):
    """Mark a device as trusted for N days.

    Trusted devices can re-pair automatically without entering a code.
    """
    if not pairing_manager_v2:
        raise HTTPException(status_code=503, detail="Server not ready")

    success = await pairing_manager_v2.trust_device(device_id, days)
    return {"trusted": success, "trust_days": days}


@app.post("/pair/trusted")
async def auto_repair_trusted(request: TrustedRePairRequest):
    """Auto re-pair a trusted device without code entry.

    Phone sends its device_id and public_key. If device is trusted,
    PC issues a new encrypted session token.
    """
    if not pairing_manager_v2:
        raise HTTPException(status_code=503, detail="Server not ready")

    result = await pairing_manager_v2.auto_repair_trusted(
        device_id=request.device_id,
        device_public_key=request.device_public_key,
    )

    if not result:
        raise HTTPException(status_code=401, detail="Device not trusted")

    return result


@app.post("/auth/rotate")
async def rotate_token(request: TokenRotateRequest):
    """Rotate a device's session token.

    Issues a new token and invalidates the old one.
    Should be called periodically (every 24h) or on suspicious activity.
    """
    if not pairing_manager_v2:
        raise HTTPException(status_code=503, detail="Server not ready")

    new_token = await pairing_manager_v2.rotate_token(
        device_id=request.device_id,
        old_token=request.old_token,
    )

    if not new_token:
        raise HTTPException(status_code=401, detail="Invalid old token")

    return {"rotated": True, "new_token": new_token}


@app.post("/auth/biometric/challenge")
async def create_biometric_challenge(request: BiometricChallengeRequest):
    """Create a biometric challenge for sensitive operations.

    Used for vault unlock, not initial pairing.
    Phone or PC must complete the challenge (Windows Hello,
    Touch ID, Face ID) before the operation proceeds.
    """
    if not pairing_manager_v2:
        raise HTTPException(status_code=503, detail="Server not ready")

    challenge = await pairing_manager_v2.create_biometric_challenge(
        device_id=request.device_id,
    )
    return challenge


@app.post("/auth/biometric/verify")
async def verify_biometric_challenge(request: BiometricVerifyRequest):
    """Verify a biometric challenge response."""
    if not pairing_manager_v2:
        raise HTTPException(status_code=503, detail="Server not ready")

    verified = await pairing_manager_v2.verify_biometric_challenge(
        challenge_id=request.challenge_id,
        response=request.response,
    )

    if not verified:
        raise HTTPException(status_code=401, detail="Invalid or expired challenge")

    return {"verified": True}


@app.post("/command")
async def execute_command(
    request: CommandRequest,
    authorization: Optional[str] = Header(default=None),
):
    """Execute a command from mobile remote."""
    if not agent_router:
        raise HTTPException(status_code=503, detail="Server not ready")

    # Verify device if provided
    if request.device_id:
        await require_device_auth(request.device_id, authorization)

    # Route command through agent
    result = await agent_router.process_command(
        text=request.text,
        device_id=request.device_id,
    )

    return result


@app.post("/command/preview")
async def preview_command_plan(
    request: PlanPreviewRequest,
    authorization: Optional[str] = Header(default=None),
):
    """Preview how a phone text instruction will be interpreted."""
    if not agent_router:
        raise HTTPException(status_code=503, detail="Server not ready")

    if request.device_id:
        await require_device_auth(request.device_id, authorization)

    return await agent_router.preview_plan(request.text)


@app.get("/approvals/pending")
async def get_pending_approvals(
    device_id: Optional[str] = None,
    authorization: Optional[str] = Header(default=None),
):
    """Get pending approval requests."""
    if not approval_manager:
        raise HTTPException(status_code=503, detail="Server not ready")
    await require_device_auth(device_id, authorization)

    approvals = await approval_manager.get_pending(device_id)
    return {"approvals": approvals}


@app.post("/approvals/resolve")
async def resolve_approval(
    request: ApprovalRequest,
    authorization: Optional[str] = Header(default=None),
    device_id: Optional[str] = Query(default=None),
):
    """Resolve an approval request."""
    if not approval_manager:
        raise HTTPException(status_code=503, detail="Server not ready")
    await require_device_auth(device_id, authorization)

    success = await approval_manager.resolve(
        approval_id=request.approval_id,
        approved=request.approved,
        master_key=request.master_key,
    )

    if not success:
        raise HTTPException(status_code=404, detail="Approval not found")

    return {"status": "resolved"}


@app.post("/emergency/stop")
async def emergency_stop(
    device_id: Optional[str] = Query(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """Emergency stop - halt all operations."""
    logger.warning("EMERGENCY STOP triggered!")
    await require_device_auth(device_id, authorization)

    if agent_router:
        await agent_router.emergency_stop()

    if approval_manager:
        await approval_manager.cancel_all_pending()

    return {"status": "stopped"}


@app.get("/history")
async def get_history(
    limit: int = 50,
    device_id: Optional[str] = None,
    authorization: Optional[str] = Header(default=None),
):
    """Get command history."""
    await require_device_auth(device_id, authorization)
    safe_limit = min(max(limit, 1), 200)
    async with db_session() as db:
        cursor = await db.execute(
            """
            SELECT id, source, device_id, input_text, intent, risk_level,
                   status, substr(result, 1, 1000) AS result, error,
                   created_at, completed_at
            FROM commands
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (safe_limit,),
        )
        rows = await cursor.fetchall()
    return {"history": [dict(row) for row in rows]}


# ============================================================
# New spec endpoints: skills, tasks, memory, templates
# ============================================================


@app.get("/skills")
async def list_skills(
    domain: Optional[str] = None,
    query: Optional[str] = None,
    device_id: Optional[str] = None,
    authorization: Optional[str] = Header(default=None),
):
    """List registered skills, optionally filtered by domain or search query."""
    if not agent_router:
        raise HTTPException(status_code=503, detail="Server not ready")
    await require_device_auth(device_id, authorization)
    skills = await agent_router.list_skills(domain=domain, query=query)
    return {"skills": skills, "count": len(skills)}


@app.post("/skills/execute")
async def execute_skill(
    request: SkillExecuteRequest,
    device_id: Optional[str] = None,
    authorization: Optional[str] = Header(default=None),
):
    """Execute a registered skill by id."""
    if not agent_router:
        raise HTTPException(status_code=503, detail="Server not ready")
    await require_device_auth(device_id, authorization)
    result = await agent_router.execute_skill(
        request.skill_id,
        request.inputs,
        command_id=request.command_id,
    )
    return result


@app.get("/skills/{skill_id}/metrics")
async def get_skill_metrics(
    skill_id: str,
    device_id: Optional[str] = None,
    authorization: Optional[str] = Header(default=None),
):
    """Return aggregate metrics for a skill."""
    if not agent_router:
        raise HTTPException(status_code=503, detail="Server not ready")
    await require_device_auth(device_id, authorization)
    return await agent_router.skill_metrics(skill_id)


@app.post("/tasks")
async def run_task(
    request: TaskRunRequest,
    device_id: Optional[str] = None,
    authorization: Optional[str] = Header(default=None),
):
    """Create and run a task graph (DAG)."""
    if not agent_router:
        raise HTTPException(status_code=503, detail="Server not ready")
    await require_device_auth(device_id, authorization)
    return await agent_router.run_task(
        request.name,
        request.nodes,
        command_id=request.command_id,
    )


@app.get("/tasks/{task_id}")
async def get_task(
    task_id: str,
    device_id: Optional[str] = None,
    authorization: Optional[str] = Header(default=None),
):
    """Return a task and its trace events."""
    if not agent_router:
        raise HTTPException(status_code=503, detail="Server not ready")
    await require_device_auth(device_id, authorization)
    task = await agent_router.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@app.post("/tasks/{task_id}/cancel")
async def cancel_task(
    task_id: str,
    device_id: Optional[str] = None,
    authorization: Optional[str] = Header(default=None),
):
    """Cancel a running task."""
    if not agent_router:
        raise HTTPException(status_code=503, detail="Server not ready")
    await require_device_auth(device_id, authorization)
    ok = await agent_router.cancel_task(task_id)
    if not ok:
        raise HTTPException(status_code=409, detail="Task cannot be cancelled")
    return {"cancelled": True}


@app.post("/memory/remember")
async def remember(
    request: MemoryRememberRequest,
    device_id: Optional[str] = None,
    authorization: Optional[str] = Header(default=None),
):
    """Save a memory entry."""
    if not agent_router:
        raise HTTPException(status_code=503, detail="Server not ready")
    await require_device_auth(device_id, authorization)
    await agent_router.remember(
        request.kind, request.key, request.value,
        request.confidence, request.source,
    )
    return {"saved": True}


@app.get("/memory/recall")
async def recall(
    kind: str,
    key: str,
    device_id: Optional[str] = None,
    authorization: Optional[str] = Header(default=None),
):
    """Recall a memory entry by kind+key."""
    if not agent_router:
        raise HTTPException(status_code=503, detail="Server not ready")
    await require_device_auth(device_id, authorization)
    entry = await agent_router.recall(kind, key)
    if entry is None:
        raise HTTPException(status_code=404, detail="Not found")
    return entry


@app.get("/memory/search")
async def search_memory(
    query: str,
    kind: Optional[str] = None,
    limit: int = 20,
    device_id: Optional[str] = None,
    authorization: Optional[str] = Header(default=None),
):
    """Search memory entries."""
    if not agent_router:
        raise HTTPException(status_code=503, detail="Server not ready")
    await require_device_auth(device_id, authorization)
    return {
        "results": await agent_router.search_memory(query, kind=kind, limit=limit),
    }


@app.post("/workflows")
async def save_workflow(
    request: WorkflowTemplateRequest,
    device_id: Optional[str] = None,
    authorization: Optional[str] = Header(default=None),
):
    """Save a workflow template."""
    if not agent_router:
        raise HTTPException(status_code=503, detail="Server not ready")
    await require_device_auth(device_id, authorization)
    await agent_router.save_workflow_template(
        request.template_id,
        request.name,
        request.plan,
        request.description,
        request.trigger_text,
    )
    return {"saved": True}


@app.get("/workflows")
async def list_workflows(
    device_id: Optional[str] = None,
    authorization: Optional[str] = Header(default=None),
):
    """List workflow templates."""
    if not agent_router:
        raise HTTPException(status_code=503, detail="Server not ready")
    await require_device_auth(device_id, authorization)
    return {"templates": await agent_router.list_workflow_templates()}


@app.get("/workflows/match")
async def match_workflow(
    text: str,
    device_id: Optional[str] = None,
    authorization: Optional[str] = Header(default=None),
):
    """Match a workflow template by trigger text."""
    if not agent_router:
        raise HTTPException(status_code=503, detail="Server not ready")
    await require_device_auth(device_id, authorization)
    template = await agent_router.match_workflow_template(text)
    if template is None:
        return {"matched": False}
    return {"matched": True, "template": template}


# WebSocket for real-time updates
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket for real-time communication with mobile."""
    device_id = websocket.query_params.get("device_id")
    token = websocket.query_params.get("token")
    if not device_id or not token or not pairing_manager:
        await websocket.close(code=1008)
        return
    if not await pairing_manager.verify_device(device_id, token):
        await websocket.close(code=1008)
        return

    await websocket.accept()
    logger.info("WebSocket connected")

    try:
        while True:
            # Receive command
            data = await websocket.receive_json()

            if data.get("type") == "command":
                # Process command
                result = await agent_router.process_command(
                    text=data["text"],
                    device_id=data.get("device_id"),
                )
                await websocket.send_json({
                    "type": "command_result",
                    "data": result,
                })

            elif data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})

    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        logger.info("WebSocket disconnected")


# Serve mobile web remote
FRONTEND_DIR = ROOT / "ai_pc_operator" / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/remote", StaticFiles(directory=str(FRONTEND_DIR)), name="remote")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info",
    )
