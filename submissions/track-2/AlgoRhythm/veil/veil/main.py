"""FastAPI application — the single tunnelled port.

rc-tunnel publishes exactly one port, so everything ships from here: the UI,
the REST API, and the WebSocket that streams the attack live. vLLM stays bound
to loopback and is never exposed.

Startup order matters and is deliberate:
  1. egress self-test — refuse to serve if the guard is not active
  2. role passphrase bootstrap — printed once to the console
  3. vLLM health check — fail loudly now, not during the demo
"""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from veil.agents.orchestrator import Orchestrator
from veil.config import CONFIG
from veil.ingest.loader import load_document
from veil.security.audit import AuditLog
from veil.security.auth import STORE, AuthContext, AuthError, PermissionDenied, require
from veil.security.egress import egress_self_test
from veil.types import Role, Span
import veil.tools  # noqa: F401  — registers every tool

_STATIC = Path(__file__).parent / "static"
_AUDIT = AuditLog(actor="system")
_RUNS: dict[str, dict[str, Any]] = {}

# Cache the selftest result so the UI doesn't probe the network on every refresh.
_SELFTEST_CACHE: dict[str, Any] | None = None
_SELFTEST_TS: float = 0.0
_SELFTEST_TTL: float = 60.0   # seconds


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Clear persistence database tables to start with a completely clean slate
    from veil.security.persistence import PERSISTENCE
    con = PERSISTENCE._con()
    try:
        con.execute("DELETE FROM documents")
        con.execute("DELETE FROM audit_reports")
        con.commit()
    except Exception as exc:
        print(f"Error clearing persistence DB: {exc}")
    finally:
        con.close()

    result = await egress_self_test()
    print("\n" + result.as_banner())
    if not result.blocked:
        raise RuntimeError(
            "Refusing to start: the egress guard did not block an external "
            "request. VEIL's core guarantee is not holding."
        )

    creds = STORE.bootstrap()
    print("\n  VEIL role passphrases (this run only)")
    for role, phrase in creds.items():
        print(f"    {role:<9} {phrase}")

    from veil.inference.client import VLLMClient

    healthy = await VLLMClient().health()
    print(f"\n  vLLM at {CONFIG.inference.base_url}: {'UP' if healthy else 'DOWN'}")
    if not healthy:
        raise RuntimeError(
            f"vLLM model server at {CONFIG.inference.base_url} is unreachable or offline. "
            "Please start vLLM on the GPU using './run.sh serve' first."
        )

    chain = _AUDIT.verify()
    print(f"  Audit chain: {chain.detail}\n")
    _AUDIT.append("server_start", {"egress_blocked": True, "vllm_up": healthy})

    # Pre-warm the selftest cache — first UI request will be instant
    import time as _time
    global _SELFTEST_CACHE, _SELFTEST_TS
    _SELFTEST_CACHE = {
        "egress_blocked": result.blocked,
        "egress_detail": result.detail,
        "audit_chain_ok": chain.ok,
        "audit_entries": chain.entries,
        "audit_detail": chain.detail,
        "allowed_hosts": list(CONFIG.security.allowed_hosts),
    }
    _SELFTEST_TS = _time.monotonic()

    yield
    _AUDIT.append("server_stop", {})


app = FastAPI(title="VEIL", version="0.1.0", lifespan=lifespan)


def auth(x_veil_token: str | None = Header(default=None)) -> AuthContext:
    try:
        return AuthContext(STORE.resolve(x_veil_token))
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


class LoginRequest(BaseModel):
    role: str
    passphrase: str


class AuditRequest(BaseModel):
    document_id: str
    aggressiveness: str = "balanced"
    max_iterations: int | None = None
    target_risk: float = 0.15


@app.post("/api/login")
async def login(req: LoginRequest) -> dict[str, Any]:
    try:
        session = STORE.login(Role(req.role), req.passphrase)
    except (ValueError, AuthError) as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    _AUDIT.append("login", {"role": req.role}, actor=req.role)
    return {"token": session.token, "role": session.role.value, "expires_at": session.expires_at}


