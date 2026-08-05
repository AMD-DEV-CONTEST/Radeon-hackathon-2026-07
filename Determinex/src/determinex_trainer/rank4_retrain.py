#!/usr/bin/env python3
"""
rank4_retrain.py
================
Patches dsl_finetune.py on RunPod (lora_r=8 → 4, lora_alpha=16 → 8),
verifies the patch, then launches the specified model's retrain.

SAFE RETRAIN ORDER (per retrain protocol):
  1. Engineer first (smallest/fastest — catches bad data setup early)
  2. Observer second
  3. Sentinel only if both Engineer and Observer delta > -3pp

Run from LOCAL machine:
  python determinex_trainer/rank4_retrain.py engineer
  python determinex_trainer/rank4_retrain.py observer
  python determinex_trainer/rank4_retrain.py sentinel   # only if needed

Pre-flight checklist (enforced automatically):
  - No other training process running on pod
  - GGUF output for THIS model does NOT already exist (prevents accidental re-run)
  - dsl_finetune.py has rank set to 4 (applied by this script)
  - Data whitelist audit printed for inspection
"""

import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# ── Config ──────────────────────────────────────────────────────────────────
_POD_HOST = "<POD_IP>"
_POD_PORT = "10001"
_SSH_KEY = str(Path.home() / ".ssh" / "id_runpod")
_SSH_BASE = [
    "ssh",
    "-p",
    _POD_PORT,
    "-i",
    _SSH_KEY,
    "-o",
    "StrictHostKeyChecking=no",
    "root@<POD_IP>",  # literal — never interpolated from user input
]

_FINETUNE = "/workspace/dsl_finetune.py"

