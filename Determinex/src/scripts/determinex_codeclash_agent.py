"""
Determinex CodeClash Agent
=======================
Wraps the Determinex Hive Mind (C1/C3/C7) as a CodeClash arena competitor.

CodeClash arenas: goal-oriented, multi-round. Model gets edit phase (improve codebase),
then compete phase (codebase runs against others in arena). Competition logs fed back.
Next round: model analyzes logs, improves strategy, edits again.

Usage:
  python scripts/determinex_codeclash_agent.py --arena RobotRumble --rounds 15 --workspace /tmp/cc_arena

Environment:
  DETERMINEX_INFERENCE_BACKEND  ollama | vllm | deepseek (default: ollama)
  DETERMINEX_CC_MODEL           c7 | c3 | c1 (default: c7 for planning)
  CODECLASH_ARENA_PATH       path to arena directory (overrides --workspace)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from pathlib import Path

# ── Logging ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="[CC] %(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("determinex_cc")

# ── Model Registry ───────────────────────────────────────────────────────────

_REGISTRY_PATH = Path(__file__).parent.parent / "determinex_model_registry.json"


def _load_registry() -> dict:
    if _REGISTRY_PATH.exists():
        return json.loads(_REGISTRY_PATH.read_text())
    return {}


REGISTRY = _load_registry()

_MODEL_MAP = {
    "c1": REGISTRY.get("models", {}).get("C1", {}).get("ollama_tag", "determinex-engineer-v10-dsl"),
    "c3": REGISTRY.get("models", {}).get("C3", {}).get("ollama_tag", "determinex-observer-v5-dsl"),
    "c7": REGISTRY.get("models", {}).get("C7", {}).get("ollama_tag", "determinex-sentinel-v3"),
}

_CC_MODEL = os.getenv("DETERMINEX_CC_MODEL", "c7").lower()
_BACKEND = os.getenv("DETERMINEX_INFERENCE_BACKEND", "ollama")
_VLLM_URL = os.getenv("DETERMINEX_VLLM_URL", "http://localhost:8000/v1")
_DS_KEY = os.getenv("DETERMINEX_DEEPSEEK_KEY", os.getenv("DEEPSEEK_API_KEY", ""))
_DS_MODEL = os.getenv("DETERMINEX_DEEPSEEK_MODEL", "deepseek-chat")
_DS_URL = "https://api.deepseek.com/v1"

# ── Inference ────────────────────────────────────────────────────────────────


def _infer(
    prompt: str, system: str = "", temperature: float = 0.2, model_key: str | None = None
) -> str:
    model_key = model_key or _CC_MODEL
    model_name = _MODEL_MAP.get(model_key, _MODEL_MAP["c7"])

    if _BACKEND == "deepseek":
        return _openai_compat(_DS_URL, _DS_KEY, _DS_MODEL, prompt, system, temperature)
    elif _BACKEND == "vllm":
        return _openai_compat(_VLLM_URL, "dummy", model_name, prompt, system, temperature)
    else:
        return _ollama(model_name, prompt, system, temperature)


def _openai_compat(
    url: str, api_key: str, model: str, prompt: str, system: str, temperature: float
) -> str:
    import urllib.request

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    payload = json.dumps(
        {"model": model, "messages": messages, "temperature": temperature, "max_tokens": 4096}
    ).encode()
    req = urllib.request.Request(
        f"{url.rstrip('/')}/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        resp = json.loads(r.read())
    return resp["choices"][0]["message"]["content"].strip()


def _ollama(model: str, prompt: str, system: str, temperature: float) -> str:
    import urllib.request

    payload = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "system": system,
            "stream": False,
            "options": {"temperature": temperature, "num_ctx": 4096},
        }
    ).encode()
    req = urllib.request.Request(
        "http://localhost:11434/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())["response"].strip()


# ── Arena State ──────────────────────────────────────────────────────────────


class ArenaState:
    def __init__(self, workspace: Path, arena_name: str):
        self.workspace = workspace
        self.arena_name = arena_name
        self.round_log = workspace / "round_history.jsonl"
        self.strategy_md = workspace / "determinex_strategy.md"
        self.codebase = workspace / "src"
        self.codebase.mkdir(parents=True, exist_ok=True)

    def current_round(self) -> int:
        if not self.round_log.exists():
            return 1
        return sum(1 for _ in self.round_log.open(encoding="utf-8")) + 1

    def load_history(self) -> list[dict]:
        if not self.round_log.exists():
            return []
        return [json.loads(l) for l in self.round_log.open(encoding="utf-8") if l.strip()]

    def record_round(self, round_num: int, outcome: dict):
        with self.round_log.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"round": round_num, **outcome}) + "\n")

    def read_competition_logs(self) -> str:
        logs = []
        for f in sorted(self.workspace.glob("competition_log_round_*.txt")):
            logs.append(f"=== {f.name} ===\n{f.read_text()[:3000]}")
        return "\n\n".join(logs[-3:]) if logs else ""

    def read_codebase(self) -> str:
        files = []
        for f in sorted(self.codebase.rglob("*.py")):
            rel = f.relative_to(self.codebase)
            files.append(f"# {rel}\n{f.read_text()[:2000]}")
        return "\n\n".join(files) if files else "(empty codebase)"


# ── Core Agent Logic ─────────────────────────────────────────────────────────


def analyze_and_plan(state: ArenaState, goal: str) -> list[dict]:
    """C7 Architect: read competition logs + current codebase → produce improvement DAG."""
    history = state.load_history()
    comp_logs = state.read_competition_logs()
    codebase = state.read_codebase()
    round_num = state.current_round()

    wins = sum(1 for h in history if h.get("result") == "win")
    losses = sum(1 for h in history if h.get("result") == "loss")

    system = (
        f"You are Determinex-7-Large (C7), the Architect model for the Determinex Hive Mind. "
        f"You are competing in the '{state.arena_name}' CodeClash arena. "
        f"Your goal: {goal}. "
        f"Current record: {wins}W-{losses}L after {round_num - 1} rounds. "
        f"Produce a JSON array of improvement steps. Each step has: "
        f"file (str), action (str: new_file|modify|delete), instruction (str), priority (1-5). "
        f"Focus on the highest-impact changes based on competition logs. "
        f"Max 5 steps per round. Return ONLY valid JSON array."
    )

    prompt = f"""COMPETITION LOGS (recent rounds):
{comp_logs if comp_logs else "(first round — no logs yet)"}

