#!/usr/bin/env python3
"""Pre-flight readiness check for the mass run.

Verifies before kickoff:
  - Docker daemon running, sufficient disk
  - Ollama responding, qwen2.5-coder model loaded
  - RAG sqlite has expected chunk counts
  - HF cache has all required datasets (PB tests + SWE-bench parquets + Multi-SWE-bench JSONLs)
  - All extracted ProgramBench test dirs present
  - Per-tool spec docs present in corpus
  - Helper scripts present at c:/tmp/ (or scripts/)

Exit code 0 = ready to launch. Non-zero = blocker found.
Run: python scripts/preflight_mass_run.py
"""

import json
import os
import pathlib
import sqlite3
import subprocess
import sys
from pathlib import Path

# Windows console: force UTF-8 output so → ✓ ✗ etc. don't crash
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ---- Configuration ----
EXPECTED_PB_RAG_CHUNKS = 7000  # we have 7,816 — allow slack
EXPECTED_SB_RAG_CHUNKS = 900  # we have 1,038 — allow slack
EXPECTED_PB_SPECS = 190  # tools with 06_behavioral_spec.md in in_progress/
EXPECTED_SB_REPO_SPECS = (
    88  # SWE-bench repos (BurntSushi/ripgrep folds with PB's burntsushi/ripgrep on Windows)
)
MIN_FREE_DISK_GB = 100  # for mass-run image pulls
MIN_FREE_RAM_GB = 8  # for Ollama + Docker + agents

DETERMINEX_ROOT = Path(os.environ.get("DETERMINEX_ROOT", Path(__file__).resolve().parents[1]))
PB_DIR = DETERMINEX_ROOT / "corpus" / "programbench"
SB_DIR = DETERMINEX_ROOT / "corpus" / "swebench"
EXTRACTED_PB = Path("T:/determinex-programbench/_extracted_tests")
HF_CACHE = Path("T:/huggingface_cache/hub")
DB_PATH = Path(
    os.environ.get(
        "DETERMINEX_DB",
        # run.determinex.app is the Tauri BUNDLE IDENTIFIER, so this directory is the
        # right place -- only the hardcoded user-profile prefix was wrong. Derive it.
        str(
            pathlib.Path(os.environ.get("APPDATA") or pathlib.Path.home() / "AppData" / "Roaming")
            / "run.determinex.app"
            / "determinex.sqlite"
        ),
    )
)

# ---- Result tracker ----
checks = []  # list of (name, status, detail) — status: "ok", "warn", "fail"


def check(name: str):
    """Decorator to register a check; the function returns (status, detail)."""

    def deco(fn):
        try:
            status, detail = fn()
        except Exception as e:
            status, detail = "fail", f"exception: {type(e).__name__}: {e}"
        checks.append((name, status, detail))
        return fn

    return deco


# ============================================================================
# DOCKER
# ============================================================================
@check("docker.daemon")
def _():
    try:
        r = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if r.returncode == 0 and r.stdout.strip():
            return "ok", f"server v{r.stdout.strip()}"
        return "fail", f"docker version returned rc={r.returncode}: {r.stderr.strip()[:200]}"
    except FileNotFoundError:
        return "fail", "docker CLI not on PATH"
    except subprocess.TimeoutExpired:
        return "fail", "docker version timed out (daemon hung?)"


