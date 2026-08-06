"""M26 — BotverseX 平台原生聊天 + TTS 调度（Reachy Mini 控制台 UX 重构）.

为什么需要这个模块：
- 官方 Conversation App 需要 OpenAI Realtime / Gemini Live（用户没有 key）
- 平台已经有自己的 LLM 后端（DeepSeek via `COPILOT_PROVIDER=openai_compatible`）
- 主控页要给新手一个零 Key 路线：直接打字聊天 → 机器人 TTS 朗读 → 头部 wobble

架构：
- Local Agent 代理 Cloud API `/api/v1/copilot/chat`（带用户的 JWT）
- 同时调度本地 TTS（piper/espeak-ng，可用时用，不可用降级）
- 调度机器人头部 wobble（POST `/api/reachy/move/goto` 周期性小幅度 pitch 抖动）模拟说话
- 维护对话状态机：idle → listening → thinking → speaking → idle

Pro 路线（OpenAI Realtime / Gemini Live）由 `reachy_conversation.py` 的
`provider='openai_pro'/'gemini_pro'` 处理，本模块不涉及。
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Literal

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/reachy/chat", tags=["reachy-chat"])

logger = logging.getLogger(__name__)


# ---- Constants ------------------------------------------------------------

ChatState = Literal["idle", "listening", "thinking", "speaking"]

# Cloud API base URL. Override with BOTVERSEX_CLOUD_API_URL for non-default
# deployments. Default is local dev (cloud API runs on :8000).
def _cloud_api_url() -> str:
    return os.environ.get(
        "BOTVERSEX_CLOUD_API_URL", "http://127.0.0.1:8000"
    ).rstrip("/")


# TTS binaries we try, in order of preference.
_TTS_CANDIDATES = ("piper", "espeak-ng", "espeak")

# Workspace-relative paths for piper voice models + venv binary. Override with
# PIPER_BIN / PIPER_VOICE env vars for non-default deployments.
_WORKSPACE_ROOT = Path(__file__).resolve().parents[3]  # apps/realtime/api -> apps/realtime -> apps -> workspace
_VENV_PIPER = _WORKSPACE_ROOT / "apps" / "realtime" / ".venv" / "bin" / "piper"
_PIPER_VOICES_DIR = _WORKSPACE_ROOT / "apps" / "realtime" / ".piper_voices"
_DEFAULT_ZH_VOICE = _PIPER_VOICES_DIR / "zh_CN-huayan-medium.onnx"
_DEFAULT_EN_VOICE = _PIPER_VOICES_DIR / "en_US-amy-medium.onnx"


def _find_tts_binary() -> str | None:
    """Find a usable TTS binary.

    Priority:
      1. PIPER_BIN env var (explicit override)
      2. workspace venv piper (apps/realtime/.venv/bin/piper) — installed via pip
      3. system piper / espeak-ng / espeak on PATH
    """
    env_bin = os.environ.get("PIPER_BIN", "").strip()
    if env_bin and os.path.exists(env_bin):
        return env_bin
    if _VENV_PIPER.exists():
        return str(_VENV_PIPER)
    for cand in _TTS_CANDIDATES:
        if shutil.which(cand):
            return cand
    return None


def _find_piper_voice() -> str | None:
    """Find a piper voice model (.onnx).

    Priority:
      1. PIPER_VOICE env var
      2. workspace zh_CN voice (Chinese — default for Chinese users)
      3. workspace en_US voice (English fallback)
    """
    env_voice = os.environ.get("PIPER_VOICE", "").strip()
    if env_voice and os.path.exists(env_voice):
        return env_voice
    if _DEFAULT_ZH_VOICE.exists():
        return str(_DEFAULT_ZH_VOICE)
    if _DEFAULT_EN_VOICE.exists():
        return str(_DEFAULT_EN_VOICE)
    return None


def _find_audio_player() -> str | None:
    """Find an audio playback binary for the dev machine's speakers."""
    for cand in ("aplay", "paplay", "ffplay", "play"):
        if shutil.which(cand):
            return cand
    return None


