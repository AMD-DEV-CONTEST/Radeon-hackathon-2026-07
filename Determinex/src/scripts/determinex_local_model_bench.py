#!/usr/bin/env python3
"""
determinex_local_model_bench.py -- clock local-model latency, calibrate timeouts
=================================================================================
Ryan: "since timing will be an issue, we should set up clock runs on these
llms in local for response time based on different vram/ram uni on the
system. then we can time them out to make sure things are moving faster than
the slower models. and get true multitool."

The multi-agent chat room (agent_chat.rs) gives every participant the same
flat timeout, which is fine for cloud-backed CLI agents (Claude Code, Codex,
Gemini CLI all respond in roughly comparable, hardware-independent time) but
wrong for a LOCAL Ollama model: its real response time depends entirely on
this machine's VRAM/RAM/CPU, and guessing a timeout without measuring is
exactly the kind of unverified assumption this project doesn't ship. This
module measures it for real, once per (model, hardware) pair, caches the
result, and turns it into a timeout the Rust chat backend can query.

Not a token-accurate cost model -- a single short-prompt latency measurement
times a safety factor, because a real chat turn's prompt (full conversation +
mission plan) is much longer than the benchmark probe. Documented as a
heuristic on purpose: better than a blind flat constant, not a promise of
precision.

CLI
---
    python scripts/determinex_local_model_bench.py bench [--model TAG]
    python scripts/determinex_local_model_bench.py estimate-timeout [--model TAG]
"""

from __future__ import annotations

import datetime as _dt
import json
import re
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BENCH_CACHE_PATH = ROOT / "logs" / "local_model_bench.json"
# Ryan: "i dont have the vram to test them all, fyi, so we will put place
# holders and others who download can report their findings." A git-tracked
# (not gitignored, unlike logs/) corpus directory, same pattern as
# corpus/programbench: anyone who runs `bench --submit` on their own
# hardware writes a real measurement here as its own small file, meant to be
# committed/PR'd -- the placeholder table below is what's used until real
# community data exists for a given model tier.
COMMUNITY_BENCH_DIR = ROOT / "corpus" / "local_model_benchmarks"

_BENCH_PROMPT = "Reply with exactly one word: ready."
_DEFAULT_MODEL = "qwen2.5-coder:14b-instruct-q4_K_M"
_CACHE_TTL_SECONDS = 7 * 24 * 3600  # a week -- hardware/model rarely changes more often than that

_TIMEOUT_FLOOR = 60
_TIMEOUT_CEILING = 900
_TIMEOUT_SAFETY_FACTOR = 6  # a real turn's prompt is far longer than the bench probe

# Rough, honestly-labeled placeholders (short-prompt latency in seconds) by
# approximate parameter-count tier, used ONLY when neither a real local
# measurement nor community-contributed data exists for a model. These are
# not derived from a benchmark -- they're a reasonable starting guess so the
# chat room has a working timeout on day one, clearly distinguishable (via
# BenchResult.source == "placeholder") from anything actually measured.
_PLACEHOLDER_SECONDS_BY_TIER = {
    "1.5b": 2.0,
    "3b": 4.0,
    "7b": 8.0,
    "8b": 9.0,
    "13b": 18.0,
    "14b": 20.0,
    "32b": 45.0,
    "34b": 48.0,
    "70b": 90.0,
    "unknown": 30.0,
}
_TIER_RE = re.compile(r"(\d+(?:\.\d+)?)b", re.IGNORECASE)


def infer_tier(model: str) -> str:
    """Best-effort parameter-count tier from a model tag like
    'qwen2.5-coder:14b-instruct-q4_K_M' -> '14b'. Falls back to the nearest
    known tier by numeric distance, or 'unknown' if no size token is found."""
    match = _TIER_RE.search(model)
    if not match:
        return "unknown"
    size = match.group(1)
    tier = f"{size}b"
    if tier in _PLACEHOLDER_SECONDS_BY_TIER:
        return tier
    try:
        size_f = float(size)
    except ValueError:
        return "unknown"
    known = [k for k in _PLACEHOLDER_SECONDS_BY_TIER if k != "unknown"]
    closest = min(known, key=lambda k: abs(float(k[:-1]) - size_f))
    return closest


def _default_model() -> str:
    import os

    return os.environ.get("DETERMINEX_LOCAL_BUILDER_MODEL", _DEFAULT_MODEL)


