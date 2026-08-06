"""Seeed Studio 豆包本体对话 — 直接集成 TheMoonAstronaut/Reachy_Mini_conversation.

不重新造轮子：机器人麦克风 + 喇叭 + 60Hz 动作 + 豆包 ASR/LLM + edge-tts，
与 Seeed Wiki 文档一致：https://wiki.seeedstudio.com/cn/reachymini_conversation/

前提：Reachy Mini daemon 音频已启用（不能 --deactivate-audio）。
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .platform_paths import default_log_path, is_windows, venv_executable
from .reachy_proxy import _reachy_daemon_env, _reachy_python, _reachy_sdk_path, _stop_broken_daemon_listener

router = APIRouter(prefix="/api/reachy/seeed-conversation", tags=["reachy-seeed-conversation"])

SEEED_REPO = "https://github.com/TheMoonAstronaut/Reachy_Mini_conversation.git"
SEEED_DIR = Path(
    os.environ.get(
        "BOTVERSEX_SEEED_CONVERSATION_DIR",
        Path.home() / ".local/share/botversex/seeed_reachymini_conversation",
    )
)
LOG_FILE = Path(
    os.environ.get(
        "BOTVERSEX_SEEED_CONV_LOG",
        str(default_log_path("botversex_seeed_conversation.log")),
    )
)
KEYS_FILE = Path(
    os.environ.get(
        "BOTVERSEX_SEEED_KEYS_FILE",
        Path.home() / ".config" / "botversex" / "reachy_seeed_keys.json",
    )
)
REALTIME_API = os.environ.get("BOTVERSEX_REALTIME_API", "http://127.0.0.1:8002")

_process: asyncio.subprocess.Process | None = None
_state: dict[str, Any] = {
    "installed": False,
    "running": False,
    "state": "stopped",
    "pid": None,
    "started_at": None,
    "returncode": None,
    "error": None,
    "command": None,
}
_log_buffer: list[str] = []
_lock = asyncio.Lock()


def _python() -> str:
    return _reachy_python() or (shutil.which("python3") or "python3")


def _pip_install_cmd(*packages: str) -> list[str]:
    python = _python()
    uv = shutil.which("uv")
    if uv:
        return [uv, "pip", "install", "--python", python, *packages]
    sdk_pip = venv_executable(_reachy_sdk_path(), "pip")
    if sdk_pip.exists():
        return [str(sdk_pip), "install", *packages]
    pip = shutil.which("pip3") or shutil.which("pip") or "pip3"
    return [pip, "install", *packages]


def _is_installed() -> bool:
    return (SEEED_DIR / "main.py").is_file()


def _keys_template() -> dict[str, str]:
    return {
        "llm_api_key": "",
        "asr_api_key": "",
        "asr_app_id": "",
        "asr_access_token": "",
        "asr_resource_id": "volc.seedasr.sauc.duration",
        "model": "doubao-seed-character-251128",
    }


def _ensure_keys_file() -> Path:
    KEYS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not KEYS_FILE.is_file():
        KEYS_FILE.write_text(
            json.dumps(_keys_template(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        KEYS_FILE.chmod(0o600)
    return KEYS_FILE


def _load_keys() -> dict[str, str]:
    keys = _keys_template()
    if KEYS_FILE.is_file():
        try:
            loaded = json.loads(KEYS_FILE.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                keys.update({k: str(v) for k, v in loaded.items() if k in keys})
        except (OSError, json.JSONDecodeError):
            pass
    for env_key, field in (
        ("REACHY_DOUBAO_LLM_KEY", "llm_api_key"),
        ("DOUBAO_LLM_API_KEY", "llm_api_key"),
        ("REACHY_DOUBAO_ASR_KEY", "asr_api_key"),
        ("DOUBAO_ASR_API_KEY", "asr_api_key"),
        ("REACHY_DOUBAO_MODEL", "model"),
    ):
        val = os.environ.get(env_key, "").strip()
        if val:
            keys[field] = val
    return keys


def _resolve_keys(
    llm_api_key: str = "",
    asr_api_key: str = "",
    model: str = "",
) -> dict[str, str]:
    stored = _load_keys()
    llm = (llm_api_key or stored["llm_api_key"]).strip()
    asr = (asr_api_key or stored["asr_api_key"]).strip()
    app_id = stored.get("asr_app_id", "").strip()
    access_token = stored.get("asr_access_token", "").strip()
    resource_id = (stored.get("asr_resource_id") or "volc.seedasr.sauc.duration").strip()
    mdl = (model or stored["model"] or "doubao-seed-character-251128").strip()
    if not llm or len(llm) < 8:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "seeed_keys_missing",
                "message": "请填写豆包 LLM API Key",
                "keys_file": str(_ensure_keys_file()),
            },
        )
    if not ((app_id and access_token) or (asr and len(asr) >= 8)):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "seeed_keys_missing",
                "message": "请填写 ASR：新版 api_key，或旧版 app_id + access_token",
                "keys_file": str(_ensure_keys_file()),
            },
        )
    return {
        "llm_api_key": llm,
        "asr_api_key": asr,
        "asr_app_id": app_id,
        "asr_access_token": access_token,
        "asr_resource_id": resource_id,
        "model": mdl,
    }


def _save_keys(llm_api_key: str, asr_api_key: str, model: str) -> None:
    path = _ensure_keys_file()
    data = _load_keys()
    data["llm_api_key"] = llm_api_key
    data["asr_api_key"] = asr_api_key
    data["model"] = model
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    path.chmod(0o600)


def _config_template(
    *,
    llm_api_key: str,
    asr_api_key: str,
    model: str,
    asr_app_id: str = "",
    asr_access_token: str = "",
    asr_resource_id: str = "volc.seedasr.sauc.duration",
) -> str:
    """Generate config.py matching upstream layout."""
    model_esc = model.replace("\\", "\\\\").replace('"', '\\"')
    llm_esc = llm_api_key.replace("\\", "\\\\").replace('"', '\\"')
    asr_esc = asr_api_key.replace("\\", "\\\\").replace('"', '\\"')
    app_esc = asr_app_id.replace("\\", "\\\\").replace('"', '\\"')
    tok_esc = asr_access_token.replace("\\", "\\\\").replace('"', '\\"')
    res_esc = asr_resource_id.replace("\\", "\\\\").replace('"', '\\"')
    return f'''"""BotverseX-generated config for Seeed Reachy Mini conversation."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
