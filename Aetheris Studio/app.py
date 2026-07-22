import asyncio
import os
import subprocess
import sys
from contextlib import asynccontextmanager, suppress
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Header, Depends, Request
from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Any

from fastapi.responses import StreamingResponse
from core.utils.agent import stream_agent
from core.utils.rate_limiter import RateLimiter

import threading


async def _unload_all_models():
    """Shared by both graceful-shutdown paths (API-triggered via
    /api/shutdown, and the lifespan `finally` below for a dev-mode Ctrl+C):
    releases the resident VTE model from VRAM. (Ollama removido -- VTE é o
    único motor.)"""
    try:
        from core.utils.vte_bridge import unload as _unload_vte
        _unload_vte()
        print("[*] Modelo VTE descarregado da VRAM.")
    except Exception as e:
        print(f"[-] Erro ao descarregar modelo VTE: {e}")


@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    # Fase 4.5: the Flutter client (aetheris_ui.exe) is what users double-click,
    # and it ensures this backend is running (BackendLauncher in main.dart).
    # The old Flet GUI (main.py, controllers/, views/) has been removed.

    # VTE loads lazily on the first chat turn (or via /api/vte/warmup); the
    # manage_memory tool owns its own MarkdownMemoryManager singleton
    # (core/utils/tools.py), nothing needs wiring here for it.

    from core.health_producer import start_health_checks
    start_health_checks()

    # First-run bootstrap: AuthManager.set_credentials() has always existed
    # but nothing ever called it -- the only way an account got created was
    # a developer running it by hand once, then reusing that same password
    # forever. Generates a random account exactly once, on the run that
    # finds none configured; every later start is a no-op (is_configured
    # already true).
    from core.auth import AuthManager
    _generated = AuthManager().ensure_configured()
    if _generated:
        _username, _password = _generated
        _cred_file = Path(__file__).parent / "GENERATED_LOGIN_READ_AND_DELETE.txt"
        _cred_file.write_text(
            "Aetheris was started for the first time and generated a local login.\n"
            "Delete this file after you've noted the credentials -- they are not\n"
            "recoverable from here once removed (only the salted hash is stored).\n\n"
            f"username: {_username}\n"
            f"password: {_password}\n",
            encoding="utf-8",
        )
        print(f"[*] First run: generated local login, written to {_cred_file}")
        print(f"[*]   username: {_username}")
        print(f"[*]   password: {_password}")

    # Egress Monitor (Blackbox Fase B): a background task, not per-request --
    # this is the one lifecycle hook in this file where a long-lived task
    # actually makes sense (confirmed: no other on_event("startup")-style
    # hook exists to piggyback on). Uses the "global" session bucket since
    # egress applies to the whole process, not one chat; per-chat egress
    # framing wasn't a real distinction psutil's connection list could make
    # anyway (it doesn't know which HTTP request opened which socket).
    _egress_task = None
    from core.audit.egress_monitor import egress_enabled, run_forever as _egress_run_forever
    if egress_enabled():
        _egress_task = asyncio.create_task(_egress_run_forever())

    # Cartographer (Blackbox Fase D): same background-task shape as the
    # Egress Monitor above -- one long-lived asyncio task, cancelled
    # cleanly on shutdown. Watches whatever project is currently active
    # (core.utils.project_path), no per-project start call needed.
    _cartographer_task = None
    from core.rag.cartographer import cartographer_enabled, run_worker as _cartographer_run_worker
    if cartographer_enabled():
        _cartographer_task = asyncio.create_task(_cartographer_run_worker())

    try:
        yield
    except asyncio.CancelledError:
        pass
    finally:
        print("[*] Aetheris API shutting down — limpando recursos...")

        if _egress_task is not None:
            _egress_task.cancel()
            with suppress(asyncio.CancelledError):
                await _egress_task

        if _cartographer_task is not None:
            _cartographer_task.cancel()
            with suppress(asyncio.CancelledError):
                await _cartographer_task

        # Descarregar o modelo VTE da VRAM
        await _unload_all_models()

        # Nota: o blanket `Stop-Process -Name "python",...` que existia aqui
        # foi removido -- ele matava TODOS os processos python do sistema
        # (perigoso: podia derrubar processos não relacionados do usuário) e
        # é desnecessário agora que /api/shutdown faz `os._exit(0)` gracioso
        # e não há mais Ollama para forçar o encerramento.


