from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Dict, List

from autotuner.models import Candidate, RunRecord, Trial


def _best(record: RunRecord) -> Trial:
    for trial in record.trials:
        if trial.candidate.key() == record.best_candidate_key:
            return trial
    raise ValueError("Best candidate is missing from the run")


def _changes(baseline: Candidate, best: Candidate) -> List[str]:
    changes = []
    baseline_values = baseline.to_dict()
    for name, value in best.to_dict().items():
        if baseline_values[name] != value:
            changes.append(
                f"{name}: {baseline_values[name]} to {value}"
            )
    return changes


def _hardware_name(hardware: Dict[str, Any]) -> str:
    names = hardware.get("gpu_names", [])
    if names:
        return ", ".join(str(item) for item in names)
    return "AMD Radeon GPU"


def _preset(candidate: Candidate) -> Dict[str, Any]:
    arguments = {
        "model": candidate.model,
        "max_model_len": candidate.max_model_len,
        "max_num_seqs": candidate.max_num_seqs,
        "gpu_memory_utilization": candidate.gpu_memory_utilization,
        "kv_cache_dtype": candidate.kv_cache_dtype,
        "quantization": candidate.quantization,
    }
    if candidate.speculative_model:
        arguments["speculative_model"] = candidate.speculative_model
        arguments["num_speculative_tokens"] = (
            candidate.num_speculative_tokens
        )
    return {
        "engine": candidate.engine,
        "environment": {
            "VLLM_ATTENTION_BACKEND": candidate.attention_backend
        },
        "arguments": arguments,
    }


def write_reports(record: RunRecord, output_directory: Path) -> None:
    output_directory.mkdir(parents=True, exist_ok=True)
    with (output_directory / "run.json").open(
        "w", encoding="utf8"
    ) as handle:
        json.dump(record.to_dict(), handle, indent=2)
        handle.write("\n")
    best = _best(record)
    with (output_directory / "best_preset.json").open(
        "w", encoding="utf8"
    ) as handle:
        json.dump(_preset(best.candidate), handle, indent=2)
        handle.write("\n")
    (output_directory / "engineering_report.md").write_text(
        markdown_report(record), encoding="utf8"
    )
    (output_directory / "dashboard.html").write_text(
        html_report(record), encoding="utf8"
    )


def load_record(path: Path) -> RunRecord:
    with path.open("r", encoding="utf8") as handle:
        value = json.load(handle)
    return RunRecord(
        run_id=str(value["run_id"]),
        name=str(value["name"]),
        started_at=str(value["started_at"]),
        completed_at=str(value["completed_at"]),
        mode=str(value["mode"]),
        hardware=dict(value["hardware"]),
        config=dict(value["config"]),
        trials=[Trial.from_dict(item) for item in value["trials"]],
        best_candidate_key=str(value["best_candidate_key"]),
    )


def markdown_report(record: RunRecord) -> str:
    baseline = record.trials[0]
    best = _best(record)
    improvement = (
        best.result.tokens_per_second
        / max(baseline.result.tokens_per_second, 0.000001)
        - 1
    ) * 100
    changes = _changes(baseline.candidate, best.candidate)
    trial_rows = "\n".join(
        "<tr>"
        f"<td>{trial.index}</td>"
        f"<td>{html.escape(trial.candidate.key())}</td>"
        f"<td>{trial.result.tokens_per_second:.2f}</td>"
        f"<td>{trial.result.latency_p95_ms:.1f}</td>"
        f"<td>{trial.result.error_rate:.3f}</td>"
        f"<td>{trial.result.quality_score:.3f}</td>"
        f"<td>{'Accepted' if trial.accepted else 'Rejected'}</td>"
        "</tr>"
        for trial in record.trials
    )
    change_lines = "\n".join(
        f"{index}. {item}" for index, item in enumerate(changes, 1)
    )
    if not change_lines:
        change_lines = "No configuration fields changed."
    evidence_notice = (
        "Evidence status: Simulation only. This artifact validates the "
        "software flow and does not report measured Radeon performance."
        if record.mode.lower() == "simulation"
        else "Evidence status: Measured Radeon run."
    )
    return f"""# Autotuner Engineering Report

{evidence_notice}

## Executive result

Autotuner evaluated {len(record.trials)} serving configurations on {_hardware_name(record.hardware)}. The best accepted configuration reached {best.result.tokens_per_second:.2f} output tokens per second. The baseline reached {baseline.result.tokens_per_second:.2f} output tokens per second. The measured improvement was {improvement:.1f} percent.

## Method

The agent measured every candidate against the same prompt set, generation length, concurrency, quality floor, error limit, and latency limit. It used the model running on the active Radeon deployment to choose the next controlled experiment when local agent mode was available.

## Winning configuration

```json
{json.dumps(_preset(best.candidate), indent=2)}
```

## Changes from baseline

{change_lines}

## Trial evidence

<table>
<thead><tr><th>Trial</th><th>Candidate</th><th>Tokens per second</th><th>P95 ms</th><th>Error rate</th><th>Quality</th><th>Decision</th></tr></thead>
<tbody>
{trial_rows}
</tbody>
</table>

## Reproducibility

The complete machine record is stored in `run.json`. The reusable serving configuration is stored in `best_preset.json`. Raw server logs, telemetry, and profiler output are stored inside each trial directory when available.

## Interpretation

This report describes measurements from one declared workload. Results should be confirmed on the target model, Radeon GPU, ROCm release, and request distribution before production use.
"""


