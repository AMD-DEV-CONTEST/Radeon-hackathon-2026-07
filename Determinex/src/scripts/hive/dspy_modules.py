"""
scripts/hive/dspy_modules.py — DSPy opt-in prompt optimization modules
======================================================================
DSPy (Demonstrate-Search-Predict) modules that replace the static hand-written
prompt templates in hive/prompt_builder.py when DETERMINEX_USE_DSPY=1 is set.

Why DSPy for Determinex:
  Determinex already has everything DSPy needs to self-optimize:
    - Labeled success/failure pairs: the WAL + training corpus
    - Deterministic oracles: the compiler/test suite
    - Multiple callable LLM backends: LiteLLM (Ollama, Claude, GPT)

  BootstrapFewShot takes the existing corpus of verified build sessions and
  automatically derives few-shot examples that maximize oracle pass rate —
  essentially letting the system prompt-tune itself from its own verified outcomes.

Usage:
    export DETERMINEX_USE_DSPY=1
    # executor.py detects this and uses DeterminexMonitor / DeterminexDAGPlanner
    # instead of the static prompt templates.

    # To optimize (run once with a training corpus):
    python scripts/hive/dspy_modules.py optimize --corpus logs/sessions/ --out dspy_weights.pkl

Integration:
    The modules implement the same interface as the static prompt functions:
      DeterminexMonitor(step_instruction, builder_output, compiler_result) -> MonitorVerdict
      DeterminexDAGPlanner(spec, lang, scaffold) -> DAGPlan

    These are duck-typed drop-ins for _parse_monitor_verdict() and the DAG gen in api_client.py.

Requirements:
    pip install dspy-ai>=2.4.0 pydantic>=2.0.0
"""

from __future__ import annotations

import os
from typing import Any  # used in oracle_metric's signature; was never imported

try:
    import dspy

    _DSPY_AVAILABLE = True
except ImportError:
    _DSPY_AVAILABLE = False


if not _DSPY_AVAILABLE:
    raise ImportError(
        "DSPy not installed. Install with: pip install 'determinex[dspy]'\n"
        "Or: pip install dspy-ai>=2.4.0"
    )


# ── DSPy Signatures ───────────────────────────────────────────────────────────


class MonitorVerdictSignature(dspy.Signature):
    """You are a code review monitor. Score the builder output on correctness,
    safety, and adherence to the step instruction. Return a score 0.0-1.0
    and a one-sentence verdict explaining the main issue or confirmation."""

    step_instruction: str = dspy.InputField(
        desc="The step instruction the builder was asked to implement"
    )
    builder_output: str = dspy.InputField(
        desc="The code the builder produced (truncated to 3000 chars)"
    )
    compiler_result: str = dspy.InputField(desc="PASS or FAIL from the compiler oracle")
    language: str = dspy.InputField(desc="Target programming language (rust, go, python, etc.)")

    score: float = dspy.OutputField(desc="Quality score from 0.0 (fail) to 1.0 (perfect)")
    verdict: str = dspy.OutputField(desc="One sentence verdict on the builder output quality")
    issues: list[str] = dspy.OutputField(desc="List of specific issues found, or empty if none")


class DAGPlanSignature(dspy.Signature):
    """You are a software architect. Given a specification and language, produce a
    step-by-step DAG build plan. Each step should be a single coherent unit of work
    (one file or one function), with explicit dependencies on prior steps."""

    spec: str = dspy.InputField(desc="The full specification of what to build")
    language: str = dspy.InputField(desc="Target programming language")
    scaffold: str = dspy.InputField(desc="Existing project scaffold (file listing)")

    steps: list[dict] = dspy.OutputField(
        desc="Ordered list of steps. Each: {id, instruction, target_file, write_mode, depends_on: []}"
    )


# ── DSPy Modules ─────────────────────────────────────────────────────────────


class DeterminexMonitor(dspy.Module):
    """DSPy drop-in for _parse_monitor_verdict() in hive/prompt_builder.py.

    When DETERMINEX_USE_DSPY=1, executor.py calls this instead of the
    static prompt + regex parse path. Produces the same (score, verdict)
    tuple contract.
    """

    def __init__(self) -> None:
        super().__init__()
        # ChainOfThought: model reasons step-by-step before outputting the verdict.
        # This reduces hallucinated high scores for clearly wrong builder outputs.
        self.predictor = dspy.ChainOfThought(MonitorVerdictSignature)

    def forward(
        self,
        step_instruction: str,
        builder_output: str,
        compiler_result: str,
        language: str = "",
    ) -> tuple[float, str]:
        """Returns (score: float, verdict: str) — same contract as _parse_monitor_verdict."""
        try:
            pred = self.predictor(
                step_instruction=step_instruction,
                builder_output=builder_output[:3000],
                compiler_result=compiler_result,
                language=language or "unknown",
            )
            score = float(pred.score) if isinstance(pred.score, (int, float)) else 0.5
            score = max(0.0, min(1.0, score))
            verdict = str(pred.verdict or "")[:200]
            return score, verdict
        except Exception as e:
            import logging

            logging.getLogger("hive.dspy").warning("DeterminexMonitor failed: %s", e)
            return 0.5, f"dspy-monitor-error: {e}"


class DeterminexDAGPlanner(dspy.Module):
    """DSPy drop-in for the DAG generation step in hive/api_client.py.

    When DETERMINEX_USE_DSPY=1, executor.py can use this instead of the
    static prompt template to generate the step manifest.
    """

    def __init__(self) -> None:
        super().__init__()
        self.predictor = dspy.ChainOfThought(DAGPlanSignature)

    def forward(
        self,
        spec: str,
        language: str,
        scaffold: str = "",
    ) -> list[dict]:
        """Returns a list of step dicts compatible with StepRecord."""
        try:
            pred = self.predictor(
                spec=spec[:4000],
                language=language,
                scaffold=scaffold[:1000],
            )
            steps = pred.steps
            if isinstance(steps, list):
                return steps
            return []
        except Exception as e:
            import logging

            logging.getLogger("hive.dspy").warning("DeterminexDAGPlanner failed: %s", e)
            return []


