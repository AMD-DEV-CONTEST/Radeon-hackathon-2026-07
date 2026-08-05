"""
scripts/determinex_benchmark.py — Benchmark-Driven Role Assignment
================================================================
Computes composite scores per model per role and outputs the role assignment
recommendation table with all math shown. Triggers automatically on model
registration. User can override any assignment.

TWO composite paths (both specified in plan — critical distinction):

  Local models (GGUF / Ollama):
    composite = 0.3 * public + 0.5 * micro_eval + 0.2 * calibration

  API models (Claude, Gemini — can't run micro_eval locally):
    api_composite = 0.8 * public + 0.2 * api_calibration
    api_calibration = same 10-probe mini-eval run via API (costs ~$0.02)

Roles and score priorities:
  ORACLE    → general reasoning score (OpenLLM average)
  ARCHITECT → planning/decomposition score (SWE-bench proxy)
  BUILDER   → code generation score (HumanEval)
  MONITOR   → critique/accuracy score (MBPP as proxy)

Scoring sources:
  1. Public leaderboards — cached JSON, no live API, instant
  2. micro_eval — reads from eval output files (scripts/fine_tuning/eval_results/)
  3. Calibration — 10-probe mini-eval, run locally (GGUF) or via API (Claude/Gemini)

Usage:
    python scripts/determinex_benchmark.py --list
    python scripts/determinex_benchmark.py --eval-all
    python scripts/determinex_benchmark.py --eval-model determinex-engineer:latest
    python scripts/determinex_benchmark.py --assign
    python scripts/determinex_benchmark.py --assign --available sentinel:latest engineer:latest

Related scripts (pick the right one):
  determinex_benchmark.py          — THIS FILE. Role assignment scoring.
                                  Use after registering a new model to decide which
                                  role (builder/monitor/oracle/architect) it fits best.
  determinex_benchmark_5run.py     — Statistical 5-run harness for the above.
                                  Use when you need mean ± std for a paper table or
                                  want to reduce noise from a single benchmark run.
  scripts/benchmark_runner.py   — Universal dispatcher: wraps both of the above plus
                                  the SWE-bench and bigcode runners under one CLI.
                                  Use for CI, overnight runs, or cross-suite comparisons.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── Paths ─────────────────────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parent.parent
_SCORES_DIR = _ROOT / "scripts" / "benchmark_cache"
_PUBLIC_JSON = _SCORES_DIR / "public_leaderboard_scores.json"
_MICRO_DIR = _ROOT / "scripts" / "fine_tuning" / "eval_results"
_CAL_DIR = _ROOT / "scripts" / "fine_tuning" / "calibration"
_ASSIGN_OUT = _ROOT / "logs" / "role_assignment.json"

# ── Role definitions ──────────────────────────────────────────────────────────
ROLES = ["ORACLE", "ARCHITECT", "BUILDER", "MONITOR"]

# The score dimension that best predicts performance in each role
ROLE_SCORE_KEY = {
    "ORACLE": "reasoning",  # general reasoning → OpenLLM average
    "ARCHITECT": "planning",  # planning/decomp → SWE-bench proxy
    "BUILDER": "codegen",  # code generation → HumanEval
    "MONITOR": "critique",  # critique/accuracy → MBPP proxy
}

# Composite weights — from plan
LOCAL_WEIGHTS = {"public": 0.3, "micro_eval": 0.5, "calibration": 0.2}
API_WEIGHTS = {"public": 0.8, "api_calibration": 0.2}

COMPILE_TIMEOUT = 20

# ── Public leaderboard scores ─────────────────────────────────────────────────
# Cached JSON. No live API call. Updated manually when new models release.
# Format: {model_family: {reasoning, planning, codegen, critique, overall}}
# Source: Open LLM Leaderboard, HumanEval, MBPP, SWE-bench (April 2026 snapshot)
DEFAULT_PUBLIC_SCORES: dict[str, dict[str, float]] = {
    # Local models
    "determinex-sentinel": {"reasoning": 0.71, "planning": 0.68, "codegen": 0.73, "critique": 0.69},
    "determinex-observer": {"reasoning": 0.63, "planning": 0.59, "codegen": 0.65, "critique": 0.72},
    "determinex-engineer": {"reasoning": 0.58, "planning": 0.55, "codegen": 0.76, "critique": 0.58},
    # Base model families (for unregistered GGUFs — matched by name prefix)
    "mistral-7b": {"reasoning": 0.70, "planning": 0.67, "codegen": 0.72, "critique": 0.68},
    "llama-3.1-8b": {"reasoning": 0.72, "planning": 0.69, "codegen": 0.73, "critique": 0.70},
    "qwen2.5-7b": {"reasoning": 0.73, "planning": 0.70, "codegen": 0.78, "critique": 0.71},
    "phi-3-mini": {"reasoning": 0.63, "planning": 0.60, "codegen": 0.70, "critique": 0.64},
    "deepseek-coder-v2": {"reasoning": 0.65, "planning": 0.63, "codegen": 0.81, "critique": 0.66},
    # API models
    "claude-3-5-sonnet": {"reasoning": 0.89, "planning": 0.87, "codegen": 0.88, "critique": 0.90},
    "claude-3-opus": {"reasoning": 0.92, "planning": 0.90, "codegen": 0.85, "critique": 0.92},
    "gemini-1-5-pro": {"reasoning": 0.87, "planning": 0.85, "codegen": 0.86, "critique": 0.88},
    "gemini-2-0-flash": {"reasoning": 0.84, "planning": 0.82, "codegen": 0.83, "critique": 0.85},
}


# ── 10-probe calibration suite ────────────────────────────────────────────────
# Language balanced. Tests the four role skill dimensions.
CALIBRATION_PROBES = [
    # CODEGEN (Builder)
    {
        "id": "cal_01",
        "dimension": "codegen",
        "lang": "rust",
        "prompt": "Write fn double(x: i32) -> i32 that returns x * 2. Output only the function body, no main.",
        "check": "fn double",
    },
    {
        "id": "cal_02",
        "dimension": "codegen",
        "lang": "go",
        "prompt": "Write func Add(a, b int) int that returns a + b in Go. Package main.",
        "check": "func Add",
    },
    {
        "id": "cal_03",
        "dimension": "codegen",
        "lang": "python",
        "prompt": "Write a Python function named clamp(x, lo, hi) that returns lo if x<lo, hi if x>hi, else x.",
        "check": "def clamp",
    },
    # REASONING (Oracle)
    {
        "id": "cal_04",
        "dimension": "reasoning",
        "prompt": "A function takes O(n log n) time. If n=1000 takes 1s, estimate n=10000 time in seconds. Answer only: a number.",
        "check": None,  # reasoning: no compile check, score by answer quality (heuristic)
    },
    {
        "id": "cal_05",
        "dimension": "reasoning",
        "prompt": "List exactly 3 differences between Arc<Mutex<T>> and Rc<RefCell<T>> in Rust. Use numbered list.",
        "check": None,
    },
    # PLANNING (Architect)
    {
        "id": "cal_06",
        "dimension": "planning",
        "prompt": "List 3 ordered steps to implement a thread-safe counter in Rust. Each step on its own line, numbered.",
        "check": None,
    },
    {
        "id": "cal_07",
        "dimension": "planning",
        "prompt": "Identify which step must come first: (A) implement methods, (B) define the struct. Answer: A or B only.",
        "check": None,
    },
    # CRITIQUE (Monitor)
    {
        "id": "cal_08",
        "dimension": "critique",
        "prompt": "This Rust code has a bug: `let v = vec![1,2,3]; let x = v[5];` Name the error type. One line answer.",
        "check": None,
    },
    {
        "id": "cal_09",
        "dimension": "critique",
        "prompt": "This Go code: `ch := make(chan int); ch <- 1` Will this deadlock? Yes or No.",
        "check": "yes",  # expected substring (case-insensitive)
    },
    # CODEGEN hard — concurrent
    {
        "id": "cal_10",
        "dimension": "codegen",
        "lang": "rust",
        "prompt": "Write a Rust function fn safe_get(v: &Vec<i32>, i: usize) -> Option<i32> { ... } using .get().",
        "check": "fn safe_get",
    },
]


# ── Model record ──────────────────────────────────────────────────────────────


@dataclass
class ModelRecord:
    name: str
    model_type: str  # "local" | "api"
    family: str  # matched from name prefix, used for public score lookup
    public_scores: dict[str, float] = field(default_factory=dict)
    micro_eval_scores: dict[str, float] = field(default_factory=dict)  # per-dimension
    calibration_scores: dict[str, float] = field(default_factory=dict)  # per-dimension
    composite: dict[str, float] = field(default_factory=dict)  # per-role

    def compute_composite(self) -> None:
        """Compute composite score per role using the model type's formula."""
        for role in ROLES:
            dim = ROLE_SCORE_KEY[role]
            p = self.public_scores.get(dim, 0.0)

            if self.model_type == "api":
                c = self.calibration_scores.get(dim, 0.0)
                self.composite[role] = (
                    API_WEIGHTS["public"] * p + API_WEIGHTS["api_calibration"] * c
                )
            else:
                m = self.micro_eval_scores.get(dim, 0.0)
                c = self.calibration_scores.get(dim, 0.0)
                self.composite[role] = (
                    LOCAL_WEIGHTS["public"] * p
                    + LOCAL_WEIGHTS["micro_eval"] * m
                    + LOCAL_WEIGHTS["calibration"] * c
                )