import logging
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

app = FastAPI(
    title="Aetheris API",
    description="FastAPI gateway managing local ChromaDB and Qwen LLM models on AMD GPU / CPU.",
    version="1.0.0",
    lifespan=lifespan
)

# SEC GUARDRAIL-07: Token de sessão interna efêmero gerado no startup
INTERNAL_TOKEN = os.environ.get("AETHERIS_INTERNAL_TOKEN")
if not INTERNAL_TOKEN:
    env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".env"))
    if os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip().startswith("AETHERIS_INTERNAL_TOKEN="):
                        INTERNAL_TOKEN = line.strip().split("=", 1)[1].strip('"\'')
                        break
        except Exception:
            pass
            
    if not INTERNAL_TOKEN:
        import secrets
        INTERNAL_TOKEN = secrets.token_hex(32)
        try:
            with open(env_path, "a", encoding="utf-8") as f:
                f.write(f"\nAETHERIS_INTERNAL_TOKEN={INTERNAL_TOKEN}\n")
        except Exception:
            pass

async def verify_internal_token(x_internal_token: Optional[str] = Header(None)):
    """
    Valida o token X-Internal-Token recebido do frontend Flutter local.
    """
    if INTERNAL_TOKEN:
        if not x_internal_token or x_internal_token != INTERNAL_TOKEN:
            raise HTTPException(status_code=403, detail="Acesso negado: Token de sessão interna inválido ou ausente.")


# Request/Response schemas
class ChatMessage(BaseModel):
    role: str
    content: str

class ChatCompletionRequest(BaseModel):
    model: str = ""
    messages: List[ChatMessage]
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = 512
    mode: str = "builder"
    # Blackbox (Fase A): scopes the Flight Recorder audit trail to this
    # conversation. Always present in practice -- chat_provider.dart's
    # sendMessage() never fires without an activeChatId -- but stays
    # Optional so an older/unpatched caller degrades to "no audit trail
    # for this turn" instead of a validation error.
    chat_id: Optional[str] = None

@app.get("/")
async def root():
    # ROOT CAUSE of the whole "backend hangs when launched by Flutter"
    # investigation: this route called check_ollama(), a synchronous
    # requests.get(OLLAMA_URL, timeout=2) call -- and in the specific
    # context of being launched by the Flutter client, that single call
    # measured ~4s wall-clock (confirmed via asyncio.to_thread making zero
    # difference, and via file-based request/response timing logging).
    # This route is polled every 500ms by BackendLauncher._isBackendAlive,
    # so a ~4s-per-call cost compounded into what looked like a permanent
    # hang under any short test timeout. Ollama is legacy here anyway --
    # VTE replaced it as the real inference engine (Fase 2) -- so the
    # right fix is removing the check entirely from this hot-polled route,
    # not chasing why contacting Ollama is slow in this specific context.
    return {
        "app": "Aetheris",
        "status": "online",
    }

class SettingsUpdateRequest(BaseModel):
    default_model: str
    # VTE's real context window (prompt + response) -- distinct from a
    # request's own max_tokens, which only bounds the response length. See
    # core/utils/vte_bridge.py's module docstring: this sizes the KV cache
    # at model-load time, so changing it needs a full vte-server restart
    # (ensure_server already detects the mismatch and does this), not
    # something a per-request field could do.
    context_length: Optional[int] = None