def _tts_kind(binary: str) -> str:
    """Classify the TTS binary so _speak_text picks the right strategy."""
    if binary.endswith("piper") or binary == "piper":
        # Only treat as piper if we have a voice model; otherwise downgrade.
        if _find_piper_voice():
            return "piper"
        return "piper_no_voice"
    if binary.endswith("espeak-ng") or binary == "espeak-ng":
        return "espeak-ng"
    if binary.endswith("espeak") or binary == "espeak":
        return "espeak"
    return "unknown"


# ---- Runtime state ---------------------------------------------------------

_chat_state: dict[str, Any] = {
    "state": "idle",
    "last_user_message": None,
    "last_reply": None,
    "last_actions": None,
    "started_at": None,
    # M26 fix: _find_tts_binary now also checks the workspace venv piper, so
    # tts_available is True even when piper isn't on the system PATH.
    "tts_available": _find_tts_binary() is not None,
    "tts_binary": _find_tts_binary(),
}
_state_lock = asyncio.Lock()
_speaking_task: asyncio.Task | None = None


# ---- API models ------------------------------------------------------------


class ChatSendRequest(BaseModel):
    message: str = Field(..., description="用户消息")
    history: list[dict[str, str]] = Field(
        default_factory=list,
        description="历史消息 [{role, content}, ...]，最近 10 条会被采用",
    )
    page: str = Field(
        default="/robots/reachy_mini",
        description="当前页面路径，给 Copilot 上下文",
    )
    speak: bool = Field(
        default=True,
        description="是否在 reply 后自动 TTS 朗读（默认 True，新手路线）",
    )
    wobble: bool = Field(
        default=True,
        description="是否在朗读时让机器人头部 wobble 模拟说话",
    )


class ChatSendResponse(BaseModel):
    reply: str
    actions: list[dict[str, str]] | None = None
    state: ChatState
    tts_available: bool
    tts_played: bool
    error: str | None = None


class ChatSpeakRequest(BaseModel):
    text: str = Field(..., description="要朗读的文本")
    wobble: bool = Field(default=True)


class ChatStatusResponse(BaseModel):
    state: ChatState
    last_user_message: str | None = None
    last_reply: str | None = None
    last_actions: list[dict[str, str]] | None = None
    started_at: float | None = None
    tts_available: bool
    tts_binary: str | None = None


# ---- Helpers ---------------------------------------------------------------


async def _set_state(state: ChatState, **fields: Any) -> None:
    async with _state_lock:
        _chat_state["state"] = state
        _chat_state.update(fields)
        if state in ("listening", "thinking"):
            _chat_state["started_at"] = time.time()


async def _forward_to_cloud(
    authorization: str | None,
    message: str,
    history: list[dict[str, str]],
    page: str,
) -> dict[str, Any]:
    """Call BotverseX Cloud API `/api/v1/copilot/chat` with the user's JWT."""
    url = f"{_cloud_api_url()}/api/v1/copilot/chat"
    headers = {"Content-Type": "application/json"}
    if authorization:
        headers["Authorization"] = authorization
    body = {
        "message": message,
        "page": page,
        "history": history,
        "client_diagnostics": None,
    }
    try:
        async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:
            r = await client.post(url, json=body, headers=headers)
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "botversex_cloud_unreachable",
                "message": f"无法连接 BotverseX Cloud API ({url}): {exc}",
                "hint": "确认 apps/api 已启动 (默认端口 8000)。",
            },
        ) from exc

    if r.status_code == 401:
        raise HTTPException(
            status_code=401,
            detail={
                "code": "botversex_auth_required",
                "message": "聊天需要登录。请在网页右上角登录后重试。",
            },
        )
    if r.status_code == 429:
        raise HTTPException(
            status_code=429,
            detail={
                "code": "botversex_rate_limited",
                "message": "聊天请求过于频繁，请稍后再试。",
            },
        )
    if r.status_code != 200:
        raise HTTPException(
            status_code=r.status_code,
            detail={
                "code": "botversex_chat_failed",
                "message": f"Cloud API 返回 {r.status_code}",
                "body": r.text[:500],
            },
        )

    try:
        return r.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "botversex_chat_invalid_json",
                "message": f"Cloud API 返回非 JSON: {exc}",
                "body": r.text[:500],
            },
        ) from exc


