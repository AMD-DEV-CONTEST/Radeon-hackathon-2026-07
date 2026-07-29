"""Notebook UI: real PrivateLocalAgent (orch) + local web + Radeon rc-tunnel.

Fixes:
- Port already in use (shutdown old servers / kill by /proc)
- Model-load-failed page (always attach ready orch, never cold-start empty demo)
- FRP 404 (health-check local before expose; re-expose after bind)
"""

from __future__ import annotations

import os
import re
import shutil
import signal
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from html import escape
from pathlib import Path
from typing import Any, Callable

from src.apps.judge_script import JUDGE_SEQUENCE, prompts_for_mode
from src.apps.modes import UI_MODES

_EMBED_SERVERS: dict[int, Any] = {}
_PUBLIC_URLS: dict[int, str] = {}
_WEB_MOD: Any = None


def render_shell(history: list[dict[str, Any]], subtitle: str = "本地私有 Agent") -> str:
    css = (
        "<style>.pla-shell{font-family:Segoe UI,PingFang SC,sans-serif;max-width:920px;"
        "margin:0 auto;padding:16px;border-radius:16px;color:#e5e7eb;background:#0f172a;"
        "border:1px solid #334155}.pla-brand{font-size:24px;font-weight:700}"
        ".pla-chat{min-height:160px;max-height:420px;overflow:auto;padding:10px}"
        ".pla-row{display:flex;margin:8px 0}.pla-row.user{justify-content:flex-end}"
        ".pla-bubble{max-width:86%;padding:10px 12px;border-radius:12px;white-space:pre-wrap}"
        ".pla-bubble.user{background:#14b8a6;color:#042f2e}.pla-bubble.bot{background:#1f2937}</style>"
    )
    if not history:
        body = "<div style='color:#64748b;text-align:center;padding:24px'>下方为完整 Agent 界面</div>"
    else:
        parts = []
        for turn in history:
            parts.append(
                f"<div class='pla-row user'><div class='pla-bubble user'>{escape(str(turn.get('q','')))}</div></div>"
            )
            parts.append(
                f"<div class='pla-row bot'><div class='pla-bubble bot'>{escape(str(turn.get('a','')))}</div></div>"
            )
        body = "".join(parts)
    return (
        f"{css}<div class='pla-shell'><div class='pla-brand'>PrivateLocalAgent</div>"
        f"<div style='color:#94a3b8;margin:4px 0 10px'>{escape(subtitle)}</div>"
        f"<div class='pla-chat'>{body}</div></div>"
    )


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _healthz(port: int, timeout: float = 3.0) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=timeout) as r:
            return b"ok" in r.read().lower()
    except Exception:
        return False


def _shutdown_tracked() -> None:
    for port, server in list(_EMBED_SERVERS.items()):
        try:
            server.shutdown()
        except Exception:
            pass
        try:
            server.server_close()
        except Exception:
            pass
        _EMBED_SERVERS.pop(port, None)


def _kill_web_demo_procs() -> None:
    """Kill leftover web_http_demo processes without relying on fuser/ss."""
    for pid_name in os.listdir("/proc"):
        if not pid_name.isdigit():
            continue
        try:
            raw = Path(f"/proc/{pid_name}/cmdline").read_bytes()
            cmd = raw.replace(b"\x00", b" ").decode("utf-8", errors="ignore")
            if "web_http_demo.py" in cmd or "pla_web_http_demo" in cmd:
                os.kill(int(pid_name), signal.SIGKILL)
        except Exception:
            continue