@app.get("/api/settings", dependencies=[Depends(verify_internal_token)])
async def get_settings():
    """Current model choice + context_length + the list of VTE models
    actually available to pick from (VTEModel.MODEL_REGISTRY -- Fase 4
    settings panel), each tagged with whether its .gguf is actually present
    in Model/ -- MODEL_REGISTRY lists every model VTE knows how to load,
    not just the ones the user has actually pulled, so picking an
    undownloaded one used to fail confusingly at load time instead of being
    caught in the picker itself."""
    from pathlib import Path
    from core.utils.settings import get_setting
    from core.utils.vte_bridge import VTE_DEFAULT_MODEL
    from vte.core.model import VTEModel, _REPO_ROOT

    def _is_downloaded(filename: str) -> bool:
        return any(p.exists() for p in (Path("Model") / filename, _REPO_ROOT / "Model" / filename))

    return {
        "default_model": get_setting("default_model", "") or VTE_DEFAULT_MODEL,
        "context_length": get_setting("context_length", 2048),
        "available_models": [
            {"name": name, "downloaded": _is_downloaded(filename)}
            for name, filename in VTEModel.MODEL_REGISTRY.items()
        ],
    }


@app.post("/api/settings", dependencies=[Depends(verify_internal_token)])
async def update_settings(request: SettingsUpdateRequest):
    """Persist the chosen default model (+ optionally context_length; Fase 4
    settings panel). Written to the same settings.json keys
    (`default_model`, `context_length`) that /v1/chat/completions/stream and
    vte_bridge.ensure_server read -- no new plumbing needed on the read
    side. This only persists the preference; it does not itself reload the
    model (see /api/vte/warmup, which the Flutter context-length picker
    calls right after this, the same way the model picker already does)."""
    from core.utils.settings import load_settings, save_settings
    from vte.core.model import VTEModel
    if request.default_model not in VTEModel.MODEL_REGISTRY:
        raise HTTPException(status_code=400, detail=f"Unknown model: {request.default_model}")
    if request.context_length is not None and request.context_length <= 0:
        raise HTTPException(status_code=400, detail="context_length must be positive")
    settings = load_settings()
    settings["default_model"] = request.default_model
    if request.context_length is not None:
        settings["context_length"] = request.context_length
    save_settings(settings)
    return {"status": "success", "default_model": request.default_model, "context_length": settings["context_length"]}


class CreateChatRequest(BaseModel):
    first_message: str = "Nova Conversa"


class RenameChatRequest(BaseModel):
    title: str


@app.get("/api/chats", dependencies=[Depends(verify_internal_token)])
async def list_chats():
    """Session CRUD over HTTP (Fase 4.5): the old Flet client ran in the
    same Python process as the backend and imported core.memory.chat_history
    directly, bypassing HTTP entirely for this. The Flutter client is a
    separate process/language and has no way to import Python -- these 5
    endpoints (list/create/messages/rename/delete) are the real gap that
    surfaced only once a genuinely separate client existed."""
    from core.memory import chat_history
    return {"chats": chat_history.list_chats()}


@app.post("/api/chats", dependencies=[Depends(verify_internal_token)])
async def create_chat(request: CreateChatRequest):
    from core.memory import chat_history
    chat_id = chat_history.create_chat(request.first_message)
    return {"chat_id": chat_id}


@app.get("/api/chats/{chat_id}/messages", dependencies=[Depends(verify_internal_token)])
async def get_chat_messages(chat_id: str):
    from core.memory import chat_history
    return {"messages": chat_history.load_chat_history(chat_id)}


class AppendMessageRequest(BaseModel):
    role: str
    content: str


@app.post("/api/chats/{chat_id}/messages", dependencies=[Depends(verify_internal_token)])
async def append_chat_message(chat_id: str, request: AppendMessageRequest):
    """Persists one message after a turn completes. Mirrors exactly what
    `chat_controller.py::send_message` did client-side (append_message calls
    at lines ~530/~659) -- persistence was never a backend responsibility of
    `stream_agent_loop`, so a separate process (Flutter) needs this to do
    the same job over HTTP."""
    from core.memory.chat_history import append_message
    from core.memory.context_compressor import count_tokens
    append_message(chat_id, request.role, request.content, count_tokens(request.content))
    return {"status": "success"}


