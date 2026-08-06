"""M22 — Reachy Mini Conversation App lifecycle proxy.

BotverseX Local Agent wraps the official `pollen-robotics/reachy_mini_conversation_app`
HuggingFace Space so the cloud UI can:
  - install the app via Allan daemon `/api/apps/install` (background job)
  - spawn the app subprocess with full env control (LLM API keys, backend,
    model, head-tracker, local-vision) — keys never leave the Local Agent
    subprocess env and are never logged
  - stream status + recent log lines to the cloud UI
  - stop / restart the app cleanly

Why we don't use daemon `/api/apps/start-app` here: Allan's `start_app` calls
`asyncio.create_subprocess_exec` without an `env=` argument, so the App
subprocess inherits the daemon's env — there is no way to inject a fresh
OPENAI_API_KEY after the daemon has already booted. By spawning the App from
the Local Agent we get full env control while still using daemon's install
infrastructure (HF Space download + pip install into the SDK venv).

Reference:
- https://github.com/pollen-robotics/reachy_mini_conversation_app
- https://huggingface.co/spaces/pollen-robotics/reachy_mini_conversation_app
"""
from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any, Literal

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .reachy_proxy import (
    _daemon_url,
    _http_base_url,
    _probe_daemon_http,
    _reachy_daemon_env,
    _reachy_python,
    _reachy_sdk_path,
)

router = APIRouter(prefix="/api/reachy/conversation", tags=["reachy-conversation"])


# ---- Constants ------------------------------------------------------------

# The daemon's AppManager registers the Conversation App with this name
# (matches the entry_point name in its pyproject.toml; uses dashes, not
# underscores, to match the PyPI/console-script convention).
CONVERSATION_APP_NAME = "reachy-mini-conversation-app"
CONVERSATION_APP_HF_URL = "https://huggingface.co/spaces/pollen-robotics/reachy_mini_conversation_app"
CONVERSATION_APP_HF_ID = "pollen-robotics/reachy_mini_conversation_app"
CONVERSATION_APP_DESCRIPTION = (
    "Conversational app for Reachy Mini combining OpenAI / Gemini / HuggingFace "
    "realtime APIs, vision pipelines, and choreographed motion libraries. "
    "Official Pollen Robotics app."
)
CONVERSATION_LOG_FILE = "/tmp/botversex_reachy_conversation.log"
CONVERSATION_GRADIO_PORT = 7860  # the app binds here when --gradio is passed

BackendProvider = Literal["huggingface", "openai", "gemini"]
HeadTracker = Literal["yolo", "mediapipe"]
# M26: which backend drives the conversation.
#   - "botversex": platform-native chat (DeepSeek text + local TTS), zero Key.
#                 Does NOT start the Conversation App subprocess; uses reachy_chat.
#   - "openai_pro"/"gemini_pro": Pro realtime voice via official Conversation App.
#                 User supplies their own OpenAI/Gemini API key. Subprocess path.
# official = 官方 Conversation App 双工（默认 HF realtime，无需 OpenAI/Gemini Key）
# botversex = 旧零 Key 文字+TTS（保留 API，UI 已下线）
# openai_pro / gemini_pro = 官方 App + 对应云厂商 Key
ConversationProvider = Literal["official", "botversex", "openai_pro", "gemini_pro"]


# ---- Runtime state ---------------------------------------------------------

_conversation_process: asyncio.subprocess.Process | None = None
_conversation_state: dict[str, Any] = {
    "running": False,
    "state": "stopped",  # stopped | installing | starting | running | error
    "backend": None,
    "model": None,
    "head_tracker": None,
    "local_vision": False,
    "gradio": False,
    "no_camera": False,
    "pid": None,
    "started_at": None,
    "returncode": None,
    "error": None,
    "command": None,
    "gradio_url": None,
}
# A small ring buffer of recent log lines for status endpoint.
_log_buffer: list[str] = []
_LOG_BUFFER_MAX = 80
_state_lock = asyncio.Lock()


# ---- Helpers ---------------------------------------------------------------


def _conversation_log_path() -> Path:
    return Path(os.environ.get(
        "REACHY_CONVERSATION_LOG_FILE", CONVERSATION_LOG_FILE
    ))


def _tail_conversation_log_file(n: int = 40) -> list[str]:
    """Read the last N lines from the conversation log file."""
    path = _conversation_log_path()
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return text.splitlines()[-max(1, n) :]


