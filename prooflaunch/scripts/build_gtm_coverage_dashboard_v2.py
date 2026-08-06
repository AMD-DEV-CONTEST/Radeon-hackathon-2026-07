#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_coverage_dashboard_v2 import (
    build_coverage_dashboard,
    verify_coverage_dashboard,
)


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def main() -> int:
    html, manifest = build_coverage_dashboard(
        _read("evidence/v10/gtm-case-evidence-funnel-v2/standard.json"),
        _read("evidence/v10/gtm-case-evidence-funnel-v2/coverage.json"),
        _read("evidence/v10/gtm-wave1-discovery-leads-v2.json"),
        _read("evidence/v10/gtm-case-identity-resolution-v2.json"),
        _read("evidence/v10/gtm-mechanism-review-queue-v2.json"),
    )
    verify_coverage_dashboard(html, manifest)
    output_dir = ROOT / "artifacts/gtm-case-coverage-v2"
    output_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_text(output_dir / "index.html", html)
    atomic_write_text(output_dir / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output_dir": str(output_dir), **manifest}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