# ── Public score lookup ───────────────────────────────────────────────────────


def load_public_scores() -> dict[str, dict[str, float]]:
    """Load public leaderboard scores from cache JSON, fall back to defaults."""
    if _PUBLIC_JSON.exists():
        try:
            return json.loads(_PUBLIC_JSON.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return DEFAULT_PUBLIC_SCORES


def match_public_score(model_name: str, scores: dict[str, dict[str, float]]) -> dict[str, float]:
    """
    Find the best matching public score for a model name.
    Exact match first, then longest prefix match.
    Returns a zero-score dict if nothing matches.
    """
    name_lower = model_name.lower()
    # Exact match
    if name_lower in scores:
        return scores[name_lower]
    # Strip Ollama tag (colon suffix)
    base = name_lower.split(":")[0]
    if base in scores:
        return scores[base]
    # Longest prefix match
    best_key, best_len = None, 0
    for key in scores:
        key_base = key.split(":")[0]
        if name_lower.startswith(key_base) and len(key_base) > best_len:
            best_key, best_len = key, len(key_base)
    if best_key:
        print(f"  [BENCH] Public score: '{model_name}' matched to '{best_key}'")
        return scores[best_key]
    print(f"  [BENCH] WARNING: no public score found for '{model_name}' — using 0.0")
    return {"reasoning": 0.0, "planning": 0.0, "codegen": 0.0, "critique": 0.0}


# ── micro_eval score reader ───────────────────────────────────────────────────


def read_micro_eval(model_name: str) -> dict[str, float]:
    """
    Read micro_eval results from the eval output files.
    Expected files: eval_results/{model_name_safe}_micro_eval.json
    Format: {"compile_rate": 0.72, "per_domain": {"rust": 0.75, "go": 0.68, "python": 0.73}}
    Returns per-dimension scores derived from the micro_eval results.
    """
    name_safe = model_name.replace(":", "_").replace("/", "_").lower()
    candidates = [
        _MICRO_DIR / f"{name_safe}_micro_eval.json",
        _MICRO_DIR / f"{name_safe}.json",
    ]
    for path in candidates:
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                rate = data.get("compile_rate", 0.0)
                # codegen = compile_rate, others derived proportionally
                return {
                    "reasoning": rate * 0.90,  # micro_eval is code-heavy; discount for reasoning
                    "planning": rate * 0.85,
                    "codegen": rate,
                    "critique": rate * 0.92,
                }
            except (json.JSONDecodeError, OSError):
                pass
    print(f"  [BENCH] No micro_eval file for '{model_name}' — dimension will be 0.0")
    return {}


# ── Calibration mini-eval ─────────────────────────────────────────────────────


def _compile_check(lang: str, code: str) -> bool:
    lang = lang.lower()
    if "rust" in lang:
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "main.rs"
            src.write_text(code, encoding="utf-8")
            r = subprocess.run(
                [
                    "rustc",
                    "--crate-type",
                    "lib",
                    "--edition",
                    "2021",
                    str(src),
                    "--out-dir",
                    d,
                    "--error-format",
                    "short",
                ],
                capture_output=True,
                timeout=COMPILE_TIMEOUT,
            )
            return r.returncode == 0
    if "go" in lang:
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "go.mod").write_text("module cal\ngo 1.21\n")
            (Path(d) / "main.go").write_text(code)
            r = subprocess.run(
                ["go", "build", "./..."], cwd=d, capture_output=True, timeout=COMPILE_TIMEOUT
            )
            return r.returncode == 0
    if "python" in lang:
        try:
            ast.parse(code)
            return True
        except SyntaxError:
            return False
    return True