def _detect_conversation_app_pid() -> int | None:
    """Best-effort: find a still-running official conversation app process."""
    import subprocess

    try:
        proc = subprocess.run(
            ["pgrep", "-f", "reachy-mini-conversation-app"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if line.isdigit():
            return int(line)
    return None


def _push_log_line(line: str) -> None:
    """Append a line to the in-memory ring buffer (best-effort, no lock)."""
    _log_buffer.append(line)
    if len(_log_buffer) > _LOG_BUFFER_MAX:
        del _log_buffer[: len(_log_buffer) - _LOG_BUFFER_MAX]


def _app_console_script() -> str | None:
    """Return the `reachy-mini-conversation-app` console script path, or None
    if the App is not installed."""
    sdk = _reachy_sdk_path()
    candidate = sdk / ".venv" / "bin" / "reachy-mini-conversation-app"
    if candidate.exists():
        return str(candidate)
    return None


def _is_app_installed() -> bool:
    """True if the conversation app entry point exists in the SDK venv."""
    return _app_console_script() is not None


async def _wait_for_install_job(job_id: str, timeout_s: float = 180.0) -> dict[str, Any]:
    """Poll the daemon `/api/apps/job-status/{job_id}` until the job completes.

    Returns the final JobInfo dict. Raises HTTPException on failure/timeout.
    """
    deadline = time.monotonic() + timeout_s
    last_info: dict[str, Any] = {}
    async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
        while time.monotonic() < deadline:
            try:
                r = await client.get(_daemon_url(f"/api/apps/job-status/{job_id}"))
                if r.status_code == 200:
                    last_info = r.json()
                    status = last_info.get("status") or last_info.get("state")
                    if status in ("done", "completed", "success"):
                        return last_info
                    if status in ("failed", "error"):
                        raise HTTPException(
                            status_code=500,
                            detail={
                                "code": "reachy_conversation_install_failed",
                                "message": "Conversation App installation failed on daemon side.",
                                "job_info": last_info,
                            },
                        )
            except httpx.RequestError:
                pass
            await asyncio.sleep(2.0)
    raise HTTPException(
        status_code=504,
        detail={
            "code": "reachy_conversation_install_timeout",
            "message": f"Timed out waiting for Conversation App install job {job_id}.",
            "last_job_info": last_info,
        },
    )


async def _ensure_app_installed() -> dict[str, Any]:
    """Install the Conversation App via the daemon if not already installed.

    Returns the daemon JobInfo on success or `{already_installed: true}` when
    the entry point is already present.
    """
    if _is_app_installed():
        return {"already_installed": True}

    # Check daemon is reachable (we need it to perform the install).
    probe = await _probe_daemon_http(timeout_s=2.0)
    if not probe.get("ok"):
        raise HTTPException(
            status_code=502,
            detail={
                "code": "reachy_daemon_unreachable",
                "message": (
                    "Cannot install Conversation App: Reachy Mini daemon is not "
                    "reachable. Start the daemon first."
                ),
            },
        )

    app_info = {
        "name": CONVERSATION_APP_NAME,
        "source_kind": "hf_space",
        "description": CONVERSATION_APP_DESCRIPTION,
        "url": CONVERSATION_APP_HF_URL,
        "extra": {
            "id": CONVERSATION_APP_HF_ID,
            "cardData": {
                "title": "Reachy Mini Conversation App",
                "short_description": "Talk with Reachy Mini!",
            },
        },
    }
    async with httpx.AsyncClient(timeout=20.0, trust_env=False) as client:
        try:
            r = await client.post(_daemon_url("/api/apps/install"), json=app_info)
        except httpx.RequestError as exc:
            raise HTTPException(
                status_code=502,
                detail={
                    "code": "reachy_daemon_unreachable",
                    "message": f"Cannot reach daemon to install Conversation App: {exc}",
                },
            ) from exc

    if r.status_code != 200:
        raise HTTPException(
            status_code=r.status_code,
            detail={
                "code": "reachy_conversation_install_request_failed",
                "message": "Daemon rejected the install request.",
                "daemon_response": r.text,
            },
        )

    job_id = r.json().get("job_id")
    if not job_id:
        raise HTTPException(
            status_code=500,
            detail={
                "code": "reachy_conversation_install_no_job_id",
                "message": "Daemon install response missing job_id.",
                "daemon_response": r.text,
            },
        )

    final = await _wait_for_install_job(job_id, timeout_s=240.0)
    if not _is_app_installed():
        raise HTTPException(
            status_code=500,
            detail={
                "code": "reachy_conversation_install_entry_point_missing",
                "message": (
                    "Daemon reported install complete but the entry point "
                    f"`{ _app_console_script() }` is not present."
                ),
                "job_info": final,
            },
        )
    return {"installed": True, "job_info": final}


def _build_subprocess_env(
    *,
    backend: BackendProvider,
    api_key: str | None,
    model: str | None,
    hf_token: str | None,
    audio_input_match: str | None = None,
    audio_input_device: str | None = None,
) -> dict[str, str]:
    """Build the env passed to the Conversation App subprocess.

    API keys are only placed in the subprocess env; they are never persisted
    and never written to logs. The status endpoint only reports which backend
    is configured, never the key.
    """
    env = _reachy_daemon_env()
    env["BACKEND_PROVIDER"] = backend

    if backend == "openai":
        if not api_key:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "reachy_conversation_missing_openai_key",
                    "message": "OpenAI backend requires an OPENAI_API_KEY.",
                },
            )
        env["OPENAI_API_KEY"] = api_key
        if model:
            env["MODEL_NAME"] = model
    elif backend == "gemini":
        if not api_key:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "reachy_conversation_missing_gemini_key",
                    "message": "Gemini backend requires a GEMINI_API_KEY.",
                },
            )
        env["GEMINI_API_KEY"] = api_key
        if model:
            env["MODEL_NAME"] = model
    else:  # huggingface
        # HF backend needs no key; HF_REALTIME_CONNECTION_MODE=deployed uses
        # the official Pollen-hosted realtime server.
        env.setdefault("HF_REALTIME_CONNECTION_MODE", "deployed")
        # Default Chinese transcription so speaking 中文 is recognized (not English garbage).
        env.setdefault("REALTIME_TRANSCRIPTION_LANGUAGE", "zh")
        # Keep TTS from being wiped by false barge-in (echo / noisy mic).
        env.setdefault("REACHY_INTERRUPT_RESPONSE", "0")
        if model:
            env["MODEL_NAME"] = model

    if hf_token:
        env["HF_TOKEN"] = hf_token

    if audio_input_device and str(audio_input_device).strip().isdigit():
        env["REACHY_AUDIO_INPUT_DEVICE"] = str(audio_input_device).strip()
    if audio_input_match and str(audio_input_match).strip():
        env["REACHY_AUDIO_INPUT_MATCH"] = str(audio_input_match).strip()

    # Make sure the App can find the daemon (it connects to localhost:8010 by
    # default, matching our managed daemon).
    env.setdefault("REACHY_MINI_DAEMON_HOST", "127.0.0.1")
    env.setdefault("REACHY_MINI_DAEMON_PORT", "8010")
    return env


