"""Benchmark harness for the 40-point ROCm optimization story.

Measures time-to-first-token and tokens/sec across prompt sizes, writes
JSON results per backend/config so runs on the Mac and the Radeon box are
directly comparable in the demo video.
"""
from __future__ import annotations

import json
import platform
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .config import Config
from .privacy import mask_endpoint
from .llm import LLM

PROMPTS = {
    "short": "Explain what a race condition is in two sentences.",
    "medium": "Write a Python function that parses a CSV file and returns rows grouped by a key column, with error handling. Explain each part.",
    "long": "Review this design: a local RAG agent indexes a codebase with embeddings in SQLite, then answers questions with a ReAct loop over search/read/grep/test tools. Discuss failure modes, latency bottlenecks and how you would optimize inference on a single consumer GPU. Be thorough.",
}


def run(cfg: Config, label: str, repeats: int = 3, out_dir: Path | None = None) -> dict:
    llm = LLM(cfg)
    results: dict = {
        "label": label,
        "base_url": mask_endpoint(cfg.base_url),
        "model": cfg.model,
        "platform": platform.platform(),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "runs": {},
    }
    for name, prompt in PROMPTS.items():
        ttfts, tps = [], []
        for _ in range(repeats):
            r = llm.chat([{"role": "user", "content": prompt}], stream=True)
            gen_time = r.total_s - (r.ttft_s or 0)
            if r.completion_tokens and gen_time > 0:
                tps.append(r.completion_tokens / gen_time)
            if r.ttft_s:
                ttfts.append(r.ttft_s)
        results["runs"][name] = {
            "ttft_s_median": round(statistics.median(ttfts), 3) if ttfts else None,
            "chunks_per_s_median": round(statistics.median(tps), 1) if tps else None,
            "repeats": repeats,
        }
    out_dir = out_dir or Path("bench-results")
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"{label}.json"
    out_path.write_text(json.dumps(results, indent=2))
    return results


def run_concurrency(
    cfg: Config,
    label: str,
    levels: tuple[int, ...] = (1, 2, 4, 8),
    out_dir: Path | None = None,
) -> dict:
    """Aggregate throughput as concurrent requests scale.

    Single-stream tokens/sec understates a GPU: an agent fleet issues many
    ReAct steps at once, and vLLM batches them. This is the axis that shows
    whether the Radeon is saturated at concurrency 1 or has headroom.
    """
    llm = LLM(cfg)
    prompt = PROMPTS["medium"]
    results: dict = {
        "label": label,
        "base_url": mask_endpoint(cfg.base_url),
        "model": cfg.model,
        "platform": platform.platform(),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "axis": "concurrency",
        "runs": {},
    }
    for n in levels:
        start = time.perf_counter()
        with ThreadPoolExecutor(max_workers=n) as pool:
            futures = [
                pool.submit(llm.chat, [{"role": "user", "content": prompt}], True)
                for _ in range(n)
            ]
            outs = [f.result() for f in futures]
        wall = time.perf_counter() - start
        total_chunks = sum(o.completion_tokens for o in outs)
        results["runs"][f"concurrency_{n}"] = {
            "requests": n,
            "wall_s": round(wall, 2),
            "aggregate_chunks_per_s": round(total_chunks / wall, 1) if wall > 0 else None,
            "per_request_chunks_per_s": round(total_chunks / wall / n, 1) if wall > 0 else None,
            "ttft_s_median": round(statistics.median([o.ttft_s for o in outs if o.ttft_s]), 3)
            if any(o.ttft_s for o in outs)
            else None,
        }
    out_dir = out_dir or Path("bench-results")
    out_dir.mkdir(exist_ok=True)
    (out_dir / f"{label}.json").write_text(json.dumps(results, indent=2))
    return results


def run_prefill(
    cfg: Config,
    label: str,
    word_counts: tuple[int, ...] = (128, 512, 2048, 8192),
    out_dir: Path | None = None,
) -> dict:
    """Time-to-first-token against input length, i.e. prefill throughput.

    A codebase agent stuffs retrieved chunks into context, so prefill cost is
    the latency the user actually feels, not decode speed.
    """
    llm = LLM(cfg)
    filler = (
        "def handler(request, context):\n"
        "    result = validate(request)\n"
        "    return dispatch(result, context)\n"
    ).split()
    results: dict = {
        "label": label,
        "base_url": mask_endpoint(cfg.base_url),
        "model": cfg.model,
        "platform": platform.platform(),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "axis": "prefill",
        "runs": {},
    }
    for n_words in word_counts:
        body = " ".join(filler[i % len(filler)] for i in range(n_words))
        prompt = f"Here is code:\n{body}\nReply with the single word OK."
        ttfts = []
        for _ in range(3):
            r = llm.chat([{"role": "user", "content": prompt}], stream=True)
            if r.ttft_s:
                ttfts.append(r.ttft_s)
        results["runs"][f"prefill_{n_words}w"] = {
            "input_words": n_words,
            "ttft_s_median": round(statistics.median(ttfts), 3) if ttfts else None,
            "repeats": 3,
        }
    out_dir = out_dir or Path("bench-results")
    out_dir.mkdir(exist_ok=True)
    (out_dir / f"{label}.json").write_text(json.dumps(results, indent=2))
    return results


def compare(baseline_path: Path, candidate_path: Path) -> str:
    """Markdown table contrasting two bench-results runs, for the ROCm
    optimization writeup: same prompts, different backend/config, so the
    only variable is what changed.
    """
    baseline = json.loads(Path(baseline_path).read_text())
    candidate = json.loads(Path(candidate_path).read_text())

    def rate(run: dict) -> float | None:
        # decode runs report a per-stream median; concurrency runs report an
        # aggregate, and comparing those is the whole point of the axis.
        return run.get("chunks_per_s_median") or run.get("aggregate_chunks_per_s")

    # Union of both files in baseline order, so an axis with different keys
    # (concurrency_1.., prefill_128w..) compares as cleanly as the prompts do.
    names = list(baseline["runs"]) + [k for k in candidate["runs"] if k not in baseline["runs"]]
    if set(names) >= set(PROMPTS):
        names = [n for n in PROMPTS if n in names] + [n for n in names if n not in PROMPTS]

    lines = [
        f"| case | {baseline['label']} ttft (s) | {candidate['label']} ttft (s) | "
        f"{baseline['label']} chunks/s | {candidate['label']} chunks/s | speedup |",
        "|---|---|---|---|---|---|",
    ]
    for name in names:
        b = baseline["runs"].get(name, {})
        c = candidate["runs"].get(name, {})
        b_tps, c_tps = rate(b), rate(c)
        speedup = f"{c_tps / b_tps:.2f}x" if b_tps and c_tps else "n/a"
        lines.append(
            f"| {name} | {b.get('ttft_s_median', 'n/a')} | {c.get('ttft_s_median', 'n/a')} | "
            f"{b_tps or 'n/a'} | {c_tps or 'n/a'} | {speedup} |"
        )
    return "\n".join(lines)
