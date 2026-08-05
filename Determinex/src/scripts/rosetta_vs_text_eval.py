"""
scripts/rosetta_vs_text_eval.py — Rosetta vs Text A/B Evaluation Framework
===========================================================================
Required Phase 1 deliverable. Without a controlled comparison, the core claim
("Rosetta reduces compiler fail/retry cycles") is unfalsifiable.

Runs every build task through two parallel pipelines:
  - Rosetta-mediated:  DSL + soft prefix injection (mocked at Phase 1 — no llama-cpp yet)
  - Text-only:         prose messages between models via Ollama

Measures per pipeline:
  - Compile success rate
  - Semantic similarity to MD spec (via nomic-embed-text / cosine)
  - Wall-clock time per step
  - Number of Builder retries per step

Critical metrics tracked:
  1. Rosetta advantage vs real context length → detects K=1 prefix dilution
  2. nomic-embed-text cosine separation on intentionally different approaches
     → detects adjudication ceiling. Threshold: 0.15 minimum

Runtime shadow evaluator:
  - First 5 steps of any NEW task type run both pipelines in parallel
  - If Rosetta compile rate < text compile rate over those 5 steps:
      → auto-fallback to text for this task type
      → log to retraining queue
      → re-enable after 20 more completions; re-measure

Usage:
    python scripts/rosetta_vs_text_eval.py --mode offline
    python scripts/rosetta_vs_text_eval.py --mode shadow --task-type rust_mutex
    python scripts/rosetta_vs_text_eval.py --mode ceiling-check
    python scripts/rosetta_vs_text_eval.py --report results/eval_latest.json
"""

from __future__ import annotations

import argparse
import ast
import concurrent.futures
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="[EVAL] %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("eval")

# ── Paths ─────────────────────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parent.parent
_RESULTS = _ROOT / "logs" / "ab_eval"
_SHADOW_DB = _ROOT / "logs" / "shadow_eval_state.json"
_RETRAIN_Q = _ROOT / "logs" / "retrain_queue.jsonl"

COMPILE_TIMEOUT = 30

# ── #38 CPU-pinned RNG — reproducibility across eval runs ─────────────────────
# Fixed seed ensures that task ordering, tie-breaking, and any stochastic
# decisions are identical across repeated runs on the same hardware.
# CPU-pinned: torch CUDA seed is set separately if GPU is available.
import random as _rng_mod

_EVAL_RNG_SEED = 0xC17ADE1  # "Determinex" — memorable, non-zero
_rng_mod.seed(_EVAL_RNG_SEED)
try:
    import numpy as _np_rng

    _np_rng.random.seed(_EVAL_RNG_SEED & 0x7FFFFFFF)  # numpy requires uint32
except ImportError:
    pass
try:
    import torch as _torch_rng

    _torch_rng.manual_seed(_EVAL_RNG_SEED)
    if _torch_rng.cuda.is_available():
        _torch_rng.cuda.manual_seed_all(_EVAL_RNG_SEED)
except ImportError:
    pass

# ── Phase 3 dependency check ──────────────────────────────────────────────────
# Phase 3 (real embedding injection) requires llama-cpp-python, torch, and the
# determinex_inference / determinex_rosetta modules. Phase 1 (DSL text prepend) runs
# without any of these.
try:
    import sys as _sys_phase3

    _sys_phase3.path.insert(0, str(Path(__file__).resolve().parent))
    from determinex_inference import DeterminexInference as _DeterminexInference
    from determinex_rosetta import RosettaStone as _RosettaStone

    _PHASE3_AVAILABLE = True
except Exception as _p3_err:
    _PHASE3_AVAILABLE = False
    _DeterminexInference = None  # type: ignore
    _RosettaStone = None  # type: ignore
    log.debug("Phase 3 not available (%s) — eval runs Phase 1 DSL text mode", _p3_err)


# ── #5 VRAM-aware parallelism ─────────────────────────────────────────────────
def _available_vram_gb() -> float:
    """Free GPU VRAM in GB, or 0.0 if no GPU / torch not installed."""
    try:
        import torch

        if torch.cuda.is_available():
            free, _total = torch.cuda.mem_get_info()
            return free / 1e9
    except Exception:
        pass
    return 0.0


_VRAM_GB = _available_vram_gb()
# Both Rosetta and text pipelines load a model each. Running them in parallel
# on <8GB free VRAM causes OOM on Tier 0 rigs. Sequential is the safe default.
_PARALLEL_OK = _VRAM_GB >= 8.0
log.info(
    "VRAM available: %.1f GB  → parallel eval: %s",
    _VRAM_GB,
    "YES" if _PARALLEL_OK else "NO (sequential)",
)


# ── #12 Hardware-calibrated ceiling threshold ─────────────────────────────────
def _calibrated_ceiling_threshold() -> float:
    """
    #12: Scale nomic cosine separation threshold to hardware tier and adjust for float drift.
    Tier 0 (<8GB free): base threshold 0.10.
    Tier 1+ (>=8GB free): base threshold 0.15.
    Additionally, if a float drift measurement is provided via the DETERMINEX_FLOAT_DRIFT
    environment variable (max absolute difference between CUDA and Metal outputs),
    the threshold is reduced proportionally (up to 0.05 reduction) to avoid false
    failures on hardware with higher numeric variance.
    """
    base = 0.10 if _VRAM_GB < 8.0 else 0.15
    drift_env = os.getenv("DETERMINEX_FLOAT_DRIFT")
    try:
        drift = float(drift_env) if drift_env is not None else 0.0
    except ValueError:
        drift = 0.0
    # Cap drift impact to 0.05 so threshold never goes below 0.05.
    adjusted = max(0.05, base - min(drift, 0.05))
    return adjusted


# ── Thresholds ─────────────────────────────────────────────────────────────────
CEILING_CHECK_MIN_SEPARATION = _calibrated_ceiling_threshold()
DILUTION_CONTEXT_BREAKPOINT = (
    512  # tokens — if Rosetta advantage vanishes above this, prefix is diluted
)
SHADOW_STEPS_PER_TYPE = 5  # run both pipelines for first N steps of new task type
SHADOW_REENABLE_THRESHOLD = 20  # task completions before re-enabling a fallen-back type
log.info("Ceiling threshold (hardware-calibrated): %.2f", CEILING_CHECK_MIN_SEPARATION)