def _build_subprocess_command(
    *,
    head_tracker: HeadTracker | None,
    local_vision: bool,
    gradio: bool,
    no_camera: bool,
    robot_name: str | None,
    debug: bool,
) -> list[str]:
    """Build the argv for the Conversation App subprocess."""
    console = _app_console_script()
    if console is None:
        # Should never happen because /start calls _ensure_app_installed first.
        raise HTTPException(
            status_code=409,
            detail={
                "code": "reachy_conversation_not_installed",
                "message": "Conversation App entry point not found. Install it first.",
            },
        )
    cmd: list[str] = [console]
    if head_tracker:
        cmd.extend(["--head-tracker", head_tracker])
    if local_vision:
        cmd.append("--local-vision")
    # Official app CLI uses --ui (serves http://127.0.0.1:7860/). Legacy --gradio is ignored.
    if gradio:
        cmd.append("--ui")
    if no_camera:
        cmd.append("--no-camera")
    if robot_name:
        cmd.extend(["--robot-name", robot_name])
    if debug:
        cmd.append("--debug")
    return cmd


async def _stream_logs(proc: asyncio.subprocess.Process) -> None:
    """Stream subprocess stdout + stderr to the log file + ring buffer."""
    log_path = _conversation_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(f"\n=== BotverseX Conversation App start at {time.ctime()} ===\n")
        fh.flush()

        async def drain(stream: asyncio.StreamReader, label: str) -> None:
            while True:
                line = await stream.readline()
                if not line:
                    break
                text = line.decode(errors="replace").rstrip()
                fh.write(f"[{label}] {text}\n")
                fh.flush()
                _push_log_line(f"[{label}] {text}")

        assert proc.stdout is not None
        assert proc.stderr is not None
        await asyncio.gather(drain(proc.stdout, "out"), drain(proc.stderr, "err"))


