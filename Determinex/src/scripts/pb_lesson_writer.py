#!/usr/bin/env python3
"""Write an accepted/rejected lesson markdown from a gate_result.json + optional REPORT.md.

The lesson distills:
  - what changed (paths only; the diff lives in git)
  - baseline vs candidate score (cited from gate_result.json)
  - newly passing / newly failing tests
  - eval JSON paths (so a future worker can trace provenance)
  - what NOT to try again (rejected lessons) or next-risk (accepted lessons)

The writer is conservative. It quotes only what is in `gate_result.json`
and (optionally) what the worker wrote in REPORT.md. It never:
  - infers numbers not present in the JSON
  - makes claims about scores outside the gate
  - writes under `corpus/programbench/locked/*`
  - modifies overrides

Output file name pattern:
  <out-dir>/<slug>.<accept|reject>.<utc-timestamp>.lesson.md

Example:
  python scripts/pb_lesson_writer.py konradsz__igrep.aa75630 \\
      .determinex_staging/pb_igrep_c4_revert/gate_result.json \\
      --report logs/programbench_factory/konradsz__igrep.aa75630/REPORT.md \\
      --out-dir logs/programbench_factory/konradsz__igrep.aa75630/lessons
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def _safe_load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        sys.stderr.write(f"failed to parse {path}: {e}\n")
        return None


def _safe_read_text(path: Path, max_chars: int = 8000) -> str:
    if not path.is_file():
        return ""
    try:
        txt = path.read_text(encoding="utf-8", errors="replace")
        return txt if len(txt) <= max_chars else txt[:max_chars] + "\n\n[... truncated]"
    except Exception:
        return ""


def _fmt_accepted_lesson(
    slug: str,
    gate: dict[str, Any],
    report_text: str,
) -> str:
    baseline = gate.get("baseline") or {}
    candidate = gate.get("candidate") or {}
    delta = gate.get("delta") or {}
    newly_passing = delta.get("newly_passing") or []
    newly_failing = delta.get("newly_failing") or []

    bp = baseline.get("passed")
    brt = baseline.get("runnable")
    cp = candidate.get("passed")
    crt = candidate.get("runnable")

    lines: list[str] = []
    lines.append(f"# {slug} - accepted lesson")
    lines.append("")
    lines.append(f"Decision: **accept** (gate exit_code={gate.get('exit_code')})")
    lines.append(f"Reason cited: `{gate.get('reason', '')}`")
    lines.append("")

    lines.append("## Scores")
    lines.append("")
    lines.append("| Side | Passed | Runnable | Eval JSON |")
    lines.append("|---|---:|---:|---|")
    lines.append(f"| baseline  | {bp} | {brt} | `{baseline.get('eval_path', '')}` |")
    lines.append(f"| candidate | {cp} | {crt} | `{candidate.get('eval_path', '')}` |")
    lines.append(
        f"| delta     | {delta.get('passed', '?'):+d} | {delta.get('runnable', '?'):+d} | - |"
        if isinstance(delta.get("passed"), int) and isinstance(delta.get("runnable"), int)
        else f"| delta     | {delta.get('passed', '?')} | {delta.get('runnable', '?')} | - |"
    )
    lines.append("")

    if bp and cp and brt and crt:
        # No invented numbers - but a percentage off cited values is safe.
        lines.append(f"Display: {(100 * cp / crt):.2f}% (was {(100 * bp / brt):.2f}%).")
        lines.append("")

    lines.append("## Newly passing tests")
    lines.append("")
    if newly_passing:
        for name in newly_passing:
            lines.append(f"- `{name}`")
    else:
        lines.append(
            "(none - score improved without any individual test flipping; verify the gate `delta.passed` carefully)"
        )
    lines.append("")

    lines.append("## Newly failing tests (regressions accepted under net-positive rule)")
    lines.append("")
    if newly_failing:
        lines.append(
            "These tests were passing before this patch and are failing now. "
            "The gate still accepted because pass count strictly improved. "
            "Track each one - they may be cross-branch contradictions that need an upstream-binary check before any next patch in this code path."
        )
        lines.append("")
        for name in newly_failing:
            lines.append(f"- `{name}`")
    else:
        lines.append("None. Clean win across all tracked tests.")
    lines.append("")

    lines.append("## Next-risk notes")
    lines.append("")
    if newly_failing:
        lines.append(
            "- Each `newly_failing` test is a candidate for cross-branch contradiction "
            "(another branch may want a different shape on the same code path). "
            "Before any next patch in this area, run `scripts/pb_upstream_oracle.py` "
            "(once authored) against the disputed fixtures to verify upstream behavior."
        )
    lines.append(
        "- The accepted patch should be reviewed by Codex for surgical-revert opportunity: "
        "if any single change inside the patch produced ALL the regressions in `newly_failing`, "
        "reverting just that sub-change is a +1 free recovery."
    )
    lines.append(
        "- Keep the per-tool failure inventory fresh: "
        "`scripts/pb_cluster_from_eval.py <slug> <new-eval-path>` regenerates clusters from "
        "the post-accept eval JSON."
    )
    lines.append("")

    if report_text.strip():
        lines.append("## Worker REPORT.md excerpt")
        lines.append("")
        lines.append("```markdown")
        lines.append(report_text.strip())
        lines.append("```")
        lines.append("")

    lines.append("## Provenance")
    lines.append("")
    lines.append(f"- Source `gate_result.json`: `{gate.get('_path', '')}`")
    lines.append(f"- Baseline eval: `{baseline.get('eval_path', '')}`")
    lines.append(f"- Candidate eval: `{candidate.get('eval_path', '')}`")
    if gate.get("candidate_run_root"):
        lines.append(f"- Candidate run root: `{gate['candidate_run_root']}`")
    lines.append("")
    return "\n".join(lines)


def _fmt_rejected_lesson(
    slug: str,
    gate: dict[str, Any],
    report_text: str,
) -> str:
    baseline = gate.get("baseline") or {}
    candidate = gate.get("candidate") or {}
    delta = gate.get("delta") or {}
    newly_failing = delta.get("newly_failing") or []
    newly_passing = delta.get("newly_passing") or []

    bp = baseline.get("passed")
    brt = baseline.get("runnable")
    cp = candidate.get("passed")
    crt = candidate.get("runnable")

    lines: list[str] = []
    lines.append(f"# {slug} - rejected lesson")
    lines.append("")
    lines.append(f"Decision: **reject** (gate exit_code={gate.get('exit_code')})")
    lines.append(f"Reason cited: `{gate.get('reason', '')}`")
    lines.append("")

    lines.append("## Scores")
    lines.append("")
    lines.append("| Side | Passed | Runnable | Eval JSON |")
    lines.append("|---|---:|---:|---|")
    lines.append(f"| baseline  | {bp} | {brt} | `{baseline.get('eval_path', '')}` |")
    lines.append(f"| candidate | {cp} | {crt} | `{candidate.get('eval_path', '')}` |")
    if isinstance(delta.get("passed"), int):
        lines.append(
            f"| delta     | {delta.get('passed', '?'):+d} | {delta.get('runnable', '?'):+d} | - |"
        )
    lines.append("")

    lines.append("## What the attempt did")
    lines.append("")
    lines.append(f"Candidate run root: `{gate.get('candidate_run_root', '')}`")
    lines.append("")
    if report_text.strip():
        lines.append("Worker REPORT excerpt (verbatim):")
        lines.append("")
        lines.append("```markdown")
        lines.append(report_text.strip())
        lines.append("```")
    else:
        lines.append("(No REPORT.md provided - only the gate JSON is available.)")
    lines.append("")

    lines.append("## Regressions observed")
    lines.append("")
    if newly_failing:
        for name in newly_failing:
            lines.append(f"- `{name}`")
    else:
        lines.append(
            "(no per-test flips; the rejection reason was probably `runnable_delta != 0` or no improvement)"
        )
    lines.append("")

    if newly_passing:
        lines.append(
            "Tests that DID flip to passing (don't ignore - these tell you what the change *was* effective for):"
        )
        lines.append("")
        for name in newly_passing:
            lines.append(f"- `{name}`")
        lines.append("")

    lines.append("## What not to try again")
    lines.append("")
    lines.append(
        f"- The exact change captured under `{gate.get('candidate_run_root', '')}` "
        "did not satisfy the gate. Do not repeat the same patch verbatim."
    )
    if newly_failing:
        lines.append(
            "- A future attempt in this code path must preserve the tests now in `newly_failing` "
            "while still fixing whatever the worker was targeting. If the targeted cluster overlaps "
            "with these regressions, the strategy is wrong and needs sub-clustering before retry."
        )
    lines.append(
        "- If the rejection was `runnable_delta != 0`, investigate whether the candidate broke "
        "test collection (e.g. a syntax error, an import that fails at module load). The gate "
        "treats that as a structural regression, not a partial win."
    )
    if isinstance(delta.get("passed"), int) and delta["passed"] == 0:
        lines.append(
            "- A tie (pass count unchanged) is treated as a reject by design. Worker effort that "
            "produces a net-zero change is a signal to switch clusters or revisit the failure "
            "inventory; do not retry the same cluster with the same approach."
        )
    lines.append("")

    lines.append("## Provenance")
    lines.append("")
    lines.append(f"- Source `gate_result.json`: `{gate.get('_path', '')}`")
    lines.append(f"- Baseline eval: `{baseline.get('eval_path', '')}`")
    lines.append(f"- Candidate eval: `{candidate.get('eval_path', '')}`")
    lines.append("")
    return "\n".join(lines)


def write_lesson(
    slug: str,
    gate_path: Path,
    out_dir: Path,
    report_path: Path | None,
) -> Path:
    if not gate_path.is_file():
        raise SystemExit(f"gate_result.json not found: {gate_path}")
    gate = _safe_load_json(gate_path)
    if not gate:
        raise SystemExit(f"could not parse gate_result.json: {gate_path}")
    gate["_path"] = str(gate_path)

    if str(out_dir).startswith(str(ROOT / "corpus" / "programbench" / "locked")):
        raise SystemExit("refusing to write lesson under corpus/programbench/locked/*")

    out_dir.mkdir(parents=True, exist_ok=True)

    decision = str(gate.get("decision", "")).lower()
    if decision not in ("accept", "reject"):
        raise SystemExit(f"gate.decision must be 'accept' or 'reject'; got {decision!r}")

    report_text = _safe_read_text(report_path, max_chars=8000) if report_path else ""

    if decision == "accept":
        body = _fmt_accepted_lesson(slug, gate, report_text)
        verdict = "accept"
    else:
        body = _fmt_rejected_lesson(slug, gate, report_text)
        verdict = "reject"

    ts = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"{slug}.{verdict}.{ts}.lesson.md"
    out_path.write_text(body, encoding="utf-8")
    return out_path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("slug", help="ProgramBench instance id, e.g. owner__repo.hash")
    ap.add_argument("gate_result", type=Path, help="path to gate_result.json")
    ap.add_argument(
        "--report",
        type=Path,
        default=None,
        help="optional path to worker REPORT.md to embed verbatim",
    )
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="lesson output dir (default: logs/programbench_factory/<slug>/lessons)",
    )
    args = ap.parse_args()

    out_dir = args.out_dir or (ROOT / "logs" / "programbench_factory" / args.slug / "lessons")
    out_path = write_lesson(args.slug, args.gate_result, out_dir, args.report)
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