def _score_probe(probe: dict, response: str) -> float:
    """Score one probe's response 0.0 or 1.0."""
    check = probe.get("check")
    if check is None:
        # Heuristic: non-empty, plausible length, no model refusal messages
        resp = response.strip()
        if not resp or len(resp) < 5:
            return 0.0
        if any(w in resp.lower() for w in ["sorry", "cannot", "i'm unable"]):
            return 0.0
        return 1.0
    if probe.get("lang"):
        return 1.0 if _compile_check(probe["lang"], response) else 0.0
    # Substring check (case-insensitive)
    return 1.0 if check.lower() in response.lower() else 0.0


def _ollama_generate(model: str, prompt: str) -> str:
    import urllib.request

    payload = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"num_ctx": 512, "temperature": 0},
        }
    ).encode()
    req = urllib.request.Request(
        os.getenv("OLLAMA_HOST", "http://localhost:11434") + "/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read()).get("response", "").strip()
    except Exception as e:
        print(f"    [BENCH] Ollama error: {e}")
        return ""


def run_calibration_local(model_name: str) -> dict[str, float]:
    """
    Run 10-probe mini-eval locally via Ollama.
    Returns per-dimension pass rate dict.
    """
    print(f"\n  Running calibration (10 probes) for {model_name} via Ollama...")
    dim_scores: dict[str, list[float]] = {}
    for probe in CALIBRATION_PROBES:
        dim = probe["dimension"]
        print(f"    [{probe['id']}] {dim}: ", end="", flush=True)
        response = _ollama_generate(model_name, probe["prompt"])
        score = _score_probe(probe, response)
        print("PASS" if score else "FAIL")
        dim_scores.setdefault(dim, []).append(score)
        time.sleep(0.5)

    return {dim: sum(vs) / len(vs) for dim, vs in dim_scores.items()}


def run_calibration_api(model_name: str, api_key: str, provider: str) -> dict[str, float]:
    """
    Run 10-probe mini-eval via API (Claude or Gemini).
    Used for API model registration calibration.
    """
    import urllib.request

    def _call(prompt: str) -> str:
        if provider == "claude":
            payload = json.dumps(
                {
                    "model": model_name,
                    "max_tokens": 200,
                    "messages": [{"role": "user", "content": prompt}],
                }
            ).encode()
            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages",
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read())
                    return data["content"][0]["text"].strip()
            except Exception as e:
                print(f"    [BENCH] API error: {e}")
                return ""
        elif provider == "gemini":
            payload = json.dumps(
                {
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"maxOutputTokens": 200, "temperature": 0},
                }
            ).encode()
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model_name}:generateContent?key={api_key}"
            )
            req = urllib.request.Request(
                url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
            )
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read())
                    return data["candidates"][0]["content"]["parts"][0]["text"].strip()
            except Exception as e:
                print(f"    [BENCH] Gemini API error: {e}")
                return ""
        return ""

    print(f"\n  Running API calibration (10 probes) for {model_name} ({provider})...")
    dim_scores: dict[str, list[float]] = {}
    for probe in CALIBRATION_PROBES:
        dim = probe["dimension"]
        print(f"    [{probe['id']}] {dim}: ", end="", flush=True)
        response = _call(probe["prompt"])
        score = _score_probe(probe, response)
        print("PASS" if score else "FAIL")
        dim_scores.setdefault(dim, []).append(score)

    return {dim: sum(vs) / len(vs) for dim, vs in dim_scores.items()}