async def _watch_process(proc: asyncio.subprocess.Process) -> None:
    """Background task: stream logs then mark the process as exited."""
    global _conversation_process
    try:
        await _stream_logs(proc)
    except Exception as exc:  # noqa: BLE001
        _push_log_line(f"[watcher] log stream error: {exc!s}")
    rc = await proc.wait()
    async with _state_lock:
        # Only update if this is still the active process (a restart could
        # have already replaced it).
        if _conversation_process is proc:
            _conversation_process = None
            _conversation_state.update(
                running=False,
                state="error" if rc not in (0, None) else "stopped",
                pid=None,
                returncode=rc,
            )


# ---- API models ------------------------------------------------------------


class ConversationStartRequest(BaseModel):
    provider: ConversationProvider = Field(
        default="official",
        description=(
            "对话后端路线。"
            "official=官方 Conversation App 双工（默认，backend 可选 huggingface/openai/gemini）；"
            "botversex=旧平台文字+TTS（已下线 UI）；"
            "openai_pro/gemini_pro=官方 App + 对应 Key（兼容旧前端）。"
        ),
    )
    backend: BackendProvider = Field(
        default="huggingface",
        description="官方 App 的 realtime 后端。huggingface 零 Key；openai/gemini 需 api_key。",
    )
    api_key: str | None = Field(
        default=None,
        description="OPENAI_API_KEY 或 GEMINI_API_KEY（backend/openai_pro/gemini_pro 需要）。",
    )
    model: str | None = Field(
        default=None,
        description="可选模型名覆盖（Pro 路线）。",
    )
    hf_token: str | None = Field(
        default=None,
        description="可选 HF token（Pro 路线，gated/private assets 用）。",
    )
    head_tracker: HeadTracker | None = Field(
        default=None,
        description="Pro 路线：启动 head tracking (yolo/mediapipe)。",
    )
    local_vision: bool = Field(
        default=False,
        description="Pro 路线：用本地 SmolVLM2 vision。",
    )
    gradio: bool = Field(
        default=True,
        description="启动 Web UI（--ui）at :7860。",
    )
    no_camera: bool = Field(
        default=True,
        description="默认仅音频双工（--no-camera）。摄像头需要额外 av 依赖，非对话必需。",
    )
    robot_name: str | None = Field(
        default=None,
        description="Pro 路线：连接特定机器人（multi-robot）。",
    )
    debug: bool = Field(
        default=False,
        description="Pro 路线：verbose logging。",
    )
    auto_install: bool = Field(
        default=True,
        description="Pro 路线：Conversation App 未装时自动从 HF 安装。",
    )
    audio_input_id: str | None = Field(
        default=None,
        description="PipeWire 麦克风节点 id（wpctl Sources）。启动前设为系统默认输入。",
    )
    audio_input_match: str | None = Field(
        default=None,
        description="SoundDevice 设备名匹配串（如 MCP01 / Reachy Mini Audio），写入 REACHY_AUDIO_INPUT_MATCH。",
    )


class ConversationStatusResponse(BaseModel):
    running: bool
    state: str
    provider: ConversationProvider | None = None
    backend: BackendProvider | None = None
    model: str | None = None
    head_tracker: HeadTracker | None = None
    local_vision: bool = False
    gradio: bool = False
    no_camera: bool = False
    pid: int | None = None
    started_at: float | None = None
    returncode: int | None = None
    error: str | None = None
    command: list[str] | None = None
    gradio_url: str | None = None
    # M26: renamed from app_installed — the botversex provider doesn't need
    # the official Conversation App installed; only Pro paths do.
    realtime_backend_available: bool = True
    pro_backend_installed: bool = False
    log_tail: list[str] = Field(default_factory=list)


# ---- Routes ----------------------------------------------------------------


