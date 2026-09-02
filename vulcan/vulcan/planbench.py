"""Does decomposing a request actually help, or just cost a round trip?

Planning is the kind of feature that is easy to add and hard to justify. It
spends one extra model call before any tool runs, which is real latency, so it
has to earn that back. This measures whether it does, on the failure it is meant
to fix: a request with more than one part, where a reactive loop answers the
first part and stops.

Scoring is deliberately blunt. Each question names two things that exist in this
repository, and an answer either mentions both or it does not. No model grades
another model, and nothing here depends on wording.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from .agent import Agent
from .config import Config


@dataclass(frozen=True)
class Question:
    text: str
    #: Lowercased substrings the answer must contain, one per part of the ask.
    must_mention: tuple[str, ...]


QUESTIONS: tuple[Question, ...] = (
    Question("Which module implements the semantic index, and which one stores memory across sessions?",
             ("rag", "memory")),
    Question("Which module talks to the LLM, and which one defines the sandboxed tools?",
             ("llm", "tools")),
    Question("Where is the ReAct loop implemented, and which environment variable selects the model?",
             ("agent", "vulcan_model")),
    Question("Which module holds runtime configuration, and which one measures throughput?",
             ("config", "bench")),
)


def _score(answer: str, q: Question) -> int:
    low = answer.lower()
    return sum(1 for token in q.must_mention if token in low)


def run_one(cfg: Config, root: Path, q: Question, index_name: str) -> dict:
    agent = Agent(cfg, root, index_name)
    steps: list[dict] = []
    t0 = time.time()
    answer = agent.run(q.text, on_step=steps.append)
    wall = time.time() - t0
    covered = _score(answer, q)
    return {
        "question": q.text,
        "planned": any("plan" in s for s in steps),
        "steps": len(steps),
        "tool_calls": sum(1 for s in steps if "tool" in s),
        "wall_seconds": round(wall, 2),
        "parts_expected": len(q.must_mention),
        "parts_covered": covered,
        "complete": covered == len(q.must_mention),
        "answer": answer[:400],
    }


def sweep(root: Path, out: str = "bench-results/planning.json", index_name: str = "default") -> dict:
    rows = {}
    for mode, enabled in (("plan_off", False), ("plan_on", True)):
        cfg = Config()
        cfg.plan = enabled
        results = [run_one(cfg, root, q, index_name) for q in QUESTIONS]
        complete = sum(1 for r in results if r["complete"])
        rows[mode] = {
            "questions": len(results),
            "complete": complete,
            "completion_rate": round(complete / len(results), 3),
            "mean_parts_covered": round(sum(r["parts_covered"] for r in results) / len(results), 3),
            "mean_steps": round(sum(r["steps"] for r in results) / len(results), 2),
            "mean_wall_seconds": round(sum(r["wall_seconds"] for r in results) / len(results), 2),
            "runs": results,
        }
        print(f"{mode:9s} complete {complete}/{len(results)}  "
              f"mean steps {rows[mode]['mean_steps']}  "
              f"mean {rows[mode]['mean_wall_seconds']}s", flush=True)

    cfg = Config()
    result = {
        "backend": cfg.base_url,
        "model": cfg.model,
        "modes": rows,
        "delta": {
            "completion_rate": round(rows["plan_on"]["completion_rate"] - rows["plan_off"]["completion_rate"], 3),
            "mean_steps": round(rows["plan_on"]["mean_steps"] - rows["plan_off"]["mean_steps"], 2),
            "mean_wall_seconds": round(rows["plan_on"]["mean_wall_seconds"] - rows["plan_off"]["mean_wall_seconds"], 2),
        },
    }
    p = Path(out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(result, indent=2) + "\n")
    print(f"wrote {p}")
    return result
