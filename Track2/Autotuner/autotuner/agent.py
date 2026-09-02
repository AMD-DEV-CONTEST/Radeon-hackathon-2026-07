from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from autotuner.config import TuneConfig
from autotuner.models import Candidate, Proposal, Trial


class TuningAgent:
    def __init__(self, config: TuneConfig) -> None:
        self.config = config

    def propose(
        self,
        remaining: List[Candidate],
        history: List[Trial],
        active_model: str,
        allow_local_inference: bool = True,
    ) -> Proposal:
        if not remaining:
            raise ValueError("No candidates remain")
        shortlist = sorted(
            remaining,
            key=lambda item: self._acquisition_score(item, history),
            reverse=True,
        )[:24]
        if self.config.use_local_agent and allow_local_inference:
            local = self._ask_local_model(shortlist, history, active_model)
            if local:
                return local
        candidate = shortlist[0]
        return Proposal(
            candidate=candidate,
            hypothesis=self._heuristic_hypothesis(candidate, history),
            source="constraint aware heuristic",
        )

    def _ask_local_model(
        self,
        candidates: List[Candidate],
        history: List[Trial],
        active_model: str,
    ) -> Optional[Proposal]:
        candidate_rows = [
            {
                "candidate_key": candidate.key(),
                "configuration": candidate.to_dict(),
            }
            for candidate in candidates
        ]
        history_rows = [
            {
                "candidate_key": trial.candidate.key(),
                "configuration": trial.candidate.to_dict(),
                "tokens_per_second": round(
                    trial.result.tokens_per_second, 3
                ),
                "latency_p95_ms": round(trial.result.latency_p95_ms, 3),
                "error_rate": round(trial.result.error_rate, 4),
                "quality_score": round(trial.result.quality_score, 4),
                "accepted": trial.accepted,
            }
            for trial in history
        ]
        prompt = (
            "You are Autotuner, a performance engineer running locally on "
            "the AMD Radeon GPU that you are tuning. Choose exactly one "
            "candidate for the next controlled experiment. Maximize output "
            "tokens per second while respecting latency, error, and quality "
            "limits. Change as little as possible when evidence is weak. "
            "Return one JSON object with candidate_key and hypothesis. "
            "Do not return prose outside the JSON object.\n\n"
            + "Limits:\n"
            + json.dumps(
                {
                    "quality_floor": self.config.quality_floor,
                    "latency_limit_ms": self.config.latency_limit_ms,
                    "error_limit": self.config.error_limit,
                }
            )
            + "\n\nHistory:\n"
            + json.dumps(history_rows)
            + "\n\nAllowed candidates:\n"
            + json.dumps(candidate_rows)
        )
        payload = {
            "model": active_model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 220,
            "temperature": 0,
            "stream": False,
        }
        request = urllib.request.Request(
            self.config.endpoint + "/chat/completions",
            data=json.dumps(payload).encode("utf8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                body = json.loads(response.read().decode("utf8"))
            content = str(body["choices"][0]["message"]["content"])
            match = re.search(r"\{.*\}", content, re.DOTALL)
            if not match:
                return None
            decision = json.loads(match.group(0))
        except (
            OSError,
            urllib.error.URLError,
            json.JSONDecodeError,
            KeyError,
            IndexError,
            TypeError,
        ):
            return None
        lookup = {candidate.key(): candidate for candidate in candidates}
        selected = lookup.get(str(decision.get("candidate_key", "")))
        if not selected:
            return None
        hypothesis = str(decision.get("hypothesis", "")).strip()
        if not hypothesis:
            hypothesis = "The local model selected this controlled change."
        return Proposal(
            candidate=selected,
            hypothesis=hypothesis,
            source="local Radeon inference",
        )

    def _acquisition_score(
        self, candidate: Candidate, history: List[Trial]
    ) -> float:
        prior = (
            self._prior("attention_backend", candidate.attention_backend)
            + self._prior("kv_cache_dtype", candidate.kv_cache_dtype)
            + self._prior("max_num_seqs", candidate.max_num_seqs)
            + self._prior(
                "gpu_memory_utilization",
                round(candidate.gpu_memory_utilization, 2),
            )
            + self._prior(
                "num_speculative_tokens", candidate.num_speculative_tokens
            )
        )
        if not history:
            return prior
        accepted = [trial for trial in history if trial.accepted]
        if not accepted:
            accepted = history
        best = max(
            accepted, key=lambda trial: trial.result.tokens_per_second
        )
        factor_means = self._factor_means(accepted)
        evidence = 0.0
        novelty = 0.0
        for name, value in candidate.to_dict().items():
            key = (name, self._hashable(value))
            observations = factor_means.get(key, [])
            if observations:
                evidence += sum(observations) / len(observations)
            else:
                novelty += 1.0
        distance = sum(
            value != best.candidate.to_dict()[name]
            for name, value in candidate.to_dict().items()
        )
        controlled_change_bonus = 3.0 if distance == 1 else 0.0
        return evidence + prior + novelty * 0.7 + controlled_change_bonus

    def _factor_means(
        self, history: List[Trial]
    ) -> Dict[Tuple[str, Any], List[float]]:
        values: Dict[Tuple[str, Any], List[float]] = defaultdict(list)
        for trial in history:
            for name, value in trial.candidate.to_dict().items():
                values[(name, self._hashable(value))].append(
                    trial.result.tokens_per_second
                )
        return values

    @staticmethod
    def _hashable(value: Any) -> Any:
        if isinstance(value, (dict, list)):
            return json.dumps(value, sort_keys=True)
        return value

    @staticmethod
    def _prior(name: str, value: Any) -> float:
        priors = {
            "attention_backend": {
                "auto": 0.0,
                "ROCM_ATTN": 2.0,
                "TRITON_ATTN": 2.5,
                "ROCM_AITER_FA": 3.0,
                "ROCM_AITER_UNIFIED_ATTN": 3.5,
            },
            "kv_cache_dtype": {"auto": 0.0, "fp8": 2.5},
            "max_num_seqs": {4: 0.0, 8: 1.0, 16: 2.0, 32: 1.0},
            "gpu_memory_utilization": {
                0.82: 0.0,
                0.88: 0.8,
                0.9: 1.0,
                0.92: 1.2,
                0.95: 0.4,
            },
            "num_speculative_tokens": {0: 0.0, 2: 1.5, 4: 3.0, 6: 2.0},
        }
        return float(priors.get(name, {}).get(value, 0.0))

    @staticmethod
    def _heuristic_hypothesis(
        candidate: Candidate, history: List[Trial]
    ) -> str:
        if not history:
            return "Establish the stock serving baseline."
        best = max(
            history, key=lambda trial: trial.result.tokens_per_second
        )
        changed = [
            name
            for name, value in candidate.to_dict().items()
            if best.candidate.to_dict()[name] != value
        ]
        if len(changed) == 1:
            return (
                f"Measure whether changing {changed[0]} improves throughput "
                "without violating the quality and reliability limits."
            )
        return (
            "Explore a promising configuration selected from observed factor "
            "performance while preserving the declared safety limits."
        )