@router.get("/env-template")
async def conversation_env_template() -> JSONResponse:
    """Return the env-var schema supported by the Conversation App.

    M26: also exposes the provider routing (botversex vs Pro) so the frontend
    can render the right UI without hardcoding.
    """
    return JSONResponse(
        content={
            # M26: provider routing
            "providers": {
                "official": {
                    "label": "官方实时对话 (默认)",
                    "description": "Pollen Conversation App 双工语音；默认 HuggingFace realtime，无需 OpenAI/Gemini Key",
                    "requires_key": False,
                    "is_pro": False,
                },
                "botversex": {
                    "label": "平台聊天 (已下线)",
                    "description": "旧 DeepSeek 文字 + 本地 TTS（UI 已移除，仅 API 兼容）",
                    "requires_key": False,
                    "is_pro": False,
                },
                "openai_pro": {
                    "label": "OpenAI Realtime (Pro)",
                    "description": "官方 Conversation App + OpenAI Key",
                    "requires_key": True,
                    "key_env": "OPENAI_API_KEY",
                    "key_hint": "https://platform.openai.com/api-keys",
                    "is_pro": True,
                },
                "gemini_pro": {
                    "label": "Gemini Live (Pro)",
                    "description": "官方 Conversation App + Gemini Key",
                    "requires_key": True,
                    "key_env": "GEMINI_API_KEY",
                    "key_hint": "https://aistudio.google.com/apikey",
                    "is_pro": True,
                },
            },
            "default_provider": "official",
            "backends": {
                "huggingface": {
                    "label": "HuggingFace (零 Key)",
                    "requires_key": False,
                    "default_model": None,
                    "env": {"HF_REALTIME_CONNECTION_MODE": "deployed"},
                },
                "openai": {
                    "label": "OpenAI Realtime",
                    "requires_key": True,
                    "key_env": "OPENAI_API_KEY",
                    "default_model": "gpt-realtime-2",
                    "key_hint": "https://platform.openai.com/api-keys",
                },
                "gemini": {
                    "label": "Gemini Live",
                    "requires_key": True,
                    "key_env": "GEMINI_API_KEY",
                    "default_model": "gemini-3.1-flash-live-preview",
                    "key_hint": "https://aistudio.google.com/apikey",
                },
            },
            "cli_flags": {
                "ui": {"default": True, "port": CONVERSATION_GRADIO_PORT, "flag": "--ui"},
                "gradio": {"default": True, "port": CONVERSATION_GRADIO_PORT, "alias_of": "--ui"},
                "no_camera": {"default": False},
            },
            "app_info": {
                "name": CONVERSATION_APP_NAME,
                "hf_url": CONVERSATION_APP_HF_URL,
                "hf_id": CONVERSATION_APP_HF_ID,
                "description": CONVERSATION_APP_DESCRIPTION,
            },
        }
    )


@router.get("/status")
async def conversation_status() -> ConversationStatusResponse:
    async with _state_lock:
        state = dict(_conversation_state)
    pro_installed = _is_app_installed()
    provider = state.get("provider")
    if not provider and state.get("running") and state.get("backend"):
        provider = "official"
    elif not provider and state.get("running"):
        provider = "botversex"

    running = bool(state.get("running", False))
    pid = state.get("pid")
    # After API restart the in-memory handle is gone; re-detect a live app so
    # the UI can keep showing transcript + Gradio while the process survives.
    if not running:
        orphan_pid = _detect_conversation_app_pid()
        if orphan_pid is not None:
            running = True
            pid = orphan_pid
            if not provider:
                provider = "official"

    log_tail = list(_log_buffer[-40:]) or _tail_conversation_log_file(40)

    return ConversationStatusResponse(
        running=running,
        state=state.get("state", "stopped") if state.get("running") else ("running" if running else state.get("state", "stopped")),
        provider=provider,
        backend=state.get("backend"),
        model=state.get("model"),
        head_tracker=state.get("head_tracker"),
        local_vision=state.get("local_vision", False),
        gradio=state.get("gradio", False) or running,
        no_camera=state.get("no_camera", False),
        pid=pid,
        started_at=state.get("started_at"),
        returncode=state.get("returncode"),
        error=state.get("error"),
        command=state.get("command"),
        gradio_url=state.get("gradio_url") or (f"http://127.0.0.1:{CONVERSATION_GRADIO_PORT}" if running else None),
        realtime_backend_available=True,  # botversex 路线总是可用（只要 cloud API 在）
        pro_backend_installed=pro_installed,
        log_tail=log_tail,
    )


