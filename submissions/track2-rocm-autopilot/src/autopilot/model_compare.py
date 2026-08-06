"""Model comparison: fine-tuned Gemma 4 vs. the rest of the Gemma family.

Two axes, both measured: never guessed:
  - speed/energy: reuses bench_runner.run_benchmark against each model's
    live vLLM endpoint (tokens/s, TTFT, joules/token).
  - quality: an LLM-judge (itself a Gemma endpoint, injectable) scores
    each model's completions on datasets/confidential_drafting.jsonl
    against a fixed rubric (0-100), so results are comparable across models.

Writes runs/model_comparison.json: the file dashboard.html polls for the
"Model comparison" panel (datasets/model_comparison.sample.json is the
replay/demo equivalent, clearly illustrative until you run this for real).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Callable

import requests

from autopilot.bench_runner import run_benchmark as _default_bench_fn

DATASET = os.environ.get("BENCH_DATASET", "datasets/confidential_drafting.jsonl")
JUDGE_BASE_URL = os.environ.get("JUDGE_BASE_URL", "http://localhost:8000")
JUDGE_MODEL = os.environ.get("JUDGE_MODEL", "google/gemma-4-26B-A4B-it")
DEFAULT_CONCURRENCY = int(os.environ.get("COMPARE_CONCURRENCY", "8"))
SAMPLE_SIZE = int(os.environ.get("COMPARE_SAMPLE_SIZE", "6"))

RUBRIC = """Score the RESPONSE to the PROMPT from 0 to 100 on this rubric:
- Completeness: every requested section/point is present (0-40)
- Structure & register: follows the requested format exactly (0-20)
- Grounding: no invented facts beyond the source notes (0-25)
- Confidentiality discipline: respects anonymization/redaction instructions (0-15)
Reply with ONLY a JSON object: {"score": <0-100 integer>, "reason": "<one sentence>"}.

PROMPT:
{prompt}

RESPONSE:
{response}"""


def load_dataset(path: str = DATASET, sample_size: int = SAMPLE_SIZE) -> list[dict]:
    rows = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    # Stratified: spread the sample across the dataset's "class" field when present.
    if sample_size >= len(rows):
        return rows
    step = max(1, len(rows) // sample_size)
    return rows[::step][:sample_size]


def _default_complete_fn(base_url: str, model: str, prompt: str, max_tokens: int) -> str:
    r = requests.post(
        f"{base_url}/v1/chat/completions",
        json={"model": model, "messages": [{"role": "user", "content": prompt}],
              "temperature": 0.2, "max_tokens": max_tokens},
        timeout=120,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"].get("content", "")


def _default_judge_fn(prompt: str, response: str) -> dict:
    text = _default_complete_fn(JUDGE_BASE_URL, JUDGE_MODEL,
                                 RUBRIC.format(prompt=prompt, response=response), 200)
    text = text.strip().strip("`")
    text = text[text.find("{"): text.rfind("}") + 1]
    obj = json.loads(text)
    return {"score": float(obj["score"]), "reason": obj.get("reason", "")}


def evaluate_quality(entry: dict, dataset: list[dict],
                     complete_fn: Callable | None = None,
                     judge_fn: Callable | None = None) -> dict:
    """Average judge score for one model over the sampled dataset rows."""
    complete_fn = complete_fn or _default_complete_fn
    judge_fn = judge_fn or _default_judge_fn
    scores, per_class = [], {}
    for row in dataset:
        response = complete_fn(entry["base_url"], entry["model"], row["prompt"],
                               row.get("max_tokens", 512))
        verdict = judge_fn(row["prompt"], response)
        scores.append(verdict["score"])
        per_class.setdefault(row.get("class", "other"), []).append(verdict["score"])
    return {
        "quality_score": round(sum(scores) / len(scores), 1) if scores else 0.0,
        "quality_by_class": {k: round(sum(v) / len(v), 1) for k, v in per_class.items()},
        "n_samples": len(scores),
    }


def evaluate_model(entry: dict, dataset: list[dict], *,
                    bench_fn: Callable | None = None,
                    complete_fn: Callable | None = None,
                    judge_fn: Callable | None = None,
                    concurrency: int = DEFAULT_CONCURRENCY) -> dict:
    """Run both axes for one model entry: {label, model, base_url, finetuned}."""
    bench_fn = bench_fn or _default_bench_fn
    speed = bench_fn({"max_num_seqs": 256, "enable_prefix_caching": True,
                      "concurrency": concurrency}, base_url=entry["base_url"])
    if "error" in speed:
        result = {"label": entry["label"], "finetuned": entry.get("finetuned", False),
                  "error": speed["error"]}
    else:
        quality = evaluate_quality(entry, dataset, complete_fn=complete_fn, judge_fn=judge_fn)
        result = {
            "label": entry["label"],
            "finetuned": entry.get("finetuned", False),
            "tokens_per_s": speed["metrics"]["tokens_per_s"],
            "ttft_ms": speed["metrics"]["ttft_ms"],
            "joules_per_token": speed["energy"]["joules_per_token"],
            **quality,
        }
    result["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return result


def compare(entries: list[dict], *, dataset_path: str = DATASET, sample_size: int = SAMPLE_SIZE,
            bench_fn: Callable | None = None, complete_fn: Callable | None = None,
            judge_fn: Callable | None = None, concurrency: int = DEFAULT_CONCURRENCY) -> dict:
    dataset = load_dataset(dataset_path, sample_size)
    models = [evaluate_model(e, dataset, bench_fn=bench_fn, complete_fn=complete_fn,
                             judge_fn=judge_fn, concurrency=concurrency) for e in entries]
    return {
        "generated_ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "objective": {
            "quality_metric": f"LLM-judge rubric score (0-100) on {sample_size} sampled "
                              f"prompts from {dataset_path}",
            "speed_metric": f"tokens/s at concurrency={concurrency}, matched across models",
        },
        "models": models,
    }


def write_comparison(state: dict, directory: str = "runs") -> Path:
    out_dir = Path(directory)
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = out_dir / "model_comparison.json.tmp"
    tmp.write_text(json.dumps(state, indent=1))
    final = out_dir / "model_comparison.json"
    tmp.replace(final)
    return final


# Default lineup: our fine-tuned Gemma 4 against the rest of the Gemma family,
# all served from their own vLLM endpoint (edit base_url/model to your setup).
DEFAULT_ENTRIES = [
    {"label": "gemma-4-12B-it (fine-tuned, ours)", "model": "google/gemma-4-12B-it-ft",
     "base_url": "http://localhost:8000", "finetuned": True},
    {"label": "gemma-4-12B-it (base)", "model": "google/gemma-4-12B-it",
     "base_url": "http://localhost:8001", "finetuned": False},
    {"label": "gemma-3-27B-it", "model": "google/gemma-3-27b-it",
     "base_url": "http://localhost:8002", "finetuned": False},
    {"label": "gemma-3-12B-it", "model": "google/gemma-3-12b-it",
     "base_url": "http://localhost:8003", "finetuned": False},
    {"label": "gemma-2-27B-it", "model": "google/gemma-2-27b-it",
     "base_url": "http://localhost:8004", "finetuned": False},
]


if __name__ == "__main__":
    state = compare(DEFAULT_ENTRIES)
    path = write_comparison(state)
    print(f"wrote {path}\n{json.dumps(state, indent=1)}")