@app.put("/api/chats/{chat_id}", dependencies=[Depends(verify_internal_token)])
async def rename_chat_endpoint(chat_id: str, request: RenameChatRequest):
    from core.memory import chat_history
    chat_history.rename_chat(chat_id, request.title)
    from core.event_bus import bus
    bus.publish("chat_renamed", {"chat_id": chat_id, "title": request.title})
    return {"status": "success"}


@app.delete("/api/chats/{chat_id}", dependencies=[Depends(verify_internal_token)])
async def delete_chat_endpoint(chat_id: str):
    from core.memory import chat_history
    chat_history.delete_chat(chat_id)
    return {"status": "success"}


_login_rate_limiter = RateLimiter(max_requests=5, window_seconds=60)


class LoginRequest(BaseModel):
    username: str
    password: str


@app.get("/api/auth/status", dependencies=[Depends(verify_internal_token)])
async def auth_status():
    from core.auth import AuthManager
    mgr = AuthManager()
    return {"configured": mgr.is_configured, "username": mgr.current_username()}


@app.post("/api/auth/login", dependencies=[Depends(verify_internal_token)])
async def auth_login(request: LoginRequest):
    """Rate-limited (Restriction #8) before this screen is exposed to a
    real user -- 5 attempts/minute, keyed per-process since this is a
    single-machine desktop app, not per-IP like a real multi-tenant server."""
    if not _login_rate_limiter.check("local"):
        raise HTTPException(status_code=429, detail="Too many login attempts. Try again in a minute.")
    from core.auth import AuthManager
    mgr = AuthManager()
    if not mgr.verify(request.username, request.password):
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    return {"status": "success", "username": request.username}


@app.get("/api/health", dependencies=[Depends(verify_internal_token)])
async def get_health():
    """
    Exposes the background health check status without causing local process blocking or locking issues.
    """
    from core.health_producer import producer
    return {
        "ollama": producer.last_ollama,
        "sqlite": producer.last_sqlite
    }


@app.get("/api/telemetry", dependencies=[Depends(verify_internal_token)])
async def get_telemetry():
    """Real GPU/model telemetry for the status-bar footer (vram, tok/s, GPU
    name, whether vte-server itself is reachable right now). A blocking
    httpx call, kept off the event loop the same way ensure_server() already
    is elsewhere in this module."""
    from core.utils.vte_bridge import get_telemetry as _get_telemetry
    return await asyncio.to_thread(_get_telemetry)


@app.get("/api/egress/status", dependencies=[Depends(verify_internal_token)])
async def get_egress_status():
    """Blackbox Egress Monitor (Fase B): the live "0 B external" indicator
    in the status footer, and what the header's connection-detail popup
    shows on click. See core/audit/egress_monitor.py's module docstring
    for why this reports connection counts rather than inventing a byte
    figure it can't reliably measure."""
    from core.audit.egress_monitor import get_status
    return get_status()

class LoadModelRequest(BaseModel):
    model: str


class ProjectPathRequest(BaseModel):
    path: str


@app.get("/api/project-path", dependencies=[Depends(verify_internal_token)])
async def get_project_path():
    from core.utils.project_path import get_active_project_path
    return {"path": get_active_project_path()}


@app.post("/api/project-path", dependencies=[Depends(verify_internal_token)])
async def set_project_path(request: ProjectPathRequest):
    from core.utils.project_path import set_active_project_path
    ok, resolved_or_reason = set_active_project_path(request.path)
    if not ok:
        raise HTTPException(status_code=400, detail=resolved_or_reason)
    return {"status": "success", "path": resolved_or_reason}