CURRENT CODEBASE:
{codebase}

ROUND {round_num}: Produce the improvement DAG as JSON array.
Focus on what the logs show is causing losses. Be concrete and specific.
Return ONLY the JSON array."""

    raw = _infer(prompt, system=system, temperature=0.1, model_key="c7")

    # Extract JSON array
    m = re.search(r"\[.*\]", raw, re.DOTALL)
    if not m:
        log.warning("C7 returned no valid JSON DAG — using fallback single step")
        return [
            {
                "file": "main.py",
                "action": "modify",
                "instruction": "Improve core algorithm based on competition analysis",
                "priority": 5,
            }
        ]

    try:
        steps = json.loads(m.group(0))
        steps.sort(key=lambda s: -s.get("priority", 1))
        log.info("C7 planned %d improvement steps for round %d", len(steps), round_num)
        return steps[:5]
    except json.JSONDecodeError:
        log.warning("C7 JSON parse failed — using fallback")
        return [
            {
                "file": "main.py",
                "action": "modify",
                "instruction": "Improve based on competition logs",
                "priority": 5,
            }
        ]


def execute_step(state: ArenaState, step: dict, round_num: int) -> tuple[bool, str]:
    """C1 Builder: execute one improvement step on the codebase."""
    target_file = state.codebase / step["file"]
    action = step.get("action", "modify")
    instruction = step["instruction"]

    current_content = target_file.read_text() if target_file.exists() else "(new file)"

    system = (
        "You are Determinex-1-Tiny (C1), the Builder model for the Determinex Hive Mind. "
        "You produce clean, correct Python code. No markdown fences. No explanations. "
        "Output ONLY the complete file content."
    )

    prompt = f"""INSTRUCTION: {instruction}