@router.post("/start")
async def conversation_start(req: ConversationStartRequest) -> JSONResponse:
    """Install (if needed) + launch the official Conversation App subprocess.

    provider='official' (default): spawn App with req.backend (huggingface = zero key).
    provider='botversex': legacy text+TTS marker only (UI removed).
    provider='openai_pro'/'gemini_pro': spawn App forced to that cloud backend.
    """
    global _conversation_process

    # --- botversex 路线：平台原生聊天，不启动 subprocess（API 兼容，UI 已下线）---
    if req.provider == "botversex":
        async with _state_lock:
            _conversation_state.update(
                running=True,
                state="running",
                backend=None,
                model=None,
                head_tracker=None,
                local_vision=False,
                gradio=False,
                no_camera=True,
                pid=None,
                started_at=time.time(),
                returncode=None,
                error=None,
                command=None,
                gradio_url=None,
                provider="botversex",
            )
        return JSONResponse(
            content={
                "ok": True,
                "provider": "botversex",
                "message": "平台原生聊天已就绪。用 POST /api/reachy/chat/send 发消息。",
                "stage": "botversex_ready",
            }
        )

    # --- 官方 App 子进程路线 ---
    if req.provider == "openai_pro":
        if req.backend == "huggingface":
            req.backend = "openai"
    elif req.provider == "gemini_pro":
        if req.backend == "huggingface":
            req.backend = "gemini"
    elif req.provider != "official":
        raise HTTPException(
            status_code=400,
            detail={
                "code": "reachy_conversation_invalid_provider",
                "message": f"Unknown provider: {req.provider}",
            },
        )

    async with _state_lock:
        if _conversation_process is not None and _conversation_process.returncode is None:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "reachy_conversation_already_running",
                    "message": "Conversation App is already running. Stop it first.",
                    "pid": _conversation_process.pid,
                },
            )

    # 0) Official duplex needs daemon audio + Reachy as PipeWire default I/O.
    audio_prep: dict[str, Any] = {"skipped": True}
    pipewire_prep: dict[str, Any] = {"skipped": True}
    volume_prep: dict[str, Any] = {"skipped": True}
    mic_prep: dict[str, Any] = {"skipped": True}
    resolved_match: str | None = (req.audio_input_match or "").strip() or None
    try:
        from .reachy_seeed_conversation import (
            _daemon_has_deactivated_audio,
            _ensure_reachy_pipewire_io,
            _list_pipewire_audio_sources,
            _restart_daemon_with_audio,
            _set_pipewire_default_source,
            _set_robot_volume,
            _sounddevice_input_match_for_source_name,
        )

        if _daemon_has_deactivated_audio():
            async with _state_lock:
                _conversation_state.update(state="starting", error=None)
            audio_prep = await _restart_daemon_with_audio()
            if not audio_prep.get("ok"):
                raise HTTPException(
                    status_code=503,
                    detail={
                        "code": "reachy_conversation_audio_required",
                        "message": (
                            "官方双工需要 daemon 开启音频，但重启带音频的 daemon 失败。"
                            "请先在机器人页「启动机器人」，或安装 gir1.2-gst-plugins-base-1.0 后重试。"
                        ),
                        "audio_prep": audio_prep,
                    },
                )
        # Route speaker to Reachy, then set daemon/ALSA volume, then re-apply
        # PipeWire boost — daemon volume/set clamps the sink back to 1.0.
        pipewire_prep = _ensure_reachy_pipewire_io()
        volume_prep = _set_robot_volume()
        pipewire_prep = _ensure_reachy_pipewire_io()  # restore 5x after volume clamp

        # Optional: user-selected microphone (PipeWire default + SoundDevice match).
        mic_prep: dict[str, Any] = {"skipped": True}
        resolved_match = (req.audio_input_match or "").strip() or None
        if req.audio_input_id:
            mic_prep = _set_pipewire_default_source(req.audio_input_id)
            if not resolved_match:
                for src in _list_pipewire_audio_sources():
                    if src["id"] == str(req.audio_input_id).strip():
                        resolved_match = _sounddevice_input_match_for_source_name(src["name"])
                        break
            mic_prep["match"] = resolved_match
        _push_log_line(f"[prep] pipewire={pipewire_prep} volume={volume_prep} mic={mic_prep}")
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        _push_log_line(f"[prep] audio check failed (continuing): {exc!s}")

    # 1) Make sure the app is installed.
    if not _is_app_installed():
        if not req.auto_install:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "reachy_conversation_not_installed",
                    "message": "Conversation App is not installed and auto_install=false.",
                    "install_url": CONVERSATION_APP_HF_URL,
                },
            )
        async with _state_lock:
            _conversation_state.update(state="installing", error=None)
        try:
            await _ensure_app_installed()
        except HTTPException:
            async with _state_lock:
                _conversation_state.update(state="error")
            raise

    # 2) Build env + command. This raises HTTPException for missing keys.
    if "resolved_match" not in locals():
        resolved_match = (req.audio_input_match or "").strip() or None
    env = _build_subprocess_env(
        backend=req.backend,
        api_key=req.api_key,
        model=req.model,
        hf_token=req.hf_token,
        audio_input_match=resolved_match,
    )
    cmd = _build_subprocess_command(
        head_tracker=req.head_tracker,
        local_vision=req.local_vision,
        gradio=req.gradio,
        no_camera=req.no_camera,
        robot_name=req.robot_name,
        debug=req.debug,
    )

    # 3) Spawn the subprocess.
    async with _state_lock:
        _conversation_state.update(
            state="starting",
            provider=req.provider,
            backend=req.backend,
            model=req.model,
            head_tracker=req.head_tracker,
            local_vision=req.local_vision,
            gradio=req.gradio,
            no_camera=req.no_camera,
            pid=None,
            started_at=time.time(),
            returncode=None,
            error=None,
            command=cmd,
            gradio_url=f"http://127.0.0.1:{CONVERSATION_GRADIO_PORT}/" if req.gradio else None,
        )
        _log_buffer.clear()

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd=str(_reachy_sdk_path()),
        )
    except Exception as exc:
        async with _state_lock:
            _conversation_state.update(
                state="error",
                error=f"Failed to spawn Conversation App: {exc!s}",
            )
        raise HTTPException(
            status_code=500,
            detail={
                "code": "reachy_conversation_spawn_failed",
                "message": f"Failed to spawn Conversation App subprocess: {exc!s}",
                "command": cmd,
            },
        ) from exc

    async with _state_lock:
        _conversation_process = proc
        _conversation_state.update(
            running=True,
            state="running",
            pid=proc.pid,
            provider=req.provider,
        )

    # Spawn a watcher task that streams logs and updates state on exit.
    asyncio.create_task(_watch_process(proc))

    return JSONResponse(
        content={
            "ok": True,
            "message": "Conversation App started.",
            "provider": req.provider,
            "pid": proc.pid,
            "command": cmd,
            "backend": req.backend,
            "gradio_url": _conversation_state.get("gradio_url"),
            "log_file": str(_conversation_log_path()),
            "audio_prep": audio_prep,
            "pipewire_prep": pipewire_prep,
            "volume_prep": volume_prep,
            "mic_prep": mic_prep,
        }
    )