def _ollama_host() -> str:
    import os

    return (
        os.environ.get("DETERMINEX_OLLAMA_URL")
        or os.environ.get("OLLAMA_HOST")
        or "http://localhost:11434"
    )


@dataclass
class HardwareFingerprint:
    total_ram_gb: float
    cpu_count: int
    gpu_name: str
    gpu_vram_gb: float


def detect_hardware() -> HardwareFingerprint:
    """Best-effort, never raises -- an unmeasurable field just comes back as
    0/"unknown" rather than blocking the benchmark."""
    total_ram_gb = 0.0
    cpu_count = 0
    try:
        import psutil

        total_ram_gb = round(psutil.virtual_memory().total / (1024**3), 1)
        cpu_count = psutil.cpu_count(logical=True) or 0
    except Exception:
        pass

    gpu_name, gpu_vram_gb = "unknown", 0.0
    try:
        # No new dependency -- nvidia-smi ships with any NVIDIA driver install
        # and is the same tool `nvidia-smi` users already have if they have a
        # CUDA-capable card. Absent on non-NVIDIA/CPU-only boxes, which is a
        # normal, expected case, not an error.
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if out.returncode == 0 and out.stdout.strip():
            first_line = out.stdout.strip().splitlines()[0]
            name, mem_mib = [p.strip() for p in first_line.split(",")]
            gpu_name = name
            gpu_vram_gb = round(float(mem_mib) / 1024, 1)
    except Exception:
        pass

    return HardwareFingerprint(
        total_ram_gb=total_ram_gb, cpu_count=cpu_count, gpu_name=gpu_name, gpu_vram_gb=gpu_vram_gb
    )


@dataclass
class BenchResult:
    model: str
    hardware_key: str
    latency_seconds: float
    tokens_generated: int
    tokens_per_second: float
    hardware: dict
    measured_at: str
    error: str | None = None
    # "measured_local" (this machine, just now) | "community" (someone else's
    # contributed corpus/local_model_benchmarks/*.json) | "placeholder" (no
    # real data anywhere yet -- a labeled guess, never silently presented as
    # a measurement).
    source: str = "measured_local"


def _hardware_key(hw: HardwareFingerprint) -> str:
    return f"ram{hw.total_ram_gb}_cpu{hw.cpu_count}_gpu{hw.gpu_name}_{hw.gpu_vram_gb}vram"