@app.get("/api/files/list", dependencies=[Depends(verify_internal_token)])
async def list_project_files(path: str = ""):
    """Lista uma pasta dentro do projeto ativo (Fase 4.5, aba "Arquivos" do
    Inspector). `path` é relativo à raiz do projeto ativo; vazio lista a
    raiz. Confinamento próprio (não usa o mesmo mecanismo de
    _active_workspace do agente, que é escopado por turno de chat, não por
    sessão de UI) -- resolve e confere que o resultado real continua DENTRO
    da raiz do projeto, rejeitando qualquer traversal."""
    from core.utils.project_path import get_active_project_path

    root = get_active_project_path()
    if not root:
        raise HTTPException(status_code=400, detail="Nenhum projeto ativo selecionado.")

    target = os.path.realpath(os.path.join(root, path)) if path else root
    root_real = os.path.realpath(root)
    if target != root_real and not target.startswith(root_real + os.sep):
        raise HTTPException(status_code=400, detail="Caminho fora do projeto ativo.")
    if not os.path.isdir(target):
        raise HTTPException(status_code=404, detail="Pasta não encontrada.")

    entries = []
    try:
        with os.scandir(target) as it:
            for entry in it:
                if entry.name.startswith("."):
                    continue
                try:
                    is_dir = entry.is_dir(follow_symlinks=False)
                    size = entry.stat(follow_symlinks=False).st_size if not is_dir else 0
                except OSError:
                    continue
                entries.append({"name": entry.name, "is_dir": is_dir, "size": size})
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))

    entries.sort(key=lambda e: (not e["is_dir"], e["name"].lower()))
    rel_path = os.path.relpath(target, root_real)
    return {"root": root_real, "path": "" if rel_path == "." else rel_path, "entries": entries}


@app.get("/api/files/search", dependencies=[Depends(verify_internal_token)])
async def search_project_files(q: str = "", limit: int = 30):
    """Autocomplete para a referência @arquivo/@pasta no chat (Fase 4.5).
    Busca recursiva por substring no nome, escopada ao projeto ativo,
    ignorando as mesmas pastas que resolve_at_reference já pula."""
    from core.utils.project_path import get_active_project_path
    from core.utils.at_reference import _SKIP_DIR_NAMES

    root = get_active_project_path()
    if not root:
        return {"results": []}
    root_real = os.path.realpath(root)

    q_lower = q.lower()
    results = []
    for current_root, dirs, files in os.walk(root_real):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in _SKIP_DIR_NAMES]
        rel_root = os.path.relpath(current_root, root_real)

        for name in sorted(dirs):
            if not q_lower or q_lower in name.lower():
                rel = name if rel_root == "." else f"{rel_root}/{name}"
                results.append({"path": rel.replace(os.sep, "/"), "is_dir": True})
                if len(results) >= limit:
                    return {"results": results}

        for name in sorted(files):
            if name.startswith("."):
                continue
            if not q_lower or q_lower in name.lower():
                rel = name if rel_root == "." else f"{rel_root}/{name}"
                results.append({"path": rel.replace(os.sep, "/"), "is_dir": False})
                if len(results) >= limit:
                    return {"results": results}

    return {"results": results}


class ResolveReferenceRequest(BaseModel):
    path: str


@app.post("/api/files/resolve-reference", dependencies=[Depends(verify_internal_token)])
async def resolve_reference(request: ResolveReferenceRequest):
    """Resolve uma referência @arquivo/@pasta do chat em conteúdo real
    (Fase 4.5) -- ver core/utils/at_reference.py."""
    from core.utils.at_reference import resolve_at_reference

    ok, content_or_reason = resolve_at_reference(request.path)
    if not ok:
        raise HTTPException(status_code=404, detail=content_or_reason)
    return {"path": request.path, "content": content_or_reason}


class ExecuteToolRequest(BaseModel):
    tool: str
    content: str
    chat_id: Optional[str] = None