@router.get("/audio-inputs")
async def conversation_audio_inputs() -> JSONResponse:
    """List available PipeWire microphones for manual selection."""
    from .reachy_seeed_conversation import _list_pipewire_audio_sources

    sources = _list_pipewire_audio_sources()
    return JSONResponse(
        content={
            "ok": True,
            "sources": sources,
            "default_id": next((s["id"] for s in sources if s.get("default")), None),
        }
    )


class AudioInputSelectRequest(BaseModel):
    id: str = Field(..., description="PipeWire source node id")


@router.post("/audio-input")
async def conversation_set_audio_input(req: AudioInputSelectRequest) -> JSONResponse:
    """Set the system default microphone (takes effect for new conversation sessions)."""
    from .reachy_seeed_conversation import (
        _list_pipewire_audio_sources,
        _set_pipewire_default_source,
        _sounddevice_input_match_for_source_name,
    )

    result = _set_pipewire_default_source(req.id)
    match = None
    name = None
    for src in _list_pipewire_audio_sources():
        if src["id"] == str(req.id).strip():
            name = src["name"]
            match = _sounddevice_input_match_for_source_name(src["name"])
            break
    return JSONResponse(
        content={
            "ok": bool(result.get("ok")),
            "id": req.id,
            "name": name,
            "match": match,
            "detail": result,
            "hint": "请停止并重新「开始对话」后生效（录音流在启动时打开）。",
        }
    )


@router.get("/audio-level")
async def conversation_audio_level(id: str | None = None, duration_ms: int = 80) -> JSONResponse:
    """Sample instantaneous loudness of a PipeWire mic (for the UI level meter)."""
    from .reachy_seeed_conversation import _sample_pipewire_audio_level

    # pw-record is blocking; keep it off the event loop.
    level = await asyncio.to_thread(_sample_pipewire_audio_level, id, duration_ms)
    return JSONResponse(content=level)