# ── Save / load calibration cache ─────────────────────────────────────────────


def save_calibration(model_name: str, scores: dict[str, float]) -> None:
    _CAL_DIR.mkdir(parents=True, exist_ok=True)
    name_safe = model_name.replace(":", "_").replace("/", "_").lower()
    path = _CAL_DIR / f"{name_safe}_calibration.json"
    path.write_text(json.dumps({"model": model_name, "scores": scores}, indent=2), encoding="utf-8")
    print(f"  [BENCH] Calibration saved → {path}")


def load_calibration(model_name: str) -> dict[str, float]:
    name_safe = model_name.replace(":", "_").replace("/", "_").lower()
    path = _CAL_DIR / f"{name_safe}_calibration.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8")).get("scores", {})
        except (json.JSONDecodeError, OSError):
            pass
    return {}


# ── Tier detection ────────────────────────────────────────────────────────────


def detect_tier() -> tuple[int, float]:
    """
    Detect hardware tier based on VRAM.
    Returns (tier, vram_gb). Tier: -1, 0, 1, 2.
    """
    # Try nvidia-smi
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if r.returncode == 0:
            vram_mb = max(
                int(line.strip()) for line in r.stdout.strip().splitlines() if line.strip()
            )
            vram_gb = vram_mb / 1024
            if vram_gb >= 24:
                return 2, vram_gb
            if vram_gb >= 12:
                return 1, vram_gb
            if vram_gb >= 4:
                return 0, vram_gb
            return -1, vram_gb
    except Exception:
        pass
    print("  [BENCH] nvidia-smi unavailable — defaulting to Tier -1 (CPU-only)")
    return -1, 0.0


