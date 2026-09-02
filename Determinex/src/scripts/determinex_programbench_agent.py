#!/usr/bin/env python3
"""
Determinex ProgramBench Agent

Probes compiled binaries, generates reimplementations via Claude, iteratively
compiles inside the task Docker container, packages submission.tar.gz.

Usage:
    python scripts/determinex_programbench_agent.py --tasks yj htmlq shellharden
    python scripts/determinex_programbench_agent.py --tasks all_easy
    python scripts/determinex_programbench_agent.py --task sclevine__yj.8016400
"""

import argparse
import dataclasses
import json
import os
import subprocess
import sys
import tarfile
import time
from dataclasses import dataclass, field
from pathlib import Path

# Force utf-8 stdout so ANSI/Unicode in Docker output never crashes prints
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from cloak_audit import (
    AUDIT_ON as _AUDIT_ON,
)
from cloak_audit import (
    CLOAK_ON as _CLOAK_ON,
)
from cloak_audit import (
    audit_call as _cloak_audit_call,
)
from cloak_audit import (
    obfuscate_compile_errors as _cloak_obfuscate,
)
from determinex_copyright_guard import get_guard as _get_provenance_guard
from determinex_programbench_probe import (
    format_failure_report,
    get_test_branches,
    local_syntax_check,
    observer_diagnose,
    run_differential,
    run_pytest_probe,
)
from pb_wal import wal_record as _wal_record
from programbench_eval_runner import run_eval as _pb_run_eval


def _run_provenance_check(
    instance_id: str,
    attempt: int,
    compile_sh: str,
    files: dict[str, str],
) -> None:
    """
    Fire-and-forget provenance check on generated code.
    Logs attribution tags to logs/copyright_guard/attribution.jsonl.
    Never raises; never blocks compilation.
    """
    try:
        combined = compile_sh + "\n" + "\n".join(files.values())
        guard = _get_provenance_guard()
        report = guard.check_provenance(combined, task_id=f"{instance_id}_a{attempt}")
        if report.has_copyright_violation:
            print(
                f"  [provenance] COPYRIGHT ALERT on attempt {attempt}: "
                + ", ".join(a.work_label for a in report.copyright_alerts)
            )
        if report.has_attributions:
            labels = [
                t.source_label
                for t in report.attribution_tags
                if t.match_type != "verbatim_reproduction"
            ]
            if labels:
                print(
                    f"  [provenance] inspiration tagged: {', '.join(labels[:3])}"
                    + (f" +{len(labels) - 3} more" if len(labels) > 3 else "")
                )
        guard.log_attribution(report)
    except Exception as exc:
        import logging

        logging.getLogger(__name__).debug("[provenance] check failed (non-fatal): %s", exc)


def _write_wal_for_attempt(run_name: str, instance_id: str, am, ev=None) -> None:
    """Write a WAL record for one attempt. ev is the EvalResult (or None if no eval ran)."""
    if not am.wal_user_msg:
        return  # nothing captured (BACKEND ERROR or pre-call failure)
    outcome = {
        "backend_tier": am.model_used,
        "syntax_blocked": am.syntax_blocked,
        "compile_ok": am.compile_ok,
        "compile_seconds": round(am.t_compile, 2),
        "claude_seconds": round(am.t_claude, 2),
        "probe_pass": am.probe_pass,
        "probe_total": am.probe_total,
        "eval_score": am.eval_score,
        "eval_passed": am.eval_passed,
        "eval_total": am.eval_total,
        "eval_cached": am.eval_cached,
        "eval_error": am.eval_error,
    }
    if ev is not None:
        outcome["categories"] = (ev.categories or [])[:8]
        outcome["failure_count"] = max(ev.total - ev.passed, 0)
    try:
        _wal_record(
            run_name=run_name,
            instance_id=instance_id,
            attempt=am.attempt,
            system_prompt=SYSTEM_PROMPT,
            user_msg=am.wal_user_msg,
            response=am.wal_response,
            outcome=outcome,
        )
    except Exception as e:
        # WAL is best-effort — don't ever crash the agent because of it
        print(f"  [wal] WARN: failed to write WAL record: {e}")


from budget_guard import BudgetExceeded, BudgetGuard

# One BudgetGuard per run, lazily created on first cloud call.
_BUDGET_GUARD: BudgetGuard | None = None


def _get_budget(run_name: str) -> BudgetGuard:
    global _BUDGET_GUARD
    if _BUDGET_GUARD is None or _BUDGET_GUARD.run_name != run_name:
        _BUDGET_GUARD = BudgetGuard(run_name=run_name or "unspecified")
    return _BUDGET_GUARD


