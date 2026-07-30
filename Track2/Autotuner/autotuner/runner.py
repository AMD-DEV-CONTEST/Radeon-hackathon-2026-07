from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from autotuner.agent import TuningAgent
from autotuner.benchmark import run_benchmark
from autotuner.config import TuneConfig
from autotuner.hardware import inspect_hardware
from autotuner.mock import mock_benchmark
from autotuner.models import (
    BenchmarkResult,
    Candidate,
    Proposal,
    RunRecord,
    Trial,
    utc_now,
)
from autotuner.report import write_reports
from autotuner.server import ServerManager
from autotuner.space import build_candidates


Progress = Callable[[str], None]


def _acceptance(
    config: TuneConfig, result: object
) -> Tuple[bool, str]:
    benchmark = result
    reasons = []
    if benchmark.quality_score < config.quality_floor:
        reasons.append("quality score is below the floor")
    if benchmark.error_rate > config.error_limit:
        reasons.append("error rate exceeds the limit")
    if benchmark.latency_p95_ms > config.latency_limit_ms:
        reasons.append("latency exceeds the limit")
    return (not reasons, "; ".join(reasons))


def _write_partial(
    output_directory: Path,
    name: str,
    started_at: str,
    mode: str,
    hardware: object,
    config: TuneConfig,
    trials: List[Trial],
) -> None:
    payload = {
        "name": name,
        "started_at": started_at,
        "mode": mode,
        "hardware": hardware,
        "config": config.to_dict(),
        "trials": [trial.to_dict() for trial in trials],
    }
    with (output_directory / "run_partial.json").open(
        "w", encoding="utf8"
    ) as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")


def run_tuning(
    config: TuneConfig,
    output_directory: Path,
    mock: bool = False,
    progress: Optional[Progress] = None,
) -> RunRecord:
    progress = progress or (lambda message: None)
    output_directory.mkdir(parents=True, exist_ok=True)
    started_at = utc_now()
    run_id = started_at.replace(":", "").replace("+", "_")
    mode = "simulation" if mock else "Radeon"
    hardware = (
        {
            "system": "simulated ROCm environment",
            "gpu_names": ["Simulated AMD Radeon GPU"],
            "gfx_targets": ["simulated"],
        }
        if mock
        else inspect_hardware()
    )
    candidates = build_candidates(config)
    remaining = {candidate.key(): candidate for candidate in candidates}
    agent = TuningAgent(config)
    current = candidates[0]
    hypothesis = "Establish the stock serving baseline."
    trials: List[Trial] = []
    trial_count = min(config.trials, len(candidates))
    for index in range(1, trial_count + 1):
        remaining.pop(current.key(), None)
        trial_directory = (
            output_directory / f"trial_{index:02d}_{current.key()}"
        )
        progress(
            f"Trial {index} of {trial_count}: {current.label()}"
        )
        trial_started = utc_now()
        proposal: Optional[Proposal] = None
        profile_enabled = index in config.profile_trials
        profile_directory = ""
        if mock:
            result = mock_benchmark(current)
            accepted, reason = _acceptance(config, result)
            trial = Trial(
                index=index,
                candidate=current,
                result=result,
                hypothesis=hypothesis,
                started_at=trial_started,
                completed_at=utc_now(),
                accepted=accepted,
                rejection_reason=reason,
            )
            trials.append(trial)
            if remaining:
                proposal = agent.propose(
                    list(remaining.values()),
                    trials,
                    current.model,
                    allow_local_inference=False,
                )
        else:
            try:
                with ServerManager(
                    config,
                    current,
                    trial_directory,
                    profile_enabled,
                ) as server:
                    result = run_benchmark(
                        config, current, trial_directory
                    )
                    accepted, reason = _acceptance(config, result)
                    profile_directory = server.profile_directory
                    trial = Trial(
                        index=index,
                        candidate=current,
                        result=result,
                        hypothesis=hypothesis,
                        started_at=trial_started,
                        completed_at=utc_now(),
                        accepted=accepted,
                        rejection_reason=reason,
                        profile_directory=profile_directory,
                    )
                    trials.append(trial)
                    if remaining:
                        proposal = agent.propose(
                            list(remaining.values()),
                            trials,
                            current.model,
                            allow_local_inference=True,
                        )
            except Exception as error:
                trial_directory.mkdir(parents=True, exist_ok=True)
                (trial_directory / "failure.txt").write_text(
                    str(error) + "\n", encoding="utf8"
                )
                result = BenchmarkResult(
                    output_tokens=0,
                    duration_seconds=0.0,
                    tokens_per_second=0.0,
                    latency_p50_ms=config.latency_limit_ms * 2,
                    latency_p95_ms=config.latency_limit_ms * 2,
                    error_rate=1.0,
                    quality_score=0.0,
                    peak_vram_mb=0.0,
                    responses=[],
                )
                trial = Trial(
                    index=index,
                    candidate=current,
                    result=result,
                    hypothesis=hypothesis,
                    started_at=trial_started,
                    completed_at=utc_now(),
                    accepted=False,
                    rejection_reason=f"candidate failed: {error}",
                    profile_directory=profile_directory,
                )
                trials.append(trial)
                if remaining:
                    proposal = agent.propose(
                        list(remaining.values()),
                        trials,
                        current.model,
                        allow_local_inference=False,
                    )
        verdict = "accepted" if trials[-1].accepted else "rejected"
        progress(
            f"Result: {result.tokens_per_second:.2f} tokens per second, "
            f"{result.latency_p95_ms:.1f} ms p95, {verdict}"
        )
        _write_partial(
            output_directory,
            config.name,
            started_at,
            mode,
            hardware,
            config,
            trials,
        )
        if not proposal:
            break
        current = proposal.candidate
        hypothesis = (
            proposal.hypothesis + f" Source: {proposal.source}."
        )
    accepted_trials = [trial for trial in trials if trial.accepted]
    eligible = accepted_trials or trials
    best = max(
        eligible, key=lambda trial: trial.result.tokens_per_second
    )
    record = RunRecord(
        run_id=run_id,
        name=config.name,
        started_at=started_at,
        completed_at=utc_now(),
        mode=mode,
        hardware=hardware,
        config=config.to_dict(),
        trials=trials,
        best_candidate_key=best.candidate.key(),
    )
    write_reports(record, output_directory)
    partial = output_directory / "run_partial.json"
    if partial.exists():
        partial.unlink()
    progress(
        f"Best result: {best.result.tokens_per_second:.2f} tokens per second"
    )
    return record
