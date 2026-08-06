"""Formatting + regression comparison for ``EvalReport`` (blueprint T3).

Pure stdlib. ``aggregate()`` averages each scorer ONLY over the cases where it
applies (see ``scorers.applies``) -- folding a "not applicable" 1.0 into the
mean is exactly how an eval gate stops meaning anything. ``compare()`` turns the
difference between two runs into a PASS/REGRESS verdict, which is what lets any
later optimization claim "done" instead of "I think it's better".

Hard rule (blueprint §6.2 rule 6): stdlib only. No torch / gradio / numpy.
"""
from __future__ import annotations

import json
from typing import Any, Mapping, Optional

from screwshell.eval.thresholds import THRESHOLDS, check_bars, is_lower_better
from screwshell.eval.types import EvalReport, as_report_dict


# --------------------------------------------------------------- aggregate --

def _percentile(values: list[float], q: float) -> float:
    """Linear-interpolation percentile (q in [0, 1]) over a sorted list.

    Small samples (1-3 cases) are the norm for a local eval run, so we avoid
    numpy and use the standard ``(n-1)*q`` interpolation; with n=1 it returns the
    single value, with n=3 and q=0.95 it returns the max -- both correct.
    """
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    rank = (len(values) - 1) * q
    lo = int(rank)
    frac = rank - lo
    if lo + 1 < len(values):
        return values[lo] + (values[lo + 1] - values[lo]) * frac
    return float(values[lo])


def _llm_summary(cases: list) -> dict:
    """Roll the per-run ``llm`` summaries into one view for the report header.

    Includes the latency percentiles (p50 / p95 / mean / total) across the
    measured queries -- these are the metrics the gate actually gates on
    (``THRESHOLDS`` declares ``p95_seconds`` etc.), so without them the gate can
    only check scorer means, which is exactly the blind spot B4 closed.
    """
    return _roll(cases)


def _roll(cases: list) -> dict:
    calls = ptok = ntok = cached = 0
    cov: list[float] = []
    secs: list[float] = []
    for cr in cases:
        llm = (cr.stats or {}).get("llm") or {}
        calls += int(llm.get("calls", 0) or 0)
        ptok += int(llm.get("prompt_tokens", 0) or 0)
        ntok += int(llm.get("new_tokens", 0) or 0)
        cached += int(llm.get("cached_tokens", 0) or 0)
        c = (llm.get("coverage") or {}).get("timings")
        if c is not None:
            cov.append(c)
        s = llm.get("seconds")
        if s is None:
            s = cr.seconds
        if s is not None:
            secs.append(float(s))
    out = {
        "calls": calls,
        "prompt_tokens": ptok,
        "new_tokens": ntok,
        "cached_tokens": cached,
        "kv_hit_rate": round(cached / ptok, 4) if ptok else 0.0,
        "timings_coverage": round(sum(cov) / len(cov), 4) if cov else 0.0,
    }
    if secs:
        secs_sorted = sorted(secs)
        out["total_seconds"] = round(sum(secs_sorted), 4)
        out["mean_seconds"] = round(sum(secs_sorted) / len(secs_sorted), 4)
        out["p50_seconds"] = round(_percentile(secs_sorted, 0.50), 4)
        out["p95_seconds"] = round(_percentile(secs_sorted, 0.95), 4)
    return out


def aggregate(report: EvalReport) -> dict:
    """Mean of each scorer over the cases where it applies.

    Returns ``{scorers: {name: mean}, applied: {name: n}, overall, cases, ok,
    failed, llm}``. ``overall`` is the unweighted mean of the applicable means
    that have at least one data point (so a scorer with zero applicable cases
    neither inflates nor deflates the headline).
    """
    scorer_names = list(report.scorers or [])
    buckets: dict[str, list[float]] = {n: [] for n in scorer_names}
    for cr in report.cases:
        applies = getattr(cr, "applies", {}) or {}
        for n in scorer_names:
            if applies.get(n):
                v = cr.scores.get(n)
                if v is not None:
                    buckets[n].append(float(v))

    means = {}
    applied = {}
    for n in scorer_names:
        vals = buckets[n]
        applied[n] = len(vals)
        means[n] = round(sum(vals) / len(vals), 4) if vals else 0.0

    nonzero = [means[n] for n in scorer_names if applied[n] > 0]
    overall = round(sum(nonzero) / len(nonzero), 4) if nonzero else 0.0
    ok = sum(1 for cr in report.cases if cr.ok)
    return {
        "scorers": means,
        "applied": applied,
        "overall": overall,
        "cases": len(report.cases),
        "ok": ok,
        "failed": len(report.cases) - ok,
        "llm": _llm_summary(report.cases),
    }


# --------------------------------------------------------------- format --

def to_json(report: EvalReport) -> str:
    """The report as a JSON string (round-trippable via ``EvalReport.load``)."""
    return json.dumps(report.to_dict(), ensure_ascii=False, indent=1)