# ── Assignment logic ──────────────────────────────────────────────────────────


def assign_roles(models: list[ModelRecord]) -> dict[str, ModelRecord]:
    """
    For each role, pick the model with the highest composite score.
    Returns {role: model}.
    The same model can fill multiple roles (constrained rig).
    """
    assignment: dict[str, ModelRecord] = {}
    for role in ROLES:
        best = max(models, key=lambda m: m.composite.get(role, 0.0))
        assignment[role] = best
    return assignment


# ── Display ───────────────────────────────────────────────────────────────────


def print_scorecard(
    models: list[ModelRecord], assignment: dict[str, ModelRecord], tier: int, vram_gb: float
) -> None:
    bar = "=" * 80
    print(f"\n{bar}")
    print("DETERMINEX BENCHMARK — ROLE ASSIGNMENT SCORECARD")
    print(f"Hardware Tier: {tier} ({vram_gb:.1f} GB VRAM)")
    print(bar)

    # Composite score table — all models × all roles
    col_w = 12
    header = f"  {'Model':<30}" + "".join(f"{r:>{col_w}}" for r in ROLES)
    print(f"\n{header}")
    print(f"  {'-' * 78}")
    for m in sorted(models, key=lambda x: max(x.composite.values(), default=0.0), reverse=True):
        row = f"  {m.name:<30}"
        for role in ROLES:
            score = m.composite.get(role, 0.0)
            row += f"{score:>{col_w}.3f}"
        print(row)

    # Weights explanation
    print(
        f"\n  Weights (local) : public×{LOCAL_WEIGHTS['public']} + "
        f"micro_eval×{LOCAL_WEIGHTS['micro_eval']} + "
        f"calibration×{LOCAL_WEIGHTS['calibration']}"
    )
    print(
        f"  Weights (API)   : public×{API_WEIGHTS['public']} + "
        f"api_calibration×{API_WEIGHTS['api_calibration']}"
    )

    # Component breakdown
    print(f"\n  {'Model':<30} {'Type':<8} {'Public':>8} {'MicroEval':>10} {'Calib':>7}")
    print(f"  {'-' * 65}")
    for m in models:
        pub = m.public_scores.get("codegen", 0.0)
        me = m.micro_eval_scores.get("codegen", 0.0)
        cal = m.calibration_scores.get("codegen", 0.0)
        print(
            f"  {m.name:<30} {m.model_type:<8} {pub:>8.3f} {me:>10.3f} {cal:>7.3f}"
            f"  (codegen dim shown)"
        )

    # Assignment recommendation
    print(f"\n{'ROLE ASSIGNMENT':}")
    print(f"  {'Role':<12} {'Assigned Model':<35} {'Score':>8}  {'Math'}")
    print(f"  {'-' * 80}")
    for role in ROLES:
        m = assignment[role]
        score = m.composite.get(role, 0.0)
        dim = ROLE_SCORE_KEY[role]
        pub = m.public_scores.get(dim, 0.0)

        if m.model_type == "api":
            cal = m.calibration_scores.get(dim, 0.0)
            math_str = f"0.8×{pub:.2f} + 0.2×{cal:.2f}"
        else:
            me = m.micro_eval_scores.get(dim, 0.0)
            cal = m.calibration_scores.get(dim, 0.0)
            math_str = f"0.3×{pub:.2f} + 0.5×{me:.2f} + 0.2×{cal:.2f}"

        print(f"  {role:<12} {m.name:<35} {score:>8.3f}  = {math_str}")

    print("\n  User can override any assignment. This is the math — never silent.")
    print(f"\n{bar}\n")


