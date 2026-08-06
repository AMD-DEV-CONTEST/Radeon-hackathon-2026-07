#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from prooflaunch_remix.files import atomic_write_text  # noqa: E402
from prooflaunch_remix.gtm_strategy_portfolio import (  # noqa: E402
    compile_strategy_portfolio_quality_audit,
    validate_strategy_portfolio_quality_audit,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compile deterministic cross-case quality gates for the local Gemma strategy portfolio."
    )
    parser.add_argument(
        "--receipt",
        default=str(ROOT / "evidence/v10/local-gemma3-12b-strategy-portfolio-v1.json"),
    )
    parser.add_argument(
        "--output",
        default=str(ROOT / "evidence/v10/local-gemma3-12b-strategy-portfolio-quality-v1.json"),
    )
    args = parser.parse_args()
    receipt = json.loads(Path(args.receipt).resolve(strict=True).read_text(encoding="utf-8"))
    audit = compile_strategy_portfolio_quality_audit(receipt)
    validate_strategy_portfolio_quality_audit(audit, receipt)
    output = Path(args.output).resolve()
    try:
        output.relative_to(ROOT)
    except ValueError as error:
        raise SystemExit("--output must remain inside the project root") from error
    atomic_write_text(output, json.dumps(audit, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "output": str(output),
                "status": audit["status"],
                "accepted_case_count": audit["accepted_case_count"],
                "channel_distribution": audit["channel_distribution"],
                "maximum_pairwise_content_jaccard": audit[
                    "maximum_pairwise_content_jaccard"
                ],
                "content_sha256": audit["content_sha256"],
                "human_preference_observed": False,
                "production_effect_observed": False,
            },
            sort_keys=True,
        )
    )
    return 0 if audit["portfolio_quality_gate_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
