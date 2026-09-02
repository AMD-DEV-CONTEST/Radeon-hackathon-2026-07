from __future__ import annotations

import itertools
import random
from typing import Any, Dict, Iterable, List

from autotuner.config import TuneConfig
from autotuner.models import Candidate


def _values(space: Dict[str, Any], name: str, default: Any) -> List[Any]:
    values = list(space.get(name, [default]))
    if not values:
        raise ValueError(f"Search dimension {name} cannot be empty")
    return values


def build_candidates(config: TuneConfig) -> List[Candidate]:
    space = config.search_space
    model_variants = _values(
        space,
        "model_variants",
        {"model": "Qwen/Qwen3-8B", "quantization": "none"},
    )
    dimensions: Iterable[Any] = itertools.product(
        [profile["name"] for profile in config.engines],
        model_variants,
        _values(space, "attention_backends", "auto"),
        _values(space, "kv_cache_dtypes", "auto"),
        _values(space, "max_num_seqs", 8),
        _values(space, "gpu_memory_utilizations", 0.9),
        _values(space, "max_model_lens", 4096),
        _values(space, "speculative_models", ""),
        _values(space, "num_speculative_tokens", 0),
    )
    candidates: List[Candidate] = []
    for (
        engine,
        variant,
        attention,
        kv_dtype,
        max_num_seqs,
        memory,
        max_model_len,
        speculative_model,
        speculative_tokens,
    ) in dimensions:
        if not speculative_model and int(speculative_tokens) != 0:
            continue
        if speculative_model and int(speculative_tokens) == 0:
            continue
        candidates.append(
            Candidate(
                engine=str(engine),
                model=str(variant["model"]),
                quantization=str(variant.get("quantization", "none")),
                attention_backend=str(attention),
                kv_cache_dtype=str(kv_dtype),
                max_num_seqs=int(max_num_seqs),
                gpu_memory_utilization=float(memory),
                max_model_len=int(max_model_len),
                speculative_model=str(speculative_model),
                num_speculative_tokens=int(speculative_tokens),
            )
        )
    if not candidates:
        raise ValueError("Search space produced no valid candidates")
    baseline = candidates[0]
    remaining = candidates[1:]
    random.Random(config.seed).shuffle(remaining)
    return [baseline] + remaining