# ── LM configuration ─────────────────────────────────────────────────────────


def configure_dspy_lm(
    model: str | None = None,
    api_base: str | None = None,
    temperature: float = 0.2,
) -> None:
    """Configure the DSPy language model from Determinex's provider config.

    Defaults to the Ollama local provider (respects DETERMINEX_NETWORK_POLICY=offline).
    Override with DETERMINEX_DSPY_MODEL and DETERMINEX_DSPY_API_BASE env vars.
    """
    model = model or os.environ.get("DETERMINEX_DSPY_MODEL", "ollama/qwen2.5-coder:14b")
    api_base = api_base or os.environ.get("DETERMINEX_DSPY_API_BASE", "http://localhost:11434")

    try:
        lm = dspy.LM(model=model, api_base=api_base, temperature=temperature)
        dspy.configure(lm=lm)
    except Exception as e:
        import logging

        logging.getLogger("hive.dspy").warning(
            "DSPy LM configuration failed (model=%s api_base=%s): %s — "
            "DETERMINEX_USE_DSPY will fall back to static prompts.",
            model,
            api_base,
            e,
        )


# ── BootstrapFewShot optimizer (run offline to produce optimized weights) ─────


def optimize_monitor(
    corpus_sessions_dir: str,
    output_path: str = "dspy_monitor_weights.pkl",
    max_demos: int = 8,
) -> None:
    """Run BootstrapFewShot to derive few-shot examples from the corpus.

    Call once after accumulating verified build sessions:
        python scripts/hive/dspy_modules.py optimize \
            --corpus logs/sessions/ --out dspy_monitor_weights.pkl

    The optimized weights are loaded automatically when DETERMINEX_USE_DSPY=1
    and the output file exists at DETERMINEX_DSPY_WEIGHTS_PATH.
    """
    import pickle

    configure_dspy_lm()

    # Build training set from WAL: (step_instruction, builder_output,
    # compiler_result, expected_score) from sessions where quality=training_ready
    trainset = _load_trainset_from_sessions(corpus_sessions_dir)
    if not trainset:
        print(
            f"No training examples found in {corpus_sessions_dir}. "
            "Run the build loop first to accumulate verified sessions."
        )
        return

    def oracle_metric(example: dspy.Example, pred: dspy.Prediction, _trace: Any = None) -> float:
        """Metric: predicted score should correlate with actual correctness_result."""
        actual_pass = example.get("correctness_result") == "pass"
        pred_score = float(pred.score) if hasattr(pred, "score") else 0.5
        # Reward high score for actual passes, low score for actual fails
        return (
            1.0
            if (actual_pass and pred_score >= 0.7) or (not actual_pass and pred_score < 0.5)
            else 0.0
        )

    monitor = DeterminexMonitor()
    optimizer = dspy.BootstrapFewShot(metric=oracle_metric, max_bootstrapped_demos=max_demos)
    optimized = optimizer.compile(monitor, trainset=trainset)
    with open(output_path, "wb") as f:
        pickle.dump(optimized, f)
    print(f"Optimized monitor weights -> {output_path} ({len(trainset)} examples)")


def _load_trainset_from_sessions(sessions_dir: str) -> list[dspy.Example]:
    """Load training examples from session WAL files."""
    import json
    from pathlib import Path

    examples = []
    for session_path in Path(sessions_dir).rglob("manifest.json"):
        try:
            manifest = json.loads(session_path.read_text(encoding="utf-8"))
            for step in manifest.get("steps", []):
                # A step whose correctness suite never RAN carries no signal in either direction,
                # so it must be excluded rather than labelled. Added 2026-07-30 alongside the
                # executor fix that made "skipped" reachable at all: until then every skip was
                # recorded as correctness_result="pass" and entered here as PASS/score=1.0, i.e. a
                # verification that had not happened. Simply letting them fall through would have
                # been the opposite error -- compiler_result="FAIL"/score=0.2 below teaches the
                # monitor that correct code is wrong.
                if step.get("correctness_result") == "skipped":
                    continue
                if step.get("quality") == "training_ready":
                    examples.append(
                        dspy.Example(
                            step_instruction=step.get("instruction", ""),
                            builder_output=step.get("builder_output_path", ""),
                            compiler_result="PASS"
                            if step.get("correctness_result") == "pass"
                            else "FAIL",
                            language=manifest.get("lang", ""),
                            score=1.0 if step.get("correctness_result") == "pass" else 0.2,
                            verdict=step.get("monitor_verdict", ""),
                            correctness_result=step.get("correctness_result", ""),
                            issues=[],
                        ).with_inputs(
                            "step_instruction", "builder_output", "compiler_result", "language"
                        )
                    )
        except Exception:
            continue
    return examples


# ── CLI ───────────────────────────────────────────────────────────────────────


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Determinex DSPy modules")
    sub = ap.add_subparsers(dest="cmd")
    opt = sub.add_parser("optimize", help="Run BootstrapFewShot on corpus sessions")
    opt.add_argument("--corpus", required=True)
    opt.add_argument("--out", default="dspy_monitor_weights.pkl")
    opt.add_argument("--max-demos", type=int, default=8)
    args = ap.parse_args()
    if args.cmd == "optimize":
        optimize_monitor(args.corpus, args.out, args.max_demos)
        return 0
    ap.print_help()
    return 1


if __name__ == "__main__":
    import sys

    sys.exit(main())