@app.get("/api/security/selftest")
async def selftest(ctx: AuthContext = Depends(auth)) -> dict[str, Any]:
    import time as _time
    global _SELFTEST_CACHE, _SELFTEST_TS

    now = _time.monotonic()
    if _SELFTEST_CACHE is None or (now - _SELFTEST_TS) > _SELFTEST_TTL:
        result = await egress_self_test()
        chain = _AUDIT.verify()
        _SELFTEST_CACHE = {
            "egress_blocked": result.blocked,
            "egress_detail": result.detail,
            "audit_chain_ok": chain.ok,
            "audit_entries": chain.entries,
            "audit_detail": chain.detail,
            "allowed_hosts": list(CONFIG.security.allowed_hosts),
        }
        _SELFTEST_TS = now
    else:
        # Refresh chain stats (cheap — no TCP probe) on cache hits
        chain = _AUDIT.verify()
        _SELFTEST_CACHE["audit_chain_ok"] = chain.ok
        _SELFTEST_CACHE["audit_entries"] = chain.entries
        _SELFTEST_CACHE["audit_detail"] = chain.detail

    return _SELFTEST_CACHE


@app.post("/api/documents")
async def upload(file: UploadFile, ctx: AuthContext = Depends(auth)) -> dict[str, Any]:
    require(ctx.session, "run_attack")
    
    # Secure filename handling to prevent directory traversal
    import uuid
    filename_clean = Path(file.filename or "document").name
    storage_name = f"{uuid.uuid4().hex}_{filename_clean}"
    dest = Path("uploads") / storage_name
    dest.parent.mkdir(exist_ok=True)
    dest.write_bytes(await file.read())

    doc = load_document(str(dest))
    if not doc["ok"]:
        raise HTTPException(status_code=400, detail=doc["error"])

    from veil.types import content_hash

    doc_id = content_hash(doc["text"])[:12]
    
    # Save the document state locally to the persistence DB
    from veil.security.persistence import PERSISTENCE
    PERSISTENCE.save_document(doc_id, filename_clean, str(dest), doc["text"], doc["spans"])
    
    _RUNS[doc_id] = {"doc": doc, "path": str(dest), "report": None}
    _AUDIT.append(
        "document_uploaded",
        {"document_id": doc_id, "filename": filename_clean, "chars": doc["char_count"]},
        actor=ctx.audit_actor,
    )
    return {
        "document_id": doc_id,
        "filename": filename_clean,
        "char_count": doc["char_count"],
        "word_count": doc["word_count"],
        "pages": len({s.page for s in doc["spans"] if s.page}),
    }


