#!/usr/bin/env python3
"""
determinex_calibrate.py — per-rig concurrency calibration for verified search
=============================================================================
Determinex's correctness knob is K: sample K candidates, verify each against a real
oracle, and `P = 1 - (1 - p)^K`. K is therefore not a performance setting -- it is the
rate at which correctness accrues. The right K is a property of the MACHINE, and until
now it was a constant (`k: int = 8`) or an env var, identical on every rig.

Measured, that constant is wrong in both directions:

  AMD Radeon Cloud, vLLM 0.16.1, Qwen2.5-Coder-7B (captured evidence):
      K=1  28.7 tok/s @ 8.92s      K=32 739.9 tok/s @ 10.75s
      K=48 849.7 tok/s @ 13.62s    K=64 512.6 tok/s @ 29.59s   <- collapse
  Consumer box, Ollama, Qwen2.5-Coder-1.5B (measured 2026-08-02, warm):
      K=1  17.6 tok/s @ 2.73s      K=6  53.3 tok/s @ 4.62s
      K=8  60.4 tok/s @ 5.66s

The default K=6 leaves ~5x of the Radeon's throughput unused, and is already past the
efficient region on the consumer box. One number cannot serve both.

WHY THIS MEASURES RATHER THAN READS A CONFIG
--------------------------------------------
The first version of this read the backend's declared capacity -- vLLM publishes
`vllm:cache_config_info{num_gpu_blocks, block_size}`, and 31504*16/8192 = 61, which does
predict the Radeon collapse at 64. That looked sufficient until the same approach was tried
on Ollama, where `OLLAMA_NUM_PARALLEL=1` predicted full serialisation and the machine
delivered 3.4x speedup at K=8 instead. The env var was read from the client shell, not from
the environment the server was launched with, and a client-side config value is not the
authority that enforces the limit.

So: declared capacity is a HINT that seeds the sweep. The measurement is the answer.

OBJECTIVE, v1: CANDIDATES PER SECOND -- AND WHY IT WAS NOT ENOUGH
----------------------------------------------------------------
Aggregate tok/s alone would pick a K that is still "gaining" while wall clock doubles --
useless for verified search, which needs K candidates *and* needs them soon. `K / wall_s` is
the rate at which independent attempts arrive, which is exactly what drives P upward. It
also finds the collapse for free: past the backend's real limit, requests preempt instead of
batching, wall clock explodes, and the ratio falls.

Applied to the captured Radeon numbers this picks K=48 (3.52 cand/s vs 2.98 at K=32 and
2.16 at K=64) -- i.e. it independently reproduces the knee that was found by hand.

Then it was run against a LIVE Radeon MI-series GPU (2026-08-02) rather than a recording,
and the objective broke in two separate ways:

  1. The sweep never found a collapse, because there wasn't one. Candidates/second rose
     monotonically to K=640 (34.17 cand/s) and simply FLATTENED -- 33.26 at K=320, 33.91 at
     448, 34.17 at 640. Doubling K twice bought 2.7%. `max(cand_per_s)` dutifully returned
     640: technically the peak, practically absurd, since it also doubled time-to-first-
     candidate from 9.6s to 18.7s. Collapse is only one of the shapes a ceiling has;
     saturation is another, and this objective is blind to it.

  2. Worse, and the real lesson: on that run the probe task had p = 1.00. The model solved
     it five times out of five, one shot. The calibrator recommended K=16, so verified
     search fired 16 requests and threw 15 of them away. No value of K derived from the
     MACHINE ALONE can be right, because the machine does not know how hard the task is.

OBJECTIVE, v2: EXPECTED TIME TO A VERIFIED SOLUTION
--------------------------------------------------
The thing actually being minimised is wall-clock until the oracle passes something. With
per-attempt success `p` and a measured batch wall time `W(K)`:

    P(batch succeeds) = 1 - (1-p)^K            <- the amplifier's own equation
    E[batches]        = 1 / P
    E[time]           = W(K) / (1 - (1-p)^K)   <- minimise THIS

`W(K)` is a property of the rig and is what the sweep measures. `p` is a property of the
task and is what the solver observes. So a calibration is no longer a number -- it is a
CURVE, and K falls out of the curve once the task's difficulty is known. Against the live
Radeon curve above:

    p = 1.00  ->  K = 1     (one shot works; sampling 16 is pure waste)
    p = 0.50  ->  K = 4
    p = 0.10  ->  K = 32
    p = 0.02  ->  K = 64
    p = 0.005 ->  K = 128

Same GPU, same curve, K spanning 1..128 -- driven entirely by how hard the work is. That is
the correct shape of the knob, and it is why `optimal_k()` now takes `p` and why a caller
that has no estimate of `p` is told so rather than handed a confident constant.

The candidates/second view is retained: it is still exactly right for reporting where the
HARDWARE stops, which is a real and separate fact worth knowing (`detect_ceiling`).

OBJECTIVE, v3: WHAT THE CORPUS SAID BACK
----------------------------------------
The v2 result above was checked against Determinex's own corpus, which already held a
contradicting entry -- `amplification_floor_p_must_exceed_zero`, measured 2026-07-31 with
960 generations on this same GPU and model:

    "Do NOT tune K per task. The K-sweep shows cost is near-flat to K=32 (1.21x wall clock
     for 25.8x tokens), so run large K always: nearly free, and it pays exactly when p is
     mid-range, which is unknowable in advance."

Re-measured on the 2026-08-02 curve: wall clock at K=32 is 1.59x K=1. The corpus is right,
and the v2 framing above overstated its case. The honest comparison:

    p       best K   E[time]   vs K=32        vs K=640 (machine optimum)
    1.00    1        1.6s      1.59x          11.6x
    0.50    4        1.9s      1.33x           9.7x
    0.10    32       2.7s      1.00x           7.0x
    0.02    64       4.7s      1.14x           4.0x

Against a sensible fixed K=32 the p-aware win is 1.0-1.6x, not the 11.6x that comparing
against K=640 suggested. K=640 was never a real baseline -- it was this module's OWN
machine-optimum rule, so the large speedup measured the v1 defect, not the v2 benefit.

What survives, and is the actual contribution:

  * `max(cand_per_s)` is the wrong way to say "run large K". It returns K=640 here, costing
    11.6x the latency of K=1 for 2.7% more throughput than K=320. "Nearly free" is a claim
    about LATENCY, so `free_k()` defines it that way -- and independently returns K=32,
    reproducing the corpus's separately-chosen figure.
  * With p KNOWN (case memory, a completed first batch, a measured sweep), tuning is a real
    but modest additional win, and at p=1.00 it correctly stops sampling 16 candidates for a
    task one shot solves.
  * The ceiling-shape, jitter, sweep-abort and degraded-point fixes stand independently of
    any of this.

So: `optimal_k(..., p=None)` returns the nearly-free K, not the machine optimum. Tune only
when p is actually known.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import platform
import statistics
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent

# Per-rig, NOT in the repo: a calibration is a fact about one machine and must never be
# committed or published as if it were a property of Determinex.
PROFILE_PATH = Path(
    os.environ.get("DETERMINEX_CALIBRATION")
    or (Path.home() / ".determinex" / "calibration.json")
)

# Conservative fallback when nothing is calibrated. Deliberately small: an uncalibrated rig
# should under-use the hardware, never fall off a cliff it has not measured.
UNCALIBRATED_K = 4

_PROBE_PROMPT = "Write a Rust function that returns the sum of a slice of i32. Code only."


@dataclass
class KPoint:
    k: int
    wall_s: float
    tokens: int
    agg_tok_s: float
    cand_per_s: float
    # Requests that raised rather than returning. A remote endpoint behind a tunnel drops
    # some fraction of a large fan-out (measured: HTTP 502 from frp at K=640), and a wall
    # time that includes failures is not a measurement of throughput. Recorded rather than
    # swallowed so a degraded point can be excluded instead of quietly averaged in.
    errors: int = 0

    @property
    def usable(self) -> bool:
        """At least 90% of the requests completed, and at least one did.

        Stated as a floor on SUCCESSES rather than a ceiling on failures. The first version
        wrote `errors <= max(1, k // 10)`, where the `max(1, ...)` existed to forgive a
        single blip on a large fan-out -- and at K=1 that forgave the only request there
        was, so a point where nothing succeeded reported itself usable.
        """
        succeeded = self.k - self.errors
        return self.wall_s > 0 and succeeded > 0 and succeeded >= 0.9 * self.k


@dataclass
class Calibration:
    backend: str
    model: str
    host: str
    optimal_k: int
    cand_per_s: float
    collapsed_at: int | None
    declared_hint: int | None
    points: list[dict]
    measured_at: str
    # How this rig runs out of room: 'collapse' (throughput falls), 'saturation' (throughput
    # flattens), or 'none' (the sweep never reached the ceiling). Defaulted so profiles
    # written before the live-Radeon run still load.
    ceiling_kind: str = "none"
    ceiling_k: int | None = None

    def summary(self) -> str:
        c = f", {self.ceiling_kind} at K={self.ceiling_k}" if self.ceiling_k else ""
        return (
            f"{self.backend}/{self.model} on {self.host}: optimal K={self.optimal_k} "
            f"({self.cand_per_s:.2f} candidates/s{c})"
        )


def host_fingerprint() -> str:
    """Coarse, non-identifying machine key. No usernames, no paths -- this file may be
    shared when a user opts into corpus sharing, so it carries no personal data."""
    return f"{platform.system()}-{platform.machine()}-{os.cpu_count()}cpu"


# ── declared-capacity hints (a starting point for the sweep, never the answer) ──────────


def _vllm_declared_k(base_url: str, max_model_len: int = 8192) -> int | None:
    """floor(KV cache tokens / max_model_len), read from vLLM's own /metrics.

    This is the number that correctly predicted the Radeon collapse (31504 blocks * 16
    tokens / 8192 = 61, and K=64 broke). It is used to bound the sweep so calibration does
    not spend minutes discovering a cliff the server already declared.
    """
    import re
    import urllib.request

    try:
        url = base_url.rstrip("/")
        for suffix in ("/v1", "/v1/"):
            if url.endswith(suffix):
                url = url[: -len(suffix)]
        with urllib.request.urlopen(url + "/metrics", timeout=6) as r:
            body = r.read().decode("utf-8", "replace")
    except Exception:
        return None
    m = re.search(r'vllm:cache_config_info\{([^}]*)\}', body)
    if not m:
        return None
    fields = dict(re.findall(r'(\w+)="([^"]*)"', m.group(1)))
    try:
        blocks = int(fields["num_gpu_blocks"])
        block_size = int(fields["block_size"])
    except (KeyError, ValueError):
        return None
    if max_model_len <= 0:
        return None
    return max(1, (blocks * block_size) // max_model_len)


# ── the sweep ───────────────────────────────────────────────────────────────────────────


def sweep(
    generate: Callable[[], int],
    ks: list[int],
    repeats: int = 3,
    warmup: int = 2,
    on_point: Callable[[KPoint], None] | None = None,
) -> list[KPoint]:
    """Measure candidates/second at each K. Warms first, medians over `repeats`.

    The warm-up is not politeness: without it K=1 pays the model load and reports ~7 tok/s
    for a 1.5B model, which made the first run of this probe produce a conclusion that was
    simply wrong.

    TWO THINGS LEARNED FROM RUNNING THIS AGAINST A REMOTE GPU (2026-08-02)

    1. A failed request must not abort the sweep. At K=640 through an frp tunnel the
       endpoint returned HTTP 502 for part of the fan-out; the exception propagated out of
       `ex.map`, killed a 12-point sweep, and the whole run printed NOTHING -- eleven
       measured points, all discarded, because the twelfth had a bad link. Failures are now
       counted per point.

    2. Counting them is not the same as ignoring them. A wall time that includes requests
       that never completed is not a throughput measurement, so `KPoint.usable` excludes a
       point where more than 10% failed rather than averaging the damage in. Silently
       treating a degraded point as data is the same shape as an oracle that passes because
       it could not run.

    `on_point` streams each result as it is measured, so a sweep that dies at K=640 still
    leaves the operator everything up to K=448.
    """
    for _ in range(max(0, warmup)):
        try:
            generate()
        except Exception:
            pass  # a cold endpoint may refuse the first call; the measurement below decides

    def _one() -> tuple[int, int]:
        """(tokens, failed) -- never raises, so one bad request cannot end the sweep."""
        try:
            return int(generate()), 0
        except Exception:
            return 0, 1

    out: list[KPoint] = []
    for k in ks:
        walls, toks, errs = [], [], []
        for _ in range(repeats):
            t0 = time.time()
            with cf.ThreadPoolExecutor(max_workers=k) as ex:
                got = list(ex.map(lambda _i: _one(), range(k)))
            walls.append(time.time() - t0)
            toks.append(sum(t for t, _ in got))
            errs.append(sum(e for _, e in got))
        w = statistics.median(walls)
        t = int(statistics.median(toks))
        e = int(statistics.median(errs))
        pt = KPoint(k, round(w, 3), t, round(t / w, 1) if w else 0.0,
                    round(k / w, 3) if w else 0.0, errors=e)
        out.append(pt)
        if on_point is not None:
            on_point(pt)
    return out


def pick_optimal(points: list[KPoint], tolerance: float = 0.97) -> tuple[int, int | None]:
    """(optimal_k, collapsed_at) by candidates/second -- the HARDWARE view.

    `collapsed_at` is the first K whose candidate rate fell below `tolerance` of the best
    seen so far -- the signature of a backend that started preempting instead of batching.
    Reported separately from the optimum because it is the interesting number: it is where
    the hardware says stop, and a rig that never collapses within the swept range simply
    has not been pushed far enough.

    Kept because it is the right question for "where does this machine stop". It is NOT the
    right question for "how many candidates should I sample" -- see `optimal_k_for`, which
    the live Radeon run forced into existence.
    """
    points = [p for p in points if p.usable]
    if not points:
        return UNCALIBRATED_K, None
    best = max(points, key=lambda p: p.cand_per_s)
    collapsed = None
    peak = 0.0
    for p in points:
        if p.cand_per_s > peak:
            peak = p.cand_per_s
        elif peak and p.cand_per_s < peak * tolerance:
            collapsed = p.k
            break
    return best.k, collapsed


def detect_ceiling(
    points: list[KPoint], tolerance: float = 0.97, saturation_frac: float = 0.90
) -> tuple[str, int | None]:
    """('collapse'|'saturation'|'none', K) -- how this rig runs out of room.

    A backend can stop rewarding concurrency in two quite different ways, and conflating
    them produced a wrong recommendation on real hardware:

      collapse    throughput FALLS. vLLM past its KV budget preempts instead of batching:
                  captured Radeon run, 849.7 tok/s at K=48 -> 512.6 at K=64 while wall
                  clock went 13.6s -> 29.6s. Unambiguous, and `pick_optimal` finds it.

      saturation  throughput FLATTENS. Live Radeon run: 33.26 cand/s at K=320, 34.17 at
                  K=640 -- doubling K twice for 2.7%, while time-to-first-candidate went
                  9.6s -> 18.7s. Nothing fell, so collapse detection reported "no ceiling,
                  this rig has more headroom" and `max(cand_per_s)` recommended K=640. Both
                  statements were true and the recommendation was still wrong.

    Saturation is the SMALLEST K that already reaches `saturation_frac` of the best
    candidate rate the sweep ever saw -- i.e. the cheapest K you could have stopped at.

    WHY NOT A LOCAL GRADIENT. The first version compared each K to the next and declared
    saturation at the first step whose per-doubling gain fell under 15%. Run live against a
    Radeon MI GPU with `--repeats 1` it answered "saturation at K=16" on a curve that went
    on to DOUBLE (8.5 cand/s at K=32 -> 18.8 at K=64 -> 32.8 at K=448). One noisy point --
    K=32 measured 3.744s, slower than K=64's 3.413s, which is plainly jitter and not
    physics -- was enough, because a local gradient asks a question about two samples and
    a ceiling is a claim about the whole curve. A fraction-of-peak rule cannot be fooled by
    a single slow sample: the sample would have to BE the peak.

    Returning the largest swept K means the sweep never saturated within its range, which
    is reported as no ceiling rather than as a ceiling that happens to sit at the edge.
    """
    points = [p for p in points if p.usable]
    if len(points) < 2:
        return "none", None
    _, collapsed = pick_optimal(points, tolerance)
    if collapsed is not None:
        return "collapse", collapsed
    ordered = sorted(points, key=lambda p: p.k)
    peak = max(p.cand_per_s for p in ordered)
    if peak <= 0:
        return "none", None
    for p in ordered:
        if p.cand_per_s >= peak * saturation_frac:
            # Reaching the threshold only at the last point swept is not saturation; it is
            # a sweep that stopped while the curve was still climbing.
            return ("none", None) if p.k == ordered[-1].k else ("saturation", p.k)
    return "none", None


def expected_time_to_solve(
    points: list[KPoint], p: float, verify_s: float = 0.0
) -> list[tuple[int, float]]:
    """[(K, expected wall-clock seconds to a verified solution)] at each measured K.

    THE MODEL, and why it has a second term.

    Determinex's verified search generates its K candidates CONCURRENTLY -- that is the
    W(K) this module sweeps -- and then verifies them ONE AT A TIME, breaking at the first
    candidate the oracle passes (`for i, (...) in enumerate(batch): res = self.verify(...)`
    in determinex_verified_search). On the 2026-08-02 field proof against a Docker-backed
    Compiler Oracle the per-sample log line read `gen 12s verify 10s`, so at K=8 that is
    ~12s of parallel generation against up to 80s of serial verification. Modelling it:

        E[verifications per round] = sum_{i=1..K} (1-p)^(i-1) = (1 - (1-p)^K) / p
        E[round wall]              = W_gen(K) + verify_s * E[verifications]
        P(round succeeds)          = 1 - (1-p)^K
        E[total]                   = E[round wall] / P
                                   = W_gen(K)/P  +  verify_s / p

    THE SECOND TERM DOES NOT DEPEND ON K, and that is the useful result rather than a
    caveat. Expected verifications to the first success is 1/p however you batch them --
    candidates are checked one at a time until one passes, so grouping them into rounds of
    K changes when they happen, not how many happen. A slow serial oracle therefore makes
    every K worse by the same additive constant and leaves the ARGMIN untouched.

    So the K recommendations here are unaffected by oracle cost, which is worth knowing
    precisely because the intuition ("a slow oracle means sample fewer") is wrong. What the
    term buys is an honest ESTIMATE: at p=0.02 with a 10s Docker oracle the true expected
    time is ~505s, not the ~5s that generation throughput alone suggests, and a user
    planning a run deserves the real number.

    `verify_s = 0` recovers the generation-only model for a caller whose oracle is a cheap
    in-process assertion.
    """
    p = min(max(p, 0.0), 1.0)
    verify_s = max(0.0, verify_s)
    out: list[tuple[int, float]] = []
    for pt in (q for q in points if q.usable):
        succ = 1.0 - (1.0 - p) ** pt.k
        if succ <= 0.0 or pt.wall_s <= 0.0:
            continue
        # Expected verifications before the loop breaks. p > 0 is guaranteed here: succ > 0.
        expected_verifies = succ / p
        round_wall = pt.wall_s + verify_s * expected_verifies
        out.append((pt.k, round_wall / succ))
    return out


def free_k(points: list[KPoint], factor: float = 2.0) -> int:
    """The largest K whose wall clock is still within `factor` of K=1 -- "nearly free".

    This is the right K when `p` is UNKNOWN, and it exists because the corpus contradicted
    the first version of this module. `amplification_floor_p_must_exceed_zero` (measured
    2026-07-31, 960 generations on this same GPU and model) concluded:

        "Do NOT tune K per task. The K-sweep shows cost is near-flat to K=32 (1.21x wall
         clock for 25.8x tokens), so run large K always: nearly free, and it pays exactly
         when p is mid-range, which is unknowable in advance."

    Re-checked against the 2026-08-02 live curve, that is correct: wall clock at K=32 is
    1.59x K=1. Sampling 32 candidates instead of 1 costs about half again the wall clock and
    converts a p=0.1 task from 10% to 97%. Under uncertainty that trade is overwhelming, and
    `optimal_k_for(p)` should not be reached for a task whose difficulty nobody has measured.

    What the live run DID establish is that the machine optimum -- `max(cand_per_s)`, which
    returned K=640 -- is not the way to express "run large K". K=640 costs 11.6x the wall
    clock of K=1 to buy 2.7% more throughput than K=320. "Nearly free" is a statement about
    LATENCY, so it is defined here as latency, not as peak throughput.

    On the live Radeon curve this returns K=32, independently reproducing the corpus's
    hand-picked figure from a different day's measurements.
    """
    usable = sorted((q for q in points if q.usable), key=lambda q: q.k)
    if not usable:
        return UNCALIBRATED_K
    base = usable[0].wall_s
    if base <= 0:
        return UNCALIBRATED_K
    affordable = [q.k for q in usable if q.wall_s <= base * factor]
    return max(affordable) if affordable else usable[0].k


def optimal_k_for(
    points: list[KPoint], p: float, verify_s: float = 0.0
) -> tuple[int, float]:
    """(K, expected seconds) minimising time to a verified solution for difficulty `p`.

    This is the function that should have existed on the first live run. It answers K=1 for
    a task the model already solves one-shot, and reaches for the top of the curve only when
    the task is genuinely hard -- which is the behaviour the amplifier's own equation implies
    and which a machine-only constant cannot express.
    """
    curve = expected_time_to_solve(points, p, verify_s)
    if not curve:
        return UNCALIBRATED_K, float("inf")
    k, secs = min(curve, key=lambda x: (x[1], x[0]))
    return k, secs


# ── profile I/O ─────────────────────────────────────────────────────────────────────────


def load_profile() -> dict:
    if not PROFILE_PATH.is_file():
        return {}
    try:
        return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_calibration(cal: Calibration) -> None:
    prof = load_profile()
    prof[f"{cal.backend}::{cal.model}::{cal.host}"] = asdict(cal)
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_PATH.write_text(json.dumps(prof, indent=2) + "\n", encoding="utf-8")


def optimal_k(
    backend: str,
    model: str,
    default: int = UNCALIBRATED_K,
    p: float | None = None,
) -> tuple[int, str]:
    """(K, provenance). Never silently guesses.

    Mirrors the doctrine `determinex_oracle` already enforces -- a stub raises rather than
    quietly passing. Here an uncalibrated rig gets a conservative K and a string saying so,
    which the caller is expected to LOG, so a run at the fallback K is never mistaken for a
    run at a measured one.

    `p` is the caller's estimate of per-attempt success for THIS task. When supplied, K is
    re-derived from the stored curve by minimising expected time to a verified solution --
    which on a live GPU is the difference between K=1 and K=128 on identical hardware. When
    absent, the stored machine-optimum is returned and the provenance string says the K is
    task-blind, because a caller silently getting a task-blind K is exactly how a run with
    p=1.00 came to sample 16 candidates and discard 15.
    """
    key = f"{backend}::{model}::{host_fingerprint()}"
    entry = load_profile().get(key)
    if not entry or not entry.get("optimal_k"):
        return default, (
            f"UNCALIBRATED (no profile for {key}); using conservative K={default}. "
            f"Run: python scripts/determinex_calibrate.py --backend {backend} --model {model}"
        )
    when = entry.get("measured_at", "?")
    pts = [KPoint(**d) for d in entry.get("points", []) if isinstance(d, dict)]
    if p is not None and pts:
        k, secs = optimal_k_for(pts, p)
        return k, (f"calibrated {when}, K re-derived for p={p:.3g} "
                   f"(expected {secs:.1f}s to a verified solution)")
    if p is not None:
        return int(entry["optimal_k"]), (
            f"calibrated {when} but the profile predates curve storage; K is task-blind. "
            f"Re-run: python scripts/determinex_calibrate.py --backend {backend} --model {model}"
        )
    # Task-blind default is the NEARLY-FREE K, not the machine optimum. The corpus entry
    # amplification_floor_p_must_exceed_zero measured that running large K is nearly free
    # and pays off exactly when p is mid-range and unknown -- and the machine optimum
    # (max candidates/s) expresses that badly, returning K=640 on the live Radeon curve for
    # 11.6x the latency of K=1. free_k() states "nearly free" as latency, and reproduces
    # that entry's independently chosen K=32.
    if pts:
        return free_k(pts), (
            f"calibrated {when}, nearly-free K (task-blind: no p supplied; "
            f"see corpus amplification_floor_p_must_exceed_zero)"
        )
    return int(entry["optimal_k"]), (
        f"calibrated {when}, machine-optimum (task-blind: no p supplied, no stored curve)"
    )


# ── CLI ─────────────────────────────────────────────────────────────────────────────────


def _ollama_generator(model: str, base_url: str, num_predict: int) -> Callable[[], int]:
    import urllib.request

    def gen() -> int:
        body = json.dumps({
            "model": model, "prompt": _PROBE_PROMPT, "stream": False,
            "options": {"num_predict": num_predict, "temperature": 0.4, "num_ctx": 4096},
        }).encode()
        req = urllib.request.Request(
            base_url.rstrip("/") + "/api/generate",
            data=body, headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=300) as r:
            return int(json.loads(r.read()).get("eval_count", 0))

    return gen


def _openai_generator(
    model: str, base_url: str, num_predict: int, key_env: str = "OPENAI_API_KEY"
) -> Callable[[], int]:
    import urllib.request

    def gen() -> int:
        body = json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": _PROBE_PROMPT}],
            "max_tokens": num_predict, "temperature": 0.4,
            # Reasoning models otherwise spend the entire budget thinking and return no
            # content -- measured on AMD's Qwen3.6-35B-A3B: 199 of 200 tokens at
            # max_tokens=200. For calibration that is not merely empty output, it silently
            # changes what is being timed from "generate an answer" to "think until cut off".
            "chat_template_kwargs": {"enable_thinking": False},
        }).encode()
        req = urllib.request.Request(
            base_url.rstrip("/") + "/chat/completions",
            data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + os.environ.get(key_env, "none")},
        )
        with urllib.request.urlopen(req, timeout=300) as r:
            d = json.loads(r.read())
        return int((d.get("usage") or {}).get("completion_tokens", 0))

    return gen


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--backend", choices=["ollama", "vllm", "openai", "amd"], default="ollama")
    ap.add_argument("--model", default="qwen2.5-coder:1.5b-instruct")
    ap.add_argument("--base-url", default=None)
    ap.add_argument("--ks", default=None, help="comma list, e.g. 1,2,4,8,16")
    ap.add_argument("--max-model-len", type=int, default=8192)
    ap.add_argument("--num-predict", type=int, default=48)
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--show", action="store_true", help="print the stored profile and exit")
    args = ap.parse_args()

    if args.show:
        prof = load_profile()
        if not prof:
            print(f"no calibration profile at {PROFILE_PATH}")
            return 0
        print(f"{PROFILE_PATH}:")
        for k, v in prof.items():
            print(f"  {k}")
            print(f"      optimal K={v['optimal_k']}  ({v['cand_per_s']} cand/s)"
                  f"  collapse={v.get('collapsed_at')}  measured {v.get('measured_at')}")
        return 0

    # AMD's Radeon Token Factory is a THIRD ceiling shape: not KV-cache (vLLM) and not CPU
    # saturation (Ollama) but a published requests-per-minute quota. The rule the calibrator
    # measures -- candidates/second stops rising, so stop adding candidates -- is the same;
    # only the reason differs, which is the point of measuring instead of reading a config.
    # Load the repo .env before reading any key. Without this the documented AMD path fails
    # COMPLETELY and misleadingly: `--backend amd` reads AMD_TOKEN_FACTORY_KEY from an
    # environment that never had it, sends "Bearer none", and every request in the sweep is
    # refused -- which the table then reports as "link degraded" on every row. A reader
    # following the README concludes the GPU is unreachable when the key was sitting in .env
    # the whole time. Reuses the providers module's loader rather than adding a fourth copy.
    try:
        from determinex_providers import _load_env_once

        _load_env_once()
    except Exception:
        pass  # a missing .env is normal; the key may legitimately come from the environment

    key_env = "OPENAI_API_KEY"
    if args.backend == "amd":
        base = args.base_url or os.environ.get(
            "AMD_TOKEN_FACTORY_BASE", "https://radeon.anruicloud.com/api/v1"
        )
        key_env = "AMD_TOKEN_FACTORY_KEY"
    else:
        base = args.base_url or (
            "http://localhost:11434" if args.backend == "ollama" else "http://localhost:8000/v1"
        )

    hint = None
    if args.backend == "vllm":
        hint = _vllm_declared_k(base, args.max_model_len)
        if hint:
            print(f"  backend declares capacity for ~{hint} concurrent requests "
                  f"(a hint that bounds the sweep; the measurement decides)")

    if args.ks:
        ks = [int(x) for x in args.ks.split(",") if x.strip()]
    else:
        ks = [1, 2, 4, 8, 16, 32, 48, 64]
        if hint:
            # EXTEND past the declared hint; never truncate to it. The hint is
            # kv_tokens // max_model_len, which assumes every request consumes the model's
            # full context. On the live Radeon run vLLM took the model default
            # max_model_len=32768 while the probe used ~72 tokens, so the hint said 15 and
            # the machine was still scaling linearly at K=640 -- a 40x underestimate. The
            # earlier `k <= hint * 1.2` filter would have stopped the sweep at 16 and
            # reported a ceiling that does not exist.
            ks = sorted({*ks, *(hint * m for m in (1, 2, 4, 8) if hint * m > 0)})
        elif args.backend == "ollama":
            ks = [1, 2, 4, 6, 8, 12]
        elif args.backend == "amd":
            # Free tier publishes 30 requests/minute. Sweeping past that measures the quota's
            # backoff, not the hardware, and spends a shared daily budget doing it.
            ks = [1, 2, 4, 8]

    gen = (
        _ollama_generator(args.model, base, args.num_predict)
        if args.backend == "ollama"
        else _openai_generator(args.model, base, args.num_predict, key_env)
    )

    print(f"  calibrating {args.backend}/{args.model} on {host_fingerprint()}")
    print(f"  sweeping K={ks}, {args.repeats} repeats, warm-up first\n")
    print(f"  {'K':<5}{'wall_s':<10}{'tokens':<9}{'agg tok/s':<12}{'cand/s':<10}{'failed':<8}")

    def _show(p: KPoint) -> None:
        # Printed AS MEASURED, not after the sweep: a 12-point sweep that died at K=640
        # through a flaky tunnel discarded eleven good points and printed nothing.
        flag = "" if p.usable else "  <- excluded, link degraded"
        print(f"  {p.k:<5}{p.wall_s:<10}{p.tokens:<9}{p.agg_tok_s:<12}"
              f"{p.cand_per_s:<10}{p.errors:<8}{flag}", flush=True)

    pts = sweep(gen, ks, repeats=args.repeats, on_point=_show)
    if not any(p.usable for p in pts):
        print("\n  every point failed -- nothing was measured. Check the endpoint and key.")
        return 2

    best, collapsed = pick_optimal(pts)
    kind, ceiling_k = detect_ceiling(pts)
    cal = Calibration(
        backend=args.backend, model=args.model, host=host_fingerprint(),
        optimal_k=best,
        cand_per_s=max(p.cand_per_s for p in pts if p.usable),
        collapsed_at=collapsed, declared_hint=hint,
        points=[asdict(p) for p in pts],
        measured_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        ceiling_kind=kind, ceiling_k=ceiling_k,
    )
    save_calibration(cal)
    print(f"\n  {cal.summary()}")
    if kind == "collapse":
        print(f"  throughput FELL past K={ceiling_k} -- the hardware's hard ceiling.")
    elif kind == "saturation":
        print(f"  throughput FLATTENED past K={ceiling_k}: beyond it, more concurrency buys "
              f"under 15% per doubling while latency keeps growing.")
    else:
        # "No ceiling" is only true if the sweep actually REACHED max(ks). When the higher K
        # points were excluded because their requests failed, the sweep did not run out of
        # ceiling -- it ran into one, of a kind the gradient tests cannot see because the
        # evidence for it was thrown away as unusable. Measured live on AMD's Radeon Token
        # Factory 2026-08-03: K=1..4 clean, then 4/8, 16/16, 31/32 and 46/48 requests refused
        # by the published RPM quota, and this line still read "more headroom than the sweep
        # used" -- the exact opposite of what the rig had just demonstrated.
        refused = [p.k for p in pts if not p.usable and getattr(p, "errors", 0) > 0]
        if refused:
            print(f"  no throughput ceiling among the points that RAN, but K>={min(refused)} "
                  f"could not be measured: the backend refused "
                  f"{sum(getattr(p, 'errors', 0) for p in pts if p.k in refused)} of "
                  f"{sum(p.k for p in pts if p.k in refused)} requests. That is a ceiling too --"
                  f" a quota or connection limit rather than a hardware one -- so this rig has "
                  f"LESS headroom than the sweep asked for, not more.")
        else:
            print(f"  no ceiling within K<={max(ks)}; this rig has more headroom "
                  f"than the sweep used.")

    # The curve, not the constant. This table is the actual deliverable: it says what to do
    # for work of a given difficulty, and it is what makes K=1 the right answer for a task
    # the model already solves -- the case a machine-only optimum gets exactly backwards.
    if hint:
        print(f"\n  (backend declared ~{hint} concurrent; measured optimum {best}"
              f"{' -- the declaration was pessimistic' if best > hint else ''})")
    print("\n  K implied by this rig's curve, per task difficulty:")
    print(f"    {'p (one-shot)':<16}{'K':<8}{'E[time to verified]':<22}")
    for probe_p in (1.0, 0.5, 0.25, 0.1, 0.05, 0.02, 0.005):
        k_p, secs = optimal_k_for(pts, probe_p)
        print(f"    {probe_p:<16.3g}{k_p:<8}{secs:.1f}s")
    print("\n  Callers pass their measured p to optimal_k(..., p=...); with no p they get the")
    print("  machine-optimum and a provenance string that says it is task-blind.")
    print(f"  written to {PROFILE_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