@router.post("/stop")
async def conversation_stop() -> JSONResponse:
    """Stop the running conversation (either botversex chat or Pro subprocess)."""
    global _conversation_process

    async with _state_lock:
        proc = _conversation_process
        provider = _conversation_state.get("provider")

    # botversex 路线：没有 subprocess，只清状态。
    if provider == "botversex" and proc is None:
        async with _state_lock:
            _conversation_state.update(
                running=False,
                state="stopped",
                pid=None,
                returncode=None,
                provider=None,
            )
        return JSONResponse(
            content={
                "ok": True,
                "provider": "botversex",
                "message": "平台聊天已停止。",
            }
        )

    if proc is None or proc.returncode is not None:
        # API may have restarted while the app kept running — kill by pid.
        orphan_pid = _detect_conversation_app_pid()
        if orphan_pid is not None:
            import signal

            try:
                os.kill(orphan_pid, signal.SIGTERM)
                await asyncio.sleep(0.8)
                try:
                    os.kill(orphan_pid, 0)
                    os.kill(orphan_pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            except ProcessLookupError:
                pass
            except OSError as exc:
                async with _state_lock:
                    _conversation_state.update(
                        running=False,
                        state="stopped",
                        pid=None,
                        provider=None,
                    )
                    _conversation_process = None
                return JSONResponse(
                    content={"ok": False, "message": f"无法停止对话进程 {orphan_pid}: {exc}"}
                )
        async with _state_lock:
            _conversation_state.update(
                running=False,
                state="stopped",
                pid=None,
                returncode=proc.returncode if proc else None,
                provider=None,
            )
            _conversation_process = None
        return JSONResponse(
            content={
                "ok": True,
                "message": (
                    f"已停止对话进程 (pid={orphan_pid})."
                    if orphan_pid is not None
                    else "Conversation App was not running."
                ),
            }
        )

    try:
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            proc.kill()
            await asyncio.wait_for(proc.wait(), timeout=3.0)
    except ProcessLookupError:
        pass

    async with _state_lock:
        rc = proc.returncode
        _conversation_process = None
        _conversation_state.update(
            running=False,
            state="stopped",
            pid=None,
            returncode=rc,
            provider=None,
        )

    return JSONResponse(
        content={
            "ok": True,
            "message": "Conversation App stopped.",
            "returncode": rc,
        }
    )


@router.post("/restart")
async def conversation_restart(request: Request) -> JSONResponse:
    """Restart the Conversation App with the same configuration as last start.

    The cloud UI keeps the last-submitted config in localStorage and re-posts
    it; we don't store API keys server-side.
    """
    body = await request.json()
    # Stop first (idempotent), then start with the supplied config.
    await conversation_stop()
    req = ConversationStartRequest.model_validate(body)
    return await conversation_start(req)


@router.get("/logs")
async def conversation_logs(tail: int = 80) -> JSONResponse:
    """Return the recent log lines (ring buffer + file tail)."""
    tail = max(1, min(int(tail), 400))
    in_mem = list(_log_buffer[-tail:])

    # Also pull from the log file in case the buffer was cleared.
    log_path = _conversation_log_path()
    file_lines: list[str] = []
    if log_path.exists():
        try:
            text = log_path.read_text(encoding="utf-8", errors="replace")
            file_lines = text.splitlines()[-tail:]
        except OSError:
            pass

    # Prefer the in-memory buffer (already labeled), fall back to file tail.
    out = in_mem if in_mem else file_lines
    return JSONResponse(
        content={
            "lines": out[-tail:],
            "log_file": str(log_path),
            "running": _conversation_state.get("running", False),
        }
    )


@router.get("/apps")
async def conversation_apps_catalog(request: Request) -> JSONResponse:
    """Forward to daemon `/api/apps/list-available` so the frontend App store
    can render the full HF Space catalog without a second proxy.
    """
    try:
        async with httpx.AsyncClient(timeout=8.0, trust_env=False) as client:
            r = await client.get(_daemon_url("/api/apps/list-available"))
        if r.status_code == 200:
            return JSONResponse(content=r.json())
        return JSONResponse(
            status_code=r.status_code,
            content={"detail": r.text, "code": "reachy_apps_catalog_failed"},
        )
    except httpx.RequestError as exc:
        return JSONResponse(
            status_code=502,
            content={
                "detail": {
                    "code": "reachy_daemon_unreachable",
                    "message": f"Cannot reach daemon: {exc}",
                }
            },
        )