@check("docker.disk")
def _():
    try:
        r = subprocess.run(
            ["docker", "system", "df", "--format", "json"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if r.returncode != 0:
            return "warn", f"system df failed: {r.stderr.strip()[:120]}"
        # Parse jsonlines
        info = []
        for line in r.stdout.splitlines():
            try:
                info.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        sizes = {it.get("Type", ""): it.get("Size", "?") for it in info}
        return "ok", f"images={sizes.get('Images', '?')}  containers={sizes.get('Containers', '?')}"
    except Exception as e:
        return "warn", str(e)[:120]


@check("disk.c_free_gb")
def _():
    import shutil

    free = shutil.disk_usage("c:/").free / (1024**3)
    if free < MIN_FREE_DISK_GB:
        return "warn", f"only {free:.1f}GB free on C: (recommended >= {MIN_FREE_DISK_GB}GB)"
    return "ok", f"{free:.1f}GB free on C:"


@check("disk.t_free_gb")
def _():
    import shutil

    if not Path("t:/").exists():
        return "warn", "T: drive not mounted"
    free = shutil.disk_usage("t:/").free / (1024**3)
    return "ok", f"{free:.1f}GB free on T:"


# ============================================================================
# OLLAMA
# ============================================================================
@check("ollama.daemon")
def _():
    try:
        import urllib.request

        r = urllib.request.urlopen("http://localhost:11434/api/tags", timeout=5)
        data = json.loads(r.read())
        models = data.get("models", [])
        return "ok", f"{len(models)} models loaded"
    except Exception as e:
        return "fail", f"can't reach Ollama: {type(e).__name__}: {str(e)[:80]}"


@check("ollama.qwen14b")
def _():
    try:
        import urllib.request

        r = urllib.request.urlopen("http://localhost:11434/api/tags", timeout=5)
        data = json.loads(r.read())
        models = [m["name"] for m in data.get("models", [])]
        wanted = "qwen2.5-coder:14b-instruct-q4_K_M"
        if wanted in models:
            return "ok", wanted
        # Fallback names
        alts = [m for m in models if "qwen2.5-coder" in m and ("14b" in m or "32b" in m)]
        if alts:
            return "warn", f"{wanted} not present; available: {alts}"
        return "fail", f"no qwen2.5-coder 14b/32b model loaded; have: {models[:5]}"
    except Exception as e:
        return "fail", str(e)[:120]


@check("vram.gpu_present")
def _():
    """Check NVIDIA GPU + recommend best-fit Ollama model for it."""
    try:
        from vram_monitor import query_vram, recommend_model
    except ImportError:
        # Add scripts dir to path so we can import the sibling module
        import sys as _sys

        _sys.path.insert(0, str(Path(__file__).parent))
        from vram_monitor import query_vram, recommend_model
    snap = query_vram()
    if not snap:
        return "warn", "nvidia-smi unavailable — running CPU-only Ollama will be slow"
    rec, _reason = recommend_model(snap["free_mb"], total_mb=snap["total_mb"])
    return "ok", (
        f"{snap['name']}: {snap['free_mb']}/{snap['total_mb']} MiB free  "
        f"→ recommend builder model: {rec}"
    )


@check("vram.headroom_ok")
def _():
    """Warn if current VRAM use is already > 50% of total (other apps consuming GPU)."""
    try:
        import sys as _sys

        _sys.path.insert(0, str(Path(__file__).parent))
        from vram_monitor import query_vram
    except ImportError:
        return "warn", "vram_monitor.py not importable"
    snap = query_vram()
    if not snap:
        return "warn", "no GPU detected"
    if snap["used_pct"] > 70:
        return "warn", (
            f"VRAM {snap['used_pct']:.0f}% used by other apps "
            f"({snap['used_mb']}/{snap['total_mb']} MiB) — close GPU apps before mass run"
        )
    return "ok", f"VRAM {snap['used_pct']:.0f}% used — plenty of headroom for Ollama"


# ============================================================================
# RAG
# ============================================================================
@check("rag.sqlite_present")
def _():
    if not DB_PATH.exists():
        return "fail", f"DB not at {DB_PATH} — start Determinex app once"
    return "ok", str(DB_PATH)


@check("rag.programbench_chunks")
def _():
    if not DB_PATH.exists():
        return "fail", "DB missing"
    conn = sqlite3.connect(str(DB_PATH))
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM wisdom WHERE metadata LIKE 'programbench |%'"
        ).fetchone()[0]
        if n < EXPECTED_PB_RAG_CHUNKS:
            return "warn", f"only {n} chunks (expected >= {EXPECTED_PB_RAG_CHUNKS})"
        return "ok", f"{n} chunks"
    finally:
        conn.close()


@check("rag.swebench_chunks")
def _():
    if not DB_PATH.exists():
        return "fail", "DB missing"
    conn = sqlite3.connect(str(DB_PATH))
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM wisdom WHERE metadata LIKE 'swebench |%'"
        ).fetchone()[0]
        if n < EXPECTED_SB_RAG_CHUNKS:
            return "warn", f"only {n} chunks (expected >= {EXPECTED_SB_RAG_CHUNKS})"
        return "ok", f"{n} chunks"
    finally:
        conn.close()


# ============================================================================
# CORPUS FILES
# ============================================================================
@check("corpus.pb_specs_count")
def _():
    if not PB_DIR.exists():
        return "fail", f"missing {PB_DIR}"
    specs = list(PB_DIR.glob("in_progress/*/06_behavioral_spec.md"))
    if len(specs) < EXPECTED_PB_SPECS:
        return "warn", f"{len(specs)} specs (expected >= {EXPECTED_PB_SPECS})"
    return "ok", f"{len(specs)} per-tool specs"


@check("corpus.pb_anchor_packs")
def _():
    anchors = list(PB_DIR.glob("anchors/*/06_behavioral_spec.md"))
    if len(anchors) < 5:
        return "warn", f"only {len(anchors)} anchor specs (expected 5)"
    return "ok", f"{len(anchors)} anchor packs (jq, fzf, lz4, fd, curlie)"