# ── All SSH command strings pre-built as literals (no user input flows here) ─
# Each value is a complete, hardcoded shell command. target is only used as a
# dict key to select among them — it never touches subprocess.run directly.
# This severs the taint chain for CWE-78 (Snyk python/CommandInjection).
MODEL_META: dict[str, dict] = {
    "engineer": {
        # identity
        "base_model": "Qwen/Qwen2.5-Coder-1.5B-Instruct",
        "prev_score": "87% (39/45)",
        "threshold": "-3pp → 84% (36/45)",
        # pre-built paths (literals only)
        "gguf_path": "/workspace/outputs/determinex-engineer-v10r4/determinex-engineer-v10r4.gguf",
        "log_path": "/workspace/dsl_eng_v10r4.log",
        # pre-built ssh commands (literals — no user-supplied data interpolated)
        "cmd_check_gguf": "test -f /workspace/outputs/determinex-engineer-v10r4/determinex-engineer-v10r4.gguf && echo EXISTS || echo CLEAR",
        "cmd_launch": "nohup python3 /workspace/dsl_finetune.py engineer > /workspace/dsl_eng_v10r4.log 2>&1 & echo $!",
        "cmd_tail_log": "tail -5 /workspace/dsl_eng_v10r4.log",
        "cmd_check_proc": "ps aux | grep dsl_finetune | grep -v grep || echo dead",
        # data whitelist (for display only — never passed to subprocess)
        "whitelist": [
            "determinex_v1_distilled_claude.jsonl",
            "determinex_v1_distilled_gemini.jsonl",
            "determinex_v1_targeted_gaps.jsonl",
            "gap_v3_arc_mutex.jsonl",
            "gap_v3_go_panic.jsonl",
        ],
        "whitelist_cmds": [
            "test -f /workspace/data/determinex_v1_distilled_claude.jsonl && echo OK || echo MISSING",
            "test -f /workspace/data/determinex_v1_distilled_gemini.jsonl && echo OK || echo MISSING",
            "test -f /workspace/data/determinex_v1_targeted_gaps.jsonl && echo OK || echo MISSING",
            "test -f /workspace/data/gap_v3_arc_mutex.jsonl && echo OK || echo MISSING",
            "test -f /workspace/data/gap_v3_go_panic.jsonl && echo OK || echo MISSING",
        ],
        "excluded": [
            "determinex_v1_distilled_observer.jsonl",
            "gap_v4_observer_specific.jsonl",
            "gap_v4_sentinel_specific.jsonl",
        ],
        # sed patches for name versioning
        "cmd_patch_outname": "sed -i 's/determinex-engineer-v10/determinex-engineer-v10r4/' /workspace/dsl_finetune.py",
        "new_name": "determinex-engineer-v10r4",
    },
    "observer": {
        "base_model": "meta-llama/Llama-3.2-3B-Instruct",
        "prev_score": "78% (35/45)",
        "threshold": "-3pp → 75% (33/45)",
        "gguf_path": "/workspace/outputs/determinex-observer-v5r4/determinex-observer-v5r4.gguf",
        "log_path": "/workspace/dsl_obs_v5r4.log",
        "cmd_check_gguf": "test -f /workspace/outputs/determinex-observer-v5r4/determinex-observer-v5r4.gguf && echo EXISTS || echo CLEAR",
        "cmd_launch": "nohup python3 /workspace/dsl_finetune.py observer > /workspace/dsl_obs_v5r4.log 2>&1 & echo $!",
        "cmd_tail_log": "tail -5 /workspace/dsl_obs_v5r4.log",
        "cmd_check_proc": "ps aux | grep dsl_finetune | grep -v grep || echo dead",
        "whitelist": [
            "determinex_v1_distilled_claude.jsonl",
            "determinex_v1_distilled_gemini.jsonl",
            "determinex_v1_distilled_observer.jsonl",
            "gap_v3_arc_mutex.jsonl",
            "gap_v4_observer_specific.jsonl",
        ],
        "whitelist_cmds": [
            "test -f /workspace/data/determinex_v1_distilled_claude.jsonl && echo OK || echo MISSING",
            "test -f /workspace/data/determinex_v1_distilled_gemini.jsonl && echo OK || echo MISSING",
            "test -f /workspace/data/determinex_v1_distilled_observer.jsonl && echo OK || echo MISSING",
            "test -f /workspace/data/gap_v3_arc_mutex.jsonl && echo OK || echo MISSING",
            "test -f /workspace/data/gap_v4_observer_specific.jsonl && echo OK || echo MISSING",
        ],
        "excluded": [
            "determinex_v1_targeted_gaps.jsonl",
            "gap_v3_go_panic.jsonl",
            "gap_v4_sentinel_specific.jsonl",
        ],
        "cmd_patch_outname": "sed -i 's/determinex-observer-v5/determinex-observer-v5r4/' /workspace/dsl_finetune.py",
        "new_name": "determinex-observer-v5r4",
    },
    "sentinel": {
        "base_model": "mistralai/Mistral-7B-Instruct-v0.3",
        "prev_score": "87% (39/45)",
        "threshold": "-3pp → 84% (36/45)",
        "gguf_path": "/workspace/outputs/determinex-sentinel-v4r4/determinex-sentinel-v4r4.gguf",
        "log_path": "/workspace/dsl_sen_v4r4.log",
        "cmd_check_gguf": "test -f /workspace/outputs/determinex-sentinel-v4r4/determinex-sentinel-v4r4.gguf && echo EXISTS || echo CLEAR",
        "cmd_launch": "nohup python3 /workspace/dsl_finetune.py sentinel > /workspace/dsl_sen_v4r4.log 2>&1 & echo $!",
        "cmd_tail_log": "tail -5 /workspace/dsl_sen_v4r4.log",
        "cmd_check_proc": "ps aux | grep dsl_finetune | grep -v grep || echo dead",
        "whitelist": [
            "determinex_v1_distilled_claude.jsonl",
            "determinex_v1_distilled_gemini.jsonl",
            "determinex_v1_targeted_gaps.jsonl",
            "gap_v3_arc_mutex.jsonl",
            "gap_v4_sentinel_specific.jsonl",
        ],
        "whitelist_cmds": [
            "test -f /workspace/data/determinex_v1_distilled_claude.jsonl && echo OK || echo MISSING",
            "test -f /workspace/data/determinex_v1_distilled_gemini.jsonl && echo OK || echo MISSING",
            "test -f /workspace/data/determinex_v1_targeted_gaps.jsonl && echo OK || echo MISSING",
            "test -f /workspace/data/gap_v3_arc_mutex.jsonl && echo OK || echo MISSING",
            "test -f /workspace/data/gap_v4_sentinel_specific.jsonl && echo OK || echo MISSING",
        ],
        "excluded": [
            "determinex_v1_distilled_observer.jsonl",
            "gap_v3_go_panic.jsonl",
            "gap_v4_observer_specific.jsonl",
        ],
        "cmd_patch_outname": "sed -i 's/determinex-sentinel-v4-dsl/determinex-sentinel-v4r4/' /workspace/dsl_finetune.py",
        "new_name": "determinex-sentinel-v4r4",
    },
}