DEFAULT_PROFILES_DIRECTORY = PROJECT_ROOT / "profiles"

BRAIN_CONFIG = {{
    "provider": "doubao",
    "doubao": {{
        "api_key": "{llm_esc}",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "model": "{model_esc}",
    }},
}}

TTS_CONFIG = {{
    "voice": "zh-CN-XiaoxiaoNeural",
}}

AUDIO_CONFIG = {{
    "silence_timeout": 2.0,
    "speaker_gain": 5.0,
}}

ASR_CONFIG = {{
    "api_key": "{asr_esc}",
    "app_id": "{app_esc}",
    "access_token": "{tok_esc}",
    "resource_id": "{res_esc}",
    "url": "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_nostream",
}}

SYSTEM_PROMPT = """You are Reachy Mini, a friendly and expressive robot assistant.
Keep responses warm and conversational in Chinese. Use physical actions to express emotions.
When the user asks to dance, celebrate, or move, include action hints in parentheses like （跳个舞）."""
'''


async def _run_cmd(cmd: list[str], *, cwd: Path | None = None, timeout: float = 600.0) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(cwd) if cwd else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=_reachy_daemon_env(),
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise HTTPException(status_code=504, detail={"code": "seeed_install_timeout", "message": "安装超时"})
    text = (stdout or b"").decode(errors="replace")
    return proc.returncode or 0, text


async def _ensure_repo() -> None:
    SEEED_DIR.parent.mkdir(parents=True, exist_ok=True)
    if _is_installed():
        return
    if SEEED_DIR.exists() and not _is_installed():
        shutil.rmtree(SEEED_DIR, ignore_errors=True)
    code, out = await _run_cmd(
        ["git", "clone", "--depth", "1", SEEED_REPO, str(SEEED_DIR)],
        timeout=120.0,
    )
    if code != 0 or not _is_installed():
        raise HTTPException(
            status_code=502,
            detail={
                "code": "seeed_clone_failed",
                "message": "克隆 Seeed 对话仓库失败",
                "output": out[-2000:],
            },
        )


async def _ensure_deps() -> None:
    await _ensure_repo()
    code, out = await _run_cmd(
        _pip_install_cmd(
            "--no-deps",
            "edge-tts",
            "soundfile",
            "scipy",
            "websockets",
            "httpx",
            "gradio",
            "fastapi",
            "reachy-mini-dances-library",
        ),
        timeout=600.0,
    )
    if code != 0:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "seeed_pip_failed",
                "message": "安装 Seeed 对话依赖失败",
                "output": out[-2000:],
            },
        )
    code2, out2 = await _run_cmd(
        _pip_install_cmd("cffi", "numpy", "scipy", "aiohttp", "tabulate"),
        timeout=300.0,
    )
    if code2 != 0:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "seeed_pip_failed",
                "message": "安装 Seeed 运行时依赖失败",
                "output": out2[-2000:],
            },
        )


def _seeed_env() -> dict[str, str]:
    env = _reachy_daemon_env()
    sdk_src = _reachy_sdk_path() / "src"
    parts = [str(sdk_src), str(SEEED_DIR)]
    existing = env.get("PYTHONPATH", "")
    if existing:
        parts.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(parts)
    env["PYTHONUNBUFFERED"] = "1"
    # Do not resolve() the python symlink — it often points at /usr/bin/python3.12
    py = Path(_python())
    venv_bin = py.parent if py.name.startswith("python") else None
    sdk = _reachy_sdk_path()
    venv_bin_dir = sdk / ".venv" / ("Scripts" if is_windows() else "bin")
    candidates = [
        venv_bin,
        venv_bin_dir,
        Path.home() / ".local" / "bin",
    ]
    path_prefix = [str(p) for p in candidates if p and p.is_dir()]
    if path_prefix:
        env["PATH"] = os.pathsep.join([*path_prefix, env.get("PATH", "")])
    return env


def _write_config(
    llm_api_key: str,
    asr_api_key: str,
    model: str,
    *,
    asr_app_id: str = "",
    asr_access_token: str = "",
    asr_resource_id: str = "volc.seedasr.sauc.duration",
) -> None:
    cfg_path = SEEED_DIR / "config.py"
    backup = SEEED_DIR / "config.py.orig"
    if cfg_path.exists() and not backup.exists():
        shutil.copy2(cfg_path, backup)
    cfg_path.write_text(
        _config_template(
            llm_api_key=llm_api_key,
            asr_api_key=asr_api_key,
            model=model,
            asr_app_id=asr_app_id,
            asr_access_token=asr_access_token,
            asr_resource_id=asr_resource_id,
        ),
        encoding="utf-8",
    )


def _keys_ready(keys: dict[str, str] | None = None) -> bool:
    k = keys or _load_keys()
    llm_ok = bool(k.get("llm_api_key", "").strip())
    asr_ok = bool(
        (k.get("asr_app_id", "").strip() and k.get("asr_access_token", "").strip())
        or k.get("asr_api_key", "").strip()
    )
    return llm_ok and asr_ok


def _push_log(line: str) -> None:
    _log_buffer.append(line)
    if len(_log_buffer) > 80:
        del _log_buffer[: len(_log_buffer) - 80]


async def _stream_logs(proc: asyncio.subprocess.Process) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as fh:
        fh.write(f"\n=== Seeed conversation start {time.ctime()} ===\n")
        assert proc.stdout is not None
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            text = line.decode(errors="replace").rstrip()
            fh.write(text + "\n")
            fh.flush()
            _push_log(text)


async def _watch(proc: asyncio.subprocess.Process) -> None:
    global _process
    try:
        await _stream_logs(proc)
    except Exception as exc:  # noqa: BLE001
        _push_log(f"[watcher] {exc!s}")
    rc = await proc.wait()
    async with _lock:
        if _process is proc:
            _process = None
            _state.update(
                running=False,
                state="error" if rc not in (0, None, -15) else "stopped",
                pid=None,
                returncode=rc,
            )


def _daemon_has_deactivated_audio() -> bool:
    try:
        if is_windows():
            proc = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                    "Select-Object -ExpandProperty CommandLine",
                ],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            text = proc.stdout or ""
        else:
            proc = subprocess.run(
                ["pgrep", "-af", "reachy_mini.daemon.app.main"],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
            text = proc.stdout or ""
        return "--deactivate-audio" in text
    except (OSError, subprocess.TimeoutExpired):
        return False


def _gstapp_typelib_available() -> bool:
    if is_windows():
        return True
    return Path("/usr/lib/x86_64-linux-gnu/girepository-1.0/GstApp-1.0.typelib").is_file()


def _audio_system_hint() -> str | None:
    if _daemon_has_deactivated_audio():
        if not _gstapp_typelib_available():
            return (
                "需要安装 GStreamer GstApp 组件（一次性，需 sudo）："
                "sudo apt install -y gir1.2-gst-plugins-base-1.0"
                " 然后刷新页面或 POST /api/reachy/seeed-conversation/setup"
            )
        return "Daemon 音频被禁用。请 POST /setup 重启 daemon。"
    return None


async def _restart_daemon_with_audio() -> dict[str, Any]:
    """Stop any daemon (incl. --deactivate-audio) and start with audio enabled.

    IMPORTANT: call ``start_local_daemon`` in-process. Do NOT HTTP-loopback to
    ``/api/reachy/local-daemon/start`` — uvicorn runs a single worker, so a
    nested self-request deadlocks until the client times out ("实时服务未响应").
    """
    await _stop_broken_daemon_listener()
    await asyncio.sleep(1.0)
    from .reachy_proxy import start_local_daemon

    try:
        resp = await start_local_daemon()
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
        return {
            "ok": False,
            "status_code": exc.status_code,
            "detail": detail,
            "daemon_http_ok": False,
        }

    body: dict[str, Any] = {}
    try:
        raw = getattr(resp, "body", b"") or b""
        if isinstance(raw, memoryview):
            raw = raw.tobytes()
        if raw:
            body = json.loads(raw.decode("utf-8", errors="replace"))
    except Exception:
        body = {"raw": str(getattr(resp, "body", ""))[:500]}

    http_ok = bool((body.get("daemon_http") or {}).get("ok") or body.get("ok"))
    return {
        "ok": http_ok,
        "status_code": getattr(resp, "status_code", 200),
        "audio_fallback_used": body.get("audio_fallback_used"),
        "audio_warning": body.get("audio_warning"),
        "daemon_http_ok": http_ok,
        "message": body.get("message"),
    }


def _reachy_alsa_card() -> str | None:
    """Find ALSA card index for Reachy Mini USB audio."""
    try:
        proc = subprocess.run(
            ["arecord", "-l"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        for line in (proc.stdout or "").splitlines():
            if "Reachy Mini Audio" in line or "Reachy Mini" in line:
                m = re.search(r"card\s+(\d+)", line, re.IGNORECASE)
                if m:
                    return m.group(1)
    except (OSError, subprocess.TimeoutExpired):
        pass
    return "3"


def _set_robot_volume() -> dict[str, Any]:
    """Best-effort volume: daemon API first, then amixer on Reachy Mini card."""
    results: dict[str, Any] = {}
    try:
        import httpx as _httpx

        r = _httpx.post(
            "http://127.0.0.1:8010/api/volume/set",
            json={"volume": 100},
            timeout=3.0,
        )
        results["daemon_volume"] = {"status": r.status_code, "body": r.text[:200]}
        r_mic = _httpx.post(
            "http://127.0.0.1:8010/api/volume/microphone/set",
            json={"volume": 100},
            timeout=3.0,
        )
        results["daemon_mic"] = {"status": r_mic.status_code, "body": r_mic.text[:200]}
    except Exception as exc:  # noqa: BLE001
        results["daemon_volume"] = {"error": str(exc)}
    if not is_windows():
        card = _reachy_alsa_card()
        for ctrl in ("PCM", "Speaker", "Master", "Capture", "Mic"):
            try:
                proc = subprocess.run(
                    ["amixer", "-c", card, "sset", ctrl, "100%"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
                if proc.returncode == 0:
                    results[f"amixer_{ctrl}"] = {"card": card, "returncode": 0}
            except (OSError, subprocess.TimeoutExpired) as exc:
                results[f"amixer_{ctrl}"] = {"error": str(exc)}
    return results


def _ensure_reachy_pipewire_io(*, set_source: bool = False) -> dict[str, Any]:
    """Point PipeWire default *sink* at Reachy Mini Audio (speaker).

    Mic/source is left alone by default — users often keep a laptop/USB mic and
    will fix stuck capture themselves (e.g. reboot). Pass set_source=True only
    when intentionally forcing the robot headset mic.
    """
    if is_windows():
        return {"skipped": True, "reason": "windows"}
    if shutil.which("wpctl") is None:
        return {"skipped": True, "reason": "wpctl missing"}

    result: dict[str, Any] = {"ok": False, "set_source": set_source}
    try:
        status = subprocess.run(
            ["wpctl", "status"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        text = status.stdout or ""
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": str(exc)}

    section = "none"
    sink_id: str | None = None
    source_id: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        # wpctl prints tree prefixes like "│  *  154. Reachy Mini Audio ..."
        if "Sinks:" in line:
            section = "sinks"
            continue
        if "Sources:" in line:
            section = "sources"
            continue
        if "Sink endpoints:" in line or "Source endpoints:" in line or "Filters:" in line:
            section = "none"
            continue
        if "Reachy Mini Audio" not in line:
            continue
        m = re.search(r"(\d+)\.", line)
        if not m:
            continue
        node_id = m.group(1)
        if section == "sinks":
            sink_id = node_id
        elif section == "sources":
            source_id = node_id

    result["sink_id"] = sink_id
    result["source_id"] = source_id
    actions: list[str] = []
    targets: list[tuple[str | None, str]] = [(sink_id, "sink")]
    if set_source:
        targets.append((source_id, "source"))
    for node_id, kind in targets:
        if not node_id:
            continue
        try:
            subprocess.run(
                ["wpctl", "set-default", node_id],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            # Official HF duplex has no Seeed-style speaker_gain; boost PipeWire
            # sink above 100% so the robot speaker is audible (was ~2.5, now 5.0).
            subprocess.run(
                ["wpctl", "set-volume", node_id, "5.0" if kind == "sink" else "1.0"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            actions.append(f"{kind}:{node_id}:{'5.0x' if kind == 'sink' else '1.0x'}")
        except (OSError, subprocess.TimeoutExpired) as exc:
            result[f"{kind}_error"] = str(exc)
    result["actions"] = actions
    result["ok"] = bool(sink_id) if not set_source else bool(sink_id or source_id)
    return result


def _list_pipewire_audio_sources() -> list[dict[str, Any]]:
    """List PipeWire *audio* sources for mic selection UI."""
    if is_windows() or shutil.which("wpctl") is None:
        return []
    try:
        status = subprocess.run(
            ["wpctl", "status"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        text = status.stdout or ""
    except (OSError, subprocess.TimeoutExpired):
        return []

    # Only parse the Audio block (before Video).
    audio_block = text
    if "\nVideo" in text:
        audio_block = text.split("\nVideo", 1)[0]

    sources: list[dict[str, Any]] = []
    section = "none"
    default_id: str | None = None
    for raw in audio_block.splitlines():
        line = raw.strip()
        if line.startswith("Sources:") or line == "Sources:":
            section = "sources"
            continue
        if "Sources:" in line and section != "sources":
            section = "sources"
            continue
        if section != "sources":
            continue
        if "Source endpoints:" in line or line.startswith("Filters:") or line.startswith("Streams:"):
            break
        m = re.search(r"(\d+)\.\s+(.+?)(?:\s+\[vol:.*\])?\s*$", line)
        if not m:
            continue
        node_id = m.group(1)
        name = m.group(2).strip().lstrip("* ").strip()
        if "*" in raw.split(m.group(0), 1)[0] or re.search(rf"\*\s*{node_id}\.", raw):
            default_id = node_id
        sources.append({"id": node_id, "name": name, "default": False})

    for src in sources:
        src["default"] = src["id"] == default_id
    return sources


def _set_pipewire_default_source(node_id: str) -> dict[str, Any]:
    """Set PipeWire default audio source (microphone)."""
    if is_windows():
        return {"ok": False, "reason": "windows"}
    if shutil.which("wpctl") is None:
        return {"ok": False, "reason": "wpctl missing"}
    node_id = str(node_id).strip()
    if not node_id.isdigit():
        return {"ok": False, "reason": "invalid id"}
    try:
        proc = subprocess.run(
            ["wpctl", "set-default", node_id],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        subprocess.run(
            ["wpctl", "set-volume", node_id, "1.0"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return {
            "ok": proc.returncode == 0,
            "id": node_id,
            "stderr": (proc.stderr or "")[:200],
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": str(exc)}


def _sounddevice_input_match_for_source_name(name: str) -> str:
    """Pick a short match string SoundDevice can resolve from a PipeWire name."""
    lowered = name.lower()
    for token in ("MCP01", "Reachy Mini Audio", "Digital Microphone", "Headphones", "USB"):
        if token.lower() in lowered:
            return token
    cleaned = re.sub(r"[^\w\s-]", " ", name).strip()
    parts = [p for p in cleaned.split() if len(p) > 2]
    return parts[0] if parts else name[:32]


def _sample_pipewire_audio_level(
    source_id: str | None = None,
    duration_ms: int = 80,
) -> dict[str, Any]:
    """Capture a short raw buffer from a PipeWire source and return RMS/peak (0..1).

    Used by the chat UI loudness meter so the user can see whether the selected
    mic is actually receiving speech before/while conversation runs.
    """
    if is_windows():
        return {"ok": False, "reason": "windows", "rms": 0.0, "peak": 0.0, "db": -120.0}
    if shutil.which("pw-record") is None:
        return {"ok": False, "reason": "pw-record missing", "rms": 0.0, "peak": 0.0, "db": -120.0}

    import math
    import struct

    duration_ms = max(40, min(int(duration_ms), 250))
    rate = 16000
    cmd = [
        "pw-record",
        "--media-category",
        "Capture",
        "--rate",
        str(rate),
        "--channels",
        "1",
        "--latency",
        "20ms",
    ]
    sid = str(source_id).strip() if source_id else ""
    if sid.isdigit():
        cmd.extend(["--target", sid])
    cmd.append("-")

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        # Let pw-record fill a short buffer, then stop.
        time.sleep(duration_ms / 1000.0)
        proc.terminate()
        try:
            raw, _err = proc.communicate(timeout=0.4)
        except subprocess.TimeoutExpired:
            proc.kill()
            raw, _err = proc.communicate(timeout=0.4)
    except OSError as exc:
        return {"ok": False, "error": str(exc), "rms": 0.0, "peak": 0.0, "db": -120.0}

    raw = raw or b""
    n = len(raw) // 2
    if n < 32:
        return {
            "ok": False,
            "reason": "no samples",
            "rms": 0.0,
            "peak": 0.0,
            "db": -120.0,
            "id": sid or None,
            "samples": n,
        }

    # Prefer the most recent window (avoid startup silence).
    window = min(n, max(256, rate * duration_ms // 1000))
    samples = struct.unpack_from(f"<{window}h", raw, (n - window) * 2)
    sum_sq = 0.0
    peak_i = 0
    for s in samples:
        v = abs(s)
        if v > peak_i:
            peak_i = v
        sum_sq += float(s) * float(s)
    rms = math.sqrt(sum_sq / len(samples)) / 32768.0
    peak = peak_i / 32768.0
    db = 20.0 * math.log10(max(rms, 1e-9))
    return {
        "ok": True,
        "id": sid or None,
        "rms": round(rms, 5),
        "peak": round(peak, 5),
        "db": round(db, 1),
        "samples": len(samples),
    }


class SeeedInstallRequest(BaseModel):
    force: bool = False


class SeeedStartRequest(BaseModel):
    llm_api_key: str = Field(default="", description="火山引擎方舟 LLM API Key（可留空，从 keys 文件读取）")
    asr_api_key: str = Field(default="", description="豆包语音识别 API Key（可留空，从 keys 文件读取）")
    model: str = Field(default="", description="方舟 Model ID")
    auto_install: bool = True
    save_keys: bool = True


class SeeedSetupRequest(BaseModel):
    restart_daemon: bool = True
    install: bool = True
    set_volume: bool = True


@router.get("/status")
async def seeed_status() -> JSONResponse:
    async with _lock:
        st = dict(_state)
    keys = _load_keys()
    st["installed"] = _is_installed()
    st["install_dir"] = str(SEEED_DIR)
    st["log_file"] = str(LOG_FILE)
    st["wiki_url"] = "https://wiki.seeedstudio.com/cn/reachymini_conversation/"
    st["log_tail"] = list(_log_buffer[-30:])
    st["keys_file"] = str(_ensure_keys_file())
    st["keys_configured"] = _keys_ready(keys)
    st["daemon_audio_deactivated"] = _daemon_has_deactivated_audio()
    st["gstapp_available"] = _gstapp_typelib_available()
    st["audio_hint"] = _audio_system_hint()
    return JSONResponse(content=st)


@router.get("/keys-template")
async def seeed_keys_template() -> JSONResponse:
    path = _ensure_keys_file()
    keys = _load_keys()
    return JSONResponse(
        content={
            "keys_file": str(path),
            "template": _keys_template(),
            "current": {
                k: ("***" if keys.get(k) else "")
                for k in ("llm_api_key", "asr_api_key", "asr_app_id", "asr_access_token", "model")
            },
            "keys_configured": _keys_ready(keys),
        }
    )


@router.post("/install")
async def seeed_install(req: SeeedInstallRequest) -> JSONResponse:
    if req.force and SEEED_DIR.exists():
        shutil.rmtree(SEEED_DIR, ignore_errors=True)
    _ensure_keys_file()
    await _ensure_deps()
    async with _lock:
        _state["installed"] = True
        _state["state"] = "installed"
    return JSONResponse(content={"ok": True, "message": "Seeed 本体对话已安装", "dir": str(SEEED_DIR)})


@router.post("/setup")
async def seeed_setup(req: SeeedSetupRequest) -> JSONResponse:
    """一键配置：keys 模板 + 安装 Seeed + 重启 daemon 音频 + 音量。"""
    steps: list[dict[str, Any]] = []
    keys_path = _ensure_keys_file()
    steps.append({"step": "keys_template", "ok": True, "path": str(keys_path)})

    if req.install:
        try:
            await _ensure_deps()
            steps.append({"step": "install", "ok": True})
        except HTTPException as exc:
            steps.append({"step": "install", "ok": False, "detail": exc.detail})
            return JSONResponse(
                status_code=exc.status_code,
                content={"ok": False, "steps": steps, "message": "安装失败"},
            )

    daemon_result: dict[str, Any] | None = None
    if req.restart_daemon and _daemon_has_deactivated_audio():
        daemon_result = await _restart_daemon_with_audio()
        steps.append({"step": "restart_daemon", **daemon_result})
    elif req.restart_daemon:
        steps.append({"step": "restart_daemon", "ok": True, "skipped": "audio already enabled"})

    volume_result: dict[str, Any] | None = None
    pipewire_result: dict[str, Any] | None = None
    if req.set_volume:
        pipewire_result = _ensure_reachy_pipewire_io()
        volume_result = _set_robot_volume()
        steps.append({"step": "pipewire", "ok": True, "detail": pipewire_result})
        steps.append({"step": "volume", "ok": True, "detail": volume_result})

    keys = _load_keys()
    return JSONResponse(
        content={
            "ok": True,
            "message": "一键配置完成。只需在 keys 文件或页面填写豆包 Key，然后点启动。",
            "keys_file": str(keys_path),
            "keys_configured": _keys_ready(keys),
            "steps": steps,
            "daemon": daemon_result,
            "volume": volume_result,
            "pipewire": pipewire_result,
        }
    )


@router.post("/start")
async def seeed_start(req: SeeedStartRequest) -> JSONResponse:
    global _process
    async with _lock:
        if _process is not None and _process.returncode is None:
            raise HTTPException(
                status_code=409,
                detail={"code": "seeed_already_running", "message": "本体对话已在运行", "pid": _process.pid},
            )

    creds = _resolve_keys(req.llm_api_key, req.asr_api_key, req.model)
    if req.save_keys and (req.llm_api_key.strip() or req.asr_api_key.strip()):
        _save_keys(creds["llm_api_key"], creds["asr_api_key"], creds["model"])

    if req.auto_install or not _is_installed():
        await _ensure_deps()

    if _daemon_has_deactivated_audio():
        raise HTTPException(
            status_code=503,
            detail={
                "code": "daemon_audio_disabled",
                "message": "Daemon 当前禁用了音频（--deactivate-audio）。请先 POST /setup 或点「一键配置」。",
            },
        )

    _write_config(
        creds["llm_api_key"],
        creds["asr_api_key"],
        creds["model"],
        asr_app_id=creds["asr_app_id"],
        asr_access_token=creds["asr_access_token"],
        asr_resource_id=creds["asr_resource_id"],
    )

    _set_robot_volume()

    python = _python()
    cmd = [python, "main.py"]
    env = _seeed_env()
    env.setdefault("REACHY_MINI_DAEMON_HOST", "127.0.0.1")
    env.setdefault("REACHY_MINI_DAEMON_PORT", "8010")

    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    log_fh = LOG_FILE.open("a", encoding="utf-8")
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(SEEED_DIR),
        env=env,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    async with _lock:
        _process = proc
        _log_buffer.clear()
        _state.update(
            running=True,
            state="running",
            installed=True,
            pid=proc.pid,
            started_at=time.time(),
            returncode=None,
            error=None,
            command=cmd,
        )

    asyncio.create_task(_watch(proc))
    log_fh.close()

    return JSONResponse(
        content={
            "ok": True,
            "message": "本体对话已启动。对着机器人说话即可（麦克风/喇叭走机器人本体）。",
            "pid": proc.pid,
            "log_file": str(LOG_FILE),
            "wiki_url": "https://wiki.seeedstudio.com/cn/reachymini_conversation/",
        }
    )


@router.post("/stop")
async def seeed_stop() -> JSONResponse:
    global _process
    async with _lock:
        proc = _process
    if proc is None or proc.returncode is not None:
        async with _lock:
            _process = None
            _state.update(running=False, state="stopped", pid=None)
        return JSONResponse(content={"ok": True, "message": "本体对话未在运行"})
    proc.terminate()
    try:
        await asyncio.wait_for(proc.wait(), timeout=5.0)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
    async with _lock:
        _process = None
        _state.update(running=False, state="stopped", pid=None, returncode=proc.returncode)
    return JSONResponse(content={"ok": True, "message": "本体对话已停止"})
