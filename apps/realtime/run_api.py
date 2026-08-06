#!/usr/bin/env python3
"""
启动 apps/realtime 的 FastAPI 服务 (:8002, HTTPS)

用法:
    cd apps/realtime
    python run_api.py          # HTTPS (default, auto-generates self-signed cert)
    python run_api.py --http   # plain HTTP (fallback)
"""

import io
import os
import sys
from pathlib import Path

# Windows 控制台默认 cp936 / gbk, convert_to_lerobot.py 里的 emoji print 会抛
# UnicodeEncodeError. 这里显式把 stdout/stderr 切 utf-8, 否则录制停止时 parquet
# 转换会因 print 失败而中断.
for _stream_name in ("stdout", "stderr"):
    _stream = getattr(sys, _stream_name)
    if hasattr(_stream, "buffer") and getattr(_stream, "encoding", "").lower() != "utf-8":
        try:
            setattr(
                sys,
                _stream_name,
                io.TextIOWrapper(_stream.buffer, encoding="utf-8", line_buffering=True),
            )
        except Exception:
            pass

# 让 `api` 包可被 import (因为 main.py 使用 from .websocket import ...)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)


def _reexec_with_project_venv() -> None:
    """Use apps/realtime/.venv when the caller picked another Python (e.g. ~/venvs/lerobot).

    Both venvs may symlink to the same system python binary; compare sys.prefix instead.
    """
    venv_dir = (Path(SCRIPT_DIR) / ".venv").resolve()
    venv_py = venv_dir / "bin" / "python"
    if not venv_py.is_file():
        return
    if Path(sys.prefix).resolve() == venv_dir:
        return
    env = os.environ.copy()
    env["VIRTUAL_ENV"] = str(venv_dir)
    env["PATH"] = str(venv_dir / "bin") + os.pathsep + env.get("PATH", "")
    os.execve(str(venv_py), [str(venv_py), *sys.argv], env)


_reexec_with_project_venv()

# 暴露 monorepo 里的 botclaw_spec 包
_SPEC_PY = os.path.abspath(os.path.join(SCRIPT_DIR, "..", "..", "packages", "botclaw-spec", "python"))
if os.path.isdir(_SPEC_PY) and _SPEC_PY not in sys.path:
    sys.path.insert(0, _SPEC_PY)

import uvicorn

# ---------------------------------------------------------------------------
# Self-signed localhost certificate generation
# ---------------------------------------------------------------------------
CERTS_DIR = os.path.join(SCRIPT_DIR, "certs")
CERT_FILE = os.path.join(CERTS_DIR, "localhost.pem")
KEY_FILE = os.path.join(CERTS_DIR, "localhost-key.pem")


def _ensure_localhost_cert() -> bool:
    """Generate a self-signed cert for localhost if not present. Returns True on success."""
    if os.path.isfile(CERT_FILE) and os.path.isfile(KEY_FILE):
        return True
    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        import datetime as _dt
        import ipaddress

        os.makedirs(CERTS_DIR, exist_ok=True)

        key = ec.generate_private_key(ec.SECP256R1())

        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, "BotverseX Local Agent"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "BotverseX"),
        ])

        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(_dt.datetime.now(_dt.timezone.utc))
            .not_valid_after(_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(days=3650))
            .add_extension(
                x509.SubjectAlternativeName([
                    x509.DNSName("localhost"),
                    x509.DNSName("127.0.0.1"),
                    x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
                    x509.IPAddress(ipaddress.IPv6Address("::1")),
                ]),
                critical=False,
            )
            .add_extension(
                x509.BasicConstraints(ca=True, path_length=0),
                critical=True,
            )
            .sign(key, hashes.SHA256())
        )

        with open(KEY_FILE, "wb") as f:
            f.write(key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            ))

        with open(CERT_FILE, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))

        print(f"[SSL] Generated self-signed certificate: {CERT_FILE}")
        return True

    except ImportError:
        print("[SSL] 'cryptography' package not installed — falling back to HTTP.")
        print("[SSL]   pip install cryptography")
        return False
    except Exception as e:
        print(f"[SSL] Failed to generate certificate: {e}")
        return False


def main():
    # Dev machines often keep LeRobot in ~/venvs/lerobot while uvicorn uses apps/realtime/.venv.
    lerobot_venv = Path.home() / "venvs" / "lerobot"
    if lerobot_venv.is_dir() and not os.environ.get("REBOT_LEROBOT_VENV"):
        os.environ.setdefault("REBOT_LEROBOT_VENV", str(lerobot_venv))

    use_https = "--http" not in sys.argv and _ensure_localhost_cert()

    proto = "https" if use_https else "http"
    ws_proto = "wss" if use_https else "ws"

    print("=" * 60)
    print("BotverseX Local Agent (apps/realtime)")
    print("=" * 60)
    print(f"API:                {proto}://localhost:8002")
    print(f"WebSocket (teleop): {ws_proto}://localhost:8002/ws/teleop")
    print(f"WebSocket (UI):     {ws_proto}://localhost:8002/ws/ui")
    print(f"Health check:       {proto}://localhost:8002/api/setup/health")
    if use_https:
        print(f"SSL cert:           {CERT_FILE}")
        print()
        print("NOTE: Your browser may warn about the self-signed certificate.")
        print(f"      Visit {proto}://localhost:8002 once and accept to trust it.")
    else:
        print()
        print("DEV: plain HTTP mode. Vite dev server proxies /api → :8002 — use this for B601 URDF/meshes.")
        print("     Restart Agent after code changes: pkill -f run_api.py; python run_api.py --http")
    print("=" * 60)

    ssl_kwargs = {}
    if use_https:
        ssl_kwargs["ssl_keyfile"] = KEY_FILE
        ssl_kwargs["ssl_certfile"] = CERT_FILE

    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=8002,
        reload=False,
        log_level="info",
        timeout_keep_alive=30,
        timeout_graceful_shutdown=5,
        limit_concurrency=200,
        **ssl_kwargs,
    )


if __name__ == "__main__":
    main()
