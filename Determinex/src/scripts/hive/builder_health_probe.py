"""Standalone Determinex Builder health probe.

This is intentionally narrower than a full Hive workflow. It verifies that the
selected Builder model can answer the existing executor health preflight and
records the exact model selected after fallback resolution.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parents[1]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from hive import executor  # noqa: E402

SCHEMA_VERSION = "determinex-builder-health-probe-v1"
DEFAULT_BUILDER_MODEL = "determinex/engineer"


def run_probe(
    *,
    model: str = DEFAULT_BUILDER_MODEL,
    fallback_model: str | None = None,
    timeout: int = 60,
    output_path: Path | None = None,
) -> dict[str, Any]:
    assignments = {"builder": model}
    fallbacks = [fallback_model] if fallback_model else None
    ok, reason = executor._preflight_builder_health(
        assignments,
        fallback_aliases=fallbacks,
        timeout=timeout,
    )
    selected = assignments.get("builder", model)
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "status": "passed" if ok else "blocked",
        "release_ready": False,
        "builder_model_requested": model,
        "builder_model_selected": selected,
        "fallback_model_requested": fallback_model or "",
        "timeout_seconds": timeout,
        "exact_blocker": "" if ok else reason,
        "reason": reason,
        "claim_boundary": (
            "A passed Builder health probe only proves model preflight health; "
            "it does not prove the first E2E workflow or release readiness."
        ),
    }
    if output_path is not None:
        payload["output_path"] = output_path.as_posix()
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_BUILDER_MODEL)
    parser.add_argument("--fallback-model", default=None)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    payload = run_probe(
        model=args.model,
        fallback_model=args.fallback_model,
        timeout=args.timeout,
        output_path=args.output,
    )
    text = json.dumps(payload, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text)
    return 0 if payload["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