# ── Result data structures ─────────────────────────────────────────────────────


@dataclass
class StepResult:
    step_id: int
    pipeline: str  # "rosetta" | "text"
    task_type: str
    lang: str
    context_tokens: int  # real token count in Builder's context (not counting prefix)
    compiled: bool
    retries: int
    wall_clock_secs: float
    semantic_sim: float  # cosine(nomic(output), nomic(md_spec))
    compiler_output: str
    builder_output: str
    bridge_status: str = "text_fallback"


@dataclass
class TaskResult:
    task_id: str
    task_type: str
    lang: str
    md_spec: str
    rosetta_steps: list[StepResult] = field(default_factory=list)
    text_steps: list[StepResult] = field(default_factory=list)

    # Aggregates (computed after all steps)
    rosetta_compile_rate: float = 0.0
    text_compile_rate: float = 0.0
    rosetta_avg_retries: float = 0.0
    text_avg_retries: float = 0.0
    rosetta_avg_wall_secs: float = 0.0
    text_avg_wall_secs: float = 0.0
    rosetta_avg_sem_sim: float = 0.0
    text_avg_sem_sim: float = 0.0

    def compute_aggregates(self) -> None:
        for attr, steps in [("rosetta", self.rosetta_steps), ("text", self.text_steps)]:
            if not steps:
                continue
            setattr(self, f"{attr}_compile_rate", sum(s.compiled for s in steps) / len(steps))
            setattr(self, f"{attr}_avg_retries", sum(s.retries for s in steps) / len(steps))
            setattr(
                self, f"{attr}_avg_wall_secs", sum(s.wall_clock_secs for s in steps) / len(steps)
            )
            setattr(self, f"{attr}_avg_sem_sim", sum(s.semantic_sim for s in steps) / len(steps))


@dataclass
class EvalReport:
    timestamp: str
    mode: str
    tasks_evaluated: int
    bridge: str = "none"
    initial_bridge_status: str = "text_fallback"
    overall_rosetta_compile_rate: float = 0.0
    overall_text_compile_rate: float = 0.0
    dilution_detected: bool = False
    dilution_breakpoint_tokens: int | None = None
    ceiling_check_passed: bool = True  # Can nomic separate intentionally different approaches?
    ceiling_separation: float | None = None
    task_results: list[dict] = field(default_factory=list)
    shadow_fallbacks: list[str] = field(default_factory=list)


# ── Compiler validators ───────────────────────────────────────────────────────


def compile_rust(code: str) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "main.rs"
        src.write_text(code, encoding="utf-8")
        try:
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
                text=True,
                timeout=COMPILE_TIMEOUT,
            )
            return (r.returncode == 0), (r.stderr or r.stdout)[:500]
        except Exception as e:
            return False, str(e)


def compile_go(code: str) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory() as d:
        Path(d, "go.mod").write_text("module eval_check\ngo 1.21\n", encoding="utf-8")
        Path(d, "main.go").write_text(code, encoding="utf-8")
        try:
            r = subprocess.run(
                ["go", "build", "./..."],
                capture_output=True,
                text=True,
                timeout=COMPILE_TIMEOUT,
                cwd=d,
            )
            return (r.returncode == 0), (r.stderr or r.stdout)[:500]
        except Exception as e:
            return False, str(e)


def compile_python(code: str) -> tuple[bool, str]:
    try:
        ast.parse(code)
        return True, ""
    except SyntaxError as e:
        return False, str(e)


def validate(lang: str, code: str) -> tuple[bool, str]:
    lang = lang.lower()
    if "rust" in lang:
        return compile_rust(code)
    if "go" in lang:
        return compile_go(code)
    if "python" in lang:
        return compile_python(code)
    return True, "(lenient — unsupported language)"


# ── Embedding / semantic similarity ──────────────────────────────────────────


