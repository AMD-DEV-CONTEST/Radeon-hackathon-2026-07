#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from prooflaunch_remix.files import atomic_write_text  # noqa: E402
from prooflaunch_remix.gtm_codex_lighthouse_portfolio import (  # noqa: E402
    compile_lighthouse_portfolio,
    compile_lighthouse_quality_portfolio,
    verify_lighthouse_portfolio,
    verify_lighthouse_quality_portfolio,
)


CONFIG = ROOT / "config/codex-lighthouse-execution-candidates-v1.json"
PORTFOLIO_OUTPUT = ROOT / "evidence/v10/gtm-codex-lighthouse-portfolio-v1.json"
QUALITY_OUTPUT = ROOT / "evidence/v10/gtm-codex-lighthouse-quality-audit-v1.json"


def load_drafts() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    source = json.loads(CONFIG.read_text(encoding="utf-8"))
    drafts = source.get("drafts")
    if (
        source.get("schema") != "ProofLaunchCodexLighthouseDraftSetV1"
        or source.get("authorship_mode")
        != "codex_workspace_clean_room_reference_authoring"
        or source.get("draft_count") != 8
        or not isinstance(drafts, list)
        or len(drafts) != 8
        or any(not isinstance(row, dict) for row in drafts)
    ):
        raise RuntimeError("Codex lighthouse draft source is invalid")
    return source, drafts


def compile_from_files() -> tuple[dict[str, Any], dict[str, Any]]:
    _source, drafts = load_drafts()
    portfolio = compile_lighthouse_portfolio(drafts)
    verify_lighthouse_portfolio(portfolio)
    quality = compile_lighthouse_quality_portfolio(portfolio)
    verify_lighthouse_quality_portfolio(quality, portfolio=portfolio)
    return portfolio, quality


def main() -> int:
    portfolio, quality = compile_from_files()
    atomic_write_text(
        PORTFOLIO_OUTPUT,
        json.dumps(portfolio, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    atomic_write_text(
        QUALITY_OUTPUT,
        json.dumps(quality, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    print(
        json.dumps(
            {
                "portfolio_output": str(PORTFOLIO_OUTPUT),
                "portfolio_sha256": portfolio["content_sha256"],
                "quality_output": str(QUALITY_OUTPUT),
                "quality_sha256": quality["content_sha256"],
                "workspace_authored_candidates": portfolio[
                    "workspace_authored_candidate_count"
                ],
                "level_1_pass_count": quality["level_1_pass_count"],
                "qualified_human_reviews": quality["qualified_human_review_count"],
                "release_eligible": quality["release_eligible_count"],
                "production_effect_observed": quality[
                    "production_effect_observed_count"
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