async def _speak_text(text: str, wobble: bool) -> dict[str, Any]:
    """Speak the given text via local TTS. Returns {played, error, tts_binary}.

    Strategy by binary kind:
      - piper (with voice model): write WAV via piper, play via aplay/paplay
      - espeak-ng / espeak: direct CLI speaks through default audio
      - piper_no_voice / no player: return gracefully with played=False
    """
    binary = _chat_state.get("tts_binary")
    if not binary:
        return {"played": False, "error": "no_tts_binary", "tts_binary": None}

    # Sanitize text — strip newlines / control chars, cap length.
    clean = " ".join(text.split())[:500]
    if not clean:
        return {"played": False, "error": "empty_text", "tts_binary": binary}

    kind = _tts_kind(binary)
    import tempfile, uuid
    tmp_id = uuid.uuid4().hex[:8]
    text_file = Path(tempfile.gettempdir()) / f"reachy_tts_{tmp_id}.txt"
    wav_file = Path(tempfile.gettempdir()) / f"reachy_tts_{tmp_id}.wav"

    try:
        text_file.write_text(clean, encoding="utf-8")
    except Exception as exc:
        return {"played": False, "error": f"write_text_failed: {exc}", "tts_binary": binary}

    player = _find_audio_player()
    proc: asyncio.subprocess.Process | None = None
    cleanup_files: list[Path] = [text_file]

    try:
        if kind == "piper":
            voice = _find_piper_voice()
            if not voice:
                return {"played": False, "error": "piper_voice_not_found", "tts_binary": binary}
            if not player:
                return {
                    "played": False,
                    "error": "no_audio_player",
                    "tts_binary": binary,
                    "hint": "Install alsa-utils: sudo apt install alsa-utils",
                }
            # Step 1: piper generates WAV from text file.
            piper_cmd = [binary, "-m", voice, "-c", f"{voice}.json", "-i", str(text_file), "-f", str(wav_file)]
            try:
                proc = await asyncio.create_subprocess_exec(
                    *piper_cmd,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE,
                )
                await asyncio.wait_for(proc.wait(), timeout=15.0)
            except (asyncio.TimeoutError, Exception) as exc:
                if proc and proc.returncode is None:
                    proc.kill()
                return {"played": False, "error": f"piper_failed: {exc}", "tts_binary": binary}
            cleanup_files.append(wav_file)
            # Step 2: play the WAV through the dev machine's speakers.
            player_cmd = _build_player_cmd(player, str(wav_file))
            proc = await asyncio.create_subprocess_exec(
                *player_cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )

        elif kind in ("espeak-ng", "espeak"):
            cmd = [binary, clean]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )

        else:
            return {"played": False, "error": f"unknown_tts_kind: {kind}", "tts_binary": binary}

        # Optional wobble: while TTS plays, send small pitch oscillations
        # to /api/reachy/move/goto to make the head bob.
        wobble_task: asyncio.Task | None = None
        if wobble and proc is not None:
            wobble_task = asyncio.create_task(_wobble_while_speaking(proc))

        try:
            await asyncio.wait_for(proc.wait(), timeout=20.0)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
        finally:
            if wobble_task and not wobble_task.done():
                wobble_task.cancel()

        return {"played": True, "error": None, "tts_binary": binary, "kind": kind, "voice": _find_piper_voice() if kind == "piper" else None, "player": player}

    finally:
        for f in cleanup_files:
            try:
                f.unlink(missing_ok=True)
            except Exception:
                pass