def _estimate_tokens(text: str) -> int:
    """Cheap, conservative token estimate for pre-call budget gates."""
    return max(1, (len(text) + 3) // 4)


def _budget_purpose(instance_id: str, attempt: int, backend: str) -> str:
    short = _short_name(instance_id) if "__" in instance_id else instance_id
    if attempt == 1:
        return f"programbench:{short}:initial_build:{backend}"
    return f"programbench:{short}:retry_with_eval_feedback:{backend}"


try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

TASKS_DIR = Path("T:/Dev/ProgramBench/src/programbench/data/tasks")
OUTPUT_BASE = Path("T:/determinex-programbench")
CORPUS_ANCHORS_DIR = Path(__file__).resolve().parent.parent / "corpus" / "programbench" / "anchors"
DOCKER_ORG = "programbench"
MAX_RETRIES = int(os.environ.get("DETERMINEX_PB_MAX_RETRIES", "10"))
MODEL = "claude-sonnet-4-6"
MAX_OUTPUT_TOKENS = 64000  # Sonnet 4.6 ceiling — needed for multi-file complex builds

# ---- Model backend (set via --model CLI flag) ----
# "anthropic" → Sonnet 4.6 via Anthropic SDK (default; needs ANTHROPIC_API_KEY)
# "local"     → Qwen2.5-Coder via local Ollama (no API spend, slower per call)
# "deepseek"  → DeepSeek V4 via OpenAI-compat SDK (cheap; needs DEEPSEEK_API_KEY)
MODEL_BACKEND = "anthropic"
LOCAL_MODEL = os.environ.get(
    "DETERMINEX_LOCAL_BUILDER_MODEL",
    "qwen2.5-coder:14b-instruct-q4_K_M",
)
ESCALATE = False  # set by --escalate CLI flag in main()
LOCAL_OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
LOCAL_NUM_PREDICT = 16000  # local model output cap (smaller than Sonnet's 64k)
LOCAL_TIMEOUT = 1800  # 30-min timeout for big generations on local hardware

# Curated easy targets (short name → full instance ID)
EASY_TARGETS: dict[str, str] = {
    "yj": "sclevine__yj.8016400",
    "htmlq": "mgdm__htmlq.6e31bc8",
    "shellharden": "anordal__shellharden.6a6ffd4",
    "zoxide": "ajeetdsouza__zoxide.67ca1bc",
    "csview": "wfxr__csview.8ac4de0",
    "ripsecrets": "sirwart__ripsecrets.34c9e03",
    "dutree": "nachoparker__dutree.44e877d",
}

# ---------------------------------------------------------------------------
# Escalation ladder — auto-promotes the builder when 7b can't make progress.
# Cheaper-first; enabled by default for `--escalate` (the mass-run path).
# ---------------------------------------------------------------------------

# Anchors get the top tier from attempt 1 — heavyweight tools where the spec
# is rich (~30-40 KB) and the architectural reasoning matters.
ANCHOR_TOOLS = {"jq", "fzf", "lz4", "fd", "curlie"}

# (backend, model_tag, label) ordered cheapest → most-capable.
# `model_tag` is used only for the "local" backend.
#
# 14b skipped on this hardware: OOMs reliably on 6GB VRAM (model needs ~8.4GB
# loaded). DeepSeek is $0.001/call, cheaper than the wasted attempt cycles
# of 14b OOMs. Restore the 14b row when running on a card with ≥10GB VRAM.
ESCALATION_LADDER: list[tuple[str, str | None, str]] = [
    ("local", "qwen2.5-coder:7b-instruct", "T1·7b"),
    ("deepseek", None, "T2·deepseek"),
]


def _short_name(instance_id: str) -> str:
    return instance_id.split("__", 1)[-1].split(".", 1)[0].lower()


def _attempt_tier(am) -> int:
    """Recover ladder index from a recorded AttemptMetrics.model_used label.

    Parses the "T<N>·..." prefix we write in the solve loop (e.g. "T2·deepseek"
    → index 1). Falls back to 0 when label is missing or malformed. Ladder-aware
    by construction — works for any 2/3/N-tier ladder so long as labels start
    with "T<rung_1_indexed>".
    """
    label = getattr(am, "model_used", "") or ""
    if label.startswith("T") and len(label) > 1 and label[1].isdigit():
        # Convert 1-indexed "T<N>" to 0-indexed ladder position.
        try:
            idx = int(label[1]) - 1
            if 0 <= idx < len(ESCALATION_LADDER):
                return idx
        except (ValueError, IndexError):
            pass
    return 0


def pick_tier(instance_id: str, history: list, escalate: bool = True) -> int:
    """Decide which ladder index this next attempt should run on.

    Rules (in priority order):
      1. Anchor tools always start at tier 2 (deepseek).
      2. If escalation disabled → always tier 0 (7b).
      3. Find the highest tier already tried; never go DOWN.
      4. At current tier, count failures with no-progress signal:
         template-leak, syntax-blocked, or compile-fail (no eval ran).
         If ≥2 such failures at current tier → escalate one rung.
      5. Hard fallback: after 4 attempts with no compile success, jump to top tier.
    """
    if not escalate:
        return 0
    # Anchors always start at the top tier of the current ladder.
    if _short_name(instance_id) in ANCHOR_TOOLS:
        return len(ESCALATION_LADDER) - 1
    if not history:
        return 0

    current = max(_attempt_tier(a) for a in history)
    same_tier = [a for a in history if _attempt_tier(a) == current]

    # Count "no-progress" failures at current tier.
    def no_progress(a) -> bool:
        if getattr(a, "syntax_blocked", False):
            return True
        if not getattr(a, "compile_ok", False):
            return True
        # Compile passed but eval also failed without scoring → still no progress.
        if getattr(a, "eval_score", -1) == 0 and not getattr(a, "eval_passed", 0):
            return True
        return False

    # Hard fallback FIRST: 4 attempts and never compiled → jump straight to top.
    # (This catches "7b structurally can't generate this language at all".)
    total_compiled = sum(1 for a in history if getattr(a, "compile_ok", False))
    if len(history) >= 4 and total_compiled == 0:
        return len(ESCALATION_LADDER) - 1

    # Soft escalation: 2 no-progress attempts at current tier → bump up one rung.
    no_prog_at_tier = sum(1 for a in same_tier if no_progress(a))
    if no_prog_at_tier >= 2 and current < len(ESCALATION_LADDER) - 1:
        return current + 1

    return current


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


@dataclass
class AttemptMetrics:
    attempt: int
    t_claude_start: float = 0.0
    t_claude_end: float = 0.0
    t_compile_end: float = 0.0
    t_probe_end: float = 0.0
    syntax_blocked: bool = False
    compile_ok: bool = False
    probe_pass: int = 0
    probe_total: int = 0
    eval_score: int = -1  # -1 = not run, 0-100 = official `programbench eval` score
    eval_passed: int = 0
    eval_total: int = 0
    eval_cached: bool = False
    eval_error: str = ""
    model_used: str = ""  # ladder label, e.g. "T1·7b" / "T2·14b" / "T3·deepseek"
    observer_diagnosis: str = ""
    # WAL capture — full prompt + response so the (failure → fix) pair becomes training data.
    # Truncated when written to disk; held in-memory at full length until then.
    wal_user_msg: str = ""
    wal_response: str = ""

    @property
    def t_claude(self) -> float:
        return self.t_claude_end - self.t_claude_start

    @property
    def t_compile(self) -> float:
        return max(0.0, self.t_compile_end - self.t_claude_end)

    @property
    def t_probe(self) -> float:
        return max(0.0, self.t_probe_end - self.t_compile_end)

    @property
    def probe_pct(self) -> float:
        if self.probe_total == 0:
            return 0.0
        return 100.0 * self.probe_pass / self.probe_total


@dataclass
class TaskMetrics:
    instance_id: str
    t_start: float = field(default_factory=time.time)
    t_probe_gen_end: float = 0.0
    attempts: list[AttemptMetrics] = field(default_factory=list)
    t_end: float = 0.0
    solved: bool = False  # legacy alias of verified_locked, kept for back-compat
    shipped: bool = False  # compile-clean submission written to disk
    verified_locked: bool = False  # official `programbench eval` returned score == 100
    final_eval_score: int = -1  # BEST eval score across all attempts (was: last)
    best_attempt: int = -1  # which attempt produced the best score
    best_compile_sh: str = ""  # cached BEST submission (for retry feedback context)
    best_files: dict[str, str] = field(default_factory=dict)
    # Per-test progress tracking: previous attempt's per-test status, used to compute
    # wins (newly passing) / regressions (newly failing) / persistent failures.
    last_per_test: dict[str, str] = field(default_factory=dict)
    # not_run tracking: if not_run increases between attempts, the packaging broke more branches.
    last_not_run: int = 0
    best_not_run: int = 0
    # Best-attempt baselines — used to anchor retry feedback after a regression.
    # When retrying after regression, we show failures from the BEST submission
    # (not the broken regression) so the model knows exactly what to fix.
    best_per_test: dict[str, str] = field(default_factory=dict)
    best_eval_feedback: str = ""

    @property
    def elapsed(self) -> float:
        return (self.t_end or time.time()) - self.t_start

    @property
    def final_pct(self) -> float:
        if not self.attempts:
            return 0.0
        last = self.attempts[-1]
        return last.probe_pct if last.compile_ok else 0.0

    def save(self, run_dir: Path) -> None:
        path = run_dir / self.instance_id / "metrics.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(dataclasses.asdict(self), indent=2), encoding="utf-8")

    def print_summary(self) -> None:
        elapsed = self.elapsed
        status = (
            "VERIFIED LOCK"
            if self.verified_locked
            else ("SHIPPED" if self.shipped else "NO SUBMISSION")
        )
        eval_str = f"{self.final_eval_score}/100" if self.final_eval_score >= 0 else "no eval"
        print(f"\n  +-- {self.instance_id}")
        print(
            f"  |   Total: {elapsed:.0f}s ({elapsed / 60:.1f}m)  Status: {status}  Final eval: {eval_str}"
        )
        print("  |")
        print(
            f"  |   {'Att':>3}  {'%Probe':>6}  {'Eval':>6}  {'Claude':>7}  {'Compile':>8}  {'Probe':>6}  Note"
        )
        print(
            f"  |   {'---':>3}  {'------':>6}  {'------':>6}  {'-------':>7}  {'--------':>8}  {'------':>6}"
        )
        for a in self.attempts:
            if a.syntax_blocked:
                note = "SYNTAX BLOCKED"
                pct = "-"
            elif not a.compile_ok:
                note = "COMPILE FAIL"
                pct = "-"
            else:
                pct = f"{a.probe_pct:.0f}%"
                if a.eval_score >= 100:
                    note = "VERIFIED LOCK"
                elif a.eval_score >= 0:
                    note = f"eval {a.eval_passed}/{a.eval_total}"
                else:
                    note = f"probe {a.probe_pass}/{a.probe_total}"
                if a.observer_diagnosis:
                    note += " [Obs]"
            ev = f"{a.eval_score}" if a.eval_score >= 0 else "-"
            print(
                f"  |   {a.attempt:>3}  {pct:>6}  {ev:>6}  "
                f"{a.t_claude:>6.0f}s  {a.t_compile:>7.0f}s  {a.t_probe:>5.0f}s  {note}"
            )
        print(
            f"  +-- final eval: {eval_str}  shipped: {self.shipped}  locked: {self.verified_locked}"
        )


# ---------------------------------------------------------------------------
# Docker helpers
# ---------------------------------------------------------------------------


def image_name(instance_id: str) -> str:
    return f"{DOCKER_ORG}/{instance_id.replace('__', '_1776_')}:task_cleanroom"


def docker_run(image: str, cmd: str, timeout: int = 120) -> tuple[str, int]:
    result = subprocess.run(
        ["docker", "run", "--rm", image, "bash", "-c", cmd],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return ((result.stdout or "") + (result.stderr or "")).strip(), result.returncode


def pull_image(instance_id: str) -> bool:
    img = image_name(instance_id)
    print(f"  Pulling {img}...")
    try:
        result = subprocess.run(
            ["docker", "pull", img], capture_output=True, text=True, timeout=1800
        )
    except subprocess.TimeoutExpired:
        print(f"  PULL TIMED OUT after 1800s — skipping {instance_id}")
        return False
    except Exception as e:
        print(f"  PULL ERRORED: {type(e).__name__}: {str(e)[:160]} — skipping {instance_id}")
        return False
    if result.returncode != 0:
        print(f"  PULL FAILED: {result.stderr[:200]}")
        return False
    print("  Pulled.")
    return True


# ---------------------------------------------------------------------------
# Binary probing
# ---------------------------------------------------------------------------

PROBE_COMMANDS = [
    "cat /workspace/README.md 2>/dev/null | head -120",
    "/workspace/executable --help 2>&1 || /workspace/executable -h 2>&1 || true",
    "/workspace/executable --version 2>&1 || true",
]

# Extra probes by task type (keyed on partial instance_id match)
EXTRA_PROBES: dict[str, list[str]] = {
    "yj": [
        # Use printf so \\n expands to real newlines inside the container
        "printf 'name: test\\nvalue: 42\\nlist:\\n  - a\\n  - b\\n' | BINARY -yj 2>&1",
        'printf \'{"name":"test","value":42}\\n\' | BINARY -jy 2>&1',
        "printf '[title]\\nhello = \"world\"\\n' | BINARY -tj 2>&1",
        "printf 'name: test\\nvalue: 42\\n' | BINARY -yj -i 2>&1",
        'printf \'{"a":1,"b":2}\\n\' | BINARY -jt 2>&1',
        "printf 'key = \"val\"\\n[section]\\nfoo = 1\\n' | BINARY -tj 2>&1",
    ],
    "htmlq": [
        'printf \'<html><body><h1 id="main">Hello</h1><p class="intro">World</p><a href="/foo">link</a></body></html>\\n\' | BINARY \'p.intro\' 2>&1',
        "printf '<html><body><h1>Hello</h1><p>World</p></body></html>\\n' | BINARY --text 'p' 2>&1",
        "printf '<html><body><a href=\"/page\">link</a></body></html>\\n' | BINARY --attribute href 'a' 2>&1",
        "printf '<ul><li>one</li><li>two</li></ul>\\n' | BINARY 'li' 2>&1",
        "printf '<div class=\"a\"><span>hi</span></div>\\n' | BINARY '.a span' 2>&1",
    ],
    "shellharden": [
        "printf '#!/bin/bash\\necho $HOME\\nls $1\\n' | BINARY --syntax-suggest /dev/stdin 2>&1 || true",
        "printf '#!/bin/bash\\nfor f in *.txt; do echo $f; done\\n' | BINARY 2>&1 || true",
    ],
    "zoxide": [
        "/workspace/executable add /tmp 2>&1 || true",
        "/workspace/executable query /tmp 2>&1 || true",
        "/workspace/executable init bash 2>&1 | head -20 || true",
    ],
    "csview": [
        "printf 'name,age,city\\nAlice,30,NYC\\nBob,25,LA' | /workspace/executable 2>&1",
        "printf 'a,b,c\\n1,2,3' | /workspace/executable --header 2>&1 || true",
    ],
    "ripsecrets": [
        "echo 'AWS_KEY=AWS_KEY_PLACEHOLDER' > /tmp/test.txt && /workspace/executable /tmp/test.txt 2>&1 || true",
    ],
    "dutree": [
        "/workspace/executable /tmp 2>&1 | head -20 || true",
    ],
}


def probe_binary(instance_id: str) -> str:
    img = image_name(instance_id)
    parts: list[str] = []

    for cmd in PROBE_COMMANDS:
        try:
            out, _ = docker_run(img, cmd, timeout=60)
            if out:
                parts.append(f"$ {cmd.split(chr(10))[0][:80]}\n{out}")
        except subprocess.TimeoutExpired:
            pass

    # Extra probes for known tasks (resolve BINARY placeholder)
    for key, probes in EXTRA_PROBES.items():
        if key in instance_id:
            for cmd in probes:
                real_cmd = cmd.replace("BINARY", "/workspace/executable")
                try:
                    out, rc = docker_run(img, real_cmd, timeout=30)
                    parts.append(f"$ {real_cmd[:80]}\n[exit {rc}]\n{out}")
                except subprocess.TimeoutExpired:
                    pass
            break

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Code generation
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are an expert software engineer reimplementing CLI tools from scratch.
You must produce a complete, working implementation given only documentation
and observed binary behavior. Focus on correctness — matching the exact output
format, flag names, and behavior of the original.

The Docker container where your code runs has:
  - python3 (3.10), pip (network available — pip install works)
  - go 1.21 (stdlib only without network, but pip is better for quick solutions)
  - cargo/rustc 1.92 (compilation takes longer)
  - gcc 11, apt-get (as root)

IMPORTANT: Your compile.sh MUST produce ./executable in the current directory.
For Python: make ./executable a self-contained executable script.
For Go: go build -o executable .
For C: gcc -o executable *.c

═══════════════════════════════════════════════════════════════════════════════
COMPILED-LANGUAGE COMPILE.SH (Go / Rust / C / C++) — READ THIS FIRST
═══════════════════════════════════════════════════════════════════════════════

If you pick Go, your compile.sh MUST contain BOTH lines, in this order:
    go mod init prog 2>/dev/null || true
    go build -o executable .
NEVER omit the `go mod init` — without it, compile fails with "cannot find main module".

If you pick Rust (single file), your compile.sh MUST be:
    rustc -O main.rs -o executable
DO NOT cp main.rs to executable. DO NOT add `chmod +x` (rustc handles it).
DO NOT use `cargo` unless you also write a Cargo.toml.

If you pick C, your compile.sh MUST be:
    gcc -O2 -o executable main.c       (single file)
    gcc -O2 -o executable *.c          (multiple files)

If you pick C++, your compile.sh MUST be:
    g++ -O2 -std=c++17 -o executable main.cpp

═══════════════════════════════════════════════════════════════════════════════
GO STDLIB QUICK-REFERENCE (preventing API hallucination):
═══════════════════════════════════════════════════════════════════════════════
- Read all stdin to []byte:       data, _ := io.ReadAll(os.Stdin)
  (NOT `os.Stdin.ReadBytes` — that doesn't exist on *os.File)
- Read stdin lines:               s := bufio.NewScanner(os.Stdin); for s.Scan() { line := s.Text() }
- Time:                           import "time"; t := time.Now()
- JSON:                           import "encoding/json"; json.Unmarshal(data, &v) / json.MarshalIndent(v, "", "  ")
- File read:                      data, _ := os.ReadFile(path)
- Args:                           os.Args[1:] for positional, flag.Parse() for flags
- Print to stderr:                fmt.Fprintln(os.Stderr, "msg")
- Exit:                           os.Exit(1)

═══════════════════════════════════════════════════════════════════════════════
RUST STDLIB QUICK-REFERENCE (preventing API hallucination):
═══════════════════════════════════════════════════════════════════════════════
- Read all stdin to String:       use std::io::Read; let mut s = String::new(); std::io::stdin().read_to_string(&mut s)?;
- Read stdin lines:               use std::io::BufRead; for line in std::io::stdin().lock().lines() { let l = line?; }
- Read all stdin to bytes:        use std::io::Read; let mut buf = Vec::new(); std::io::stdin().read_to_end(&mut buf)?;
- Args:                           let args: Vec<String> = std::env::args().collect();
- Print to stderr:                eprintln!("msg");
- Exit with code:                 std::process::exit(1);
- File read:                      let s = std::fs::read_to_string(&path)?;
- Single-file program: use ONLY `std::*` — no external crates work without Cargo.toml.
  Common need? Implement it yourself in pure std (e.g., write a tiny regex-free parser).

═══════════════════════════════════════════════════════════════════════════════
HARD RULES — violating these wastes a full attempt cycle (~2-3 minutes):
═══════════════════════════════════════════════════════════════════════════════

R1. NEVER `pip install` a package with the same name as the tool you're
    reimplementing. (`fzf`, `ripgrep`, `htmlq`, `jq`, etc. are NOT pip packages.)
    YOU are writing the tool. Don't try to install the tool you're rewriting.

R2. STDLIB FIRST. Default to Python stdlib (`json`, `re`, `argparse`,
    `subprocess`, `pathlib`, `csv`, `xml.etree`, `sqlite3`, `urllib`). Only
    `pip install` for things stdlib genuinely cannot do (e.g. `lxml` for HTML,
    `requests` for HTTP convenience, `colorama` for ANSI on Windows).
    If you must pip install, use a real, well-known package — never a guess.

R3. NO MULTI-LINE STRING BANNERS. Do not write decorative comment banners with
    `print("# =================...")` spanning many `=` chars on a single line —
    the 7B builder consistently breaks the closing quote and produces a
    SyntaxError. Use `print("# " + "=" * 60)` or just omit banners.

R4. CLOSE EVERY STRING AND BRACKET. Before emitting the </file> tag, mentally
    scan: every `"` paired, every `'` paired, every `(`, `[`, `{` closed, every
    `def`/`class` ends with a body. An unclosed string costs a full attempt.

R5. ONE FILE PER LANGUAGE WHEN POSSIBLE. Prefer a single `main.py` over
    splitting into 4 modules — small surface area means fewer broken imports.

R6. NO PLACEHOLDERS. Never write `# TODO`, `pass  # implement later`,
    `raise NotImplementedError`, `# stub`, or empty function bodies. The grader
    runs the binary against real inputs — empty bodies fail every test.

R7. EXIT CODES MATTER. Standard CLI convention: 0 on success, non-zero on
    error. Most tests assert `result.returncode == 0` for valid input. Your
    `executable` should `sys.exit(0)` (or just return) on success and only
    raise/exit non-zero on real errors.

R8. READ STDIN PROPERLY. Many ProgramBench tools take input on stdin. Use
    `sys.stdin.read()` for whole-input reads, `sys.stdin.buffer.read()` for
    binary, and `for line in sys.stdin:` for streaming. Don't assume input
    is a file argument unless the spec says so.

R9. WRITE TO STDOUT, NOT FILES. Tests capture stdout via subprocess.
    Use `print(...)` or `sys.stdout.write(...)` — not `open("out.txt", "w")`.

R10. compile.sh MUST CONTAIN REAL BUILD COMMANDS — not comments. The grader
    invokes `./executable [args]` directly. After compile.sh runs, `./executable`
    MUST exist in the current working directory, executable, with a working
    shebang. COMMENTS ALONE FAIL EVERY TEST.

    EXACT TEMPLATE for Python:
      #!/bin/bash
      set -e
      pip install --quiet --no-cache-dir <only-real-pkgs>   # OMIT this line if no deps needed
      cp main.py executable
      chmod +x executable
      # main.py must start with: #!/usr/bin/env python3

    EXACT TEMPLATE for Go:
      #!/bin/bash
      set -e
      go build -o executable .

    EXACT TEMPLATE for Rust (single-file):
      #!/bin/bash
      set -e
      rustc -O main.rs -o executable

    EXACT TEMPLATE for C / C++:
      #!/bin/bash
      set -e
      gcc -O2 -o executable *.c              # for C
      g++ -O2 -std=c++17 -o executable *.cpp  # for C++

    NEVER emit a compile.sh that is just `#!/bin/bash` + `set -e` + comments.
    NEVER emit `# build / prepare the executable` as if it were code. Build it.

R11. ARG PARSING. Use `argparse` for >3 flags; manual `sys.argv[1:]` parsing
    for simple cases. Match flag names EXACTLY (case-sensitive, dash-style:
    `--no-color` not `--noColor`). Do NOT add click/typer (unnecessary dep).

R12. UTF-8 EXPLICITLY. Every `open(...)` needs `encoding="utf-8"`. Default
    Linux locale may be C (ASCII-only) and silently break on Unicode input.
    For binary I/O use `sys.stdin.buffer` / `sys.stdout.buffer`.

R13. SUBPROCESS WRAPPING IS FAIR GAME. If the tool wraps a system utility
    (`tar`, `git`, `ffmpeg`, `curl`, `awk`), it's OK to `subprocess.run()`
    that utility from inside your executable. The grader checks output, not
    implementation. Use `subprocess.run([...], capture_output=True, text=True)`.

R14. NO ANSI COLORS BY DEFAULT. Most tests strip-compare or byte-compare
    output. Only emit color if `--color=always` is passed OR `sys.stdout.isatty()`
    is True. Default to plain text.

R15. ERROR FORMAT. Standard Unix style: `tool-name: error: <message>` to
    stderr (NOT stdout), then `sys.exit(1)`. Many tests assert on stderr
    content as well as exit code.

R16. PATHLIB. Use `pathlib.Path` for path handling, not string concat.
    `Path.expanduser()` for `~`, `Path.resolve()` for relative.

R17. JSON. Whole-file: `json.loads(sys.stdin.read())`. JSONL/NDJSON:
    iterate `for line in sys.stdin: json.loads(line)`. Many tools accept
    BOTH — try whole-file first, fall back to per-line on JSONDecodeError.

R18. NEVER MAKE NETWORK CALLS AT RUNTIME (during ./executable invocation).
    The grader sandbox blocks outbound HTTP. pip install during compile.sh
    is fine; `urlopen()` while executing is not. Use stub / local data.

R19. IMPLEMENT --help, --version, -h, -v ALWAYS. Many test branches start
    with `BINARY --help` to confirm the binary exists; missing this kills
    the entire test branch. Even a one-line help message + exit 0 works.

R20. PRESERVE INPUT ORDER UNLESS SORTED IS REQUESTED. If input has order
    (lines from stdin, command-line args), preserve it. Default sort is
    lexicographic; only sort when the spec says so.

R21. NEWLINE AT END OF OUTPUT. POSIX convention: last line ends with `\\n`.
    `print()` adds it; `sys.stdout.write()` does NOT. Tests do byte-exact
    compares; missing trailing newline is the #1 silent-failure mode.

R22. compile.sh STARTS WITH `#!/bin/bash` + `set -e`. Without `set -e`, a
    silent dependency-install failure leaves you with a "compiled" binary
    that crashes on every test. Always fail loud.

R23. pip install --quiet --no-cache-dir <pkg>. Default pip is verbose and
    slow; --quiet is 5-10× faster and avoids log truncation. Always pin
    nothing; let pip pick the latest compatible version.

R24. EMPTY STDIN MUST NOT CRASH. Tests routinely pass `b""` and assert
    `returncode == 0` with empty output. Code path: `data = sys.stdin.read();
    if not data: sys.exit(0)`. Don't call `json.loads("")` etc.

R25. STREAM LARGE INPUT. Some tests are 50MB+. Use `for line in sys.stdin:`
    or `sys.stdin.buffer.read(chunk_size)` instead of `sys.stdin.read()` if
    the tool's nature allows streaming.

R26. RAW STRINGS FOR REGEX. Use `r"\\d+"` not `"\\d+"` to avoid double-escape
    bugs. Same for Windows-style paths if any (won't apply in Docker, but
    preserves habits).

R27. NO `input()`, NO `eval()`, NO `exec()`. `input()` is interactive — tests
    pipe stdin via subprocess so it'd block. `eval`/`exec` is a security
    + correctness antipattern — never the right answer.

R28. DOCKER RUNS AS ROOT. No `sudo` available (and not needed). `apt-get`
    works directly. `pip install` works directly. No permission errors
    expected — if you see one, it's a real bug.

R29. READ THE BEHAVIORAL SPEC FIRST. If `corpus/programbench/anchors/<NN>_<tool>/
    06_behavioral_spec.md` is provided in your context, it has the EXACT
    expected behavior with examples. The spec wins over your guess every time.

R30. ON RETRY, READ `prior_error` CAREFULLY. The retry feedback contains the
    exact failing test name + assertion message + test code. Fix THAT specific
    failure — do not rewrite from scratch. Each retry that ignores feedback
    is a wasted attempt.

R31. SIGPIPE. Tools that pipe into `head`/`grep` get SIGPIPE when the
    consumer closes early. Add `import signal; signal.signal(signal.SIGPIPE,
    signal.SIG_DFL)` near the top of the executable (Linux only — wrap in
    try/except for portability).

R32. NO PLACEHOLDER OUTPUTS like "TODO", "stub", "TBD", or empty `[]`/`{}` —
    tests check exact content. If you don't know the right output for a
    given input, omit the function or return something derivable from input
    (echo it back, etc.) — never a placeholder.

R33. EXPECT BINARY DATA. Some tools (lz4, blake3, ripsecrets) work on bytes,
    not strings. Use `sys.stdin.buffer.read()` and `sys.stdout.buffer.write()`.
    Don't decode unless the spec says it's text.
═══════════════════════════════════════════════════════════════════════════════
"""


def parse_response(text: str) -> tuple[str, dict[str, str]]:
    """Extract compile_sh and source files from Claude's response."""
    import re

    compile_sh = ""
    files: dict[str, str] = {}

    # Extract <compile_sh>...</compile_sh> (handles slightly wrong tags)
    m = re.search(
        r"<(?:compile_sh|compile\.sh|compilesh)[^>]*>(.*?)</(?:compile_sh|compile\.sh|compilesh)>",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    if m:
        compile_sh = m.group(1).strip()

    # Extract <file name="...">...</file> blocks (handles single/double/no quotes and name= vs path=)
    for m in re.finditer(
        r'<file\s+(?:name|path)=["\']?([^"\'>\s]+)["\']?>(.*?)</file>',
        text,
        re.DOTALL | re.IGNORECASE,
    ):
        fname, content = m.group(1), m.group(2).strip()
        files[fname] = content

    # Fallback: handle unclosed <file> tags (response truncated at max_tokens)
    if not files:
        for m in re.finditer(
            r'<file\s+(?:name|path)=["\']?([^"\'>\s]+)["\']?>(.*)', text, re.DOTALL | re.IGNORECASE
        ):
            fname, content = m.group(1), m.group(2).strip()
            # Strip any trailing partial XML
            content = re.sub(r"\s*</?\w[^>]*>?\s*$", "", content).strip()
            files[fname] = content
            break  # Only grab the first (and likely only) file

    # Fallback: try markdown code blocks if no XML tags found
    if not compile_sh:
        # Look for compile.sh in code blocks - check for compiler commands directly
        for m in re.finditer(r"```(?:bash|sh)?\n(.*?)```", text, re.DOTALL):
            block = m.group(1).strip()
            if any(x in block for x in ["gcc", "rustc", "go build", "./executable", "cp main.py"]):
                compile_sh = block
                break

    # Fallback: if files still empty, try to extract named code blocks
    if not files and compile_sh:
        for m in re.finditer(r"```(?:python|go|rust|c|cpp|sh|bash)?\n(.*?)```", text, re.DOTALL):
            block = m.group(1).strip()
            if block == compile_sh:
                continue

            # Label before the block?
            pre = text[max(0, text.index(m.group(0)) - 200) : text.index(m.group(0))]
            label_match = re.search(r"(\S+\.\w+)\s*[:\n]\s*$", pre.strip())
            if label_match:
                files[label_match.group(1)] = block
            elif "main.py" in pre[-80:] or "main.go" in pre[-80:] or "main.rs" in pre[-80:]:
                ext_match = re.search(r"(main\.\w+)", pre[-80:])
                if ext_match:
                    files[ext_match.group(1)] = block
            elif len(block) > 100 and not files:
                # Guess language by content if no label
                if "import " in block or "def " in block:
                    files["main.py"] = block
                elif "package main" in block:
                    files["main.go"] = block
                elif "fn main()" in block or "use std::" in block:
                    files["main.rs"] = block
                elif "#include" in block:
                    files["main.c"] = block
                else:
                    files["main.py"] = block
                break

    return compile_sh, files


CORPUS_ROOT = Path(__file__).resolve().parent.parent / "corpus" / "programbench"
CORPUS_INPROGRESS = CORPUS_ROOT / "in_progress"
CORPUS_STRATEGY = CORPUS_ROOT / "_strategy"
CORPUS_LOCKED = CORPUS_ROOT / "locked"
WISDOM_DB_PATH = Path(os.path.expanduser("~/AppData/Roaming/run.determinex.app/determinex.sqlite"))


def load_behavioral_spec(instance_id: str) -> str:
    """Return the empirical behavioral spec for this tool, in order of preference:
       1. corpus/programbench/in_progress/<iid>/06_behavioral_spec.md  (193 tools)
       2. corpus/programbench/anchors/<NN>_<short>/06_behavioral_spec.md  (5 anchors)
    Returns "" if neither exists.
    """
    # Per-tool spec — covers 193 of ~200 tools at ~38KB each.
    inprog_spec = CORPUS_INPROGRESS / instance_id / "06_behavioral_spec.md"
    if inprog_spec.exists():
        return inprog_spec.read_text(encoding="utf-8", errors="replace")

    # Anchor specs — fallback for the 5 anchor tools.
    if not CORPUS_ANCHORS_DIR.exists():
        return ""
    short = instance_id.split("__", 1)[-1].split(".", 1)[0]
    for d in sorted(CORPUS_ANCHORS_DIR.iterdir()):
        if not d.is_dir():
            continue
        parts = d.name.split("_", 1)
        if len(parts) == 2 and parts[1].lower() == short.lower():
            spec_file = d / "06_behavioral_spec.md"
            if spec_file.exists():
                return spec_file.read_text(encoding="utf-8", errors="replace")
    return ""


# ── Universal playbook — loaded once, cached, prepended to every user_msg ───

_PLAYBOOK_CACHE: str | None = None

_PB_PLAYBOOK_PATH = (
    Path(__file__).resolve().parent.parent / "docs" / "programs" / "programbench" / "PB_PLAYBOOK.md"
)


def load_universal_playbook() -> str:
    """Concatenate the load-bearing strategy docs into one block. Cached."""
    global _PLAYBOOK_CACHE
    if _PLAYBOOK_CACHE is not None:
        return _PLAYBOOK_CACHE
    parts: list[str] = []
    for fname in (
        "universal_cli_patterns.md",
        "per_language_scaffolds.md",
        "empirical_spec_method.md",
    ):
        p = CORPUS_STRATEGY / fname
        if p.exists():
            txt = p.read_text(encoding="utf-8", errors="replace")
            parts.append(f"## {fname}\n\n{txt}")
    # Append the campaign playbook with proven fix recipes
    if _PB_PLAYBOOK_PATH.exists():
        txt = _PB_PLAYBOOK_PATH.read_text(encoding="utf-8", errors="replace")
        # Trim to first 3000 chars to stay within token budget
        parts.append("## PB_PLAYBOOK (proven recipes)\n\n" + txt[:3000])
    _PLAYBOOK_CACHE = "\n\n---\n\n".join(parts)
    return _PLAYBOOK_CACHE


# ── Locked-tool lessons — same-language prior-art for transfer learning ─────


# Filename hint → language map. Used to pick which locked tools' lessons apply.
def _detect_lang(files: dict[str, str]) -> str:
    if not files:
        return ""
    fnames = " ".join(files.keys()).lower()
    if "main.py" in fnames or fnames.endswith(".py"):
        return "python"
    if "main.go" in fnames or ".go" in fnames:
        return "go"
    if "main.rs" in fnames or ".rs" in fnames:
        return "rust"
    if ".cpp" in fnames or ".cc" in fnames:
        return "cpp"
    if ".c" in fnames:
        return "c"
    return ""


# Per-language lessons (curated from `corpus/programbench/locked/<X>/lessons.md`)
_LOCKED_LESSONS_CACHE: dict[str, str] | None = None


def load_locked_lessons_for_lang(_lang: str) -> str:
    """Return concatenated `lessons.md` from locked tools.
    Currently lessons are general CLI wisdom (transferable across languages),
    so `_lang` is accepted for future per-language filtering but not yet used."""
    global _LOCKED_LESSONS_CACHE
    if _LOCKED_LESSONS_CACHE is None:
        _LOCKED_LESSONS_CACHE = {}
        if CORPUS_LOCKED.exists():
            # heuristic: htmlq, ripsecrets are both Rust originals; their lessons are
            # transferable to other small CLI tools regardless of target language.
            for d in CORPUS_LOCKED.iterdir():
                if not d.is_dir():
                    continue
                lp = d / "lessons.md"
                if lp.exists():
                    _LOCKED_LESSONS_CACHE.setdefault("any", "")
                    _LOCKED_LESSONS_CACHE["any"] += (
                        f"\n\n## Lessons from locked tool: {d.name}\n\n"
                        + lp.read_text(encoding="utf-8", errors="replace")
                    )
    return _LOCKED_LESSONS_CACHE.get("any", "")


# ── RAG retrieval against wisdom DB (sqlite-vec + fastembed) ────────────────

_RAG_CONN = None
_RAG_EMBEDDER = None


def _rag_init() -> bool:
    """Lazy init of sqlite + fastembed. Returns False if unavailable."""
    global _RAG_CONN, _RAG_EMBEDDER
    if _RAG_CONN is not None and _RAG_EMBEDDER is not None:
        return True
    if not WISDOM_DB_PATH.exists():
        return False
    try:
        import sqlite3

        import sqlite_vec
        from fastembed import TextEmbedding

        _RAG_CONN = sqlite3.connect(str(WISDOM_DB_PATH), check_same_thread=False)
        _RAG_CONN.enable_load_extension(True)
        sqlite_vec.load(_RAG_CONN)
        _RAG_EMBEDDER = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
        return True
    except Exception as _e:
        print(f"  [rag] init failed: {_e}; RAG disabled")
        return False


def rag_retrieve_for_task(instance_id: str, top_k: int = 5, max_chars: int = 6000) -> str:
    """Query wisdom DB for top-K most-relevant chunks for this tool.
    Returns formatted block or "" if RAG unavailable / no hits.
    Filters to programbench-tagged chunks only.

    Query construction: use the FIRST 600 chars of the tool's own behavioral spec
    (which describes what the tool does) rather than a generic "reimplement CLI"
    phrase. This dramatically improves chunk relevance — was returning lz4/atlas
    for go-mod-outdated; now returns Go/JSON/markdown-related chunks.
    """
    if not _rag_init():
        return ""
    short = instance_id.split("__", 1)[-1].split(".", 1)[0]
    # Build a domain-specific query from the tool's actual spec content.
    spec_path = CORPUS_INPROGRESS / instance_id / "06_behavioral_spec.md"
    if spec_path.exists():
        spec_head = spec_path.read_text(encoding="utf-8", errors="replace")[:600]
        # Strip YAML frontmatter if present
        if spec_head.startswith("---"):
            end = spec_head.find("---", 3)
            if end > 0:
                spec_head = spec_head[end + 3 :]
        # Strip markdown headers and collapse whitespace
        spec_head = " ".join(
            line for line in spec_head.split("\n") if line.strip() and not line.startswith("#")
        )
        query = f"{short} CLI tool: {spec_head[:400]}"
    else:
        query = f"reimplement {short} CLI tool"
    try:
        embeds = list(_RAG_EMBEDDER.embed([query]))  # type: ignore
        if not embeds:
            return ""
        vec = embeds[0]
        if hasattr(vec, "tolist"):
            vec_list = vec.tolist()
        else:
            vec_list = list(vec)
        # serialize as float32 little-endian
        import struct

        vec_bytes = struct.pack(f"<{len(vec_list)}f", *vec_list)
        cur = _RAG_CONN.cursor()  # type: ignore
        # sqlite-vec requires `k = ?` on KNN queries (not LIMIT).
        # Pull a wider set first, then filter to programbench-tagged in Python.
        wide_k = top_k * 6
        cur.execute(
            """
            SELECT vss.rowid
            FROM vss_wisdom vss
            WHERE vss.embedding_vector MATCH ? AND k = ?
        """,
            (vec_bytes, wide_k),
        )
        rowids = [r[0] for r in cur.fetchall()]
        if not rowids:
            return ""
        placeholders = ",".join("?" * len(rowids))
        cur.execute(
            f"""
            SELECT id, metadata, content FROM wisdom
            WHERE id IN ({placeholders}) AND metadata LIKE '%programbench%'
        """,
            rowids,
        )
        rows = cur.fetchall()[:top_k]
        if not rows:
            return ""
        out_parts = []
        running = 0
        for _id, meta, content in rows:
            chunk = f"--- {meta} ---\n{content}\n"
            if running + len(chunk) > max_chars:
                break
            out_parts.append(chunk)
            running += len(chunk)
        return "\n".join(out_parts)
    except Exception as _e:
        print(f"  [rag] query failed: {_e}")
        return ""


def _generate_via_local_ollama(
    system_prompt: str, user_msg: str, model_tag: str | None = None
) -> str:
    """Call local Ollama; returns the assistant message text. Used when MODEL_BACKEND=local."""
    import urllib.error
    import urllib.request

    payload = {
        "model": model_tag or LOCAL_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ],
        "stream": False,
        "options": {
            "num_predict": LOCAL_NUM_PREDICT,
            "temperature": 0.1,
            # 16K context — anything bigger spills KV cache to RAM on 6GB VRAM
            # and stalls the call. Local 7b gets a TRUNCATED corpus injection;
            # full corpus only goes to DeepSeek which has 64K and runs in cloud.
            "num_ctx": 16384,
        },
    }
    # Retry up to 3x on transient errors (HTTP 500/503/connection reset).
    # Ollama can hiccup under VRAM/RAM pressure; one 500 shouldn't kill a 115-task run.
    last_err: Exception | None = None
    for tries in range(3):
        req = urllib.request.Request(
            f"{LOCAL_OLLAMA_URL}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=LOCAL_TIMEOUT) as resp:
                data = json.loads(resp.read())
                return data.get("message", {}).get("content", "")
        except urllib.error.HTTPError as e:
            last_err = e
            print(f"  [ollama] HTTP {e.code} on try {tries + 1}/3 — backing off {3 * (tries + 1)}s")
            import time as _t

            _t.sleep(3 * (tries + 1))
        except urllib.error.URLError as e:
            last_err = e
            print(
                f"  [ollama] connection error on try {tries + 1}/3: {e} — backing off {3 * (tries + 1)}s"
            )
            import time as _t

            _t.sleep(3 * (tries + 1))
    # All 3 retries failed — return empty string so attempt is marked failed but run continues.
    print(
        f"  [ollama] FAILED after 3 retries: {last_err}. Returning empty (attempt will be marked failed)."
    )
    return ""


def _generate_via_deepseek(system_prompt: str, user_msg: str) -> tuple[str, int, int]:
    """Call DeepSeek via OpenAI-compat SDK. Returns (text, tokens_in, tokens_out).
    Model selectable via env DETERMINEX_DEEPSEEK_MODEL (default 'deepseek-chat').
    Use 'deepseek-reasoner' for the thinking model when chat plateaus.
    Retries up to 3× on transient errors (5xx, timeouts, connection reset)."""
    from openai import OpenAI

    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY not set")
    model = os.environ.get("DETERMINEX_DEEPSEEK_MODEL", "deepseek-chat")
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    last_err: Exception | None = None
    for tries in range(3):
        try:
            completion = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_msg},
                ],
                max_tokens=16000,
                temperature=0.1,
                timeout=600,  # 10min — reasoner can take a while
            )
            text = completion.choices[0].message.content or ""
            usage = getattr(completion, "usage", None)
            in_tok = int(getattr(usage, "prompt_tokens", 0) or 0)
            out_tok = int(getattr(usage, "completion_tokens", 0) or 0)
            return text, in_tok, out_tok
        except Exception as e:
            last_err = e
            es = str(e).lower()
            # Retry on transient errors only (don't burn money on auth/quota fails)
            transient = any(
                s in es
                for s in (
                    "timeout",
                    "timed out",
                    "503",
                    "502",
                    "504",
                    "connection",
                    "reset",
                    "rate limit",
                    "ratelimit",
                    "too many requests",
                )
            )
            if not transient or tries == 2:
                # Non-transient or last try → give up
                raise
            backoff = 5 * (tries + 1)
            print(
                f"  [deepseek] transient error on try {tries + 1}/3: {str(e)[:120]} — backing off {backoff}s"
            )
            import time as _t

            _t.sleep(backoff)
    # Should not reach here
    raise last_err if last_err else RuntimeError("deepseek call failed")


def generate_code(
    instance_id: str,
    observations: str,
    prior_error: str = "",
    attempt: int = 1,
    backend: str | None = None,
    model_tag: str | None = None,
    run_name: str = "",
    prior_compile_sh: str = "",
    prior_files: dict[str, str] | None = None,
    best_eval_score: int = -1,
) -> tuple[str, dict[str, str], str, str]:
    """Generate (compile_sh, files) for one attempt.

    backend / model_tag override the module-level MODEL_BACKEND / LOCAL_MODEL
    when escalation is in play. Falls back to globals if not provided.
    run_name is used for cloak audit logging.

    prior_compile_sh + prior_files = the WORKING-OR-BEST submission from a previous
    attempt, injected into the prompt so the model can diff + patch instead of
    rewriting from scratch (avoids regression).
    """
    backend = backend or MODEL_BACKEND

    task_yaml = (TASKS_DIR / instance_id / "task.yaml").read_text()

    # ── Corpus injection sizing — backend-aware + attempt-aware ──
    # Local 7b: 16K context (KV cache fits in 6GB VRAM only at this size).
    # DeepSeek: 64K context. On RETRY attempts, the error_block adds the full
    # best source (up to 25KB) + failure analysis; shrink corpus so total fits.
    if backend == "local":
        spec_max, playbook_max, lessons_max, rag_max = 8000, 3000, 1500, 2500  # ~15KB total
    elif attempt == 1:
        spec_max, playbook_max, lessons_max, rag_max = 38000, 8000, 3000, 5000  # ~54KB
    else:
        # Retry: prior source (~25KB) + failure analysis (~8KB) = ~33KB error block.
        # Keep spec tight (10K for key Python rules), reduce playbook/rag/lessons.
        spec_max, playbook_max, lessons_max, rag_max = 10000, 2000, 1000, 1500  # ~14.5KB corpus

    spec = load_behavioral_spec(instance_id)
    spec_block = ""
    if spec:
        spec_block = f"""

Behavioral spec (empirically derived from the actual test suite — follow this as the authoritative contract):
<behavioral_spec>
{spec[:spec_max]}
</behavioral_spec>
"""
        if attempt == 1:
            print(
                f"  [spec] injecting {min(len(spec), spec_max):,}/{len(spec):,} chars of behavioral spec ({backend})"
            )

    # Universal playbook (loaded once, cached): CLI patterns + per-language scaffolds + spec method.
    playbook = load_universal_playbook()
    playbook_block = ""
    if playbook:
        playbook_block = f"""

Universal CLI implementation playbook (apply these patterns to every tool):
<playbook>
{playbook[:playbook_max]}
</playbook>
"""
        if attempt == 1:
            print(
                f"  [playbook] injecting {min(len(playbook), playbook_max):,} chars of universal patterns"
            )

    # Locked-tool lessons (transferable wisdom from prior wins).
    lessons = load_locked_lessons_for_lang("any")
    lessons_block = ""
    if lessons:
        lessons_block = f"""

Lessons from previously-locked tools (transferable wisdom):
<locked_lessons>
{lessons[:lessons_max]}
</locked_lessons>
"""
        if attempt == 1:
            print(
                f"  [lessons] injecting {min(len(lessons), lessons_max):,} chars of locked-tool lessons"
            )

    # RAG retrieval — top-K semantic matches from corpus wisdom DB (8956 chunks).
    rag = rag_retrieve_for_task(instance_id, top_k=5, max_chars=rag_max)
    rag_block = ""
    if rag:
        rag_block = f"""

Additional context from Determinex corpus (semantic retrieval):
<rag_context>
{rag}
</rag_context>
"""
        if attempt == 1:
            print(f"  [rag] retrieved {len(rag):,} chars of relevant chunks")

    error_block = ""
    if prior_error:
        # Build a "diff + patch" feedback block: show the model its OWN prior code so it
        # can incrementally fix instead of rewriting from scratch (which causes regression).
        prior_src_block = ""
        if prior_compile_sh or prior_files:
            best_msg = f"BEST score so far: {best_eval_score}/100. " if best_eval_score >= 0 else ""
            prior_src_parts = [
                f"\n\nYour PREVIOUS attempt's submission is below. {best_msg}"
                "DIFF + PATCH this code — fix only the failing tests. "
                "DO NOT rewrite from scratch (that causes regression).\n"
            ]
            if prior_compile_sh:
                prior_src_parts.append(
                    f"<prior_compile_sh>\n{prior_compile_sh[:1500]}\n</prior_compile_sh>\n"
                )
            for fname, content in (prior_files or {}).items():
                # Cap each file at 25KB — shellharden Python impl is ~600 lines (~20KB)
                prior_src_parts.append(
                    f'<prior_file name="{fname}">\n{content[:25000]}\n</prior_file>\n'
                )
            prior_src_block = "".join(prior_src_parts)

        error_block = f"""
Previous attempt {attempt - 1} FAILED. Read the full failure analysis below:
<compile_error>
{prior_error[:8000]}
</compile_error>
Fix ONLY the failing tests above. DO NOT remove or modify code that makes other tests pass.
{prior_src_block}"""

    # On RETRY attempts, error_block goes FIRST so the rich failure-feedback isn't
    # truncated when the prompt approaches the model's context limit. Spec/playbook
    # also shrink on retry (see sizing above). On attempt 1 there's no feedback so
    # corpus injection comes first naturally.
    if attempt == 1 or not error_block.strip():
        user_msg = f"""Reimplement this program from scratch. Match its exact CLI behavior.

Task metadata:
{task_yaml}

Observed behavior (README + binary probes):
{observations}
{playbook_block}{rag_block}{lessons_block}{spec_block}{error_block}"""
    else:
        user_msg = f"""PATCH your best submission to fix the failing tests. DO NOT rewrite from scratch — \
the best submission is shown in the error block below; make SURGICAL targeted changes only.

Task metadata:
{task_yaml}

Observed behavior (README + binary probes):
{observations}
{error_block}
{playbook_block}{rag_block}{lessons_block}{spec_block}"""
    # Detect if the spec mandates Python (contains our Python-only sentinel).
    # When true, lock the format section to Python-only so DeepSeek can't pick Rust.
    _spec_full = load_behavioral_spec(instance_id)
    _python_only = "OUTPUT PYTHON CODE ONLY" in _spec_full

    # Append the format/template section after either branch above.
    if _python_only:
        # Spec mandates Python — show ONLY the Python template, never Rust/Go/C.
        user_msg += """

⚠️⚠️⚠️ LANGUAGE LOCKED: PYTHON ONLY ⚠️⚠️⚠️
The behavioral spec requires Python. compile.sh = `cp main.py executable`.
DO NOT write Rust, Go, C, or any other language. OUTPUT main.py ONLY.

Output format:

<compile_sh>
#!/bin/bash
set -e
cp main.py executable
chmod +x executable
</compile_sh>
<source_files>
<file name="main.py">
[your complete Python implementation starting with #!/usr/bin/env python3]
</file>
</source_files>

Rules:
- compile.sh MUST be exactly: cp main.py executable && chmod +x executable
- main.py MUST start with: #!/usr/bin/env python3
- For complex tools: split into multiple <file> blocks (lexer.py, parser.py, etc.).
  main.py imports the others; compile.sh cp's only main.py to executable.
- TREAT THE BEHAVIORAL SPEC AS AUTHORITATIVE. Bench tests are byte-exact.
- Match flag names, output format, and exit codes EXACTLY.
- Handle stdin/stdout correctly.
- No placeholders, no TODOs, no `pass` stubs.
"""
    else:
        user_msg += """

═══════════════════════════════════════════════════════════════════════════════
PICK ONE LANGUAGE. Use the matching compile.sh + file pattern EXACTLY.
DO NOT MIX PATTERNS ACROSS LANGUAGES.
═══════════════════════════════════════════════════════════════════════════════

▼ Python (interpreted — copy source to executable, never compile it):
  compile_sh:
    #!/bin/bash
    set -e
    cp main.py executable
    chmod +x executable
  files: main.py with `#!/usr/bin/env python3` as line 1.

▼ Rust (compiled — rustc generates the binary; do NOT cp):
  compile_sh:
    #!/bin/bash
    set -e
    rustc -O main.rs -o executable
  files: main.rs (NO shebang, real Rust source with `fn main() {}`).
  WRONG: `cp main.rs executable && rustc -O executable` (this corrupts the source).

▼ Go (compiled — go build generates the binary):
  compile_sh:
    #!/bin/bash
    set -e
    go mod init prog 2>/dev/null || true
    go build -o executable .
  files: main.go with `package main` and `func main() {}`.

▼ C (compiled — gcc generates the binary):
  compile_sh:
    #!/bin/bash
    set -e
    gcc -O2 -o executable main.c
  files: main.c (or *.c — adjust gcc args).

▼ C++ (compiled — g++ generates the binary):
  compile_sh:
    #!/bin/bash
    set -e
    g++ -O2 -std=c++17 -o executable main.cpp
  files: main.cpp.

═══════════════════════════════════════════════════════════════════════════════

Respond with EXACTLY this format (no other text outside the tags). Pick the
language above whose template matches your implementation:

<compile_sh>
#!/bin/bash
set -e
[ONE of the compile.sh bodies above — real shell commands, not comments]
</compile_sh>
<source_files>
<file name="[main.py | main.rs | main.go | main.c | main.cpp]">
[REPLACE this entire block with your real source code. For Python start with
`#!/usr/bin/env python3`. For Rust use `fn main() {}`. For Go use `package main`
+ `func main() {}`. For C/C++ use `int main()`. Do NOT leave this placeholder.]
</file>
</source_files>

Rules:
- compile.sh MUST produce ./executable in CWD. NEVER comments-only compile.sh.
- For complex tools: split Python into multiple <file> blocks (lexer.py, parser.py,
  evaluator.py). main.py imports the others; cp only main.py to executable.
- If a behavioral spec is provided above: TREAT IT AS AUTHORITATIVE. Bench tests are
  byte-exact against golden files. Output formatting, error format, exit codes are
  non-negotiable.
- Match flag names, output format, and exit codes EXACTLY.
- Handle stdin/stdout correctly. If the tool reads from a file arg OR stdin, handle both.
- No placeholders, no TODOs, no `pass` stubs.
"""

    if backend == "anthropic":
        guard = _get_budget(run_name)
        tokens_in_est = _estimate_tokens(SYSTEM_PROMPT) + _estimate_tokens(user_msg)
        tokens_out_est = MAX_OUTPUT_TOKENS
        ok, why, est = guard.allow_estimated(instance_id, MODEL, tokens_in_est, tokens_out_est)
        purpose = _budget_purpose(instance_id, attempt, backend)
        if not ok:
            guard.ledger(
                instance_id=instance_id,
                attempt=attempt,
                model=MODEL,
                purpose=purpose,
                tokens_in_est=tokens_in_est,
                tokens_out_est=tokens_out_est,
                allowed=False,
                reason=why,
            )
            print(f"  [budget] BLOCKED Claude call: {why} (est=${est:.4f})")
            raise BudgetExceeded(why)
        guard.ledger(
            instance_id=instance_id,
            attempt=attempt,
            model=MODEL,
            purpose=purpose,
            tokens_in_est=tokens_in_est,
            tokens_out_est=tokens_out_est,
            allowed=True,
            reason=f"pre-call estimate ${est:.4f}",
        )
        print(
            f"  [budget] Claude preflight: est=${est:.4f} "
            f"total=${guard.state.spend_usd:.4f}/${guard.state.max_usd}"
        )
        import anthropic

        client = anthropic.Anthropic(
            api_key=os.environ.get("ANTHROPIC_API_KEY")
            or os.environ.get("DETERMINEX_ANTHROPIC_KEY")
        )
        print(f"  Calling Claude (attempt {attempt}/{MAX_RETRIES})...")
        # Streaming required for max_tokens > ~10min generation budget (SDK hard guard).
        with client.messages.stream(
            model=MODEL,
            max_tokens=MAX_OUTPUT_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        ) as stream:
            chunks: list[str] = []
            for chunk in stream.text_stream:
                chunks.append(chunk)
            text = "".join(chunks)
        tokens_out_est_actual = _estimate_tokens(text)
        cost = guard.charge(MODEL, tokens_in_est, tokens_out_est_actual, instance_id)
        guard.ledger(
            instance_id=instance_id,
            attempt=attempt,
            model=MODEL,
            purpose=purpose,
            tokens_in_est=tokens_in_est,
            tokens_out_est=tokens_out_est,
            tokens_in=tokens_in_est,
            tokens_out=tokens_out_est_actual,
            cost_usd=cost,
            allowed=True,
            reason="charged after streamed response using char/4 token estimate",
            outcome={"response_chars": len(text)},
        )
        print(
            f"  [budget] Claude call charged: in~={tokens_in_est} out~={tokens_out_est_actual} "
            f"cost=${cost:.4f} total=${guard.state.spend_usd:.4f}/${guard.state.max_usd}"
        )
    elif backend == "local":
        eff_model = model_tag or LOCAL_MODEL
        print(f"  Calling local Ollama ({eff_model}, attempt {attempt}/{MAX_RETRIES})...")
        text = _generate_via_local_ollama(SYSTEM_PROMPT, user_msg, model_tag=eff_model)
    elif backend == "deepseek":
        # If cloak ON, obfuscate identifiers in <compile_error> blocks before sending.
        outbound_msg = user_msg
        obf_map: dict[str, str] = {}
        if _CLOAK_ON:
            outbound_msg, obf_map = _cloak_obfuscate(user_msg)
        # Budget gate: refuse if this specific call would blow the cap.
        guard = _get_budget(run_name)
        ds_model = os.environ.get("DETERMINEX_DEEPSEEK_MODEL", "deepseek-chat")
        tokens_in_est = _estimate_tokens(SYSTEM_PROMPT) + _estimate_tokens(outbound_msg)
        tokens_out_est = int(os.environ.get("DETERMINEX_DEEPSEEK_MAX_TOKENS", "32000"))
        ok, why, est = guard.allow_estimated(instance_id, ds_model, tokens_in_est, tokens_out_est)
        purpose = _budget_purpose(instance_id, attempt, backend)
        if not ok:
            guard.ledger(
                instance_id=instance_id,
                attempt=attempt,
                model=ds_model,
                purpose=purpose,
                tokens_in_est=tokens_in_est,
                tokens_out_est=tokens_out_est,
                allowed=False,
                reason=why,
            )
            print(f"  [budget] BLOCKED DeepSeek call: {why} (est=${est:.4f})")
            raise BudgetExceeded(why)
        guard.ledger(
            instance_id=instance_id,
            attempt=attempt,
            model=ds_model,
            purpose=purpose,
            tokens_in_est=tokens_in_est,
            tokens_out_est=tokens_out_est,
            allowed=True,
            reason=f"pre-call estimate ${est:.4f}",
        )

        print(
            f"  Calling DeepSeek V4 (attempt {attempt}/{MAX_RETRIES}){' [CLOAKED]' if _CLOAK_ON else ''}..."
        )
        _t0 = time.time()
        text, _in_tok, _out_tok = _generate_via_deepseek(SYSTEM_PROMPT, outbound_msg)
        _latency = time.time() - _t0

        # Charge budget + report running spend (model name from env so reasoner is priced correctly).
        cost = guard.charge(ds_model, _in_tok, _out_tok, instance_id)
        guard.ledger(
            instance_id=instance_id,
            attempt=attempt,
            model=ds_model,
            purpose=purpose,
            tokens_in_est=tokens_in_est,
            tokens_out_est=tokens_out_est,
            tokens_in=_in_tok,
            tokens_out=_out_tok,
            cost_usd=cost,
            allowed=True,
            reason="charged after API usage report",
            outcome={"latency_s": round(_latency, 2), "response_chars": len(text or "")},
        )
        print(
            f"  [budget] DeepSeek call: in={_in_tok} out={_out_tok} cost=${cost:.4f}  total=${guard.state.spend_usd:.4f}/${guard.state.max_usd}"
        )

        # Audit log every cloud call (whether cloaked or not).
        if _AUDIT_ON:
            try:
                _cloak_audit_call(
                    run_name=run_name or "unspecified",
                    instance_id=instance_id,
                    attempt=attempt,
                    model="deepseek-chat",
                    req_text=outbound_msg,
                    resp_text=text or "",
                    latency_s=_latency,
                    obfuscated=_CLOAK_ON,
                    obfuscation_map=obf_map,
                )
            except Exception as _e:
                print(f"  [cloak_audit] WARNING: failed to log: {_e}")
    else:
        raise RuntimeError(f"unknown backend: {backend}")

    compile_sh_parsed, files_parsed = parse_response(text)
    if compile_sh_parsed and not files_parsed:
        import re as _re

        print(f"  [DEBUG] No files parsed. Response len={len(text)}")
        # Try the exact regex and show what happens
        pat = r'<file\s+name=["\']?([^"\'>\s]+)["\']?>(.*?)</file>'
        matches = list(_re.finditer(pat, text, _re.DOTALL))
        print(f"  [DEBUG] regex matches: {len(matches)}")
        # Show all <file occurrences with 120 chars
        for i, m in enumerate(_re.finditer(r"<file", text)):
            snippet = text[m.start() : m.start() + 120]
            print(f"  [DEBUG] <file at {m.start()}: {repr(snippet)}")
        # Show last 200 chars (closing tags)
        print(f"  [DEBUG] Response tail: {repr(text[-300:])}")
    # Return (parsed compile_sh, parsed files, full user_msg, full response) so the
    # solve loop can write WAL records with the complete prompt/response context.
    return compile_sh_parsed, files_parsed, user_msg, text


# ---------------------------------------------------------------------------
# Compilation + packaging
# ---------------------------------------------------------------------------


def compile_in_container(
    instance_id: str, compile_sh: str, files: dict[str, str]
) -> tuple[bool, str]:
    """Write files to a temp dir, volume-mount into container, run compile.sh in one shot."""
    img = image_name(instance_id)

    # Use a persistent path on T: so Docker Desktop can mount it (must be under a shared drive)
    staging_root = Path("T:/determinex-programbench/_compile_staging")
    staging_root.mkdir(parents=True, exist_ok=True)

    import uuid

    staging = staging_root / str(uuid.uuid4())
    staging.mkdir()
    try:
        (staging / "compile.sh").write_text(
            compile_sh.replace("\r\n", "\n"), newline="\n", encoding="utf-8"
        )
        for fname, content in files.items():
            fpath = staging / fname
            fpath.parent.mkdir(parents=True, exist_ok=True)
            fpath.write_text(content.replace("\r\n", "\n"), newline="\n", encoding="utf-8")

        # Convert Windows path to Docker-compatible path
        # T:/foo → /t/foo  (Docker Desktop mounts drives under /letter)
        staging_str = str(staging).replace("\\", "/")
        # T:/determinex-programbench/... → //t/determinex-programbench/...
        if staging_str[1] == ":":
            docker_path = "/" + staging_str[0].lower() + staging_str[2:]
        else:
            docker_path = staging_str

        script = (
            "cp -r /mnt/src/. /workspace/ && "
            "cd /workspace && "
            "rm -f ./executable && "
            "chmod +x compile.sh && "
            "./compile.sh && "
            "ls -la ./executable"
        )

        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "-v",
                f"{docker_path}:/mnt/src:ro",
                img,
                "bash",
                "-c",
                script,
            ],
            capture_output=True,
            timeout=300,
        )
        stdout = result.stdout.decode("utf-8", errors="replace")
        stderr = result.stderr.decode("utf-8", errors="replace")
        success = result.returncode == 0 and "executable" in stdout
        return success, (stdout + stderr).strip()
    except subprocess.TimeoutExpired:
        return False, "compile.sh timed out after 300s"
    finally:
        import shutil

        shutil.rmtree(staging, ignore_errors=True)