def to_markdown(report: EvalReport) -> str:
    """A human-readable report: header, score table, per-case, llm accounting."""
    agg = aggregate(report)
    lines: list[str] = []
    lines.append(f"# Eval Report — {report.tag or 'run'}")
    lines.append("")
    lines.append(f"- started : {report.started}")
    lines.append(f"- engine  : {report.engine}   git_sha: {report.git_sha}")
    lines.append(f"- cases   : {agg['cases']}   ok: {agg['ok']}   "
                 f"failed: {agg['failed']}   wall: {report.seconds}s")
    flags = report.config if isinstance(report.config, dict) else None
    if flags:
        lines.append(f"- flags   : {flags}")
    lines.append("")
    lines.append("## Scores (mean over applicable cases)")
    lines.append("")
    lines.append("| scorer | mean | applied |")
    lines.append("| --- | --- | --- |")
    for n in report.scorers:
        lines.append(f"| {n} | {agg['scorers'].get(n)} | {agg['applied'].get(n)} |")
    lines.append(f"| **overall** | **{agg['overall']}** | |")
    lines.append("")
    lines.append("## Per-case")
    lines.append("")
    for cr in report.cases:
        ok = "ok" if cr.ok else "FAIL"
        lines.append(f"- [{ok}] `{cr.case_id}` status={cr.status} "
                     f"{cr.seconds}s skills={','.join(cr.skills) or '-'}")
    lines.append("")
    llm = agg.get("llm", {})
    lines.append("## LLM accounting")
    lines.append("")
    lines.append(f"- calls={llm.get('calls')} prompt={llm.get('prompt_tokens')}tok "
                 f"new={llm.get('new_tokens')}tok "
                 f"cached={llm.get('cached_tokens')}tok")
    lines.append(f"- kv_hit_rate={llm.get('kv_hit_rate')} "
                 f"timings_coverage={llm.get('timings_coverage')}")
    if llm.get("p95_seconds") is not None:
        lines.append(f"- latency : p50={llm.get('p50_seconds')}s "
                     f"p95={llm.get('p95_seconds')}s "
                     f"mean={llm.get('mean_seconds')}s "
                     f"total={llm.get('total_seconds')}s")
    return "\n".join(lines)


# --------------------------------------------------------------- compare --

def compare(baseline: Any, current: Any,
            tol: Optional[float] = None) -> dict:
    """Regression gate between two reports (or their ``to_dict()`` dicts).

    Two things are checked, and either one fails the gate:

    1. **Scorer regression** -- for every scorer mean present in both arms, the
       current run is compared to the baseline. "Worse" honours
       ``is_lower_better()``: a higher-is-better scorer (our quality scorers)
       regresses on a drop below ``-tol``; a lower-is-better metric (e.g. a
       latency in seconds) regresses on a *rise* above ``+tol``. The old code
       always used ``delta < -tol`` and merely recorded ``lower_is_worse``
       without acting on it -- so a latency regression could never be caught.
    2. **Absolute bars** -- the measurable LLM latency / token metrics in the
       *current* ``aggregate`` are checked against ``THRESHOLDS`` via
       ``check_bars`` / ``meets`` (B4-b). A metric that misses its bar is a
       gate failure regardless of the baseline.

    The two arms are read from each report's embedded ``aggregate`` (the on-disk
    shape is stable, so a baseline saved last week still compares cleanly).
    """
    b = as_report_dict(baseline)
    c = as_report_dict(current)
    if tol is None:
        tol = THRESHOLDS.get("regression_tolerance", 0.05)

    b_agg = (b.get("aggregate") or {})
    c_agg = (c.get("aggregate") or {})
    b_scores = b_agg.get("scorers") or {}
    c_scores = c_agg.get("scorers") or {}
    per: dict[str, dict] = {}
    regressed: list[str] = []
    for name in sorted(set(b_scores) | set(c_scores)):
        base = b_scores.get(name)
        cur = c_scores.get(name)
        if base is None or cur is None:
            per[name] = {"base": base, "current": cur, "delta": None,
                         "regressed": False, "reason": "missing arm"}
            continue
        delta = round(cur - base, 4)
        lower = is_lower_better(name)
        # Higher-is-better (default): a drop below -tol regresses.
        # Lower-is-better: a rise above +tol regresses.
        worse = (delta < -tol) if not lower else (delta > tol)
        direction = "down" if delta < 0 else ("up" if delta > 0 else "flat")
        per[name] = {"base": base, "current": cur, "delta": delta,
                     "regressed": bool(worse),
                     "lower_is_better": lower, "direction": direction}
        if worse:
            regressed.append(name)

    # Absolute bars on the measurable LLM latency / token metrics (B4-b).
    bars_failed = check_bars(c_agg)

    verdict = "PASS"
    if regressed:
        verdict = "REGRESS"
    if bars_failed:
        verdict = "FAIL"

    return {
        "verdict": verdict,
        "regressed": regressed,
        "bars_failed": list(bars_failed.keys()),
        "tolerance": tol,
        "scorers": per,
        "bars": bars_failed,
        "baseline_overall": b_agg.get("overall"),
        "current_overall": c_agg.get("overall"),
    }


__all__ = ["aggregate", "to_json", "to_markdown", "compare", "_percentile",
           "_roll"]
