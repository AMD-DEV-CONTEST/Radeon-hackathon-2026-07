"""
Empirical Performance Metrology & Inter-process GPU Mutex.
Measures kernel throughput by generating from two isolated vte-server instances (official kernel vs. candidate kernel, both running the same fixed reference model) in an interleaved A/B order, using each response's own real GPU-measured decoding_speed_tps rather than client-side wall-clock timing. OS-level non-blocking file locks serialize this against any other GPU-bound optimizer work.
"""

import os
import statistics
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.optimizer.isolated_runner import REFERENCE_MODEL, IsolatedInstancePair, generate_at


class GPUSafetyLock:
    def __init__(self, lock_path: Optional[Path] = None):
        current_file = Path(__file__).resolve()
        project_root = current_file.parent.parent.parent
        self.lock_file = lock_path or (project_root / "cache" / "gpu_execution.lock")
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        self._handle: Optional[Any] = None

    def acquire(self) -> bool:
        try:
            self._handle = open(self.lock_file, "a+")
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self._handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except Exception:
            if self._handle:
                try:
                    self._handle.close()
                except Exception:
                    pass
                self._handle = None
            return False

    def release(self) -> None:
        if self._handle:
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
                self._handle.close()
            except Exception:
                pass
            self._handle = None


def _spread(values: List[float]) -> Dict[str, Any]:
    """median / p25 / p75 for one arm of the A/B.

    p25 and p75 are None below 2 samples, which callers read as
    "insufficient reps to judge significance" rather than as a flat
    result."""
    if not values:
        return {"median": 0.0, "p25": None, "p75": None, "n": 0}
    if len(values) < 2:
        return {"median": values[0], "p25": None, "p75": None, "n": 1}
    q = statistics.quantiles(values, n=4, method="inclusive")
    return {"median": statistics.median(values), "p25": q[0], "p75": q[2], "n": len(values)}


def _is_significant(ref: Dict[str, Any], cand: Dict[str, Any]) -> Optional[bool]:
    """Non-overlapping interquartile ranges => the delta is real.

    The same test Hyperloom's apply_and_bench applies before trusting a
    measured delta. Without it a fixed percentage threshold cannot tell a
    genuine small win from run-to-run noise: two byte-identical instances
    measured 0.37% apart on this hardware, so any "gain" inside that band
    is indistinguishable from nothing.

    Returns None when either arm has too few reps to have a spread."""
    if any(v is None for v in (ref.get("p25"), ref.get("p75"), cand.get("p25"), cand.get("p75"))):
        return None
    return (cand["p25"] > ref["p75"]) or (cand["p75"] < ref["p25"])


class BenchmarkMetrology:
    def measure_single_run(self, base_url: str, model_name: str, prompt_length: int = 128) -> float:
        messages = [
            {"role": "system", "content": "Benchmark test prompt."},
            {"role": "user", "content": "Hello " * (prompt_length // 2)}
        ]

        try:
            resp = generate_at(base_url, model_name, messages, temperature=0.0, max_tokens=64)
            return float(resp.get("usage", {}).get("decoding_speed_tps", 0.0))
        except Exception:
            return 0.0

    def run_interleaved_ab_benchmark(
        self, official_base_url: str, candidate_base_url: str,
        model_name: str = REFERENCE_MODEL, trials: int = 3,
    ) -> Dict[str, Any]:
        """Interleaves requests between the official and candidate isolated
        instances (order flips each trial) so any thermal throttling or
        clock-speed drift over the run's duration affects both sides
        roughly equally instead of biasing whichever side runs first/last.
        Each single-run rate is the server's own real decoding_speed_tps
        (see measure_single_run/generate_at), not a client-side estimate."""
        warmup_messages = [
            {"role": "system", "content": "Warmup prompt."},
            {"role": "user", "content": "Warmup message"}
        ]
        for _ in range(2):
            try:
                generate_at(official_base_url, model_name, warmup_messages, temperature=0.0, max_tokens=16)
                generate_at(candidate_base_url, model_name, warmup_messages, temperature=0.0, max_tokens=16)
            except Exception:
                pass

        ref_rates: List[float] = []
        cand_rates: List[float] = []

        for i in range(trials):
            if i % 2 == 0:
                r = self.measure_single_run(official_base_url, model_name)
                c = self.measure_single_run(candidate_base_url, model_name)
            else:
                c = self.measure_single_run(candidate_base_url, model_name)
                r = self.measure_single_run(official_base_url, model_name)

            if r > 0:
                ref_rates.append(r)
            if c > 0:
                cand_rates.append(c)

        ref_spread = _spread(ref_rates)
        cand_spread = _spread(cand_rates)
        med_ref = ref_spread["median"]
        med_cand = cand_spread["median"]
        speedup_pct = ((med_cand - med_ref) / med_ref * 100.0) if med_ref > 0 else 0.0

        return {
            "reference_tok_s": med_ref,
            "candidate_tok_s": med_cand,
            "speedup_pct": speedup_pct,
            "is_speedup": speedup_pct > 0.0,
            # None = too few reps to judge; False = inside the noise band;
            # True = the arms' interquartile ranges do not overlap.
            "significant": _is_significant(ref_spread, cand_spread),
            "reference_spread": ref_spread,
            "candidate_spread": cand_spread,
            "trials_count": trials,
        }

    def run_interleaved_ab_benchmark_pair(
        self, pair: IsolatedInstancePair, model_name: str = REFERENCE_MODEL, trials: int = 3,
    ) -> Dict[str, Any]:
        """Convenience wrapper for the common case: an already-entered
        IsolatedInstancePair for the kernel/candidate under test."""
        return self.run_interleaved_ab_benchmark(pair.official_base_url, pair.candidate_base_url, model_name, trials)