def package_submission(
    instance_id: str, compile_sh: str, files: dict[str, str], run_dir: Path
) -> Path:
    """Package as submission.tar.gz in the run directory."""
    task_dir = run_dir / instance_id
    task_dir.mkdir(parents=True, exist_ok=True)

    # Write files to a staging area for inspection
    staging = task_dir / "source"
    staging.mkdir(exist_ok=True)
    (staging / "compile.sh").write_text(
        compile_sh.replace("\r\n", "\n"), newline="\n", encoding="utf-8"
    )
    for fname, content in files.items():
        fpath = staging / fname
        fpath.parent.mkdir(parents=True, exist_ok=True)
        fpath.write_text(content.replace("\r\n", "\n"), newline="\n", encoding="utf-8")

    # Create submission.tar.gz
    sub_path = task_dir / "submission.tar.gz"
    with tarfile.open(sub_path, "w:gz") as tar:
        tar.add(staging / "compile.sh", arcname="compile.sh")
        for fname in files:
            src = staging / fname
            if src.exists():
                tar.add(src, arcname=fname)

    print(f"  Packaged: {sub_path}")
    return sub_path


# ---------------------------------------------------------------------------
# Main solve loop
# ---------------------------------------------------------------------------


def solve_task(instance_id: str, run_dir: Path, run_name: str = "") -> bool:
    print(f"\n{'=' * 60}")
    print(f"Task: {instance_id}")
    print(f"{'=' * 60}")

    metrics = TaskMetrics(instance_id=instance_id, t_start=time.time())

    # Pull image (force fresh if env says so, otherwise only if missing)
    force_pull = os.environ.get("DETERMINEX_PB_FORCE_PULL", "").lower() in ("1", "true", "yes")
    images = subprocess.run(
        ["docker", "images", "-q", image_name(instance_id)], capture_output=True, text=True
    ).stdout.strip()
    if not images or force_pull:
        if force_pull and images:
            print(f"  DETERMINEX_PB_FORCE_PULL=1 → re-pulling {image_name(instance_id)}")
        if not pull_image(instance_id):
            return False

    # Probe binary
    print("  Probing binary...")
    observations = probe_binary(instance_id)
    print(f"  Observations: {len(observations)} chars")

    # Check for blob data (actual pytest suite) — preferred over generated probes
    branches = get_test_branches(instance_id)
    has_blobs = len(branches) > 0
    metrics.t_probe_gen_end = time.time()
    if has_blobs:
        print(f"  Using actual pytest suite ({len(branches)} test branches) — ground truth mode")
    else:
        print("  No blob data — will use differential probe vs reference binary")

    prior_error = ""
    compile_sh: str = ""
    files: dict[str, str] = {}
    for attempt in range(1, MAX_RETRIES + 1):
        am = AttemptMetrics(attempt=attempt, t_claude_start=time.time())

        # Escalation: pick the right tier for this attempt based on history.
        if ESCALATE:
            tier_idx = pick_tier(instance_id, metrics.attempts, escalate=True)
            backend, model_tag, tier_label = ESCALATION_LADDER[tier_idx]
            am.model_used = tier_label
            print(
                f"  Attempt {attempt}: tier={tier_label} (backend={backend}, model={model_tag or 'cloud'})"
            )
        else:
            backend = MODEL_BACKEND
            model_tag = LOCAL_MODEL if MODEL_BACKEND == "local" else None
            am.model_used = backend if backend != "local" else (LOCAL_MODEL or "local")

        try:
            # Inject prior source ONLY when we have a real best (a compile-clean,
            # eval-scored submission). Otherwise model would diff broken code.
            inject_prior = metrics.best_compile_sh and metrics.final_eval_score > 0
            compile_sh, files, _wal_user_msg, _wal_response = generate_code(
                instance_id,
                observations,
                prior_error,
                attempt,
                backend=backend,
                model_tag=model_tag,
                run_name=run_name,
                prior_compile_sh=metrics.best_compile_sh if inject_prior else "",
                prior_files=metrics.best_files if inject_prior else None,
                best_eval_score=metrics.final_eval_score if inject_prior else -1,
            )
            am.wal_user_msg = _wal_user_msg
            am.wal_response = _wal_response
        except BudgetExceeded as e:
            # Budget cap reached — no point in retrying remaining attempts.
            # Give up immediately; saves ~3 wasted retry cycles per capped task.
            print(f"  Attempt {attempt}: BUDGET CAP — giving up early ({e})")
            am.syntax_blocked = True
            am.t_claude_end = time.time()
            metrics.attempts.append(am)
            _write_wal_for_attempt(run_name, instance_id, am, locals().get("ev"))
            break
        except Exception as e:
            # Backend hard failure (Ollama down, API key invalid, etc).
            # Mark this attempt failed but keep iterating — don't crash the whole run.
            print(f"  Attempt {attempt}: BACKEND ERROR ({type(e).__name__}): {str(e)[:200]}")
            prior_error = f"Backend ({backend}) call failed with {type(e).__name__}: {str(e)[:300]}. Retrying."
            am.syntax_blocked = True  # Reuse this flag — won't count as compile attempt
            am.t_claude_end = time.time()
            metrics.attempts.append(am)
            _write_wal_for_attempt(run_name, instance_id, am, locals().get("ev"))
            time.sleep(5)
            continue
        am.t_claude_end = time.time()

        if not compile_sh:
            print(f"  Attempt {attempt}: failed to parse response (no compile_sh)")
            prior_error = "Claude's response did not contain a valid <compile_sh> block. Please follow the exact format."
            am.syntax_blocked = True
            metrics.attempts.append(am)
            _write_wal_for_attempt(run_name, instance_id, am, locals().get("ev"))
            continue

        print(
            f"  Attempt {attempt}: compile_sh={len(compile_sh)}b, files={list(files.keys())} | Claude: {am.t_claude:.0f}s"
        )

        # --- Sidecar step 0: template-leak detector (free, instant) ---
        # Catch the model verbatim-copying our prompt placeholders before wasting compile.
        leaks: list[str] = []
        cs_low = compile_sh.lower()
        bad_in_compile = [
            "# install deps if needed",
            "# build / prepare the executable",
            "# build/prepare the executable",
            "# must produce ./executable when done",
            "[replace ",
        ]
        for marker in bad_in_compile:
            if marker in cs_low:
                leaks.append(f"compile.sh contains unmodified template placeholder: '{marker}'")
        bad_in_files = [
            "[replace this entire block",
            "# complete source code",
            "# additional module (use multiple files",
            "# your full implementation here",
            "# ... your code here ...",
            "# todo:",
        ]
        for fname, content in (files or {}).items():
            cl = content.lower()
            for marker in bad_in_files:
                if marker in cl:
                    leaks.append(f"{fname} contains unmodified template placeholder: '{marker}'")
            # Also catch effectively-empty bodies (just shebang or just one comment)
            real_lines = [
                ln for ln in content.splitlines() if ln.strip() and not ln.strip().startswith("#")
            ]
            if len(real_lines) < 3:
                leaks.append(f"{fname} has fewer than 3 lines of real code — looks empty/stub")
        if leaks:
            msg = (
                "TEMPLATE LEAK — you copied placeholder text verbatim instead of writing real code:\n  - "
                + "\n  - ".join(leaks[:5])
            )
            print(f"  Attempt {attempt}: TEMPLATE LEAK:\n  - " + "\n  - ".join(leaks[:5]))
            prior_error = (
                msg
                + "\n\nReplace ALL placeholder/template text with a complete working implementation. The compile.sh must contain real shell commands; the source files must contain real source code."
            )
            am.syntax_blocked = True
            am.t_compile_end = time.time()
            metrics.attempts.append(am)
            _write_wal_for_attempt(run_name, instance_id, am, locals().get("ev"))
            continue

        # --- Sidecar step 1: provenance check (fire-and-forget, never blocks) ---
        _run_provenance_check(instance_id, attempt, compile_sh, files)

        # --- Sidecar step 2: local syntax check (free, instant) ---
        syntax_ok, syntax_err = local_syntax_check(compile_sh, files)
        if not syntax_ok:
            print(f"  Attempt {attempt}: LOCAL SYNTAX FAIL:\n{syntax_err[:300]}")
            prior_error = f"Syntax error caught before compilation:\n{syntax_err}"
            am.syntax_blocked = True
            am.t_compile_end = time.time()
            metrics.attempts.append(am)
            _write_wal_for_attempt(run_name, instance_id, am, locals().get("ev"))
            continue

        success, compile_output = compile_in_container(instance_id, compile_sh, files)
        am.t_compile_end = time.time()
        am.compile_ok = success

        if not success:
            print(f"  Attempt {attempt}: COMPILE FAILED ({am.t_compile:.0f}s)")

            # Print bottom of error to console so we can see the actual fatal error
            console_err = compile_output[-500:] if len(compile_output) > 500 else compile_output
            print(f"  Error (last 500 chars):\n{console_err}")

            # Keep the BOTTOM 4000 characters of the compiler output, since Rust outputs warnings
            # first and the fatal error at the very end.
            safe_output = compile_output[-4000:] if len(compile_output) > 4000 else compile_output
            prior_error = safe_output

            same_error_count = 0
            for prev in metrics.attempts:
                if not prev.compile_ok and not prev.syntax_blocked:
                    same_error_count += 1
            if same_error_count >= 2:
                # 3+ compile fails in a row — likely the model is stuck on the same approach
                lang_hint = ""
                if "main.go" in (files or {}):
                    lang_hint = (
                        "\n\nGO STUCK-LOOP HINT: Did you forget `go mod init prog 2>/dev/null || true` "
                        "in compile.sh before `go build`? That's the #1 Go failure cause. "
                        "Also: `os.Stdin.ReadBytes` does NOT exist — use `io.ReadAll(os.Stdin)`."
                    )
                elif "main.rs" in (files or {}):
                    lang_hint = (
                        "\n\nRUST STUCK-LOOP HINT: For single-file Rust, use `rustc -O main.rs -o executable`. "
                        "Do NOT use external crates without a Cargo.toml. Use only std::*. "
                        "Stdin: `use std::io::Read; let mut s = String::new(); io::stdin().read_to_string(&mut s)?;`"
                    )
                elif "main.go" not in (files or {}) and any(
                    f.endswith(".go") for f in (files or {})
                ):
                    lang_hint = "\n\nGO HINT: file should be named main.go, with `package main` declaration."
                prior_error = (
                    f"REPEAT COMPILE FAILURE (attempt {attempt}, this error class has now failed {same_error_count + 1} times). "
                    f"The same approach is not working. CHANGE STRATEGY this attempt — do NOT just tweak the prior code. "
                    f"Re-read your compile.sh AND source from scratch.{lang_hint}\n\nLatest compile error:\n{safe_output}"
                )
            metrics.attempts.append(am)
            _write_wal_for_attempt(run_name, instance_id, am, locals().get("ev"))
            time.sleep(1)
            continue

        # Compile succeeded — run the actual pytest suite (or fallback diff probe)
        print(f"  Attempt {attempt}: COMPILE OK ({am.t_compile:.0f}s) — running tests...")

        if has_blobs:
            failures, probe_raw, passed, total = run_pytest_probe(
                instance_id, compile_sh, files, timeout=1800
            )
            if probe_raw == "NO_BLOBS":
                # Blob cache disappeared mid-run — treat as unrecoverable for this attempt
                am.t_probe_end = time.time()
                am.probe_pass = 0
                am.probe_total = 0
                print(f"  Attempt {attempt}: PROBE NO_BLOBS (cache miss)")
                prior_error = "Probe blob cache unavailable — check HF snapshot dir."
                metrics.attempts.append(am)
                _write_wal_for_attempt(run_name, instance_id, am, locals().get("ev"))
                time.sleep(1)
                continue
            elif probe_raw.startswith("COMPILE_FAILED"):
                # compile.sh failed inside the probe container
                am.t_probe_end = time.time()
                am.probe_pass = 0
                am.probe_total = 0
                compile_err = probe_raw[len("COMPILE_FAILED\n") :]
                print(f"  Attempt {attempt}: PROBE COMPILE FAILED")
                prior_error = compile_err
                am.compile_ok = False
                metrics.attempts.append(am)
                _write_wal_for_attempt(run_name, instance_id, am, locals().get("ev"))
                time.sleep(1)
                continue
            elif probe_raw.startswith("PROBE_TIMEOUT_OR_CRASH") or probe_raw == "probe timed out":
                am.t_probe_end = time.time()
                am.probe_pass = 0
                am.probe_total = 0
                print(f"  Attempt {attempt}: PROBE TIMED OUT/CRASHED")
                prior_error = "Test runner timed out or crashed. Consider a faster implementation."
                metrics.attempts.append(am)
                _write_wal_for_attempt(run_name, instance_id, am, locals().get("ev"))
                time.sleep(1)
                continue
        else:
            # Fallback: differential probe vs reference binary
            failures, probe_raw = run_differential(instance_id, compile_sh, files, [])
            passed = 0 - len(failures)
            total = 0

        am.t_probe_end = time.time()
        am.probe_pass = passed
        am.probe_total = total

        pct = f"{am.probe_pct:.0f}%" if total > 0 else "N/A"
        print(
            f"  Attempt {attempt}: internal probe {pct} ({passed}/{total}) | probe: {am.t_probe:.0f}s"
        )

        # Fast pre-filter: if the internal pytest probe found real failures
        # (only meaningful when has_blobs=True), don't pay the cost of the
        # full official eval — feed those failures back immediately.
        if has_blobs and failures and total > 0:
            f0 = failures[0]
            if "test" in f0:
                print(f"  Internal first failure: {f0['test']}")
                print(f"    {f0['message'][:120]}")
            else:
                print(f"  Internal first failure: {f0.get('cmd', '')[:80]}")
            diagnosis = observer_diagnose(instance_id, failures, observations)
            am.observer_diagnosis = diagnosis[:200] if diagnosis else ""
            prior_error = diagnosis + format_failure_report(failures)
            metrics.attempts.append(am)
            _write_wal_for_attempt(run_name, instance_id, am, locals().get("ev"))
            time.sleep(1)
            continue

        # Compile passed + internal probe is clean (or unavailable).
        # Package the submission so the official harness can evaluate it.
        # NOTE: only overwrite the on-disk submission if this attempt beats prior best.
        prior_best = metrics.final_eval_score
        print(f"  Attempt {attempt}: packaging candidate submission for official eval...")
        package_submission(instance_id, compile_sh, files, run_dir)
        metrics.shipped = True

        # Run the OFFICIAL `programbench eval` — the only judge of true scores.
        eval_t0 = time.time()
        ev = _pb_run_eval(instance_id, run_dir)
        eval_dt = time.time() - eval_t0
        am.eval_score = ev.score
        am.eval_passed = ev.passed
        am.eval_total = ev.total
        am.eval_cached = ev.cached
        am.eval_error = ev.error[:300]

        cache_tag = " [cached]" if ev.cached else ""
        if ev.error:
            print(f"  Attempt {attempt}: official eval ERROR ({eval_dt:.0f}s): {ev.error[:200]}")
        else:
            print(
                f"  Attempt {attempt}: official eval = {ev.score}/100  "
                f"({ev.passed}/{ev.total} tests, {eval_dt:.0f}s){cache_tag}  best-so-far={max(prior_best, ev.score)}/100"
            )

        # BEST-tracking: only treat this as the canonical submission if it beats prior best.
        if ev.score > prior_best:
            metrics.final_eval_score = ev.score
            metrics.best_attempt = attempt
            metrics.best_compile_sh = compile_sh
            metrics.best_files = dict(files or {})
            metrics.best_not_run = ev.not_run
            # Snapshot per-test and feedback from BEST submission — used to anchor retry
            # prompts after regressions so the model sees what the BEST code fails, not
            # what the regressed code fails (which is a meaningless baseline to diff from).
            metrics.best_per_test = dict(ev.per_test)
            metrics.best_eval_feedback = ev.feedback_block()
            # Submission tarball already written by package_submission above; it IS the new best.
        elif ev.score < prior_best and prior_best >= 0 and metrics.best_compile_sh:
            # This attempt regressed. Restore the BEST submission to disk so we ship the best one.
            print(
                f"  Attempt {attempt}: REGRESSION ({ev.score} < best {prior_best}) — restoring best submission to disk"
            )
            package_submission(instance_id, metrics.best_compile_sh, metrics.best_files, run_dir)
            # Reset last_per_test to best's baseline so the NEXT retry's diff is vs the BEST
            # (not vs this broken regression).  Without this, next attempt sees "YOU BROKE 517
            # TESTS" comparing against the regression, even though the model is patching best.
            metrics.last_per_test = dict(metrics.best_per_test)

        if ev.is_lock:
            print(f"  Attempt {attempt}: VERIFIED LOCK — official eval = 100/100, submitting")
            metrics.verified_locked = True
            metrics.solved = True  # back-compat
            metrics.t_end = time.time()
            metrics.attempts.append(am)
            _write_wal_for_attempt(run_name, instance_id, am, locals().get("ev"))
            metrics.save(run_dir)
            metrics.print_summary()
            return True

        # REGRESSION DETECTOR: if 2 consecutive attempts scored below prior best, stop.
        # The model is oscillating around a local maximum and more attempts won't help.
        eval_history = [a.eval_score for a in metrics.attempts if a.eval_score >= 0]
        eval_history.append(ev.score)
        if len(eval_history) >= 3 and prior_best >= 0:
            # Last two attempts both regressed below the best
            recent = eval_history[-2:]
            if all(s < prior_best for s in recent) and prior_best >= 30:
                print(
                    f"  Attempt {attempt}: REGRESSION-STOP — 2 attempts in a row scored below best ({prior_best}). "
                    f"Local max reached. Shipping best submission."
                )
                metrics.attempts.append(am)
                _write_wal_for_attempt(run_name, instance_id, am, locals().get("ev"))
                metrics.t_end = time.time()
                metrics.save(run_dir)
                metrics.print_summary()
                return False

        # Eval ran but didn't lock. Use its failure list as next-attempt feedback.
        if ev.error:
            err_low = ev.error.lower()
            if "copy_executable_failed" in err_low or "no such file" in err_low:
                # Most common failure: compile.sh ran but never produced ./executable
                lang_hint = ""
                if any(f.endswith(".py") for f in (files or {})):
                    src = next((f for f in files if f.endswith(".py")), "main.py")
                    lang_hint = (
                        f"Your compile.sh ran cleanly but did NOT create ./executable.\n"
                        f"You must add real commands. Example for Python:\n\n"
                        f"  #!/bin/bash\n"
                        f"  set -e\n"
                        f"  pip install --quiet --no-cache-dir <any deps>  # only if needed\n"
                        f"  cp {src} executable\n"
                        f"  chmod +x executable\n\n"
                        f"Comments alone (`# build the executable`) are NOT commands.\n"
                        f"The harness runs `./executable` directly — must exist in CWD after compile.sh."
                    )
                elif any(f.endswith(".go") for f in (files or {})):
                    lang_hint = (
                        "Your compile.sh did NOT produce ./executable. Use:\n"
                        "  go build -o executable ."
                    )
                elif any(f.endswith(".rs") for f in (files or {})):
                    lang_hint = (
                        "Your compile.sh did NOT produce ./executable. Use:\n"
                        "  rustc main.rs -o executable\n"
                        "or, if cargo project: `cargo build --release && cp target/release/<name> executable`"
                    )
                elif any(
                    f.endswith(".c") or f.endswith(".cc") or f.endswith(".cpp")
                    for f in (files or {})
                ):
                    lang_hint = (
                        "Your compile.sh did NOT produce ./executable. Use:\n"
                        "  gcc -O2 -o executable *.c\n"
                        "or for C++: `g++ -O2 -std=c++17 -o executable *.cpp`"
                    )
                else:
                    lang_hint = (
                        "Your compile.sh ran cleanly but did NOT create ./executable.\n"
                        "Add real build commands — comments are not commands."
                    )
                prior_error = (
                    f"OFFICIAL EVAL FAILED: missing ./executable.\n\n{lang_hint}\n\n"
                    f"Raw error: {ev.error}"
                )
            elif "compile_sh_failed" in err_low or "compile.sh" in err_low and "exit" in err_low:
                prior_error = (
                    f"OFFICIAL EVAL FAILED: compile.sh exited non-zero.\n"
                    f"Check for missing pip packages, wrong syntax in shell, or apt-get failures.\n\n"
                    f"Raw error: {ev.error}"
                )
            else:
                prior_error = (
                    f"OFFICIAL EVAL FAILED: {ev.error}\n\n"
                    "Common fixes:\n"
                    "  - Ensure ./executable exists after compile.sh runs\n"
                    "  - chmod +x executable\n"
                    "  - Use #!/usr/bin/env python3 (or similar) shebang at top of source\n"
                    "  - compile.sh starts with `#!/bin/bash` and `set -e`"
                )
        else:
            # Diff per-test status vs prior attempt → wins/regressions/persistent.
            progress_block = ""
            if ev.per_test and metrics.last_per_test:
                wins, regressions = [], []
                for name, status in ev.per_test.items():
                    prev = metrics.last_per_test.get(name)
                    if status == "passed" and prev == "failure":
                        wins.append(name)
                    elif status == "failure" and prev == "passed":
                        regressions.append(name)
                if regressions:
                    # REGRESSIONS go FIRST — model must undo before fixing forward.
                    progress_block = (
                        f"🚨 CRITICAL — YOU BROKE {len(regressions)} TESTS IN YOUR LAST ATTEMPT.\n"
                        f"   Before doing ANYTHING else: UNDO the change(s) that caused these regressions.\n"
                        f"   Tests that were passing before and now fail: "
                        + ", ".join(regressions[:12])
                        + (f", ... +{len(regressions) - 12} more" if len(regressions) > 12 else "")
                        + "\n\n"
                    )
                elif wins:
                    progress_block = (
                        f"✓ Good progress — you FIXED {len(wins)} tests last attempt: "
                        + ", ".join(wins[:8])
                        + (f", ... +{len(wins) - 8} more" if len(wins) > 8 else "")
                        + "\n  Keep going — now fix the remaining failures below.\n\n"
                    )

            # not_run regression check — packaging broke more branches than last attempt.
            # This is separate from behavioral regressions: the binary is running but silently
            # failing to emit JUnit XML for some branches. Must be flagged explicitly.
            not_run_delta = ev.not_run - metrics.last_not_run if metrics.last_not_run > 0 else 0
            if not_run_delta > 0:
                progress_block = (
                    f"🔇 PACKAGING REGRESSION: {not_run_delta} MORE tests went not_run (missing from JUnit XML) vs last attempt.\n"
                    f"   Total not_run: {ev.not_run}. Your last change broke JUnit output for additional branches.\n"
                    f"   UNDO the packaging change that caused this — do NOT proceed until not_run stops increasing.\n"
                    f"   Check compile.sh: exec wrapper, binary placement, argv[0], stdout/stderr routing.\n\n"
                ) + progress_block
            metrics.last_not_run = ev.not_run

            # If this attempt regressed below the best, anchor next retry to the BEST
            # submission's failures instead of this regression's failures.  The model is
            # about to patch the BEST code — it needs to know what THAT code fails, not
            # what this broken attempt fails (two completely different failure sets).
            if ev.score < prior_best and prior_best >= 0 and metrics.best_eval_feedback:
                # last_per_test was already reset to best's baseline above (in the regression
                # branch of BEST-tracking), so the wins/regressions block above is already
                # correct.  Just replace the feedback body with best's target failures.
                regressed_by = prior_best - ev.score
                prior_error = (
                    f"⚠ REGRESSION: This attempt scored {ev.score}/100, down from best "
                    f"{prior_best}/100 ({regressed_by} pts lost). Best submission RESTORED.\n"
                    f"Your task: fix the {prior_best}/100 submission's REMAINING failures below.\n"
                    f"Do NOT touch anything that was passing in the {prior_best}/100 run.\n\n"
                    + metrics.best_eval_feedback
                )
            else:
                # Normal progress: save current per_test and use current feedback.
                metrics.last_per_test = dict(ev.per_test)
                # Regressions lead — model MUST see them before any new failure detail.
                prior_error = progress_block + ev.feedback_block()

        metrics.attempts.append(am)
        _write_wal_for_attempt(run_name, instance_id, am, locals().get("ev"))
        time.sleep(1)

    print(f"  GAVE UP after {MAX_RETRIES} attempts.")
    metrics.t_end = time.time()
    metrics.save(run_dir)
    metrics.print_summary()

    # Last attempt's submission is already on disk if any compiled.
    return False


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Determinex ProgramBench Agent")
    parser.add_argument("--task", help="Full instance ID (e.g. sclevine__yj.8016400)")
    parser.add_argument(
        "--tasks", nargs="+", help="Short task names (yj, htmlq, ...) or 'all_easy'"
    )
    parser.add_argument(
        "--run-name", default=f"determinex_{int(time.time())}", help="Run directory name"
    )
    parser.add_argument("--workers", type=int, default=1, help="Parallel workers (future)")
    parser.add_argument(
        "--model",
        choices=("anthropic", "local", "deepseek"),
        default="anthropic",
        help="Builder backend: anthropic (Sonnet 4.6), local (Ollama Qwen2.5-Coder), deepseek (DeepSeek V4). Default: anthropic.",
    )
    parser.add_argument(
        "--local-model",
        default=None,
        help="Override Ollama model tag (default: qwen2.5-coder:14b-instruct-q4_K_M, env: DETERMINEX_LOCAL_BUILDER_MODEL)",
    )
    parser.add_argument(
        "--escalate",
        action="store_true",
        help="Auto-escalate builder when stuck: 7b → 14b → DeepSeek. Anchors start at DeepSeek.",
    )
    parser.add_argument(
        "--no-escalate",
        dest="escalate",
        action="store_false",
        help="Disable escalation (use --model + --local-model only).",
    )
    parser.set_defaults(escalate=False)
    args = parser.parse_args()

    # Apply backend selection globally
    global MODEL_BACKEND, LOCAL_MODEL, ESCALATE
    MODEL_BACKEND = args.model
    if args.local_model:
        LOCAL_MODEL = args.local_model
    ESCALATE = bool(args.escalate)
    if ESCALATE:
        ladder = " → ".join(label for _b, _m, label in ESCALATION_LADDER)
        print(f"[builder] ESCALATION ON  ladder: {ladder}  anchors→T3 from attempt 1")
    else:
        print(
            f"[builder] backend={MODEL_BACKEND}"
            + (f" model={LOCAL_MODEL}" if MODEL_BACKEND == "local" else f" model={MODEL}")
        )

    run_dir = OUTPUT_BASE / args.run_name
    run_dir.mkdir(parents=True, exist_ok=True)
    print(f"Run directory: {run_dir}")

    # Resolve task list
    instance_ids: list[str] = []
    if args.task:
        instance_ids.append(args.task)
    if args.tasks:
        for t in args.tasks:
            if t == "all_easy":
                instance_ids.extend(EASY_TARGETS.values())
            elif t in EASY_TARGETS:
                instance_ids.append(EASY_TARGETS[t])
            else:
                # Maybe it's a full instance_id
                instance_ids.append(t)

    if not instance_ids:
        parser.print_help()
        print("\nAvailable short names:", list(EASY_TARGETS.keys()))
        sys.exit(1)

    run_start = time.time()
    results: dict[str, bool] = {}
    for iid in instance_ids:
        results[iid] = solve_task(iid, run_dir, run_name=args.run_name)
    run_elapsed = time.time() - run_start

    print(f"\n{'=' * 60}")
    print("RESULTS")
    print(f"{'=' * 60}")
    passed = sum(results.values())
    for iid, ok in results.items():
        # Load saved metrics for per-task summary
        mfile = run_dir / iid / "metrics.json"
        elapsed_str = ""
        final_pct_str = ""
        attempts_str = ""
        if mfile.exists():
            try:
                m = json.loads(mfile.read_text(encoding="utf-8"))
                elapsed_s = (m.get("t_end") or 0) - m.get("t_start", 0)
                elapsed_str = f"{elapsed_s:.0f}s"
                attempts = m.get("attempts", [])
                attempts_str = f"{len(attempts)} attempts"
                last = next((a for a in reversed(attempts) if a.get("compile_ok")), None)
                if last:
                    pct = 100.0 * last["probe_pass"] / max(last["probe_total"], 1)
                    final_pct_str = f"{pct:.0f}%"
            except Exception:
                pass
        print(
            f"  {'PASS' if ok else 'FAIL'}  {iid}  {final_pct_str:>5}  {attempts_str}  {elapsed_str}"
        )

    print(
        f"\n{passed}/{len(results)} solved  |  total wall time: {run_elapsed:.0f}s ({run_elapsed / 60:.1f}m)"
    )
    print(f"Run dir: {run_dir}")
    print("\nTo evaluate:")
    print(f"  cd T:/Dev/ProgramBench && uv run programbench eval {run_dir}")


if __name__ == "__main__":
    main()
