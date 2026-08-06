"""Gateway orchestration entry — one command to bring up the whole stack.

Pipeline (Gateway Layer 5):
    resolve config  ->  prelaunch checks  ->  setsid daemon llama-server
                      ->  wait for /health  ->  launch relay (uvicorn)

Relay keeps its thin forwarding + MoL routing role (Layer2 §2 three-plane
boundary); the coordinator remains the sole owner of global LoRA / queue / lock.
We do NOT expose the raw /lora-adapters endpoint (security boundary) and we do
NOT move global state into the gateway.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time

from screwshell.gateway.config import ServerConfig
from screwshell.gateway.capacity import plan_fit
from screwshell.gateway import capacity as _cap
from screwshell.gateway.reliability import (
    daemonize, prelaunch_check, validate_paths,
)

log = logging.getLogger("screwshell.gateway")

RELAY_PORT = int(os.getenv("RELAY_PORT", "18090"))
LLAMA_PORT = int(os.getenv("LLAMA_PORT", "8080"))

# These mirror local-deploy/start_relay.sh so a relay launched via the gateway
# CLI keeps the same observability / trust / upstream behaviour as a manually
# launched one. cli.py used to set only RELAY_BIND_ADDR + RELAY_PORT, which left
# OBSERV_DIR unset -> observ store disabled -> /v1/observ/* empty in the UI.
RELAY_TRUST_TOKEN = os.getenv("RELAY_TRUST_TOKEN", "screwshell-relay-devtoken")
RELAY_LLAMA_URL = os.getenv("RELAY_LLAMA_URL", "http://127.0.0.1:8080")
_DEFAULT_OBSERV_DIR = os.getenv(
    "OBSERV_DIR",
    os.path.join(os.getcwd(), "screwshell_run", "observ"))


def _wait_health(url: str, timeout: float = 120.0, interval: float = 2.0) -> bool:
    import httpx
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = httpx.get(url, timeout=5.0)
            if r.status_code == 200:
                return True
        except Exception:  # noqa: BLE001 - server not up yet
            pass
        time.sleep(interval)
    return False


def bring_up(cfg: ServerConfig,
             llama_binary: str = "llama-server",
             relay_bind: str = "127.0.0.1",
             llama_log: str | None = None,
             relay_log: str | None = None,
             observ_dir: str = _DEFAULT_OBSERV_DIR,
             health_timeout: float = 120.0) -> dict:
    """Generate config, validate, daemonize llama-server, then launch relay.

    Returns a status dict. Raises RuntimeError on prelaunch failure (so the
    caller / CLI can exit non-zero instead of silently proceeding).
    """
    check = prelaunch_check(
        cfg.model_path, port=cfg.port, lora_paths=cfg.lora_paths,
        binary=llama_binary, extra_ports=[RELAY_PORT])
    if not check.ok:
        raise RuntimeError("prelaunch 校验未通过：\n  - " + "\n  - ".join(check.errors))

    # locate llama-fit-params next to the llama-server binary so ngl resolution
    # does not depend on PATH (fit lives in the same build dir).
    import os as _os
    import shutil as _shutil
    import time as _time
    _llama_dir = _os.path.dirname(llama_binary)
    _fit_binary = _os.path.join(_llama_dir, "llama-fit-params")

    # Resolve llama-fit-params ONCE and cache it on the config so to_argv /
    # command_line never re-run the (slow, 27B-loading) fit subprocess. fit can
    # momentarily drop the ngl value (bare "-ngl") while the previous
    # llama-server is still releasing VRAM right after a restart kill, so we
    # retry a few times — BUT only if the binary actually exists. If fit is
    # absent we skip the loop entirely and fall back without blocking startup.
    if _os.path.sep in _fit_binary or _shutil.which(_fit_binary):
        _fit_out = None
        for _attempt in range(4):
            _fit_out = _cap.fit_params(cfg.model_path, binary=_fit_binary)
            if _fit_out is not None:
                break
            _time.sleep(3)
        cfg.fit_result = _fit_out
        if _fit_out is None:
            log.warning("llama-fit-params 不可用，回退到默认 n_gpu_layers（不写死 999 旁路 fit）。")
        else:
            log.info("llama-fit-params 实测：ctx=%s ngl=%s", _fit_out["ctx"], _fit_out["ngl"])
    else:
        log.info("llama-fit-params 未找到（%s），跳过 fit，回退默认 n_gpu_layers。", _fit_binary)

    # to_argv / command_line reuse cfg.fit_result (no second fit subprocess).
    argv = cfg.to_argv(llama_binary, fit_binary=_fit_binary)
    log.info("launching llama-server: %s", cfg.command_line(llama_binary))
    llama_proc = daemonize(argv, log_path=llama_log, cwd=os.getcwd())

    if not _wait_health(f"http://{cfg.host}:{cfg.port}/health", health_timeout):
        llama_proc.kill()
        raise RuntimeError("llama-server 启动后未能在超时内响应 /health")

    # launch the relay (thin gateway) in-process via uvicorn in a thread so a
    # single command owns both; relay stays a thin forwarder (Layer2 §2).
    relay_proc = _launch_relay(relay_bind, relay_log, observ_dir=observ_dir)
    return {
        "llama_pid": llama_proc.pid,
        "relay_pid": relay_proc.pid,
        "llama_argv": argv,
        "relay_bind": relay_bind,
        "relay_port": RELAY_PORT,
    }


def _launch_relay(bind: str, log_path: str | None,
                  observ_dir: str = _DEFAULT_OBSERV_DIR) -> "object":
    """Start the relay under uvicorn in a detached subprocess.

    Returns the Popen. We daemonize it too (setsid) so the whole stack survives
    the spawning SSH session. Importing uvicorn only here keeps gateway import
    cheap on headless boxes.

    Propagates the production relay env (OBSERV_DIR / RELAY_TRUST_TOKEN /
    RELAY_LLAMA_URL) so a gateway-launched relay behaves identically to one
    started via local-deploy/start_relay.sh -- otherwise observ store is
    disabled and /v1/observ/* shows empty in the UI.
    """
    import screwshell.gateway.relay as relay_mod
    argv = [sys.executable, "-m", "screwshell.gateway.relay"]
    env = dict(os.environ)
    env["RELAY_BIND_ADDR"] = bind
    env["RELAY_PORT"] = str(RELAY_PORT)
    env["RELAY_TRUST_TOKEN"] = RELAY_TRUST_TOKEN
    env["RELAY_LLAMA_URL"] = RELAY_LLAMA_URL
    env["OBSERV_DIR"] = observ_dir
    out = open(log_path, "ab") if log_path else open(os.devnull, "wb")
    return subprocess_popen_daemon(argv, env, out)


def subprocess_popen_daemon(argv, env, out):
    import subprocess
    return subprocess.Popen(
        argv, env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=out,
        start_new_session=True, close_fds=True)


def _build_config_from_args(args: argparse.Namespace) -> ServerConfig:
    lora_paths = []
    if args.loras:
        for item in args.loras.split(","):
            item = item.strip()
            if item:
                lora_paths.append(item)

    # When no explicit ctx-size was given, prefer llama-fit-params (authoritative
    # per-model/per-GPU) over the self-written formula. plan_fit falls back to
    # the formula (capped at 131072) if fit is unavailable.
    ctx_tokens = args.ctx_size
    if ctx_tokens is None and args.vram_gb:
        ctx_tokens = plan_fit(args.model, args.vram_gb, quant=args.quant,
                              wanted_ctx=131072).ctx_tokens

    cfg = ServerConfig(
        model_path=args.model,
        lora_paths=lora_paths,
        quant=args.quant,
        host=args.host,
        port=args.port,
        threads=args.threads,
        n_gpu_layers=args.n_gpu_layers,
        reasoning_budget=args.reasoning_budget,
        ctx_tokens=ctx_tokens,
        vram_total_gb=args.vram_gb,
    )
    # 4b (optional): expose llama.cpp /metrics for the relay's global view.
    # Forwarded as a raw extra arg so it reaches the llama-server argv verbatim.
    if args.metrics:
        cfg.extra_args = list(cfg.extra_args) + ["--metrics"]
    return cfg


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="screwshell-gateway",
                                description="bring up llama-server + relay")
    p.add_argument("--model", required=True, help="path to base GGUF")
    p.add_argument("--loras", default="",
                   help="comma-separated LoRA .gguf paths (single --lora value)")
    p.add_argument("--quant", default=None)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=LLAMA_PORT)
    p.add_argument("--threads", type=int, default=24)
    p.add_argument("--n-gpu-layers", type=int, default=None,
                   help="default: derive from llama-fit-params (no 999 bypass)")
    p.add_argument("--reasoning-budget", type=int, default=4096,
                   help="finite; never -1 (avoids HANDOFF §6 deadlock)")
    p.add_argument("--ctx-size", type=int, default=None,
                   help="override capacity-derived ctx")
    p.add_argument("--vram-gb", type=float, default=None,
                   help="total VRAM for capacity-derived ctx")
    p.add_argument("--llama-binary", default="llama-server")
    p.add_argument("--llama-log", default=None)
    p.add_argument("--relay-log", default=None)
    p.add_argument("--relay-bind", default="127.0.0.1")
    p.add_argument("--health-timeout", type=float, default=120.0)
    p.add_argument("--metrics", action="store_true",
                   help="enable llama.cpp /metrics endpoint (prometheus counters)")
    p.add_argument("--json", action="store_true", help="print status as JSON")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO)
    try:
        cfg = _build_config_from_args(args)
        status = bring_up(cfg, llama_binary=args.llama_binary,
                          relay_bind=args.relay_bind,
                          llama_log=args.llama_log, relay_log=args.relay_log,
                          health_timeout=args.health_timeout)
    except RuntimeError as e:
        log.error("%s", e)
        return 1
    if args.json:
        print(json.dumps(status, indent=2))
    else:
        log.info("stack up: llama pid=%s relay pid=%s",
                 status["llama_pid"], status["relay_pid"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