@check("corpus.sb_repo_specs")
def _():
    if not SB_DIR.exists():
        return "fail", f"missing {SB_DIR}"
    specs = list(SB_DIR.glob("repos/*/06_repo_spec.md"))
    if len(specs) < EXPECTED_SB_REPO_SPECS:
        return "warn", f"{len(specs)} repo specs (expected >= {EXPECTED_SB_REPO_SPECS})"
    return "ok", f"{len(specs)} per-repo specs"


@check("corpus.sb_instance_index")
def _():
    p = SB_DIR / "swebench_instance_index.jsonl"
    if not p.exists():
        return "fail", f"missing {p}"
    n = sum(1 for _ in p.open(encoding="utf-8"))
    return "ok", f"{n:,} instances indexed"


# ============================================================================
# HF CACHE
# ============================================================================
@check("hf.programbench_tests")
def _():
    p = HF_CACHE / "datasets--programbench--ProgramBench-Tests" / "snapshots"
    if not p.exists():
        return "fail", f"missing {p}"
    snaps = list(p.iterdir())
    if not snaps:
        return "fail", "no snapshots"
    snap = sorted(snaps)[-1]
    n_tasks = sum(1 for d in snap.iterdir() if d.is_dir())
    return "ok", f"{n_tasks} task dirs in {snap.name[:12]}..."


@check("hf.swebench_verified")
def _():
    p = HF_CACHE / "datasets--princeton-nlp--SWE-bench_Verified" / "snapshots"
    if not p.exists():
        return "fail", f"missing {p}"
    parquets = list(p.rglob("*.parquet"))
    return ("ok" if parquets else "fail"), f"{len(parquets)} parquet files"


@check("hf.multi_swe_bench")
def _():
    p = HF_CACHE / "datasets--ByteDance-Seed--Multi-SWE-bench" / "snapshots"
    if not p.exists():
        return "fail", f"missing {p}"
    jsonls = list(p.rglob("*.jsonl"))
    return ("ok" if jsonls else "fail"), f"{len(jsonls)} jsonl files"


# ============================================================================
# EXTRACTED TESTS
# ============================================================================
@check("extracted.pb_test_dirs")
def _():
    if not EXTRACTED_PB.exists():
        return "fail", f"missing {EXTRACTED_PB}"
    dirs = [d for d in EXTRACTED_PB.iterdir() if d.is_dir()]
    if len(dirs) < 190:
        return "warn", f"only {len(dirs)} extracted dirs (expected ~190)"
    return "ok", f"{len(dirs)} task dirs extracted"


# ============================================================================
# AGENTS
# ============================================================================
@check("agents.pb_agent_present")
def _():
    p = DETERMINEX_ROOT / "scripts" / "determinex_programbench_agent.py"
    return ("ok" if p.exists() else "fail"), str(p)


@check("agents.swe_agent_present")
def _():
    p = DETERMINEX_ROOT / "scripts" / "determinex_swebench_agent.py"
    return ("ok" if p.exists() else "fail"), str(p)


@check("agents.local_builder_flag")
def _():
    """Check if --model local flag is wired in."""
    p = DETERMINEX_ROOT / "scripts" / "determinex_programbench_agent.py"
    if not p.exists():
        return "fail", "PB agent missing"
    text = p.read_text(encoding="utf-8", errors="replace")
    if "--model" in text and "local" in text:
        return "ok", "--model local appears wired in PB agent"
    return "warn", "PB agent has no --model local wiring (will hit Anthropic API)"


# ============================================================================
# RUN
# ============================================================================
def main():
    print("=" * 60)
    print("DETERMINEX MASS-RUN PREFLIGHT")
    print("=" * 60)
    counts = {"ok": 0, "warn": 0, "fail": 0}
    for name, status, detail in checks:
        glyph = {"ok": "[OK]  ", "warn": "[WARN]", "fail": "[FAIL]"}[status]
        counts[status] += 1
        print(f"{glyph}  {name:35s}  {detail}")
    print()
    print(f"Summary: {counts['ok']} ok, {counts['warn']} warn, {counts['fail']} fail")
    print()
    if counts["fail"] > 0:
        print("BLOCKED: fix [FAIL] checks before kicking off mass run.")
        sys.exit(1)
    if counts["warn"] > 0:
        print("CAUTION: review [WARN] checks; mass run may proceed but expect issues.")
        sys.exit(2)
    print("READY: all checks pass. Mass run can launch.")
    sys.exit(0)


if __name__ == "__main__":
    main()