@app.post("/api/tools/execute", dependencies=[Depends(verify_internal_token)])
async def execute_tool(request: ExecuteToolRequest):
    """Runs one tool from core/utils/tools.py::TOOL_REGISTRY on demand.
    Used by the Flutter client to actually perform a file-mutating tool call
    (write_file/edit_file) after the user approves it in the confirm dialog
    -- core/utils/agent.py's stream_agent pauses instead of auto-running
    those, see its `confirm_tool` SSE event.

    Blackbox (Fase A): this is the ONLY place a gated tool call actually
    executes (stream_agent's own auto-dispatch path, agent.py, never
    reaches TOOLS_REQUIRING_CONFIRMATION tools -- they always pause here
    instead). Routed through audited_tool_call so it's logged identically
    to a model-initiated, non-gated call; the approval itself is logged as
    a separate confirm_decision entry right before, since audited_tool_call
    only knows about the tool_call/tool_result pair, not the fact that a
    human just clicked Approve."""
    from core.utils.tools import TOOL_REGISTRY
    from core.auth import AuthManager
    from core.audit.flight_recorder import audited_tool_call, audit_enabled, get_recorder

    handler = TOOL_REGISTRY.get(request.tool)
    if handler is None:
        raise HTTPException(status_code=400, detail=f"Unknown tool: {request.tool}")

    owner = AuthManager().current_username()
    if audit_enabled() and request.chat_id:
        get_recorder(request.chat_id).append(
            "confirm_decision", {"tool": request.tool, "decision": "approved"}, actor=owner or "unknown",
        )
    result = await audited_tool_call(request.chat_id, request.tool, request.content, owner, handler)
    return {"tool": request.tool, "result": result}


class DeclineToolRequest(BaseModel):
    tool: str
    content: str = ""
    chat_id: Optional[str] = None


@app.post("/api/tools/decline", dependencies=[Depends(verify_internal_token)])
async def decline_tool(request: DeclineToolRequest):
    """The other half of the confirm gate: the user clicked Decline instead
    of Approve. Before this endpoint existed, a decline was 100% client-
    local (chat_screen.dart just cleared its pending-confirm state and
    appended a local "user stopped the run" message) -- nothing ever
    reached the backend, so the Flight Recorder's approval/rejection ratio
    (a real UX metric, Fase E) had no rejection side to measure at all.
    Records the decision only; nothing executes."""
    from core.audit.flight_recorder import audit_enabled, get_recorder
    from core.auth import AuthManager

    owner = AuthManager().current_username()
    if audit_enabled() and request.chat_id:
        get_recorder(request.chat_id).append(
            "confirm_decision", {"tool": request.tool, "decision": "declined"}, actor=owner or "unknown",
        )
    return {"status": "recorded"}


@app.get("/api/audit/{session_id}", dependencies=[Depends(verify_internal_token)])
async def get_audit_log(session_id: str, since_seq: int = 0):
    """Polling endpoint for the Blackbox timeline (Fase A). Live entries
    also stream as `audit_entry` SSE events during an active turn (see
    agent.py), but there is no persistent broadcast channel outside of
    one -- this is the source of truth for anything else (opening the
    panel for a past session, catching up after a reload)."""
    from core.audit.flight_recorder import get_recorder

    rec = get_recorder(session_id)
    entries = rec.read_all(since_seq=since_seq)
    return {"session_id": session_id, "entries": entries, "head_seq": rec.head_seq}


@app.get("/api/audit/{session_id}/verify", dependencies=[Depends(verify_internal_token)])
async def verify_audit_log(session_id: str):
    """Backs the Blackbox panel's "Verify integrity" button (UC-01). See
    scripts/audit_verify.py for the standalone CLI equivalent a third
    party can run without this app installed at all."""
    from core.audit.flight_recorder import verify_chain, log_path_for

    ok, errors = verify_chain(log_path_for(session_id))
    return {"session_id": session_id, "ok": ok, "errors": errors}


class TimeTravelPreviewRequest(BaseModel):
    session_id: str
    target_commit: str
    paths: List[str]


class TimeTravelRollbackRequest(BaseModel):
    session_id: str
    target_commit: str
    paths: List[str]


@app.post("/api/timetravel/preview", dependencies=[Depends(verify_internal_token)])
async def preview_rollback(request: TimeTravelPreviewRequest):
    """Read-only: what a rollback WOULD change, for the confirm dialog's
    diff preview -- see core/audit/timetravel.py::preview_rollback."""
    from core.audit.timetravel import preview_rollback as _preview
    return await _preview(request.target_commit, request.paths)