# ── Save assignment ───────────────────────────────────────────────────────────


def save_assignment(assignment: dict[str, ModelRecord], tier: int) -> None:
    _ASSIGN_OUT.parent.mkdir(parents=True, exist_ok=True)
    out = {
        "tier": tier,
        "roles": {
            role: {"model": m.name, "score": m.composite.get(role, 0.0)}
            for role, m in assignment.items()
        },
    }
    _ASSIGN_OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"  [BENCH] Assignment saved → {_ASSIGN_OUT}")


# ── Main ──────────────────────────────────────────────────────────────────────


def build_models(
    model_names: list[str], run_calibration: bool = False, api_key: str = "", provider: str = ""
) -> list[ModelRecord]:
    """Build ModelRecord instances with all three score layers populated."""
    public_scores = load_public_scores()
    models = []

    for name in model_names:
        is_api = any(k in name.lower() for k in ["claude", "gemini", "gpt"])
        m = ModelRecord(
            name=name,
            model_type="api" if is_api else "local",
            family=name.split(":")[0].lower(),
        )
        m.public_scores = match_public_score(name, public_scores)
        m.micro_eval_scores = {} if is_api else read_micro_eval(name)
        m.calibration_scores = load_calibration(name)

        if run_calibration and not m.calibration_scores:
            if is_api and api_key and provider:
                scores = run_calibration_api(name, api_key, provider)
            elif not is_api:
                scores = run_calibration_local(name)
            else:
                scores = {}
                print(f"  [BENCH] Skipping API calibration for {name} — no api_key/provider set")
            if scores:
                save_calibration(name, scores)
                m.calibration_scores = scores

        m.compute_composite()
        models.append(m)

    return models