def _cosine(a: list[float], b: list[float]) -> float:
    import math

    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def embed_nomic(text: str) -> list[float]:
    """
    Embed via nomic-embed-text through Ollama.
    Falls back to a zero vector on failure so eval continues without crashing.
    """
    try:
        import urllib.request

        payload = json.dumps({"model": "nomic-embed-text", "input": text}).encode()
        req = urllib.request.Request(
            "http://localhost:11434/api/embed",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            # Ollama /api/embed returns {"embeddings": [[...]]}
            return data["embeddings"][0]
    except Exception as e:
        log.warning("nomic-embed-text unavailable (%s) — semantic_sim will be 0.0", e)
        return []


def semantic_similarity(output: str, md_spec: str) -> float:
    v_out = embed_nomic(output)
    v_spec = embed_nomic(md_spec)
    if not v_out or not v_spec:
        return 0.0
    return _cosine(v_out, v_spec)


# ── Ollama text pipeline ──────────────────────────────────────────────────────

_arch_cache: dict[str, str] = {}


def _get_arch(model: str) -> str:
    if model in _arch_cache:
        return _arch_cache[model]
    try:
        import urllib.request

        req = urllib.request.Request(
            "http://localhost:11434/api/show",
            data=json.dumps({"name": model}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            arch = data.get("model_info", {}).get("general.architecture", "qwen2").lower()
    except Exception:
        arch = "qwen2"
    _arch_cache[model] = arch
    return arch


def _build_prompt(arch: str, system: str, user: str) -> str:
    if arch in ("qwen2", "qwen3", "mistral", "gemma", "phi3"):
        return (
            f"<|im_start|>system\n{system}<|im_end|>\n"
            f"<|im_start|>user\n{user}<|im_end|>\n"
            f"<|im_start|>assistant\n"
        )
    return (
        f"<|begin_of_text|>"
        f"<|start_header_id|>system<|end_header_id|>\n\n{system}<|eot_id|>"
        f"<|start_header_id|>user<|end_header_id|>\n\n{user}<|eot_id|>"
        f"<|start_header_id|>assistant<|end_header_id|>\n\n"
    )


def _strip_fences(text: str) -> str:
    """Remove markdown code fences that models sometimes emit despite instructions."""
    text = re.sub(r"^```[a-zA-Z]*\n?", "", text.strip())
    text = re.sub(r"\n?```$", "", text)
    return text.strip()


def ollama_generate(model: str, prompt: str, system: str = "") -> str:
    """Call Ollama generate with correct ChatML template for the model architecture."""
    import urllib.request

    arch = _get_arch(model)
    full_prompt = _build_prompt(arch, system or "You are an expert programmer.", prompt)
    payload = {
        "model": model,
        "prompt": full_prompt,
        "stream": False,
        "options": {"num_ctx": 2048, "temperature": 0, "num_predict": 512},
    }
    try:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            "http://localhost:11434/api/generate",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read())
            return _strip_fences(result.get("response", "").strip())
    except Exception as e:
        log.error("Ollama call failed: %s", e)
        return ""


def count_tokens_approx(text: str) -> int:
    """
    #14 Tokenizer parity: estimate token count in a way that's consistent
    across both pipelines on the same hardware.

    Priority order:
    1. tiktoken cl100k_base — close to Llama/Mistral BPE, fast, no model load
    2. Whitespace-split with subword inflation factor — better than char/4 for code
       (code tokens are longer than prose; char/4 overcounts by ~40% for code)

    Both pipelines call this function identically, so counts are comparable even
    if the estimate isn't exact. What matters is consistency, not precision.
    """
    try:
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        return max(1, len(enc.encode(text)))
    except (ImportError, Exception):
        pass
    # Whitespace word count * 1.3 subword factor — more accurate than char/4 for code
    words = text.split()
    return max(1, int(len(words) * 1.3))


# ── Pipelines ─────────────────────────────────────────────────────────────────


def run_text_pipeline_step(
    task: dict, step: dict, builder_model: str, md_spec: str, max_retries: int = 3
) -> StepResult:
    """
    Text-only pipeline: plain English prose between roles via Ollama.
    Builder receives the step instruction as a text prompt, generates code,
    Compiler Oracle validates, retry on failure.
    """
    lang = task["lang"]
    system = (
        f"You are an expert {lang} programmer. "
        "Output ONLY correct compilable code, no explanations, no markdown fences."
    )
    instruction = step["instruction"]
    context_prompt = f"Task: {instruction}\n\nGenerate the {lang} code for this step only."
    context_tokens = count_tokens_approx(context_prompt)

    retries = 0
    last_error = ""
    start = time.perf_counter()

    for attempt in range(max_retries):
        prompt = context_prompt
        if last_error:
            prompt += f"\n\nPrevious attempt failed with:\n{last_error}\nFix the error."

        code = ollama_generate(builder_model, prompt, system)
        compiled, err = validate(lang, code)
        if compiled:
            break
        last_error = err[:300]
        retries += 1

    wall = time.perf_counter() - start
    sim = semantic_similarity(code, md_spec)

    return StepResult(
        step_id=step["id"],
        pipeline="text",
        task_type=task.get("task_type", "unknown"),
        lang=lang,
        context_tokens=context_tokens,
        compiled=compiled,
        retries=retries,
        wall_clock_secs=wall,
        semantic_sim=sim,
        compiler_output=last_error,
        builder_output=code,
        bridge_status="text_fallback",
    )


def run_rosetta_pipeline_step(
    task: dict,
    step: dict,
    builder_model: str,
    md_spec: str,
    max_retries: int = 3,
    phase3: dict | None = None,
    bridge_mode: str = "none",
) -> StepResult:
    """
    Phase 1 (default, phase3=None): DSL context prepended to text prompt via Ollama.
      Tests communication overhead — compact DSL vs prose, same model, same tokenizer.

    Phase 3 (phase3 dict provided): real embedding injection via DeterminexInference +
      RosettaStone. Bypasses tokenizer entirely for the semantic prefix.
      phase3 dict keys: "inference" (DeterminexInference), "stone" (RosettaStone), "arch" (str).
    """
    if bridge_mode == "none":
        result = run_text_pipeline_step(task, step, builder_model, md_spec, max_retries)
        result.pipeline = "text_baseline"
        result.bridge_status = "text_fallback"
        return result

    if phase3 is not None:
        return _run_rosetta_phase3(task, step, md_spec, max_retries, phase3)

    lang = task["lang"]
    instruction = step["instruction"]
    dsl_context = step.get("dsl_context", _generate_dsl_context(step, lang))

    system = (
        f"You are an expert {lang} programmer operating in the Determinex Hive Mind.\n"
        "You receive structured DSL context from the Oracle. "
        "Output ONLY correct compilable code. No explanations. No markdown fences."
    )
    context_prompt = (
        f"DSL CONTEXT:\n{dsl_context}\n\n"
        f"STEP INSTRUCTION: {instruction}\n\n"
        f"Generate the {lang} code for this step only."
    )
    context_tokens = count_tokens_approx(context_prompt)

    retries = 0
    last_error = ""
    start = time.perf_counter()

    for attempt in range(max_retries):
        prompt = context_prompt
        if last_error:
            prompt += f"\n\nCOMPILER ERROR:\n{last_error}\nFix the error."

        code = ollama_generate(builder_model, prompt, system)
        compiled, err = validate(lang, code)
        if compiled:
            break
        last_error = err[:300]
        retries += 1

    wall = time.perf_counter() - start
    sim = semantic_similarity(code, md_spec)

    return StepResult(
        step_id=step["id"],
        pipeline="rosetta_text_space_scaffold",
        task_type=task.get("task_type", "unknown"),
        lang=lang,
        context_tokens=context_tokens,
        compiled=compiled,
        retries=retries,
        wall_clock_secs=wall,
        semantic_sim=sim,
        compiler_output=last_error,
        builder_output=code,
        bridge_status="text_fallback",
    )


def _run_rosetta_phase3(
    task: dict,
    step: dict,
    md_spec: str,
    max_retries: int,
    phase3: dict,
) -> StepResult:
    """
    Phase 3: real Rosetta embedding injection via DeterminexInference + RosettaStone.

    Source embedding strategy:
      1. Call inference.model.embed(instruction) to get the model's own semantic
         vector for the instruction text (mean-pooled over tokens).
      2. Try stone.project(source_h, arch, arch) through Rosetta.
         If dim mismatch (e.g. Qwen2-1.5B dim=1536 vs rosetta qwen2 dim=3584),
         fall back to direct self-injection (no cross-arch transfer).
      3. Inject [1, hidden_dim] soft prefix via inject_soft_prompt().
      4. The text prompt (with ChatML template) carries instruction + compiler error on retry.

    The semantic intent travels as a floating-point vector — not tokens.
    The compiler error travels as text (tokens) — tokenizer handles structured errors fine.
    """
    import numpy as np
    import torch

    inference: _DeterminexInference = phase3["inference"]
    stone: _RosettaStone = phase3["stone"]
    arch: str = phase3["arch"]
    lang: str = task["lang"]
    instruction: str = step["instruction"]

    # ── Get source embedding from instruction text ────────────────────────────
    try:
        raw_emb = inference.model.embed(instruction)
        arr = np.array(raw_emb, dtype=np.float32)
        if arr.ndim == 2:
            arr = arr.mean(axis=0)  # [n_tokens, dim] → [dim]
        source_h = torch.from_numpy(arr)  # [hidden_dim]
    except Exception as exc:
        log.warning("Phase 3 embed() failed (%s) — using zero probe vector", exc)
        source_h = torch.zeros(inference.hidden_dim, dtype=torch.float32)

    # ── Project through Rosetta (or fall back to direct injection) ────────────
    try:
        projected_h = stone.project(source_h.unsqueeze(0), arch, arch)  # [1, dim]
        mode = "rosetta"
    except (ValueError, KeyError) as exc:
        # Dim mismatch: the builder model's hidden_dim is not in rosetta_v1.pt.
        # Common case: Qwen2-1.5B (1536) vs rosetta trained on Qwen2-7B (3584).
        # Fall back: inject the model's own embedding directly — tests the injection
        # mechanism without cross-arch transfer.
        log.warning("Rosetta projection failed (%s) — using direct self-injection", exc)
        projected_h = source_h.unsqueeze(0)  # [1, hidden_dim]
        mode = "direct"

    log.info("Phase 3 step %d: mode=%s hidden_dim=%d", step["id"], mode, projected_h.shape[-1])

    # ── Retry loop: semantic prefix stays constant, text carries error feedback ──
    context_tokens = count_tokens_approx(instruction)
    retries = 0
    last_error = ""
    start = time.perf_counter()
    code = ""
    compiled = False

    for attempt in range(max_retries):
        # Build ChatML-formatted text prompt (Qwen2 template)
        prompt_text = instruction
        if last_error:
            prompt_text = f"{instruction}\n\nCOMPILER ERROR:\n{last_error}\nFix the error."

        chat_prompt = (
            f"<|im_start|>system\n"
            f"You are an expert {lang} programmer. Output ONLY correct compilable code, "
            f"no explanations, no markdown fences.<|im_end|>\n"
            f"<|im_start|>user\n{prompt_text}<|im_end|>\n"
            f"<|im_start|>assistant\n"
        )

        try:
            text_tokens = inference.model.tokenize(chat_prompt.encode("utf-8"), special=True)
            out_tokens = inference.inject_soft_prompt(text_tokens, projected_h)
            code = _strip_fences(
                inference.model.detokenize(out_tokens).decode("utf-8", errors="ignore")
            )
        except Exception as exc:
            log.warning("Phase 3 inject attempt %d failed: %s", attempt, exc)
            last_error = str(exc)[:300]
            retries += 1
            continue

        compiled, err = validate(lang, code)
        if compiled:
            break
        last_error = err[:300]
        retries += 1

    wall = time.perf_counter() - start
    sim = semantic_similarity(code, md_spec)

    return StepResult(
        step_id=step["id"],
        pipeline=f"rosetta_phase3_{mode}",
        task_type=task.get("task_type", "unknown"),
        lang=lang,
        context_tokens=context_tokens,
        compiled=compiled,
        retries=retries,
        wall_clock_secs=wall,
        semantic_sim=sim,
        compiler_output=last_error,
        builder_output=code,
        bridge_status=("rosetta_projected" if mode == "rosetta" else "direct_self_injection"),
    )


def _generate_dsl_context(step: dict, lang: str) -> str:
    """Generate a DSL context string from step metadata if not provided."""
    lang_token = lang.upper()
    intent = step.get("intent", "implement")
    pattern = step.get("pattern", "general")
    constraints = step.get("constraints", ["correct"])
    constraint_str = " ".join(f"CONSTRAINT:{c}" for c in constraints)
    return (
        f"INTENT:{intent} LANG:{lang_token} PATTERN:{pattern}\n"
        f"{constraint_str}\n"
        f"CONTEXT:step={step['id']} FOCUS:implementation scope=function\n"
        f"CONFIDENCE:0.85 ENTROPY_CAL:0.20"
    )


# ── Dilution detection ────────────────────────────────────────────────────────


def detect_dilution(task_results: list[TaskResult]) -> tuple[bool, int | None]:
    """
    Check if Rosetta advantage disappears above ~512 real context tokens.
    Groups steps by context_tokens bucket, computes Rosetta - text compile rate delta.
    Returns (dilution_detected, breakpoint_token_count).
    """
    buckets: dict[int, list[tuple[bool, bool]]] = {}  # bucket → [(rosetta_ok, text_ok)]

    for tr in task_results:
        paired: dict[int, dict[str, StepResult]] = {}
        for s in tr.rosetta_steps:
            paired.setdefault(s.step_id, {})["rosetta"] = s
        for s in tr.text_steps:
            paired.setdefault(s.step_id, {})["text"] = s

        for sid, pair in paired.items():
            if "rosetta" not in pair or "text" not in pair:
                continue
            bucket = (pair["rosetta"].context_tokens // 128) * 128  # 128-token bucket width
            buckets.setdefault(bucket, []).append((pair["rosetta"].compiled, pair["text"].compiled))

    if len(buckets) < 2:
        return False, None

    sorted_buckets = sorted(buckets.items())
    # Compute delta per bucket
    deltas = []
    for bucket, pairs in sorted_buckets:
        r_rate = sum(r for r, _ in pairs) / len(pairs)
        t_rate = sum(t for _, t in pairs) / len(pairs)
        deltas.append((bucket, r_rate - t_rate))
        log.info("  context_tokens~%d: Rosetta delta=%.2f", bucket, r_rate - t_rate)

    # Detect if delta flips negative above the breakpoint
    for bucket, delta in deltas:
        if bucket >= DILUTION_CONTEXT_BREAKPOINT and delta < 0:
            log.warning("DILUTION DETECTED at ~%d tokens (delta=%.2f)", bucket, delta)
            return True, bucket

    return False, None


# ── Adjudication ceiling check ────────────────────────────────────────────────

# Intentionally contrasting approach pairs to test nomic's discrimination
CEILING_CHECK_PAIRS = [
    {
        "name": "rust_mutex_vs_channel",
        "a": "use std::sync::{Arc, Mutex};\nfn counter() {\n    let c = Arc::new(Mutex::new(0usize));\n    let mut g = c.lock().unwrap();\n    *g += 1;\n}",
        "b": "use std::sync::mpsc;\nfn counter() {\n    let (tx, rx) = mpsc::channel::<usize>();\n    tx.send(1).unwrap();\n    let _ = rx.recv().unwrap();\n}",
    },
    {
        "name": "result_vs_panic",
        "a": "fn divide(a: f64, b: f64) -> Option<f64> {\n    if b == 0.0 { None } else { Some(a / b) }\n}",
        "b": 'fn divide(a: f64, b: f64) -> f64 {\n    if b == 0.0 { panic!("division by zero"); }\n    a / b\n}',
    },
    {
        "name": "sync_vs_async",
        "a": 'fn fetch_data() -> String {\n    std::thread::sleep(std::time::Duration::from_millis(10));\n    String::from("data")\n}',
        "b": 'async fn fetch_data() -> String {\n    tokio::time::sleep(tokio::time::Duration::from_millis(10)).await;\n    String::from("data")\n}',
    },
]


def run_ceiling_check() -> tuple[bool, float]:
    """
    Check whether nomic-embed-text can separate intentionally different code approaches
    by at least 0.15 cosine distance (plan threshold).
    Returns (passed, min_separation_seen).
    """
    log.info("=== Adjudication Ceiling Check ===")
    separations = []
    for pair in CEILING_CHECK_PAIRS:
        va = embed_nomic(pair["a"])
        vb = embed_nomic(pair["b"])
        if not va or not vb:
            log.warning("  [%s] embeddings unavailable — skipping", pair["name"])
            continue
        sim = _cosine(va, vb)
        separation = 1.0 - sim  # lower cosine = higher separation
        separations.append(separation)
        status = "OK" if separation >= CEILING_CHECK_MIN_SEPARATION else "FAIL"
        log.info("  [%s] cosine=%.3f separation=%.3f → %s", pair["name"], sim, separation, status)

    if not separations:
        return False, 0.0

    min_sep = min(separations)
    passed = min_sep >= CEILING_CHECK_MIN_SEPARATION
    if not passed:
        log.warning(
            "Ceiling check FAILED (min separation=%.3f < %.2f). "
            "Adjudication will run in COARSE MODE — compile rate is primary differentiator.",
            min_sep,
            CEILING_CHECK_MIN_SEPARATION,
        )
    else:
        log.info("Ceiling check PASSED (min separation=%.3f)", min_sep)
    return passed, min_sep


# ── Shadow evaluator / runtime state ──────────────────────────────────────────


class ShadowEvaluator:
    """
    Tracks per-task-type shadow evaluation state.
    Persisted to _SHADOW_DB (JSON) so it survives app restarts.
    """

    def __init__(self):
        self._db: dict = self._load()

    def _load(self) -> dict:
        if _SHADOW_DB.exists():
            try:
                return json.loads(_SHADOW_DB.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    def _save(self) -> None:
        _SHADOW_DB.parent.mkdir(parents=True, exist_ok=True)
        _SHADOW_DB.write_text(json.dumps(self._db, indent=2), encoding="utf-8")

    def should_run_shadow(self, task_type: str) -> bool:
        """Returns True if this task type needs shadow evaluation."""
        state = self._db.get(
            task_type, {"shadow_count": 0, "fallback": False, "completions_since_fallback": 0}
        )
        if (
            state.get("fallback")
            and state.get("completions_since_fallback", 0) < SHADOW_REENABLE_THRESHOLD
        ):
            return False  # in fallback, not yet time to re-enable
        if state.get("shadow_count", 0) < SHADOW_STEPS_PER_TYPE:
            return True  # still in shadow window
        return False

    def record_shadow_result(
        self,
        task_type: str,
        rosetta_compiled: bool,
        text_compiled: bool,
        fallback_queue: list[str],
    ) -> bool:
        """
        Record one shadow step result. Returns True if auto-fallback triggered.
        Appends to retrain queue on fallback.
        """
        state = self._db.setdefault(
            task_type,
            {
                "shadow_count": 0,
                "rosetta_pass": 0,
                "text_pass": 0,
                "fallback": False,
                "completions_since_fallback": 0,
            },
        )

        if (
            state.get("fallback")
            and state.get("completions_since_fallback", 0) >= SHADOW_REENABLE_THRESHOLD
        ):
            # Re-enable: reset shadow window
            log.info(
                "[SHADOW] Re-enabling Rosetta for task_type=%s after %d completions",
                task_type,
                SHADOW_REENABLE_THRESHOLD,
            )
            state.update(
                {
                    "shadow_count": 0,
                    "rosetta_pass": 0,
                    "text_pass": 0,
                    "fallback": False,
                    "completions_since_fallback": 0,
                }
            )

        state["shadow_count"] += 1
        if rosetta_compiled:
            state["rosetta_pass"] += 1
        if text_compiled:
            state["text_pass"] += 1

        # Check for auto-fallback after collecting SHADOW_STEPS_PER_TYPE steps
        triggered = False
        if state["shadow_count"] >= SHADOW_STEPS_PER_TYPE:
            r_rate = state["rosetta_pass"] / state["shadow_count"]
            t_rate = state["text_pass"] / state["shadow_count"]
            if r_rate < t_rate:
                log.warning(
                    "[SHADOW] AUTO-FALLBACK for task_type=%s (rosetta=%.0f%% < text=%.0f%%)",
                    task_type,
                    r_rate * 100,
                    t_rate * 100,
                )
                state["fallback"] = True
                state["completions_since_fallback"] = 0
                triggered = True
                # Write to retrain queue
                entry = {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "type": "rosetta_fallback",
                    "task_type": task_type,
                    "rosetta_compile_rate": r_rate,
                    "text_compile_rate": t_rate,
                    "shadow_steps": state["shadow_count"],
                }
                _RETRAIN_Q.parent.mkdir(parents=True, exist_ok=True)
                with _RETRAIN_Q.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(entry) + "\n")
                fallback_queue.append(task_type)

        self._save()
        return triggered

    def record_completion(self, task_type: str) -> None:
        """Called when a non-shadow task of this type completes. Ticks the re-enable counter."""
        state = self._db.get(task_type)
        if state and state.get("fallback"):
            state["completions_since_fallback"] = state.get("completions_since_fallback", 0) + 1
            self._save()

    def is_fallback(self, task_type: str) -> bool:
        state = self._db.get(task_type, {})
        return (
            bool(state.get("fallback"))
            and state.get("completions_since_fallback", 0) < SHADOW_REENABLE_THRESHOLD
        )


# ── Offline evaluation set ────────────────────────────────────────────────────

EVAL_TASKS = [
    {
        "task_id": "rust_mutex_basic",
        "task_type": "rust_mutex",
        "lang": "rust",
        "md_spec": "Implement a thread-safe counter using Arc<Mutex<usize>>. Expose increment() and get() methods.",
        "steps": [
            {
                "id": 1,
                "instruction": "define Counter struct with Arc<Mutex<usize>> field",
                "dsl_context": "INTENT:define LANG:RUST PATTERN:shared-state\nCONSTRAINT:thread-safe\nCONTEXT:step=1 FOCUS:struct-definition",
                "intent": "define",
                "pattern": "shared-state",
                "constraints": ["thread-safe"],
            },
            {
                "id": 2,
                "instruction": "implement increment() and get() methods on Counter",
                "dsl_context": "INTENT:implement LANG:RUST PATTERN:mutex-raii\nCONSTRAINT:no-deadlock CONSTRAINT:memory-safe\nCONTEXT:step=2 prev_status=COMPILER_PASS",
                "intent": "implement",
                "pattern": "mutex-raii",
                "constraints": ["no-deadlock", "memory-safe"],
            },
        ],
    },
    {
        "task_id": "go_error_wrap",
        "task_type": "go_error_handling",
        "lang": "go",
        "md_spec": "Implement WrapError using fmt.Errorf with %w verb and verify errors.Is works on wrapped errors.",
        "steps": [
            {
                "id": 1,
                "instruction": "implement WrapError(msg string, err error) error using fmt.Errorf %w",
                "dsl_context": "INTENT:implement LANG:GO PATTERN:error-wrapping\nCONSTRAINT:errors-is-compatible\nCONTEXT:step=1",
                "intent": "implement",
                "pattern": "error-wrapping",
                "constraints": ["errors-is-compatible"],
            },
            {
                "id": 2,
                "instruction": "implement CheckWrap() that verifies errors.Is works on the wrapped error",
                "dsl_context": "INTENT:implement LANG:GO PATTERN:error-verification\nCONSTRAINT:errors-is-compatible\nCONTEXT:step=2 prev_status=COMPILER_PASS",
                "intent": "implement",
                "pattern": "error-verification",
                "constraints": ["errors-is-compatible"],
            },
        ],
    },
    {
        "task_id": "python_thread_safe",
        "task_type": "python_concurrency",
        "lang": "python",
        "md_spec": "Implement a thread-safe session tracker with add_session(user_id, duration) and get_total(user_id).",
        "steps": [
            {
                "id": 1,
                "instruction": "define SessionTracker class with threading.Lock and defaultdict",
                "dsl_context": "INTENT:define LANG:PYTHON PATTERN:thread-safe-state\nCONSTRAINT:thread-safe\nCONTEXT:step=1",
                "intent": "define",
                "pattern": "thread-safe-state",
                "constraints": ["thread-safe"],
            },
            {
                "id": 2,
                "instruction": "implement add_session(user_id, duration) and get_total(user_id) methods",
                "dsl_context": "INTENT:implement LANG:PYTHON PATTERN:thread-safe-accumulator\nCONSTRAINT:thread-safe CONSTRAINT:correct-default\nCONTEXT:step=2 prev_status=COMPILER_PASS",
                "intent": "implement",
                "pattern": "thread-safe-accumulator",
                "constraints": ["thread-safe"],
            },
        ],
    },
    {
        "task_id": "rust_result_handling",
        "task_type": "rust_error_handling",
        "lang": "rust",
        "md_spec": "Implement safe_divide returning Option<f64>, returning None for zero divisor.",
        "steps": [
            {
                "id": 1,
                "instruction": "implement fn safe_divide(a: f64, b: f64) -> Option<f64>",
                "dsl_context": "INTENT:implement LANG:RUST PATTERN:option-return\nCONSTRAINT:no-panic CONSTRAINT:zero-safe\nCONTEXT:step=1",
                "intent": "implement",
                "pattern": "option-return",
                "constraints": ["no-panic", "zero-safe"],
            },
        ],
    },
    {
        "task_id": "go_context_cancel",
        "task_type": "go_concurrency",
        "lang": "go",
        "md_spec": "Implement ProcessData(ctx context.Context, inputs []int) that processes inputs in goroutines, respecting ctx.Done().",
        "steps": [
            {
                "id": 1,
                "instruction": "implement ProcessData with goroutines and ctx.Done() select case",
                "dsl_context": "INTENT:implement LANG:GO PATTERN:context-cancellation\nCONSTRAINT:goroutine-safe CONSTRAINT:ctx-respecting\nCONTEXT:step=1",
                "intent": "implement",
                "pattern": "context-cancellation",
                "constraints": ["goroutine-safe"],
            },
        ],
    },
]


# ── Run one task through both pipelines ──────────────────────────────────────


def run_task_comparison(
    task: dict,
    builder_model: str,
    shadow: ShadowEvaluator,
    fallback_queue: list[str],
    max_retries: int = 3,
    phase3_ctx: dict | None = None,
    bridge_mode: str = "none",
) -> TaskResult:
    task_type = task.get("task_type", "unknown")
    result = TaskResult(
        task_id=task["task_id"], task_type=task_type, lang=task["lang"], md_spec=task["md_spec"]
    )

    if shadow.is_fallback(task_type):
        log.info("[%s] In text-only fallback for task_type=%s", task["task_id"], task_type)
        shadow.record_completion(task_type)

    log.info("Task: %s [%s]", task["task_id"], task_type)
    run_shadow = shadow.should_run_shadow(task_type)

    for step in task["steps"]:
        # Run both pipelines — parallel on I/O-bound tasks
        def _rosetta(s=step):
            return run_rosetta_pipeline_step(
                task,
                s,
                builder_model,
                task["md_spec"],
                max_retries,
                phase3=phase3_ctx,
                bridge_mode=bridge_mode,
            )

        def _text(s=step):
            return run_text_pipeline_step(task, s, builder_model, task["md_spec"], max_retries)

        # ── #5 VRAM-aware parallel execution ─────────────────────────────────
        # On constrained hardware (<8GB free VRAM), running both pipelines in
        # parallel risks OOM when each pipeline loads a separate model.
        # Sequential mode avoids this at the cost of ~2x wall clock time.
        if run_shadow or not shadow.is_fallback(task_type):
            if _PARALLEL_OK:
                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                    f_r = pool.submit(_rosetta)
                    f_t = pool.submit(_text)
                    r_step = f_r.result()
                    t_step = f_t.result()
            else:
                # Sequential: Tier 0 constrained — avoid dual-model OOM
                r_step = _rosetta()
                t_step = _text()
        else:
            # Fallback: text only
            t_step = _text()
            r_step = t_step  # mirror so aggregates don't break

        result.rosetta_steps.append(r_step)
        result.text_steps.append(t_step)

        if run_shadow:
            shadow.record_shadow_result(task_type, r_step.compiled, t_step.compiled, fallback_queue)

        log.info(
            "  Step %d → Rosetta: %s (%ds, %d retries) | Text: %s (%ds, %d retries)",
            step["id"],
            "PASS" if r_step.compiled else "FAIL",
            int(r_step.wall_clock_secs),
            r_step.retries,
            "PASS" if t_step.compiled else "FAIL",
            int(t_step.wall_clock_secs),
            t_step.retries,
        )
        log.info("    BridgeStatus: %s", r_step.bridge_status)

    result.compute_aggregates()
    return result


# ── Report formatting ─────────────────────────────────────────────────────────


def print_report(report: EvalReport, task_results: list[TaskResult]) -> None:
    bar = "=" * 70
    print(f"\n{bar}")
    print("ROSETTA vs TEXT — A/B EVALUATION REPORT")
    print(f"Timestamp : {report.timestamp}")
    print(f"Mode      : {report.mode}")
    print(f"Tasks     : {report.tasks_evaluated}")
    print(bar)

    print(f"\n{'OVERALL':}")
    print(f"  Rosetta compile rate : {report.overall_rosetta_compile_rate:.1%}")
    print(f"  Text    compile rate : {report.overall_text_compile_rate:.1%}")
    delta = report.overall_rosetta_compile_rate - report.overall_text_compile_rate
    print(
        f"  Delta                : {delta:+.1%}  ({'Rosetta wins' if delta > 0 else 'Text wins' if delta < 0 else 'Tied'})"
    )

    print(f"\n{'DILUTION CHECK':}")
    if report.dilution_detected:
        print(f"  ⚠ DILUTION DETECTED at ~{report.dilution_breakpoint_tokens} tokens")
        print("    K=1 prefix is being attention-washed above this context size.")
        print("    → Architectural review required before deploying Rosetta at long contexts.")
    else:
        print("  ✓ No dilution detected across context length buckets.")

    print(f"\n{'ADJUDICATION CEILING':}")
    if report.ceiling_check_passed:
        print(f"  ✓ Ceiling check PASSED (min separation={report.ceiling_separation:.3f})")
    else:
        print(
            f"  ⚠ Ceiling check FAILED (min separation={report.ceiling_separation:.3f} < {CEILING_CHECK_MIN_SEPARATION})"
        )
        print("    Adjudication running in COARSE MODE — compile rate is primary differentiator.")

    if report.shadow_fallbacks:
        print(f"\n{'SHADOW FALLBACKS':}")
        for t in report.shadow_fallbacks:
            print(f"  ⚠ AUTO-FALLBACK to text-only: task_type={t}")

    print(f"\n{'TASK BREAKDOWN':}")
    print(
        f"  {'Task ID':<30} {'R.Compile':>10} {'T.Compile':>10} {'R.Retries':>10} {'T.Retries':>10} {'R.Wall':>8} {'T.Wall':>8}"
    )
    print(f"  {'-' * 88}")
    for tr in task_results:
        print(
            f"  {tr.task_id:<30} {tr.rosetta_compile_rate:>10.1%} {tr.text_compile_rate:>10.1%}"
            f" {tr.rosetta_avg_retries:>10.2f} {tr.text_avg_retries:>10.2f}"
            f" {tr.rosetta_avg_wall_secs:>7.1f}s {tr.text_avg_wall_secs:>7.1f}s"
        )
    print(bar)


def save_report(report: EvalReport, task_results: list[TaskResult], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(report)
    payload["task_results"] = [asdict(tr) for tr in task_results]
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    log.info("Report saved → %s", out_path)


def load_and_print_report(path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    print(json.dumps(data, indent=2))


# ── Main ──────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Rosetta vs Text A/B Evaluator")
    parser.add_argument(
        "--mode", choices=["offline", "shadow", "ceiling-check", "report"], default="offline"
    )
    parser.add_argument(
        "--builder-model",
        default="determinex-engineer:latest",
        help="Ollama model tag to use as Builder",
    )
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--task-type", default=None, help="For shadow mode: task type to evaluate")
    parser.add_argument(
        "--report", type=Path, default=None, help="For report mode: path to saved JSON report"
    )
    parser.add_argument(
        "--out", type=Path, default=None, help="Where to save the JSON report (offline mode)"
    )
    parser.add_argument(
        "--gguf-path",
        type=Path,
        default=None,
        help="GGUF model path for Phase 3 embedding injection",
    )
    parser.add_argument(
        "--rosetta-path",
        type=Path,
        default=None,
        help="rosetta_v1.pt path for Phase 3 (default: ~/.determinex/rosetta/rosetta_v1.pt)",
    )
    parser.add_argument(
        "--arch-name",
        default="qwen2_7b",
        help="Rosetta arch key for projection (SIZE-SPECIFIC, e.g. qwen2_7b not qwen2)",
    )
    parser.add_argument(
        "--bridge",
        choices=["none", "text-space", "soft-prefix"],
        default="none",
        help="Which Rosetta bridge to engage. 'none' = pure text baseline. "
        "'text-space' = Layer 2A approximation. 'soft-prefix' = Layer 2B injection. "
        "Every result must report a BridgeStatus so fallbacks cannot be silently "
        "counted as Rosetta successes.",
    )
    args = parser.parse_args()

    # ── BRIDGE PRE-FLIGHT — report status BEFORE running so user knows what we ran ──
    # Eval reports must distinguish rosetta_projected / direct_self_injection /
    # text_fallback / failed_bridge. Resolve before the rest of the run so we
    # can refuse to label text-only results as Rosetta.
    try:
        from rosetta.model_registry import BridgeStatus

        _bridge_status_initial = {
            "none": BridgeStatus.TEXT_FALLBACK.value,
            "text-space": BridgeStatus.TEXT_FALLBACK.value,  # 2A approximates via text — explicit
            "soft-prefix": BridgeStatus.FAILED_BRIDGE.value,  # promoted to ROSETTA_PROJECTED on success
        }[args.bridge]
    except ImportError:
        _bridge_status_initial = "failed_bridge"
    log.info(
        "[Bridge] --bridge=%s  initial_status=%s  arch=%s",
        args.bridge,
        _bridge_status_initial,
        args.arch_name,
    )

    # ── REPORT MODE ───────────────────────────────────────────────────────────
    if args.mode == "report":
        if not args.report or not args.report.exists():
            log.error("--report path required and must exist")
            sys.exit(1)
        load_and_print_report(args.report)
        return

    # ── CEILING CHECK ONLY ────────────────────────────────────────────────────
    if args.mode == "ceiling-check":
        passed, min_sep = run_ceiling_check()
        sys.exit(0 if passed else 1)

    # ── Phase 3 setup ─────────────────────────────────────────────────────────
    phase3_ctx: dict | None = None
    if args.gguf_path:
        if not _PHASE3_AVAILABLE:
            log.error(
                "Phase 3 requires determinex_inference + determinex_rosetta + llama-cpp-python"
            )
            sys.exit(1)
        rosetta_path = args.rosetta_path or (
            Path.home() / ".determinex" / "rosetta" / "rosetta_v1.pt"
        )
        if not args.gguf_path.exists():
            log.error("GGUF not found: %s", args.gguf_path)
            sys.exit(1)
        if not rosetta_path.exists():
            log.error("rosetta_v1.pt not found: %s", rosetta_path)
            sys.exit(1)
        log.info("Phase 3 mode: loading DeterminexInference from %s", args.gguf_path)
        _p3_inf = _DeterminexInference(str(args.gguf_path), args.arch_name)
        _p3_stone = _RosettaStone.load(rosetta_path)
        phase3_ctx = {"inference": _p3_inf, "stone": _p3_stone, "arch": args.arch_name}
        log.info("Phase 3 ready — arch=%s hidden_dim=%d", args.arch_name, _p3_inf.hidden_dim)

    # ── OFFLINE / SHADOW ──────────────────────────────────────────────────────
    shadow = ShadowEvaluator()
    fallback_queue: list[str] = []

    if args.mode == "shadow":
        # Run only tasks matching task_type
        tasks = [t for t in EVAL_TASKS if t.get("task_type") == args.task_type]
        if not tasks:
            log.error("No tasks found for task_type=%s", args.task_type)
            sys.exit(1)
    else:
        tasks = EVAL_TASKS

    task_results: list[TaskResult] = []
    for task in tasks:
        tr = run_task_comparison(
            task,
            args.builder_model,
            shadow,
            fallback_queue,
            args.max_retries,
            phase3_ctx,
            args.bridge,
        )
        task_results.append(tr)

    # ── Aggregate metrics ─────────────────────────────────────────────────────
    all_r_compile = [s.compiled for tr in task_results for s in tr.rosetta_steps]
    all_t_compile = [s.compiled for tr in task_results for s in tr.text_steps]
    overall_r_rate = sum(all_r_compile) / max(len(all_r_compile), 1)
    overall_t_rate = sum(all_t_compile) / max(len(all_t_compile), 1)

    diluted, breakpoint = detect_dilution(task_results)
    ceiling_ok, min_sep = run_ceiling_check()

    report = EvalReport(
        timestamp=datetime.now(UTC).isoformat(),
        mode=args.mode,
        tasks_evaluated=len(task_results),
        bridge=args.bridge,
        initial_bridge_status=_bridge_status_initial,
        overall_rosetta_compile_rate=overall_r_rate,
        overall_text_compile_rate=overall_t_rate,
        dilution_detected=diluted,
        dilution_breakpoint_tokens=breakpoint,
        ceiling_check_passed=ceiling_ok,
        ceiling_separation=min_sep,
        shadow_fallbacks=fallback_queue,
    )

    print_report(report, task_results)

    out = args.out or (_RESULTS / f"eval_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.json")
    save_report(report, task_results, out)

    # Exit non-zero if Rosetta isn't winning (or tied) — for CI integration
    sys.exit(0 if overall_r_rate >= overall_t_rate else 1)


if __name__ == "__main__":
    main()