def _load_web_module() -> Any:
    global _WEB_MOD
    import importlib.util
    import sys

    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    demo_path = root / "scripts" / "web_http_demo.py"
    spec = importlib.util.spec_from_file_location("pla_web_http_demo", demo_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {demo_path}")
    web = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(web)
    _WEB_MOD = web
    return web


def _attach_orch(web: Any, orch: Any, default_mode: str) -> None:
    upload_dir = getattr(getattr(orch, "tools", None), "upload_dir", None)
    if upload_dir is None:
        from src.config import load_settings

        upload_dir = load_settings().resolve("data/uploads")
    Path(upload_dir).mkdir(parents=True, exist_ok=True)
    web.ORCH = orch
    web.UPLOAD_DIR = Path(upload_dir)
    web.READY = True
    web.LOADING = False
    web.LOAD_ERROR = ""
    web.MODE = default_mode if default_mode in {m.id for m in UI_MODES} else "chat"
    if not getattr(web, "SESSIONS", None):
        web._new_session(web.MODE)
    else:
        # keep sessions, ensure current exists
        try:
            web._ensure_session()
            web.SESSIONS[web.CURRENT_ID]["mode"] = web.MODE
        except Exception:
            web._new_session(web.MODE)


def start_web_for_orch(orch: Any, default_mode: str = "chat", port: int = 7900) -> int:
    """Start (or restart) Doubao web UI bound to an already-ready orchestrator."""
    _shutdown_tracked()
    _kill_web_demo_procs()
    time.sleep(0.6)

    web = _load_web_module()
    _attach_orch(web, orch, default_mode)

    # Prefer requested port; if still busy, pick a free one.
    bind_port = int(port)
    if _port_open(bind_port) and not _healthz(bind_port):
        # zombie listener — try kill again then maybe switch port
        _kill_web_demo_procs()
        time.sleep(0.6)
    if _port_open(bind_port):
        # still busy: use ephemeral port
        bind_port = _free_port()
        print(f"[ui] port {port} busy → using {bind_port}", flush=True)

    server = web.ThreadingHTTPServer(("127.0.0.1", bind_port), web.Handler)
    server.allow_reuse_address = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _EMBED_SERVERS[bind_port] = server

    for _ in range(30):
        if _healthz(bind_port):
            break
        time.sleep(0.2)
    else:
        raise RuntimeError(f"web started but /healthz failed on :{bind_port}")

    print(f"[ui] agent web ready on http://127.0.0.1:{bind_port}/ (orch attached)", flush=True)
    return bind_port


# Back-compat aliases used by older notebook cells
_start_web_for_orch = start_web_for_orch


def _kill_port(port: int) -> None:  # noqa: ARG001
    _shutdown_tracked()
    _kill_web_demo_procs()
    time.sleep(0.4)


def _rc_tunnel_bin() -> str | None:
    for p in (
        shutil.which("rc-tunnel"),
        str(Path.home() / ".local" / "bin" / "rc-tunnel"),
    ):
        if p and Path(p).exists():
            return p
    return None


def ensure_rc_tunnel_installed() -> str | None:
    existing = _rc_tunnel_bin()
    if existing:
        return existing
    installer = Path("/var/run/secrets/frp-self-service/install")
    if not installer.exists():
        print("[ui] rc-tunnel installer missing — recreate Notebook Pod if needed", flush=True)
        return None
    subprocess.run(["bash", str(installer)], check=False, timeout=180)
    os.environ["PATH"] = str(Path.home() / ".local" / "bin") + os.pathsep + os.environ.get("PATH", "")
    return _rc_tunnel_bin()


def expose_rc_tunnel(port: int) -> str | None:
    """Expose local agent web via official Radeon rc-tunnel. Returns public https URL."""
    if not _healthz(port):
        raise RuntimeError(f"refuse expose: local :{port} /healthz not ok")
    bin_path = ensure_rc_tunnel_installed()
    if not bin_path:
        return None
    subprocess.run([bin_path, "stop"], check=False, capture_output=True, text=True, timeout=60)
    time.sleep(0.5)
    proc = subprocess.run(
        [bin_path, "expose", "--port", str(port)],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    out = (proc.stdout or "") + "\n" + (proc.stderr or "")
    print(out, flush=True)
    m = re.search(r"https?://[^\s]*radeon\.firstdg\.ai[^\s]*", out)
    if not m:
        # quarantine may keep previous domain — ask status
        st = subprocess.run([bin_path, "status"], check=False, capture_output=True, text=True, timeout=30)
        out2 = (st.stdout or "") + "\n" + (st.stderr or "")
        print(out2, flush=True)
        m = re.search(r"https?://[^\s]*radeon\.firstdg\.ai[^\s]*", out2)
    if not m:
        return None
    url = m.group(0).rstrip("/")
    if url.startswith("http://"):
        url = "https://" + url[len("http://") :]
    _PUBLIC_URLS[port] = url
    # wait until public responds (best-effort)
    for _ in range(20):
        try:
            with urllib.request.urlopen(url + "/healthz", timeout=3) as r:
                if b"ok" in r.read().lower():
                    break
        except Exception:
            time.sleep(0.5)
    print(f"[ui] public={url}", flush=True)
    return url


def display_agent_ui(local_url: str, public_url: str | None) -> None:
    from IPython.display import HTML, clear_output, display

    embed = public_url or local_url
    clear_output(wait=True)
    display(
        HTML(
            f"""
<div style="font-family:Segoe UI,PingFang SC,Microsoft YaHei,sans-serif;color:#e5e7eb">
  <div style="padding:12px 14px;border-radius:12px;background:#0f172a;border:1px solid #334155;margin-bottom:10px">
    <b style="color:#99f6e4;font-size:20px">PrivateLocalAgent</b>
    <span style="color:#94a3b8;margin-left:8px">真实智能体 · 本地推理 · 可上传</span>
    <div style="margin-top:8px;font-size:13px;line-height:1.7">
      <a href="{escape(embed)}" target="_blank" rel="noopener" style="color:#5eead4">打开外部完整界面</a>
      &nbsp;|&nbsp; 本机 <code style="color:#fbbf24">{escape(local_url)}</code>
      {f'&nbsp;|&nbsp; 公网 <code style="color:#fbbf24">{escape(public_url)}</code>' if public_url else ''}
    </div>
  </div>
  <iframe src="{escape(embed)}" title="PrivateLocalAgent"
    style="width:100%;height:800px;border:1px solid #334155;border-radius:14px;background:#0b1220"></iframe>
</div>
"""
        )
    )


class NotebookVisualChat:
    def __init__(
        self,
        runner: Any,
        plan_fn: Callable[[str], list[str]] | None = None,
        default_mode: str = "chat",
        upload_dir: Path | str | None = None,
    ) -> None:
        self.runner = runner
        self.plan_fn = plan_fn
        self.mode = default_mode
        self.history: list[dict[str, Any]] = []
        self.port: int | None = None
        self.local_url: str | None = None
        self.public_url: str | None = None
        tools = getattr(runner, "tools", None)
        ud = upload_dir or getattr(tools, "upload_dir", None)
        if ud:
            self.upload_dir = Path(ud)
        else:
            from src.config import load_settings

            self.upload_dir = load_settings().resolve("data/uploads")
        self.upload_dir.mkdir(parents=True, exist_ok=True)

    def ask(self, query: str, mode: str | None = None) -> str:
        if mode:
            self.mode = mode
        result = self.runner.run(query, mode=self.mode)
        turn = {
            "q": query,
            "a": getattr(result, "answer", str(result)),
            "tools": list(getattr(result, "used_tools", None) or []),
            "mode": getattr(result, "app_mode", None) or self.mode,
        }
        self.history.append(turn)
        return str(turn["a"])

    def show(self, use_widgets: bool | None = None) -> None:  # noqa: ARG002
        prefer = int(os.getenv("PLA_NOTEBOOK_UI_PORT", "7900") or 7900)
        port = start_web_for_orch(self.runner, self.mode, port=prefer)
        self.port = port
        self.local_url = f"http://127.0.0.1:{port}/"
        try:
            self.public_url = expose_rc_tunnel(port)
        except Exception as exc:  # noqa: BLE001
            print(f"[ui] rc-tunnel failed: {exc}", flush=True)
            self.public_url = None
        display_agent_ui(self.local_url, self.public_url)


def launch_notebook_visual(
    runner: Any,
    plan_fn: Callable[[str], list[str]] | None = None,
    default_mode: str = "chat",
    upload_dir: Path | str | None = None,
) -> NotebookVisualChat:
    ui = NotebookVisualChat(
        runner,
        plan_fn=plan_fn,
        default_mode=default_mode,
        upload_dir=upload_dir,
    )
    ui.show()
    return ui