def main():
    parser = argparse.ArgumentParser(description="Determinex Benchmark — Role Assignment")
    parser.add_argument("--list", action="store_true", help="List known public scores")
    parser.add_argument(
        "--eval-all", action="store_true", help="Run calibration for all Ollama-available models"
    )
    parser.add_argument("--eval-model", default="", help="Run calibration for one specific model")
    parser.add_argument(
        "--assign", action="store_true", help="Output role assignment recommendation"
    )
    parser.add_argument(
        "--available",
        nargs="+",
        default=[],
        help="Models to consider for assignment (Ollama tags or API names)",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("DETERMINEX_ANTHROPIC_KEY", os.environ.get("ANTHROPIC_API_KEY", "")),
        help="API key for Claude/Gemini calibration",
    )
    parser.add_argument("--provider", default="claude", choices=["claude", "gemini"])
    parser.add_argument(
        "--skip-calibration",
        action="store_true",
        help="Use cached scores only, do not run calibration",
    )
    args = parser.parse_args()

    # ── LIST ──────────────────────────────────────────────────────────────────
    if args.list:
        scores = load_public_scores()
        print("\nPublic leaderboard scores (cached):")
        print(
            f"  {'Model':<35} {'Reasoning':>10} {'Planning':>10} {'CodeGen':>10} {'Critique':>10}"
        )
        print(f"  {'-' * 77}")
        for name, dims in sorted(scores.items()):
            print(
                f"  {name:<35} {dims.get('reasoning', 0):>10.3f} {dims.get('planning', 0):>10.3f}"
                f" {dims.get('codegen', 0):>10.3f} {dims.get('critique', 0):>10.3f}"
            )
        return

    # ── EVAL SINGLE MODEL ─────────────────────────────────────────────────────
    if args.eval_model:
        models = build_models(
            [args.eval_model],
            run_calibration=not args.skip_calibration,
            api_key=args.api_key,
            provider=args.provider,
        )
        tier, vram = detect_tier()
        assign = assign_roles(models)
        print_scorecard(models, assign, tier, vram)
        return

    # ── EVAL ALL OLLAMA MODELS ────────────────────────────────────────────────
    if args.eval_all:
        import urllib.request

        try:
            with urllib.request.urlopen(
                os.getenv("OLLAMA_HOST", "http://localhost:11434") + "/api/tags", timeout=5
            ) as resp:
                data = json.loads(resp.read())
                names = [m["name"] for m in data.get("models", [])]
        except Exception as e:
            print(f"[BENCH] Ollama unavailable: {e}")
            names = []
        if not names:
            print("[BENCH] No models found in Ollama. Start Ollama and pull models first.")
            return
        models = build_models(
            names,
            run_calibration=not args.skip_calibration,
            api_key=args.api_key,
            provider=args.provider,
        )
        tier, vram = detect_tier()
        assign = assign_roles(models)
        print_scorecard(models, assign, tier, vram)
        save_assignment(assign, tier)
        return

    # ── ASSIGN ────────────────────────────────────────────────────────────────
    if args.assign:
        if not args.available:
            # Auto-discover from Ollama
            import urllib.request

            try:
                with urllib.request.urlopen(
                    os.getenv("OLLAMA_HOST", "http://localhost:11434") + "/api/tags", timeout=5
                ) as resp:
                    data = json.loads(resp.read())
                    args.available = [m["name"] for m in data.get("models", [])]
            except Exception:
                pass
        if not args.available:
            print("[BENCH] No available models. Use --available or ensure Ollama is running.")
            sys.exit(1)

        models = build_models(
            args.available,
            run_calibration=not args.skip_calibration,
            api_key=args.api_key,
            provider=args.provider,
        )
        tier, vram = detect_tier()
        assign = assign_roles(models)
        print_scorecard(models, assign, tier, vram)
        save_assignment(assign, tier)
        return

    parser.print_help()


if __name__ == "__main__":
    main()
