#!/usr/bin/env python3
"""Start Doubao-style web UI + Cloudflare quick tunnel (trycloudflare.com)."""

from __future__ import annotations

import os
import shutil
import ssl
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PORT = int(os.getenv("HTTP_PORT", "7900"))


def _ensure_persistence_env(env: dict[str, str]) -> None:
    persist = Path("/workspace/persistence")
    if not persist.is_dir():
        return
    data_root = env.get("PLA_DATA_ROOT") or str(persist / "PrivateLocalAgent")
    hf_home = env.get("HF_HOME") or str(persist / "huggingface")
    Path(data_root).mkdir(parents=True, exist_ok=True)
    Path(hf_home).mkdir(parents=True, exist_ok=True)
    env.setdefault("PLA_DATA_ROOT", data_root)
    env.setdefault("HF_HOME", hf_home)
    env.setdefault("HF_ENDPOINT", env.get("HF_ENDPOINT", "https://hf-mirror.com"))
    print(f"[persistence] PLA_DATA_ROOT={env['PLA_DATA_ROOT']}")
    print(f"[persistence] HF_HOME={env['HF_HOME']}")


def _download(url: str, target: Path, *, allow_insecure: bool = False) -> None:
    """Download cloudflared. Prefer TLS verify; insecure only as explicit fallback."""
    target.parent.mkdir(parents=True, exist_ok=True)
    curl = shutil.which("curl")
    if curl:
        cmd = [curl, "-fsSL", "-o", str(target), url]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode == 0 and target.exists() and target.stat().st_size > 1_000_000:
            return
        if allow_insecure:
            print("[cloudflare] WARNING: retrying download with TLS verify disabled", flush=True)
            r = subprocess.run([curl, "-kfsSL", "-o", str(target), url], capture_output=True, text=True)
            if r.returncode == 0 and target.exists() and target.stat().st_size > 1_000_000:
                return

    wget = shutil.which("wget")
    if wget:
        args = ["-O", str(target), url]
        if allow_insecure:
            args = ["--no-check-certificate", *args]
            print("[cloudflare] WARNING: wget without certificate check", flush=True)
        r = subprocess.run([wget, *args], capture_output=True, text=True)
        if r.returncode == 0 and target.exists() and target.stat().st_size > 1_000_000:
            return

    if allow_insecure:
        print("[cloudflare] WARNING: urllib download with unverified TLS", flush=True)
        ctx = ssl._create_unverified_context()
    else:
        ctx = ssl.create_default_context()
    with urllib.request.urlopen(url, context=ctx, timeout=120) as resp, target.open("wb") as f:
        shutil.copyfileobj(resp, f)


def ensure_cloudflared() -> str:
    existing = shutil.which("cloudflared")
    if existing:
        return existing

    for p in ("/usr/local/bin/cloudflared", "/usr/bin/cloudflared"):
        if Path(p).exists():
            return p

    bin_dir = ROOT / ".tools"
    bin_dir.mkdir(parents=True, exist_ok=True)
    target = bin_dir / ("cloudflared.exe" if os.name == "nt" else "cloudflared")
    if target.exists() and target.stat().st_size > 1_000_000:
        return str(target)

    urls = []
    if os.name == "nt":
        urls.append(
            "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
        )
    else:
        urls.append(
            "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64"
        )

    last_err: Exception | None = None
    for url in urls:
        for insecure in (False, True):
            try:
                print(f"[cloudflare] downloading {url} (insecure={insecure})")
                if target.exists():
                    target.unlink()
                _download(url, target, allow_insecure=insecure)
                if os.name != "nt":
                    target.chmod(0o755)
                if target.exists() and target.stat().st_size > 1_000_000:
                    return str(target)
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                print(f"[cloudflare] download failed: {exc}")

    raise RuntimeError(
        "无法自动下载 cloudflared。请在终端手动安装官方二进制后重试（勿用不明镜像）。\n"
        "  curl -L -o .tools/cloudflared "
        "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64\n"
        "  chmod +x .tools/cloudflared\n"
        f"原始错误: {last_err}"
    )


def wait_health(port: int, seconds: int = 30) -> None:
    import urllib.error

    url = f"http://127.0.0.1:{port}/healthz"
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return
        except Exception:  # noqa: BLE001
            time.sleep(1)
    print("[web] health check timeout — continuing anyway")


def main() -> None:
    env = os.environ.copy()
    env["HTTP_HOST"] = "127.0.0.1"
    env["HTTP_PORT"] = str(PORT)
    _ensure_persistence_env(env)

    print(f"[web] starting PrivateLocalAgent studio on http://127.0.0.1:{PORT}")
    web = subprocess.Popen(
        [sys.executable, str(ROOT / "scripts" / "web_http_demo.py")],
        cwd=str(ROOT),
        env=env,
    )
    wait_health(PORT)
    try:
        cf = ensure_cloudflared()
    except Exception as exc:  # noqa: BLE001
        web.terminate()
        raise SystemExit(str(exc)) from exc

    print("[cloudflare] quick tunnel (no login). Public URL prints below.")
    print("[cloudflare] >>> 打开网页: 使用下方 https://xxxx.trycloudflare.com")
    print("[cloudflare] >>> 页面左侧「评委清单」与 Demo 视频同一套问题")
    print("[cloudflare] Keep this terminal open while demoing.")
    try:
        subprocess.call([cf, "tunnel", "--url", f"http://127.0.0.1:{PORT}"])
    finally:
        web.terminate()
        try:
            web.wait(timeout=5)
        except Exception:  # noqa: BLE001
            web.kill()


if __name__ == "__main__":
    main()