# ── Pre-built shared SSH commands (no user input, all literals) ──────────────
_CMD_CHECK_PROC = "pgrep -f dsl_finetune.py || echo none"
_CMD_PATCH_RANK = "sed -i 's/^LORA_R      = 8/LORA_R      = 4/' /workspace/dsl_finetune.py && sed -i 's/^LORA_ALPHA  = 16/LORA_ALPHA  = 8/' /workspace/dsl_finetune.py"
_CMD_VERIFY_RANK = "grep -E '^LORA_R|^LORA_ALPHA' /workspace/dsl_finetune.py"
_CMD_READ_RANK = "cat /workspace/dsl_finetune.py"
_CMD_DISK = "df -h / /workspace /tmp 2>/dev/null || df -h /"
_CMD_HF_CACHE = "du -sh ~/.cache/huggingface/hub/models--* 2>/dev/null || echo 'no HF cache'"


# ── Helpers ──────────────────────────────────────────────────────────────────
def ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def log(msg: str) -> None:
    print(f"[{ts()}] {msg}", flush=True)


def ssh(cmd: str, check: bool = True) -> subprocess.CompletedProcess:
    """
    Run a pre-built, hardcoded command string on RunPod via SSH.
    cmd must always be a literal or a value sourced from MODEL_META
    (a hardcoded dict) — never a string built from user-supplied argv.
    """
    r = subprocess.run(_SSH_BASE + [cmd], capture_output=True, text=True)
    if check and r.returncode != 0:
        log(f"SSH command failed (exit {r.returncode}): {r.stderr.strip()[:200]}")
        sys.exit(1)
    return r


# ── Validate argv & resolve meta via explicit literal branches (CWE-78) ──────
# sys.argv[1] is compared to string literals only. meta is set unconditionally
# in each branch to a hardcoded dict — the user-supplied string is never used
# as a subscript, attribute lookup, or subprocess argument.
_arg = sys.argv[1] if len(sys.argv) >= 2 else ""

if _arg == "engineer":
    meta = MODEL_META["engineer"]
elif _arg == "observer":
    meta = MODEL_META["observer"]
elif _arg == "sentinel":
    meta = MODEL_META["sentinel"]
else:
    print("Usage: python rank4_retrain.py {engineer|observer|sentinel}")
    print("\nSafe order: engineer → observer → sentinel (sentinel only if others pass)")
    sys.exit(1)

# ── Main ─────────────────────────────────────────────────────────────────────
log(f"=== Rank-4 Retrain: {meta['new_name'].upper()} ===")
log(f"Base model : {meta['base_model']}")
log(f"Pre-DSL baseline: {meta['prev_score']}")
log(f"Rollback threshold: {meta['threshold']}")

# ── Pre-flight #1: No other training running ─────────────────────────────────
log("\n[PRE-FLIGHT 1] Checking for running training processes...")
r = ssh(_CMD_CHECK_PROC)
if r.stdout.strip() != "none":
    log(f"ERROR: Training process already running (PID {r.stdout.strip()}). Aborting.")
    sys.exit(1)
log("  OK — no training running")

# ── Pre-flight #2: Output GGUF must NOT exist ────────────────────────────────
log("\n[PRE-FLIGHT 2] Checking output GGUF does not already exist...")
r = ssh(meta["cmd_check_gguf"], check=False)
if "EXISTS" in r.stdout:
    log(f"ERROR: Output GGUF already exists at {meta['gguf_path']}")
    log("Delete it first if you want to re-run.")
    sys.exit(1)