def _detect_reachy_audio_device() -> str | None:
    """Detect the Reachy Mini USB audio card (speaker + mic array) if present.

    The robot enumerates as `Pollen Robotics Reachy Mini Audio` over USB and
    shows up as an ALSA card named `Audio` (e.g. `hw:3,0`). Returns an aplay
    device string like `plughw:CARD=Audio,DEV=0` or `None` if not found.
    """
    try:
        proc = subprocess.run(
            ["aplay", "-l"], capture_output=True, text=True, timeout=2.0
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    for line in proc.stdout.splitlines():
        if "Reachy Mini Audio" in line or line.startswith("card ") and "Audio [Reachy Mini Audio]" in line:
            # e.g. "card 3: Audio [Reachy Mini Audio], device 0: USB Audio [USB Audio]"
            m = re.match(r"card\s+(\d+):\s+Audio\s+\[Reachy Mini Audio\]", line)
            if m:
                return f"plughw:CARD=Audio,DEV=0"
    return None


_REACHY_AUDIO_DEVICE: str | None | bool | None = None  # cached; False = checked, none found


def _build_player_cmd(player: str, wav_path: str) -> list[str]:
    """Build a play-command for the given player binary.

    When the Reachy Mini USB audio card is detected, aplay is pointed at the
    robot's built-in 5W speaker instead of the host's default output. This
    makes the robot itself "talk" — matching how other open-source projects
    (reachy_mini_conversation_app, phola/reachy-brain) use the on-robot audio.
    """
    global _REACHY_AUDIO_DEVICE
    if _REACHY_AUDIO_DEVICE is None:
        _REACHY_AUDIO_DEVICE = _detect_reachy_audio_device() or False

    if player.endswith("aplay"):
        device = _REACHY_AUDIO_DEVICE if _REACHY_AUDIO_DEVICE else None
        if device:
            return [player, "-q", "-D", device, wav_path]
        return [player, "-q", wav_path]
    if player.endswith("paplay"):
        return [player, wav_path]
    if player.endswith("ffplay"):
        return [player, "-nodisp", "-autoexit", "-loglevel", "quiet", wav_path]
    if player.endswith("play"):
        return [player, "-q", wav_path]
    return [player, wav_path]


async def _wobble_while_speaking(proc: asyncio.subprocess.Process) -> None:
    """Send small pitch oscillations to make the head bob while TTS plays.

    Sends a goto every 200ms with pitch alternating ±0.08 rad. Stops when the
    TTS subprocess exits or this task is cancelled.
    """
    daemon_host = os.environ.get("REACHY_MINI_HOST", "127.0.0.1")
    daemon_port = int(os.environ.get("REACHY_MINI_PORT", "8010"))
    url = f"http://{daemon_host}:{daemon_port}/api/move/goto"
    amplitudes = [0.08, -0.06, 0.07, -0.05]
    i = 0
    async with httpx.AsyncClient(timeout=2.0, trust_env=False) as client:
        while proc.returncode is None:
            pitch = amplitudes[i % len(amplitudes)]
            i += 1
            try:
                await client.post(
                    url,
                    json={
                        "pitch": pitch,
                        "yaw": 0.0,
                        "roll": 0.0,
                        "duration": 0.25,
                    },
                )
            except httpx.RequestError:
                # Daemon may be unreachable; just stop wobbling silently.
                return
            try:
                await asyncio.sleep(0.2)
            except asyncio.CancelledError:
                return


# ---- Routes ----------------------------------------------------------------


@router.get("/status")
async def chat_status() -> ChatStatusResponse:
    async with _state_lock:
        s = dict(_chat_state)
    return ChatStatusResponse(
        state=s.get("state", "idle"),
        last_user_message=s.get("last_user_message"),
        last_reply=s.get("last_reply"),
        last_actions=s.get("last_actions"),
        started_at=s.get("started_at"),
        tts_available=bool(s.get("tts_available")),
        tts_binary=s.get("tts_binary"),
    )


@router.post("/send")
async def chat_send(req: ChatSendRequest, request: Request) -> JSONResponse:
    """Send a message to the BotverseX Copilot and (optionally) TTS the reply.

    Forwards the user's Authorization header to the Cloud API so the chat runs
    under the user's account (LLM credentials live in the Cloud `.env`).
    """
    global _speaking_task

    authorization = request.headers.get("authorization")

    # Cancel any in-flight speaking task from a previous send.
    if _speaking_task and not _speaking_task.done():
        _speaking_task.cancel()
        _speaking_task = None

    await _set_state(
        "listening",
        last_user_message=req.message,
        last_reply=None,
        last_actions=None,
    )

    try:
        cloud_resp = await _forward_to_cloud(
            authorization=authorization,
            message=req.message,
            history=req.history,
            page=req.page,
        )
    except HTTPException as exc:
        await _set_state("idle")
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail, "state": "idle"},
        )

    reply = cloud_resp.get("reply") or cloud_resp.get("answer") or ""
    actions = cloud_resp.get("actions") or None

    await _set_state(
        "thinking",
        last_reply=reply,
        last_actions=actions,
    )

    tts_played = False
    tts_error: str | None = None
    motion_action_types = {"reachy_play_dance", "reachy_play_emotion", "reachy_goto", "reachy_goto_pose"}
    has_motion_action = any(
        isinstance(a, dict) and a.get("type") in motion_action_types
        for a in (actions or [])
    )
    if req.speak and reply:
        await _set_state("speaking")
        # 官方 conversation_app 是「一边说话一边做动作」——TTS 不阻塞 HTTP 返回，
        # 前端拿到 actions 后立刻 dispatch，机器人边播边跳。
        async def _bg_speak() -> None:
            global _speaking_task
            try:
                await _speak_text(reply, wobble=req.wobble and not has_motion_action)
            except Exception as exc:
                logger.warning("background TTS failed: %s", exc)
            finally:
                await _set_state("idle")
                _speaking_task = None

        _speaking_task = asyncio.create_task(_bg_speak())
        tts_played = True  # started — playback continues in background
    else:
        await _set_state("idle")

    return JSONResponse(
        content={
            "reply": reply,
            "actions": actions,
            "state": "speaking" if _speaking_task and not _speaking_task.done() else "idle",
            "tts_available": _chat_state.get("tts_available", False),
            "tts_played": tts_played,
            "error": tts_error,
        }
    )


