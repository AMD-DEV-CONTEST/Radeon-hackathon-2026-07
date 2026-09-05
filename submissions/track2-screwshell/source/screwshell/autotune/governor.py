#!/usr/bin/env python3
"""L3 runtime governor: dual-mode LoRA scheduling + conservative gear machine.

Two scheduling modes (decided by available VRAM vs. what the roster needs):
  * "roomy" : all adapters preloaded; swap via llama.cpp scale hot-toggle
              (~0.65ms on W7900, zero restart). No restart-swap needed.
  * "tight" : VRAM can't hold the whole roster preloaded. Swap experts by
              restarting llama-server with a different `--lora` set
              (llama-swap style). One swap == one full 27B base reload.
              Measured on W7900: ~4.6-5.1s each, ~19.4s worst for a 4-expert
              task. Mitigated by step clustering + predictive prewarm.

Conservative gear machine (observes -> decides -> adjusts, never online-optimizes):
  * tok/s sustained below threshold  -> drop ctx gear (8192->6144->4096...).
  * empty-answer rate high           -> disable thinking / shrink max_tokens
                                        (the G3 "thinking eats the context"
                                         fake-empty trap we already hit).
  * VRAM > 90%                       -> enable KV quantization.
  * exceeding the per-task swap cap  -> emit an alert, suggest narrowing scope.

Nothing here talks to a GPU at import time; every decision primitive is a pure
function so it is unit-testable without hardware. The only hardware-touching
piece is `LlamaServerLifecycle`, which is isolated and mockable.
"""
from __future__ import annotations

import glob
import json
import os
import re
import signal
import socket
import subprocess
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Callable


# ----------------------------- data types -----------------------------

@dataclass
class RuntimeMetrics:
    tokens_per_s: float = 0.0
    empty_rate: float = 0.0      # fraction of empty/garbage answers in window
    vram_pct: float = 0.0        # 0-100 (0 = unknown/not measured)
    ctx_tokens: int = 0          # current context window
    thinking_on: bool = True
    kv_quant: str = "none"       # none | q8_0 | q4_0 ...


@dataclass
class GovernorAction:
    kind: str                    # swap_expert | set_ctx | set_thinking |
                                 # set_kv_quant | alert
    payload: dict = field(default_factory=dict)
    reason: str = ""


@dataclass
class SwapStep:
    step_id: str
    expert: str                  # adapter/pack name, or "base"
    deps: list[str] = field(default_factory=list)


@dataclass
class SwapPlan:
    order: list[str]             # step_ids in execution order
    clusters: list[list[str]]    # consecutive same-expert groups
    swaps: int                   # expert changes across the plan
    feasible: bool = True


@dataclass
class GovernorConfig:
    tok_s_low: float = 12.0
    low_streak: int = 3
    empty_rate_high: float = 0.30
    vram_high: float = 90.0
    ctx_gears: tuple = (8192, 6144, 4096, 3072)
    max_swaps_per_task: int = 8
    # how many consecutive "good" observations before we may recover one ctx gear
    recover_streak: int = 30


# ----------------------------- mode selection -----------------------------

def select_mode(avail_vram_gb: float, roster_load_gb: float) -> str:
    """Return 'roomy' if all adapters fit preloaded, else 'tight'.

    avail_vram_gb  : free VRAM the server may use.
    roster_load_gb : base + sum of every adapter that would be preloaded.
    """
    if avail_vram_gb >= roster_load_gb:
        return "roomy"
    return "tight"


# ----------------------------- step clustering -----------------------------