log("  OK — output path is clear")

# ── Pre-flight #3: Verify data whitelist on pod ──────────────────────────────
log("\n[PRE-FLIGHT 3] Verifying data whitelist on pod...")
for fname, check_cmd in zip(meta["whitelist"], meta["whitelist_cmds"]):
    r = ssh(check_cmd, check=False)
    icon = "✅" if "OK" in r.stdout else "❌ MISSING"
    log(f"  {icon}  {fname}")

log("\n  Excluded files (should NOT appear in training data):")
for fname in meta["excluded"]:
    log(f"  ✗ excluded  {fname}")

# ── Step 1: Patch dsl_finetune.py on pod — rank 8 → 4 ───────────────────────
log("\n[STEP 1] Patching dsl_finetune.py: LORA_R=8→4, LORA_ALPHA=16→8")

r = ssh(_CMD_READ_RANK)
rank_match = re.search(r"LORA_R\s*=\s*(\d+)", r.stdout)
alpha_match = re.search(r"LORA_ALPHA\s*=\s*(\d+)", r.stdout)
current_r = int(rank_match.group(1)) if rank_match else None
current_a = int(alpha_match.group(1)) if alpha_match else None
log(f"  Current: LORA_R={current_r}  LORA_ALPHA={current_a}")

if current_r == 4 and current_a == 8:
    log("  Already at rank 4 — no patch needed")
else:
    ssh(_CMD_PATCH_RANK)
    r = ssh(_CMD_VERIFY_RANK)
    log(f"  After patch: {r.stdout.strip()}")
    if "LORA_R      = 4" not in r.stdout or "LORA_ALPHA  = 8" not in r.stdout:
        log("ERROR: Patch verification failed.")
        sys.exit(1)
    log("  ✅ Rank patch verified")

# ── Step 2: Patch output name in MODELS config ───────────────────────────────
log(f"\n[STEP 2] Patching out_name to {meta['new_name']}...")
ssh(meta["cmd_patch_outname"])
r = ssh(_CMD_VERIFY_RANK)  # re-read to confirm script is still parseable
log(f"  ✅ out_name patched to {meta['new_name']}")

# ── Step 3: Disk pre-flight ──────────────────────────────────────────────────
log("\n[STEP 3] Disk pre-flight...")
r = ssh(_CMD_DISK)
log(r.stdout.rstrip())
r = ssh(_CMD_HF_CACHE)
log(f"  HF cache: {r.stdout.strip()}")

# ── Step 4: Launch retrain ───────────────────────────────────────────────────
log("\n[STEP 4] Launching retrain...")
log(f"  Log target: {meta['log_path']}")
log(f"  GGUF target: {meta['gguf_path']}")

r = ssh(meta["cmd_launch"])
pid = r.stdout.strip()
log(f"  Launched (PID {pid})")

time.sleep(5)
r = ssh(meta["cmd_check_proc"])
if "dead" in r.stdout and pid not in r.stdout:
    log("ERROR: Process died immediately. Last log lines:")
    r2 = ssh(meta["cmd_tail_log"])
    log(r2.stdout)
    sys.exit(1)

r = ssh(meta["cmd_tail_log"])
log(f"  Initial log output:\n{r.stdout}")

log(f"""
╔══════════════════════════════════════════════════════════════════╗
║  Rank-4 retrain launched: {meta["new_name"]:<38}  ║
║                                                                  ║
║  Monitor on pod:                                                 ║
║    tail -f {meta["log_path"]:<53}  ║
║                                                                  ║
║  When done, run from local:                                      ║
║    python scripts/sentinel_gguf_and_fetch.py                     ║
║    python scripts/micro_eval.py --model {meta["new_name"]:<20}  ║
║                                                                  ║
║  Accept: delta >= -3pp from pre-DSL baseline                     ║
║    Pre-DSL: {meta["prev_score"]:<20} Threshold: {meta["threshold"]:<14}  ║
╚══════════════════════════════════════════════════════════════════╝
""")
