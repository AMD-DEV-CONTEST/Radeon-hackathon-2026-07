"""Gateway Layer 4 — reliability: pre-launch validation + daemonize.

Prevents the silent failures documented in HANDOFF_GATEWAY_RELOCATION §5.5/§6:
  * port already in use -> refuse to start (and the box has no ss/lsof/fuser,
    so we parse /proc/net/tcp, see docs/TRUTH.md §6.5).
  * llama-server binary missing -> refuse.
  * model / LoRA GGUF missing -> refuse.
  * daemon: launch under setsid so the server survives the SSH session that
    spawned it (nohup & alone gets reaped by the platform).

Pure stdlib + subprocess; no torch/CUDA import.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field


@dataclass
class CheckResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)
        self.ok = False


def _port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """Check a TCP port without ss/lsof/fuser (parse /proc/net/tcp).

    Matches both 127.0.0.1 (0100007F) and 0.0.0.0 (00000000) listeners.
    Falls back to a socket connect if /proc is unavailable (non-Linux).
    """
    hex_port = f"{port:04X}"
    candidates = {"0100007F", "00000000"}  # 127.0.0.1 and 0.0.0.0
    for fname in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(fname) as fh:
                for line in fh.readlines()[1:]:
                    parts = line.split()
                    if len(parts) < 4:
                        continue
                    local = parts[1]
                    state = parts[3]
                    # local looks like 0100007F:1F90 ; state 0A = LISTEN
                    addr, _, p = local.partition(":")
                    if p.upper() == hex_port and addr.upper() in candidates \
                            and state.upper() == "0A":
                        return True
        except OSError:
            continue
    # fallback: try a real connect
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        try:
            s.connect((host, port))
            return True
        except OSError:
            return False


def validate_paths(model_path: str, lora_paths: list[str] | None = None,
                   binary: str = "llama-server") -> CheckResult:
    res = CheckResult(ok=True)
    if not os.path.isfile(model_path):
        res.add_error(f"底模文件缺失：{model_path}")
    for lp in (lora_paths or []):
        if not os.path.isfile(lp):
            res.add_error(f"LoRA 权重缺失：{lp}")
    # binary may be a bare name on PATH or an absolute path
    if os.path.sep in binary:
        if not os.path.isfile(binary):
            res.add_error(f"llama-server 二进制缺失：{binary}")
    elif not _which(binary):
        res.add_error(f"llama-server 二进制不在 PATH：{binary}")
    return res


def _which(name: str) -> bool:
    from shutil import which
    return which(name) is not None


def prelaunch_check(model_path: str, port: int = 8080,
                    lora_paths: list[str] | None = None,
                    binary: str = "llama-server",
                    extra_ports: list[int] | None = None) -> CheckResult:
    res = validate_paths(model_path, lora_paths, binary)
    if _port_in_use(port):
        res.add_error(f"端口 {port} 已被占用，启动前请先释放。")
    for p in (extra_ports or []):
        if _port_in_use(p):
            res.add_error(f"端口 {p} 已被占用，启动前请先释放。")
    if not res.ok:
        res.warnings.append("校验未通过：已停止启动，避免静默退出。")
    return res


def daemonize(argv: list[str], *, log_path: str | None = None,
              cwd: str | None = None) -> subprocess.Popen:
    """Launch ``argv`` under setsid so it outlives the spawning SSH session.

    Returns the Popen. Never use bare ``nohup ... &`` here — the platform reaps
    it (HANDOFF §6). stdout/stderr go to ``log_path`` (or DEVNULL) so the
    detached process does not hold the controlling terminal.
    """
    import sys
    out = open(log_path, "ab") if log_path else open(os.devnull, "wb")
    proc = subprocess.Popen(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=out,
        stderr=out,
        cwd=cwd,
        start_new_session=True,          # equivalent to setsid(1)
        close_fds=True,
    )
    return proc