def cluster_steps(steps: list[SwapStep]) -> SwapPlan:
    """Dependency-aware greedy clustering to minimize expert swaps.

    Among currently-runnable steps (all deps already scheduled), we prefer one
    sharing the *currently mounted* expert to avoid a swap. This keeps a valid
    topological order while grouping same-expert work together.

    Returns SwapPlan with `swaps` = number of expert changes (initial mount is
    NOT counted as a swap).
    """
    by_id = {s.step_id: s for s in steps}
    scheduled: set[str] = set()
    order: list[str] = []
    mounted: str | None = None
    swaps = 0

    def runnable() -> list[SwapStep]:
        out = []
        for s in steps:
            if s.step_id in scheduled:
                continue
            if all(d in scheduled for d in s.deps):
                out.append(s)
        return out

    remaining = len(steps)
    guard = remaining * remaining + 1  # safety against logic bugs
    while remaining > 0 and guard > 0:
        guard -= 1
        avail = runnable()
        if not avail:
            # cycle / unsatisfiable deps -> mark infeasible, stop
            return SwapPlan(order=order, clusters=[], swaps=swaps, feasible=False)
        # prefer same expert as currently mounted
        pick = next((x for x in avail if x.expert == mounted), avail[0])
        if mounted is None:
            mounted = pick.expert          # first mount, not a swap
        elif pick.expert != mounted:
            mounted = pick.expert
            swaps += 1
        order.append(pick.step_id)
        scheduled.add(pick.step_id)
        remaining -= 1

    # build consecutive same-expert clusters from order
    clusters: list[list[str]] = []
    for sid in order:
        exp = by_id[sid].expert
        if clusters and clusters[-1] and by_id[clusters[-1][0]].expert == exp:
            clusters[-1].append(sid)
        else:
            clusters.append([sid])
    return SwapPlan(order=order, clusters=clusters, swaps=swaps, feasible=True)


# ----------------------------- gear machine -----------------------------

class Governor:
    """Conservative runtime feedback loop. Pure decisions; no GPU access."""

    def __init__(self, config: GovernorConfig | None = None,
                 mode: str = "auto", initial_ctx: int = 8192):
        self.cfg = config or GovernorConfig()
        self.mode = mode                      # "roomy" | "tight" | "auto"
        self._low_streak = 0
        self._good_streak = 0
        self._ctx_idx = self._nearest_gear(initial_ctx)
        self._thinking_on = True
        self._kv_quant = "none"
        self._swap_count = 0

    def _nearest_gear(self, ctx: int) -> int:
        # index of the smallest gear >= ctx, clamped
        for i, g in enumerate(self.cfg.ctx_gears):
            if ctx <= g:
                return i
        return len(self.cfg.ctx_gears) - 1

    def reset_swap_count(self) -> None:
        self._swap_count = 0

    def note_swap(self) -> None:
        self._swap_count += 1

    def observe(self, m: RuntimeMetrics) -> list[GovernorAction]:
        actions: list[GovernorAction] = []

        # 1) tok/s too low for a sustained streak -> drop one ctx gear
        if m.tokens_per_s > 0 and m.tokens_per_s < self.cfg.tok_s_low:
            self._low_streak += 1
        else:
            self._low_streak = 0
        if self._low_streak >= self.cfg.low_streak and self._ctx_idx < len(self.cfg.ctx_gears) - 1:
            self._ctx_idx += 1
            self._low_streak = 0
            self._good_streak = 0
            actions.append(GovernorAction(
                kind="set_ctx", payload={"ctx": self.cfg.ctx_gears[self._ctx_idx]},
                reason=f"tok/s {m.tokens_per_s:.1f} < {self.cfg.tok_s_low} for "
                       f"{self.cfg.low_streak} samples"))

        # 2) empty-answer rate high -> disable thinking / shrink headroom
        if m.empty_rate > self.cfg.empty_rate_high and self._thinking_on:
            self._thinking_on = False
            actions.append(GovernorAction(
                kind="set_thinking", payload={"thinking": False},
                reason=f"empty_rate {m.empty_rate:.0%} > {self.cfg.empty_rate_high:.0%} "
                       f"(G3 thinking-eats-context trap)"))

        # 3) VRAM pressure -> enable KV quantization
        if m.vram_pct >= self.cfg.vram_high and self._kv_quant == "none":
            self._kv_quant = "q8_0"
            actions.append(GovernorAction(
                kind="set_kv_quant", payload={"kv_quant": "q8_0"},
                reason=f"VRAM {m.vram_pct:.0f}% >= {self.cfg.vram_high:.0f}%"))

        # 4) slow recovery: if everything good for a long while, recover one gear
        good = (m.tokens_per_s >= self.cfg.tok_s_low and
                m.empty_rate <= self.cfg.empty_rate_high and
                (m.vram_pct == 0 or m.vram_pct < self.cfg.vram_high))
        if good:
            self._good_streak += 1
        else:
            self._good_streak = 0
        if (self._good_streak >= self.cfg.recover_streak and
                self._ctx_idx > 0):
            self._ctx_idx -= 1
            self._good_streak = 0
            actions.append(GovernorAction(
                kind="set_ctx", payload={"ctx": self.cfg.ctx_gears[self._ctx_idx]},
                reason="sustained healthy metrics, recovering one ctx gear"))

        return actions

    def swap_cap_exceeded(self) -> GovernorAction | None:
        if self._swap_count > self.cfg.max_swaps_per_task:
            return GovernorAction(
                kind="alert",
                payload={"swaps": self._swap_count,
                         "cap": self.cfg.max_swaps_per_task},
                reason="per-task swap cap exceeded; consider narrowing scope "
                       "to fewer experts")
        return None