@router.post("/speak")
async def chat_speak(req: ChatSpeakRequest) -> JSONResponse:
    """Speak an arbitrary text via local TTS (used by 「再说一遍」 button)."""
    global _speaking_task

    if _speaking_task and not _speaking_task.done():
        _speaking_task.cancel()
        _speaking_task = None

    if not _chat_state.get("tts_available"):
        return JSONResponse(
            status_code=503,
            content={
                "ok": False,
                "error": "no_tts_binary",
                "message": "未检测到 piper/espeak。安装任一即可启用语音朗读。",
                "hint": "Ubuntu: sudo apt install espeak-ng || pip install piper-tts",
            },
        )

    await _set_state("speaking")

    async def _run_speak() -> None:
        try:
            await _speak_text(req.text, wobble=req.wobble)
        finally:
            await _set_state("idle")

    _speaking_task = asyncio.create_task(_run_speak())

    return JSONResponse(
        content={
            "ok": True,
            "message": "开始朗读",
            "tts_binary": _chat_state.get("tts_binary"),
        }
    )


@router.post("/stop")
async def chat_stop() -> JSONResponse:
    """Stop any in-flight TTS speaking and reset state to idle."""
    global _speaking_task
    if _speaking_task and not _speaking_task.done():
        _speaking_task.cancel()
        _speaking_task = None
    await _set_state("idle")
    return JSONResponse(content={"ok": True, "state": "idle"})


@router.get("/tts/availability")
async def chat_tts_availability() -> JSONResponse:
    """Report which TTS binaries + voice models + audio players are available.

    Used by the frontend to show precise install hints when something's missing.
    """
    available = {cand: bool(shutil.which(cand)) for cand in _TTS_CANDIDATES}
    venv_piper_ok = _VENV_PIPER.exists()
    voice = _find_piper_voice()
    player = _find_audio_player()
    env_voice = os.environ.get("PIPER_VOICE", "")
    return JSONResponse(
        content={
            "available": available,
            "any_available": bool(available.values()) or venv_piper_ok,
            "active_binary": _chat_state.get("tts_binary"),
            "active_kind": _tts_kind(_chat_state.get("tts_binary") or "") if _chat_state.get("tts_binary") else None,
            "venv_piper_installed": venv_piper_ok,
            "venv_piper_path": str(_VENV_PIPER) if venv_piper_ok else None,
            "piper_voice_configured": bool(voice) and os.path.exists(voice),
            "piper_voice_path": voice,
            "piper_voice_lang": "zh_CN" if voice and "zh_CN" in voice else ("en_US" if voice and "en_US" in voice else None),
            "audio_player": player,
            "install_hints": {
                "espeak-ng": "sudo apt install espeak-ng",
                "piper_pip": "cd apps/realtime && .venv/bin/python -m pip install piper-tts",
                "piper_voice": "download a voice from https://github.com/rhasspy/piper-voices/tree/v1.0.0",
                "alsa_utils": "sudo apt install alsa-utils  # provides aplay",
            },
        }
    )