@app.get("/api/documents/{document_id}")
async def get_document(document_id: str, ctx: AuthContext = Depends(auth)) -> dict[str, Any]:
    from veil.security.persistence import PERSISTENCE
    
    # Load from memory registry, falling back to persistence DB
    entry = _RUNS.get(document_id)
    if not entry:
        doc = PERSISTENCE.load_document(document_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Unknown document.")
        report = PERSISTENCE.load_report(document_id)
        entry = {"doc": doc, "path": doc["path"], "report": report}
        _RUNS[document_id] = entry
    else:
        report = entry.get("report")
        if not report:
            report = PERSISTENCE.load_report(document_id)
            entry["report"] = report

    return {
        "document_id": document_id,
        "original": entry["doc"]["text"] if ctx.can("view_evidence") else None,
        "redacted": report.final_text if report else None,
        "curve": report.curve if report else [],
        "findings": ctx.project(report.iterations[-1].findings) if report and report.iterations else [],
    }


@app.get("/api/audit")
async def audit_tail(n: int = 50, ctx: AuthContext = Depends(auth)) -> dict[str, Any]:
    try:
        require(ctx.session, "view_audit")
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    chain = _AUDIT.verify()
    return {"chain_ok": chain.ok, "detail": chain.detail, "entries": _AUDIT.tail(n)}


@app.websocket("/ws/audit")
async def ws_audit(ws: WebSocket) -> None:
    """Runs the audit and narrates it. The narration is the demo."""
    await ws.accept()
    try:
        opening = json.loads(await ws.receive_text())
        ctx = AuthContext(STORE.resolve(opening.get("token")))
        require(ctx.session, "run_attack")
    except (AuthError, PermissionDenied, json.JSONDecodeError) as exc:
        await ws.send_json({"event": "error", "detail": str(exc)})
        await ws.close()
        return

    entry = _RUNS.get(opening.get("document_id", ""))
    if not entry:
        await ws.send_json({"event": "error", "detail": "Unknown document."})
        await ws.close()
        return

    async def progress(payload: dict[str, Any]) -> None:
        from fastapi.websockets import WebSocketState
        if ws.client_state == WebSocketState.DISCONNECTED:
            raise WebSocketDisconnect()
        try:
            await ws.send_json(payload)
        except (WebSocketDisconnect, RuntimeError) as exc:
            raise WebSocketDisconnect() from exc

    from veil.security.persistence import PERSISTENCE
    from veil.agents.personas import ALL_PERSONAS, BY_NAME
    
    selected_names = opening.get("personas", [])
    if selected_names:
        personas = tuple(BY_NAME[name] for name in selected_names if name in BY_NAME)
    else:
        personas = ALL_PERSONAS

    orch = Orchestrator(
        personas=personas,
        audit=AuditLog(actor=ctx.audit_actor),
        on_progress=progress
    )
    doc = entry["doc"]
    try:
        report = await orch.run(
            document_text=doc["text"],
            spans=doc["spans"],
            source_path=entry["path"],
            max_iterations=opening.get("max_iterations"),
            aggressiveness=opening.get("aggressiveness", "balanced"),
            target_risk=float(opening.get("target_risk", 0.15)),
        )
        entry["report"] = report
        
        # Save generated report output to the persistence DB
        PERSISTENCE.save_report(opening.get("document_id"), report.final_text, report)
        
        await ws.send_json(
            {
                "event": "final",
                "findings": ctx.project(report.iterations[-1].findings) if report.iterations else [],
                "redacted": report.final_text,
                **report.as_dict(),
            }
        )
    except Exception as exc:  # noqa: BLE001 - a dead socket must not take the server with it
        await ws.send_json({"event": "error", "detail": f"{type(exc).__name__}: {exc}"})
    finally:
        await ws.close()


class ChatRequest(BaseModel):
    message: str


class OverrideRequest(BaseModel):
    aggressiveness: str = "balanced"
    overrides: dict[str, str]  # finding_id -> edit_type ("suppress"|"generalize"|"pseudonymize"|"restructure"|"reject")


@app.post("/api/documents/{document_id}/chat")
async def chat(document_id: str, req: ChatRequest, ctx: AuthContext = Depends(auth)) -> dict[str, Any]:
    from veil.security.persistence import PERSISTENCE
    doc = PERSISTENCE.load_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Unknown document.")
    report = PERSISTENCE.load_report(document_id)
    if not report:
        raise HTTPException(status_code=400, detail="Document has not been audited yet.")

    projected_findings = ctx.project(report.iterations[-1].findings) if report.iterations else []

    # Format localized chat context for local inference
    system_prompt = (
        "You are VEIL-Audit-Assistant. You discuss the security state of a document with the user.\n"
        "Here is the context of the current audit:\n"
        f"- Role of user: {ctx.session.role.value}\n"
        f"- Current document text:\n{report.final_text}\n\n"
        f"- Findings:\n{json.dumps(projected_findings, indent=2)}\n\n"
        f"- Risk Curve:\n{json.dumps(report.curve, indent=2)}\n\n"
        "Rules:\n"
        "1. Only discuss information present in the provided context.\n"
        "2. Do not reveal raw re-identification reasoning or exact location spans to Redactors or Viewers.\n"
        "3. If requested to change/reject an edit or generalize instead of suppress, explain how the user can "
        "adjust settings or apply custom overrides, or explain the safety implications.\n"
        "Keep your reply concise and professional."
    )

    from veil.inference.client import VLLMClient
    client = VLLMClient()
    response, _ = await client.complete(prefix=system_prompt, suffix=req.message)

    _AUDIT.append(
        "chat_message",
        {"document_id": document_id, "message": req.message},
        actor=ctx.audit_actor,
    )
    return {"reply": response}


@app.post("/api/documents/{document_id}/override")
async def override(document_id: str, req: OverrideRequest, ctx: AuthContext = Depends(auth)) -> dict[str, Any]:
    require(ctx.session, "apply_edits")
    from veil.security.persistence import PERSISTENCE
    doc = PERSISTENCE.load_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Unknown document.")
    report = PERSISTENCE.load_report(document_id)
    if not report:
        raise HTTPException(status_code=400, detail="Document has not been audited yet.")

    # Re-run custom repair and verification wave
    orch = Orchestrator(audit=AuditLog(actor=ctx.audit_actor))
    last_iteration = report.iterations[-1]
    
    final_text, new_findings, risk_val, util_val = await orch.custom_repair_and_verify(
        document_text=doc["text"],
        spans=doc["spans"],
        findings=last_iteration.findings,
        aggressiveness=req.aggressiveness,
        overrides=req.overrides,
        source_path=doc["path"]
    )

    from veil.scoring import risk as risk_scoring
    from veil.scoring import utility as utility_scoring
    
    r_scored = risk_scoring.score(new_findings)
    u_scored = utility_scoring.score(doc["text"], final_text)
    
    new_iter_num = len(report.iterations) + 1
    report.iterations.append(
        IterationResult(
            iteration=new_iter_num,
            findings=new_findings,
            residual_risk=risk_val,
            utility_retained=util_val,
            elapsed_s=0.0
        )
    )
    report.curve.append(
        {
            "iteration": new_iter_num,
            "residual_risk": risk_val,
            "risk_band": r_scored.band,
            "utility_retained": util_val,
            "findings": len(new_findings),
            "override_applied": True,
            **u_scored.as_dict()
        }
    )
    report.final_text = final_text
    
    PERSISTENCE.save_report(document_id, final_text, report)
    
    _AUDIT.append(
        "overrides_applied",
        {"document_id": document_id, "overrides": req.overrides},
        actor=ctx.audit_actor,
    )
    
    return {
        "document_id": document_id,
        "redacted": final_text,
        "curve": report.curve,
        "findings": ctx.project(new_findings)
    }


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(_STATIC / "index.html")


@app.exception_handler(PermissionDenied)
async def _denied(_: Any, exc: PermissionDenied) -> JSONResponse:
    return JSONResponse(status_code=403, content={"detail": str(exc)})


# Serve compiled Vite assets (JS, CSS, etc.) and fall back to index.html
# for any unknown path so client-side routing works.
if (_STATIC / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=str(_STATIC / "assets")), name="assets")


@app.get("/favicon.svg")
async def favicon() -> FileResponse:
    f = _STATIC / "favicon.svg"
    if f.exists():
        return FileResponse(f, media_type="image/svg+xml")
    return FileResponse(_STATIC / "index.html")


@app.get("/{full_path:path}")
async def spa_fallback(full_path: str) -> FileResponse:  # noqa: ARG001
    """Return index.html for any path not matched by the API — lets the React
    router handle navigation without a server round-trip."""
    return FileResponse(_STATIC / "index.html")


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=CONFIG.app_port, log_level="info")


if __name__ == "__main__":
    main()