# ----------------------------- server lifecycle -----------------------------

def _port_free(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) != 0


def _wait_port_free(port: int, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _port_free(port):
            return True
        time.sleep(0.5)
    return _port_free(port)


def _listener_pid(port: int) -> str | None:
    """Find the PID of the process listening on TCP `port` via /proc."""
    hexport = f"{port:04X}"
    for proto in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(proto) as f:
                next(f)
                for line in f:
                    parts = line.split()
                    if len(parts) < 10:
                        continue
                    if parts[3] != "0A":          # 0A = LISTEN
                        continue
                    if parts[1].split(":")[-1].upper() != hexport:
                        continue
                    inode = parts[9]
                    for fdlink in glob.glob("/proc/[0-9]*/fd/*"):
                        try:
                            if os.readlink(fdlink).endswith(f"socket:[{inode}]"):
                                return fdlink.split("/")[2]
                        except Exception:
                            pass
        except Exception:
            continue
    return None


def _health_ok(url: str, timeout: float = 2.0) -> bool:
    try:
        urllib.request.urlopen(url, timeout=timeout)
        return True
    except Exception:
        return False


class LlamaServerLifecycle:
    """Manage a single llama-server process: start / stop / restart-with-lora.

    Used ONLY in 'tight' mode for restart-swap. Kill scope is our own process
    group; takeover (killing a pre-existing listener) is explicit and opt-in.
    """

    def __init__(self, launch_cmd_template: str, port: int = 8080,
                 health_path: str = "/health", serve_timeout: float = 180.0,
                 log_path: str = "llama_server.log"):
        self.launch_cmd_template = launch_cmd_template
        self.port = port
        self.health_url = f"http://127.0.0.1:{port}{health_path}"
        self.serve_timeout = serve_timeout
        self.log_path = log_path
        self._proc = None
        self.current_lora = None
        # runtime-tunable launch params (fed by the governor gear machine).
        # Use {ctx} / {kv} placeholders in the template to opt in; otherwise the
        # server's statically configured values are used.
        self.ctx_tokens: int = 8192
        self.kv_quant: str = "none"

    def _ensure_port_free(self, takeover: bool = False) -> None:
        if _port_free(self.port):
            return
        if takeover:
            pid = _listener_pid(self.port)
            if pid:
                try:
                    os.kill(int(pid), signal.SIGTERM)
                except Exception:
                    pass
            _wait_port_free(self.port, timeout=15.0)
        else:
            raise RuntimeError(
                f"port {self.port} occupied by another process; pass "
                f"takeover=True to interrupt it, or use a different port")

    def _render_cmd(self, lora: str) -> str:
        cmd = self.launch_cmd_template
        cmd = cmd.replace("{lora}", lora)
        cmd = cmd.replace("{ctx}", str(self.ctx_tokens))
        cmd = cmd.replace("{kv}", self.kv_quant)
        # base-only expert: drop the --lora token entirely
        if not lora:
            cmd = re.sub(r"\s*--lora\s+", " ", cmd)
        return cmd

    def start(self, lora: str, takeover: bool = False) -> float:
        """Launch a fresh server with `lora` substituted. Returns time-to-serve
        (seconds from launch until a real completion answers)."""
        self._ensure_port_free(takeover)
        cmd = self._render_cmd(lora)
        t0 = time.time()
        with open(self.log_path, "ab") as logf:
            self._proc = subprocess.Popen(
                cmd, shell=True, stdout=logf, stderr=subprocess.STDOUT,
                start_new_session=True)
        # wait for HTTP up
        while time.time() - t0 < self.serve_timeout:
            if _health_ok(self.health_url):
                break
            time.sleep(0.5)
        # wait for model actually loaded (a real completion)
        to_serve = None
        if _health_ok(self.health_url):
            payload = json.dumps({"model": "m",
                                  "messages": [{"role": "user", "content": "hi"}],
                                  "max_tokens": 1, "temperature": 0.0}).encode()
            req = urllib.request.Request(
                f"{self.health_url.rsplit('/', 1)[0]}/v1/chat/completions",
                data=payload, headers={"Content-Type": "application/json"},
                method="POST")
            t_ft = time.time()
            try:
                urllib.request.urlopen(req, timeout=self.serve_timeout).read()
                to_serve = time.time() - t0
            except Exception:
                to_serve = None
        self.current_lora = lora
        return to_serve if to_serve is not None else (time.time() - t0)

    def start_argv(self, argv: list[str], takeover: bool = False) -> tuple[bool, float]:
        """Launch a llama-server from an explicit argv list (NO shell).

        Used by the autotune cycle (tune-loop plan, Todo 2) so the argv is built
        by ``ServerConfig.to_argv()`` (list form, no injection) rather than a
        shell template. Returns ``(ok, to_serve)`` where ``ok`` is False when the
        server does not pass health/completion within ``serve_timeout`` — a hard
        failure signal the cycle uses to trigger immediate rollback.

        ``takeover=True`` lets it kill an externally-launched listener on the
        port (e.g. the production server) before starting; ``takeover=False``
        refuses to start if the port is occupied.
        """
        self._ensure_port_free(takeover)
        t0 = time.time()
        try:
            with open(self.log_path, "ab") as logf:
                self._proc = subprocess.Popen(
                    argv, stdout=logf, stderr=subprocess.STDOUT,
                    start_new_session=True)
        except Exception as e:  # noqa: BLE001 - e.g. binary not found
            # Hard failure: cannot even launch (bad path / missing executable).
            # Return ok=False so the cycle can roll back rather than crash.
            self._proc = None
            return False, time.time() - t0
        # wait for HTTP up
        while time.time() - t0 < self.serve_timeout:
            if _health_ok(self.health_url):
                break
            time.sleep(0.5)
        # wait for a real completion (model loaded) — hard failure if it fails
        to_serve = None
        if _health_ok(self.health_url):
            payload = json.dumps({"model": "m",
                                  "messages": [{"role": "user", "content": "hi"}],
                                  "max_tokens": 1, "temperature": 0.0}).encode()
            req = urllib.request.Request(
                f"{self.health_url.rsplit('/', 1)[0]}/v1/chat/completions",
                data=payload, headers={"Content-Type": "application/json"},
                method="POST")
            try:
                urllib.request.urlopen(req, timeout=self.serve_timeout).read()
                to_serve = time.time() - t0
            except Exception:
                to_serve = None
        if to_serve is None:
            # hard failure: server never became healthy/served. Kill the zombie
            # so a later rollback can reclaim the port.
            try:
                self.stop()
            except Exception:
                pass
            return False, time.time() - t0
        self.current_lora = None
        return True, to_serve

    def stop(self) -> None:
        if self._proc is None:
            return
        try:
            pgid = os.getpgid(self._proc.pid)
            os.killpg(pgid, signal.SIGTERM)
        except Exception:
            try:
                self._proc.kill()
            except Exception:
                return
        try:
            self._proc.wait(timeout=10)
        except Exception:
            try:
                os.killpg(os.getpgid(self._proc.pid), signal.SIGKILL)
            except Exception:
                pass
        _wait_port_free(self.port, timeout=20.0)
        self._proc = None

    def restart_with(self, lora: str, takeover: bool = False) -> float:
        """Stop current server, start with new `lora`. Returns time-to-serve."""
        self.stop()
        return self.start(lora, takeover=takeover)
