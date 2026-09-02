"""Derive the first-E2E rerun evidence from a real session manifest.

Why this exists
---------------
`_first_e2e_gate` reads `rerun_after_builder_health_latest.json` and passes the release when it
says PASSED with all steps complete. Nothing wrote that file. It was maintained by hand: a human
ran a session, read the numbers off the console, and typed them into the evidence the gate then
trusted. Every field the gate checks -- status, steps_complete, steps_total, steps_failed -- was
therefore an assertion by the same party the gate exists to constrain, and a typo in the operator's
favour is indistinguishable from a pass.

This script closes that by reading the session's own committed manifest. `status` is computed from
the observed steps, never accepted as input, so a session that did not finish cannot be written up
as one that did. The claim is bounded to what the session actually exercised: `correctness_result`
is reported verbatim, including empty, so "the compiler was the only oracle" stays visible instead
of being smoothed into a correctness claim.

Usage
    python scripts/release/capture_first_e2e_rerun.py --session <session-id> [--supersedes <id>]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

SCHEMA_VERSION = "determinex-first-e2e-rerun-v3"
PASSED = "FIRST_E2E_RERUN_PASSED"
FAILED = "FIRST_E2E_RERUN_FAILED"

# A step is only complete when the session says so AND the oracle passed. A step marked complete
# whose compiler_result is not "pass" was never verified, and counting it would reintroduce by
# arithmetic exactly the overclaim this file removes by provenance.
_COMPLETE = "complete"
_ORACLE_PASS = "pass"


class CaptureError(RuntimeError):
    """The session cannot be written up as evidence."""


def load_manifest(root: Path, session_id: str) -> dict[str, Any]:
    path = root / "sessions" / session_id / "manifest.json"
    if not path.is_file():
        raise CaptureError(f"no session manifest at {path} -- run the session before capturing it")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CaptureError(f"unreadable session manifest {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise CaptureError(f"session manifest {path} is not an object")
    if str(data.get("session_id") or "") != session_id:
        raise CaptureError(
            f"manifest session_id {data.get('session_id')!r} does not match requested {session_id!r}"
        )
    return data


def summarise_steps(steps: list[Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    per_step: list[dict[str, Any]] = []
    complete = failed = pending = 0
    for raw in steps:
        if not isinstance(raw, dict):
            continue
        status = str(raw.get("status") or "")
        oracle = str(raw.get("compiler_result") or "")
        verified = status == _COMPLETE and oracle == _ORACLE_PASS
        if verified:
            complete += 1
        elif status in {"failed", "escalated", "blocked"}:
            failed += 1
        else:
            # Marked complete without a passing oracle lands here on purpose: not a failure the
            # session reported, but not something we may count as verified either.
            pending += 1
        per_step.append(
            {
                "id": raw.get("id"),
                "status": status,
                "compiler_result": oracle,
                "correctness_result": str(raw.get("correctness_result") or ""),
                "quality": str(raw.get("quality") or ""),
                "retries": int(raw.get("retries") or 0),
            }
        )
    observed: dict[str, Any] = {
        "steps_complete": complete,
        "steps_total": len(per_step),
        "steps_failed": failed,
        "steps_pending": pending,
    }
    return observed, per_step


def build_record(
    manifest: dict[str, Any],
    *,
    generated_at_utc: str,
    supersedes: str = "",
    notes: list[str] | None = None,
) -> dict[str, Any]:
    steps = manifest.get("steps")
    observed, per_step = summarise_steps(steps if isinstance(steps, list) else [])
    observed["api_cost_usd"] = float(manifest.get("api_cost_usd") or 0.0)
    observed["session_budget_usd"] = float(manifest.get("session_budget_usd") or 0.0)

    passed = (
        observed["steps_total"] > 0
        and observed["steps_complete"] == observed["steps_total"]
        and observed["steps_failed"] == 0
        and observed["steps_pending"] == 0
        and not manifest.get("budget_exhausted")
        and not (manifest.get("pending_escalations") or [])
    )

    harness = str(manifest.get("correctness_test_harness") or "")
    qualifications = [
        (
            f"Every step was verified by the Compiler Oracle ({observed['steps_complete']}/"
            f"{observed['steps_total']} compiler_result=pass)."
            if passed
            else f"{observed['steps_complete']}/{observed['steps_total']} steps reached a passing "
            f"Compiler Oracle result; {observed['steps_failed']} failed and "
            f"{observed['steps_pending']} did not reach a verified state."
        ),
    ]
    if not harness:
        qualifications.append(
            "correctness_result is empty because the spec shipped no test harness, so the compiler "
            "was the only oracle. This is a compile-verified workflow, not a behaviour-verified one."
        )
    if manifest.get("pending_escalations"):
        qualifications.append(
            f"{len(manifest['pending_escalations'])} escalation(s) are still pending on this session."
        )
    qualifications.append(
        "A passing first-E2E rerun proves the user workflow completed against this build. It does "
        "not by itself authorise release; see the full gate report."
    )

    record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": PASSED if passed else FAILED,
        "generated_at_utc": generated_at_utc,
        "session_id": str(manifest.get("session_id") or ""),
        "lang": str(manifest.get("lang") or ""),
        "release_ready": False,
        "authority_granted": False,
        "observed_result": observed,
        "per_step": per_step,
        "qualifications": qualifications,
        "environment": {
            "models": _model_environment(),
            "oracle_backend": os.environ.get("DETERMINEX_ORACLE_BACKEND", "docker"),
            "api_cost_usd": observed["api_cost_usd"],
        },
        "session_created_at": str(manifest.get("created_at") or ""),
        "session_updated_at": str(manifest.get("updated_at") or ""),
        "spec_path": str(manifest.get("md_spec_path") or ""),
        "derived_from": f"sessions/{manifest.get('session_id')}/manifest.json",
        "notes": list(notes or []),
        "next_required_action": (
            ""
            if passed
            else "Investigate the non-verified steps in the session manifest and rerun the workflow."
        ),
    }
    if supersedes:
        record["supersedes"] = supersedes
    return record


def _model_environment() -> str:
    """Report the model ladder without asserting locality we have not established."""
    for name in ("DETERMINEX_BUILDER_MODEL", "DETERMINEX_LOCAL_BUILDER_MODEL"):
        value = os.environ.get(name)
        if value:
            return f"{name}={value}"
    return (
        "local only (determinex-engineer-v11-dsl / -observer-v6-dsl / -sentinel-v5-dsl via Ollama)"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True, help="session id to write up")
    parser.add_argument("--supersedes", default="", help="session id this rerun replaces")
    parser.add_argument("--note", action="append", default=[], help="repeatable context note")
    parser.add_argument("--root", default=str(REPO_ROOT))
    parser.add_argument(
        "--output",
        default="assurance/evidence/first_end_to_end_user_workflow/rerun_after_builder_health_latest.json",
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    try:
        manifest = load_manifest(root, args.session)
    except CaptureError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2

    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    record = build_record(
        manifest, generated_at_utc=stamp, supersedes=args.supersedes, notes=args.note
    )

    out = (root / args.output) if not Path(args.output).is_absolute() else Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(record, indent=2) + "\n"
    tmp = out.with_suffix(out.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(payload)
        fh.flush()
        os.fsync(fh.fileno())
    tmp.replace(out)

    print(json.dumps(record["observed_result"], indent=2))
    print(f"status: {record['status']}")
    print(f"wrote: {out}")
    return 0 if record["status"] == PASSED else 1


if __name__ == "__main__":
    raise SystemExit(main())