def _read_cache() -> dict:
    if not BENCH_CACHE_PATH.exists():
        return {}
    try:
        return json.loads(BENCH_CACHE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_cache(cache: dict) -> None:
    BENCH_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    BENCH_CACHE_PATH.write_text(
        json.dumps(cache, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _cache_key(model: str, hardware_key: str) -> str:
    return f"{model}::{hardware_key}"


def bench_model(model: str | None = None, *, force: bool = False) -> BenchResult:
    """Clock one real round-trip against the local Ollama model. Cached per
    (model, hardware) pair for _CACHE_TTL_SECONDS -- re-measures automatically
    once stale, or immediately if force=True."""
    model = model or _default_model()
    hw = detect_hardware()
    hw_key = _hardware_key(hw)
    cache = _read_cache()
    key = _cache_key(model, hw_key)

    if not force:
        cached = cache.get(key)
        if cached:
            age = (
                _dt.datetime.now(_dt.UTC) - _dt.datetime.fromisoformat(cached["measured_at"])
            ).total_seconds()
            if age < _CACHE_TTL_SECONDS and not cached.get("error"):
                return BenchResult(**cached)

    import urllib.request

    payload = json.dumps({"model": model, "prompt": _BENCH_PROMPT, "stream": False}).encode("utf-8")
    started = time.monotonic()
    tokens_generated = 0
    error = None
    try:
        req = urllib.request.Request(
            f"{_ollama_host()}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        tokens_generated = int(body.get("eval_count", 0) or 0)
    except Exception as e:
        error = str(e)
    latency = round(time.monotonic() - started, 3)
    tps = round(tokens_generated / latency, 2) if latency > 0 and tokens_generated else 0.0

    result = BenchResult(
        model=model,
        hardware_key=hw_key,
        latency_seconds=latency,
        tokens_generated=tokens_generated,
        tokens_per_second=tps,
        hardware=asdict(hw),
        measured_at=_dt.datetime.now(_dt.UTC).isoformat(timespec="seconds"),
        error=error,
        source="measured_local",
    )
    cache[key] = asdict(result)
    _write_cache(cache)
    return result


def load_community_benchmarks() -> list[BenchResult]:
    """Read every contributed measurement under corpus/local_model_benchmarks/
    -- other users' real hardware runs, git-committed (unlike the local-only
    logs/ cache), so a fresh clone starts with SOME real data instead of only
    placeholders."""
    if not COMMUNITY_BENCH_DIR.exists():
        return []
    out: list[BenchResult] = []
    for path in sorted(COMMUNITY_BENCH_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            data["source"] = "community"
            out.append(
                BenchResult(
                    **{k: v for k, v in data.items() if k in BenchResult.__dataclass_fields__}
                )
            )
        except (json.JSONDecodeError, OSError, TypeError):
            continue
    return out


def _placeholder_result(model: str) -> BenchResult:
    tier = infer_tier(model)
    seconds = _PLACEHOLDER_SECONDS_BY_TIER[tier]
    return BenchResult(
        model=model,
        hardware_key="unknown",
        latency_seconds=seconds,
        tokens_generated=0,
        tokens_per_second=0.0,
        hardware={},
        measured_at=_dt.datetime.now(_dt.UTC).isoformat(timespec="seconds"),
        source="placeholder",
    )


def estimate_timeout_seconds(model: str | None = None) -> int:
    """The number the chat backend actually wants: a sane per-turn timeout for
    this model, clamped to a floor/ceiling so neither an unmeasurably-fast nor
    an absurdly-slow reading produces a useless timeout. Priority order for
    where the underlying latency number comes from:
      1. a real measurement on THIS machine (bench_model's cache)
      2. community-contributed data for the same model tag, if this machine
         has never measured it (corpus/local_model_benchmarks/)
      3. a labeled placeholder guess by parameter-count tier, if neither
         exists yet -- never silently presented as a real measurement
    A benchmarking failure at any stage falls through to the next source
    rather than raising -- calibration must never block a real turn."""
    model = model or _default_model()

    local = bench_model(model)
    if not local.error and local.latency_seconds > 0:
        latency = local.latency_seconds
    else:
        community = [r for r in load_community_benchmarks() if r.model == model and not r.error]
        if community:
            latency = sorted(r.latency_seconds for r in community)[len(community) // 2]  # median
        else:
            latency = _placeholder_result(model).latency_seconds

    estimate = int(latency * _TIMEOUT_SAFETY_FACTOR)
    return max(_TIMEOUT_FLOOR, min(_TIMEOUT_CEILING, estimate))


def submit_community_bench(model: str | None = None) -> Path:
    """Run a REAL bench on this machine and write it as its own file under
    corpus/local_model_benchmarks/, meant to be `git add`ed and PR'd -- the
    mechanism for "others who download can report their findings." Never
    overwrites another contributor's file (timestamp + hardware in the name)."""
    result = bench_model(model, force=True)
    COMMUNITY_BENCH_DIR.mkdir(parents=True, exist_ok=True)
    safe_model = re.sub(r"[^a-zA-Z0-9_.-]", "_", result.model)
    safe_hw = re.sub(r"[^a-zA-Z0-9_.-]", "_", result.hardware_key)
    # Microsecond resolution, not just seconds -- two rapid submissions (e.g.
    # scripted back-to-back runs) at second-only granularity silently
    # collided and clobbered each other, found live by this module's own
    # test suite.
    ts = _dt.datetime.now(_dt.UTC).strftime("%Y%m%dT%H%M%S%f")
    path = COMMUNITY_BENCH_DIR / f"{safe_model}__{safe_hw}__{ts}.json"
    data = asdict(result)
    data["source"] = "community"
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Clock local Ollama model latency, calibrate agent-chat timeouts"
    )
    sub = parser.add_subparsers(dest="cmd")

    p_bench = sub.add_parser("bench")
    p_bench.add_argument("--model", default=None)
    p_bench.add_argument("--force", action="store_true", help="ignore cache, measure now")

    p_est = sub.add_parser("estimate-timeout")
    p_est.add_argument("--model", default=None)

    args = parser.parse_args()

    if args.cmd == "bench":
        result = bench_model(args.model, force=args.force)
        print(json.dumps(asdict(result)))
        return 0

    if args.cmd == "estimate-timeout":
        print(json.dumps({"timeout_seconds": estimate_timeout_seconds(args.model)}))
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    import sys

    sys.exit(main())