def html_report(record: RunRecord) -> str:
    baseline = record.trials[0]
    best = _best(record)
    improvement = (
        best.result.tokens_per_second
        / max(baseline.result.tokens_per_second, 0.000001)
        - 1
    ) * 100
    maximum = max(
        trial.result.tokens_per_second for trial in record.trials
    )
    cards = []
    for trial in record.trials:
        width = trial.result.tokens_per_second / maximum * 100
        state = "accepted" if trial.accepted else "rejected"
        cards.append(
            f"""<article class="trial {state}">
<div class="trialhead"><strong>Trial {trial.index}</strong><span>{html.escape(trial.candidate.key())}</span></div>
<div class="bar"><i style="width:{width:.1f}%"></i></div>
<div class="metrics"><b>{trial.result.tokens_per_second:.2f}</b> tokens per second <span>{trial.result.latency_p95_ms:.0f} ms p95</span></div>
<p>{html.escape(trial.hypothesis)}</p>
</article>"""
        )
    changes = "".join(
        f"<li>{html.escape(item)}</li>"
        for item in _changes(baseline.candidate, best.candidate)
    ) or "<li>No configuration fields changed</li>"
    simulated = record.mode.lower() == "simulation"
    eyebrow = (
        "SIMULATION ONLY | NO HARDWARE PERFORMANCE CLAIM"
        if simulated
        else "AMD RADEON ROCm LOCAL INFERENCE"
    )
    notice = (
        "This deterministic artifact validates the product flow. Replace it "
        "with a measured Radeon run before final submission."
        if simulated
        else "This dashboard was generated from the recorded Radeon run."
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Autotuner Radeon Report</title>
<style>
:root{{--ink:#eef2ff;--muted:#9ba7c5;--panel:#151b2e;--red:#ff4b55;--orange:#ff8b38;--green:#45d19a}}
*{{box-sizing:border-box}} body{{margin:0;background:#090d18;color:var(--ink);font:16px/1.55 Inter,ui-sans-serif,system-ui,sans-serif}}
main{{width:min(1080px,92vw);margin:0 auto;padding:64px 0 80px}} .eyebrow{{color:var(--orange);letter-spacing:.16em;text-transform:uppercase;font-weight:800}}
h1{{font-size:clamp(44px,8vw,92px);line-height:.95;margin:18px 0 28px;max-width:900px}} .lede{{font-size:21px;color:var(--muted);max-width:780px}}
.scoreboard{{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin:42px 0}} .score{{background:linear-gradient(145deg,#1a2138,#101526);padding:24px;border:1px solid #28314d;border-radius:18px}}
.score b{{display:block;font-size:38px}} .score span{{color:var(--muted)}} section{{margin-top:52px}} h2{{font-size:28px}}
.trial{{background:var(--panel);border:1px solid #28314d;border-radius:15px;padding:18px;margin:12px 0}} .trial.rejected{{opacity:.58}} .trialhead,.metrics{{display:flex;justify-content:space-between;gap:20px}}
.trialhead span,.metrics span,.trial p{{color:var(--muted)}} .bar{{height:8px;background:#252d46;border-radius:99px;overflow:hidden;margin:14px 0}} .bar i{{display:block;height:100%;background:linear-gradient(90deg,var(--red),var(--orange));border-radius:99px}}
.winner{{background:linear-gradient(145deg,#32171d,#18192a);border:1px solid #60313a;border-radius:20px;padding:28px}} code{{color:#ffc69f}} li{{margin:8px 0}}
@media(max-width:700px){{.scoreboard{{grid-template-columns:1fr}}.trialhead,.metrics{{display:block}}}}
</style>
</head>
<body><main>
<div class="eyebrow">{eyebrow}</div>
<h1>The agent made itself {improvement:.1f}% faster.</h1>
<p class="lede">{html.escape(record.name)} ran {len(record.trials)} controlled experiments on {_hardware_name(record.hardware)} and exported a reproducible serving preset.</p>
<p class="lede">{html.escape(notice)}</p>
<div class="scoreboard">
<div class="score"><b>{baseline.result.tokens_per_second:.2f}</b><span>baseline tokens per second</span></div>
<div class="score"><b>{best.result.tokens_per_second:.2f}</b><span>best tokens per second</span></div>
<div class="score"><b>{best.result.latency_p95_ms:.0f} ms</b><span>winning p95 latency</span></div>
</div>
<section class="winner"><div class="eyebrow">Winning candidate</div><h2>{html.escape(best.candidate.key())}</h2><code>{html.escape(best.candidate.label())}</code><ol>{changes}</ol></section>
<section><h2>Experiment timeline</h2>{''.join(cards)}</section>
</main></body></html>
"""