@app.post("/api/timetravel/rollback", dependencies=[Depends(verify_internal_token)])
async def rollback_snapshot(request: TimeTravelRollbackRequest):
    """The actual undo (Fase C). UI-initiated (there's no live model turn
    involved when a user browses the Blackbox timeline and clicks Undo --
    see timetravel.py's module docstring for why this is a separate
    endpoint from the model-facing rollback_action tool rather than
    reusing /api/tools/execute), but routed through the exact same
    audited_tool_call as every other execution so it's logged identically
    -- undoing is itself a gated, audited write (invariant I4)."""
    from core.utils.tools import TOOL_REGISTRY
    from core.audit.flight_recorder import audited_tool_call, audit_enabled, get_recorder
    from core.auth import AuthManager

    owner = AuthManager().current_username()
    content = "\n".join([request.target_commit, *request.paths])
    if audit_enabled():
        get_recorder(request.session_id).append(
            "confirm_decision", {"tool": "rollback_action", "decision": "approved"}, actor=owner or "unknown",
        )
    result = await audited_tool_call(
        request.session_id, "rollback_action", content, owner, TOOL_REGISTRY["rollback_action"],
    )
    return {"result": result}


@app.get("/api/timetravel/{session_id}/snapshots", dependencies=[Depends(verify_internal_token)])
async def get_snapshots(session_id: str):
    """The Blackbox Time-Travel timeline's data source."""
    from core.audit.timetravel import list_snapshots
    return {"session_id": session_id, "snapshots": await list_snapshots(session_id)}


@app.get("/api/cartographer/status", dependencies=[Depends(verify_internal_token)])
async def get_cartographer_status():
    """Backs the discreet mapping-progress badge in the title bar
    (Fase D). {mapped, total, state} for whatever project is currently
    active; {mapped: 0, total: 0, state: "idle"} if none is."""
    from core.rag.cartographer import mapping_status
    from core.utils.project_path import get_active_project_path

    project_path = get_active_project_path()
    if not project_path:
        return {"mapped": 0, "total": 0, "structural_only": 0, "state": "idle"}
    return await mapping_status(project_path)


class TerminalRunRequest(BaseModel):
    command: str


