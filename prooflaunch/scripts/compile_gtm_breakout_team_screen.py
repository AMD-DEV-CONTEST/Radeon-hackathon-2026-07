#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from pypdf import PdfReader

from prooflaunch_remix.gtm_breakout_team_screening import (
    compile_breakout_team_screen,
    parse_deloitte_fast500_text,
    verify_breakout_team_screen,
)


SOURCE_URL = "https://www.deloitte.com/content/dam/assets-zone3/us/en/docs/services/deloitte-private/2025/us-2025-technology-fast-500-rankings.pdf"


def main() -> int:
    parser = argparse.ArgumentParser(description="Cross-screen official revenue-growth winners against the startup directory candidate pool.")
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--landscape", type=Path, default=Path("evidence/v10/gtm-startup-landscape-yc-v1.json"))
    parser.add_argument("--output", type=Path, default=Path("evidence/v10/gtm-breakout-team-screen-fast500-yc-v1.json"))
    args = parser.parse_args()
    pdf_bytes = args.pdf.read_bytes()
    reader = PdfReader(str(args.pdf))
    text = "\n".join((page.extract_text() or "") for page in reader.pages[1:])
    rows = parse_deloitte_fast500_text(text)
    landscape = json.loads(args.landscape.read_text(encoding="utf-8"))
    screen = compile_breakout_team_screen(
        rows,
        landscape,
        source_url=SOURCE_URL,
        source_pdf_sha256=hashlib.sha256(pdf_bytes).hexdigest(),
    )
    verify_breakout_team_screen(screen)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(screen, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "candidate_count": screen["candidate_count"],
                "yc_exact_crossmatch_count": screen["yc_exact_crossmatch_count"],
                "outcome_priority_band_counts": screen["outcome_priority_band_counts"],
                "content_sha256": screen["content_sha256"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