CURRENT FILE ({step["file"]}):
{current_content[:3000]}

ACTION: {action}

Produce the complete updated file content. No markdown. No explanations. Just the code."""

    try:
        new_content = _infer(prompt, system=system, temperature=0.15, model_key="c1")
        # Strip markdown fences if model adds them
        new_content = re.sub(r"^```python\s*\n?", "", new_content.strip())
        new_content = re.sub(r"\n?```\s*$", "", new_content).strip()

        target_file.parent.mkdir(parents=True, exist_ok=True)
        target_file.write_text(new_content)
        log.info("C1 wrote %s (%d lines)", step["file"], new_content.count("\n"))
        return True, new_content
    except Exception as e:
        log.error("C1 failed on step %s: %s", step["file"], e)
        return False, str(e)


def monitor_review(state: ArenaState, step: dict, code: str) -> tuple[str, float]:
    """C3 Monitor: review C1's output for quality and correctness."""
    system = (
        "You are Determinex-3-Medium (C3), the Monitor model for the Determinex Hive Mind. "
        "You review code quality, correctness, and strategic alignment. "
        "Respond in Semantic DSL format: VERDICT:PASS|FAIL CONFIDENCE:0.0-1.0 NOTE:brief_reason"
    )

    prompt = f"""STEP INSTRUCTION: {step["instruction"]}
TARGET FILE: {step["file"]}

GENERATED CODE:
{code[:2000]}

Review: does this code correctly implement the instruction? Will it help win in the arena?
Respond: VERDICT:PASS|FAIL CONFIDENCE:0.0-1.0 NOTE:brief_reason"""

    raw = _infer(prompt, system=system, temperature=0.1, model_key="c3")

    verdict = "PASS" if "VERDICT:PASS" in raw or "PASS" in raw.upper() else "FAIL"
    conf_m = re.search(r"CONFIDENCE[:\s]+([\d.]+)", raw)
    conf = float(conf_m.group(1)) if conf_m else 0.7

    log.info("C3 verdict: %s (conf=%.2f)", verdict, conf)
    return verdict, conf


def run_round(state: ArenaState, goal: str, round_num: int) -> dict:
    """Execute one full edit round: plan → build → monitor → validate."""
    log.info("=" * 60)
    log.info("ROUND %d — %s", round_num, state.arena_name)
    log.info("=" * 60)

    t0 = time.time()
    steps = analyze_and_plan(state, goal)

    results = []
    for i, step in enumerate(steps, 1):
        log.info("[Step %d/%d] %s → %s", i, len(steps), step["action"], step["file"])

        success, content = execute_step(state, step, round_num)
        if not success:
            results.append({"step": i, "file": step["file"], "status": "error"})
            continue

        # Syntax check on Python files. Routes through intake.hardened_runner
        # (HARDENED_VERIFIED_TASK_AND_CODECLASH_LOCK_001) so the user-
        # controlled codebase path is workspace-bounded, env-scrubbed, and
        # Docker/network blocked.
        if step["file"].endswith(".py"):
            from intake.hardened_runner import run as _hardened_run

            r = _hardened_run(
                [sys.executable, "-m", "py_compile", str(state.codebase / step["file"])],
                workspace=state.codebase,
                timeout=30,
            )
            # blocked / timed_out / tool_missing / exit_code != 0 all count as compile_fail
            if r.blocked or r.timed_out or r.tool_missing or r.exit_code != 0:
                detail = (r.reason if r.blocked else (r.stderr or "py_compile fail"))[:200]
                log.warning("py_compile FAIL: %s", detail)
                results.append({"step": i, "file": step["file"], "status": "compile_fail"})
                continue

        verdict, conf = monitor_review(state, step, content)
        results.append(
            {
                "step": i,
                "file": step["file"],
                "status": "pass" if verdict == "PASS" else "monitor_fail",
                "confidence": conf,
            }
        )

    elapsed = time.time() - t0
    outcome = {
        "steps_planned": len(steps),
        "steps_completed": sum(1 for r in results if r["status"] == "pass"),
        "elapsed_s": round(elapsed, 1),
        "result": "pending",  # filled after competition phase
        "step_results": results,
    }

    state.record_round(round_num, outcome)
    log.info(
        "Round %d edit phase complete: %d/%d steps passed in %.0fs",
        round_num,
        outcome["steps_completed"],
        outcome["steps_planned"],
        elapsed,
    )
    return outcome