@app.post("/api/terminal/run", dependencies=[Depends(verify_internal_token)])
async def run_terminal_command(request: TerminalRunRequest):
    """Terminal embutido no app (Fase 4.5, aba "Terminal" do Inspector).
    Roda na pasta do projeto ativo -- NÃO é sandboxed (mesma característica
    já documentada para a ferramenta bash do próprio agente, ver
    GetWorkspaceTool): só confinamento de cwd, sem allowlist/blocklist de
    comando. Aceitável no mesmo modelo de confiança do resto do app (desktop
    de um usuário só, ver Restrição #10 do plano)."""
    from core.utils.project_path import get_active_project_path
    from core.utils.subprocess_streaming import run_subprocess_streaming
    from core.utils.constants import MAX_OUTPUT_CHARS

    cwd = get_active_project_path() or None
    try:
        proc = await asyncio.create_subprocess_shell(
            request.command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Falha ao iniciar comando: {e}")

    stdout, stderr, rc, timed_out = await run_subprocess_streaming(proc, timeout=120)
    output = stdout.rstrip()
    err = stderr.rstrip()
    if err:
        output = (output + "\nSTDERR: " + err).strip() if output else "STDERR: " + err
    output = output[:MAX_OUTPUT_CHARS]
    return {
        "output": output or "(sem saída)",
        "exit_code": rc if rc is not None else -1,
        "timed_out": timed_out,
        "cwd": cwd or "",
    }


@app.post("/api/vte/warmup", dependencies=[Depends(verify_internal_token)])
async def warmup_vte_model(request: LoadModelRequest):
    """Eagerly loads a VTE model into VRAM and blocks until it's resident,
    returning only then. Fase 4.5: the old Flet flow's /ollama/load gave a
    visible "carregando modelo" spinner backed by a real synchronous load;
    saving a choice via /api/settings never did that (it only persists a
    preference, VTE loads lazily on first chat turn) -- this restores the
    same visible-loading feedback for the new Flutter model picker."""
    import asyncio
    from core.utils.vte_bridge import ensure_server
    try:
        await asyncio.to_thread(ensure_server, request.model)
        return {"status": "success", "model": request.model}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/shutdown", dependencies=[Depends(verify_internal_token)])
async def shutdown_api():
    """
    Graceful shutdown triggered over HTTP (the Flutter client calls this on
    window close). Used to signal itself with os.kill(pid, CTRL_C_EVENT) to
    trigger the lifespan `finally` block -- but CTRL_C_EVENT only reaches a
    process attached to a real console, and this backend is now launched
    via pythonw.exe (Fase 4.5, no console at all) so that signal silently
    went nowhere: confirmed by testing, the process never exited and the
    VTE model stayed resident in VRAM. This does the same cleanup
    (_unload_all_models, same as the lifespan `finally`) directly, then
    exits the process itself -- works identically with or without a
    console attached.
    """
    await _unload_all_models()

    import threading

    def _exit_process():
        os._exit(0)

    # Small delay so this response actually reaches the client before the
    # process disappears.
    threading.Timer(0.3, _exit_process).start()
    return {"status": "shutting down"}

@app.post("/v1/chat/completions/stream", dependencies=[Depends(verify_internal_token)])
async def chat_completions_stream(body: ChatCompletionRequest, http_request: Request):
    """SSE stream endpoint for chat completions, driven by the native
    agent loop (core/utils/agent.py::stream_agent). VTE is the only
    inference engine; this is the sole live chat endpoint.

    http_request goes into stream_agent so it can poll
    http_request.is_disconnected() -- StreamingResponse does NOT do this on
    its own. Confirmed directly: cancelling from the Flutter side (closing
    its connection to THIS endpoint) never stopped the remote vte-server's
    own generation, because nothing here ever noticed the client was gone
    and kept fully consuming/forwarding stream_agent's output regardless,
    which kept the downstream httpx request to vte-server alive too --
    vte-server's own is_disconnected() polling only fires on ITS OWN
    connection (from this process), which stayed open the whole time."""
    try:
        from core.utils.vte_bridge import VTE_DEFAULT_MODEL
        from core.utils.settings import get_setting
        from core.auth import AuthManager
        from core.utils.reasoning_budget import suggest_max_tokens

        owner = AuthManager().current_username()
        model = get_setting("default_model") or VTE_DEFAULT_MODEL

        messages_dict = [{"role": msg.role, "content": msg.content} for msg in body.messages]
        last_user_text = next(
            (m["content"] for m in reversed(messages_dict) if m.get("role") == "user"), ""
        )
        generator = stream_agent(
            model=model,
            messages=messages_dict,
            temperature=body.temperature if body.temperature is not None else 0.3,
            max_tokens=suggest_max_tokens(last_user_text, body.max_tokens),
            owner=owner,
            mode=body.mode or "builder",
            request=http_request,
            session_id=body.chat_id,
        )
        return StreamingResponse(generator, media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    # 127.0.0.1, not 0.0.0.0 (Fase 4.5): binding all interfaces made Windows
    # treat this as a real network-facing server and show its interactive
    # "Windows Defender Firewall has blocked some features of this app"
    # prompt on every launch from an automated/non-interactive parent
    # (Process.start from the Flutter launcher, PowerShell) -- nobody there
    # to click "Allow access", so the socket accepted TCP but the firewall
    # silently dropped the actual response the first time this was tested.
    # Loopback-only never triggers that prompt, and this is a single-user
    # desktop app that never needs LAN-facing access anyway.
    uvicorn.run("app:app", host="127.0.0.1", port=8001, reload=False)