def update_strategy(state: ArenaState, round_num: int, competition_result: str):
    """After competition: C7 writes strategy notes for next round."""
    comp_logs = state.read_competition_logs()
    history = state.load_history()
    wins = sum(1 for h in history if h.get("result") == "win")
    losses = sum(1 for h in history if h.get("result") == "loss")

    system = (
        "You are Determinex-7-Large (C7). Analyze competition results and update your strategy. "
        "Be specific about what worked and what to improve next round. Max 200 words."
    )
    prompt = f"""Round {round_num} result: {competition_result}
Record: {wins}W-{losses}L

Competition logs:
{comp_logs[:2000]}

Write a concise strategy update for round {round_num + 1}. What specific changes will improve performance?"""

    strategy = _infer(prompt, system=system, temperature=0.2, model_key="c7")
    with state.strategy_md.open("a", encoding="utf-8") as f:
        f.write(f"\n\n## Round {round_num} → {round_num + 1} Strategy\n\n{strategy}\n")
    log.info("Strategy updated for round %d", round_num + 1)


# ── Main ─────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Determinex CodeClash Agent")
    parser.add_argument("--arena", default="RobotRumble", help="Arena name")
    parser.add_argument(
        "--goal", default="Maximize score across all competition rounds", help="High-level goal"
    )
    parser.add_argument("--rounds", type=int, default=15, help="Total rounds to run")
    parser.add_argument(
        "--workspace", default="/tmp/determinex_codeclash", help="Arena workspace directory"
    )
    parser.add_argument("--resume", action="store_true", help="Resume from existing workspace")
    args = parser.parse_args()

    workspace = Path(os.getenv("CODECLASH_ARENA_PATH", args.workspace))
    state = ArenaState(workspace, args.arena)
    start_round = state.current_round() if args.resume else 1

    log.info("Determinex CodeClash Agent v1.0")
    log.info(
        "Arena: %s | Goal: %s | Rounds: %d-%d", args.arena, args.goal, start_round, args.rounds
    )
    log.info("Models: C1=%s C3=%s C7=%s", _MODEL_MAP["c1"], _MODEL_MAP["c3"], _MODEL_MAP["c7"])
    log.info("Backend: %s", _BACKEND)

    for round_num in range(start_round, args.rounds + 1):
        outcome = run_round(state, args.goal, round_num)

        # In automated mode: competition happens externally, result injected via file
        result_file = workspace / f"result_round_{round_num}.txt"
        if result_file.exists():
            result = result_file.read_text().strip()
            log.info("Competition result for round %d: %s", round_num, result)
            update_strategy(state, round_num, result)
            # Update the round record with the actual result
            history = state.load_history()
            if history:
                history[-1]["result"] = result
                with state.round_log.open("w", encoding="utf-8") as f:
                    for h in history:
                        f.write(json.dumps(h) + "\n")
        else:
            log.info("No result file found for round %d — waiting for competition phase", round_num)
            log.info("Place result in: %s", result_file)
            log.info("Then re-run with --resume to continue")
            break

    log.info("Determinex CodeClash session complete.")


if __name__ == "__main__":
    main()
