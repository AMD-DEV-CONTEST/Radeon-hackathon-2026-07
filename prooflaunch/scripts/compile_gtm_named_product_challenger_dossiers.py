#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from prooflaunch_remix.gtm_challenger_dossier import compile_challenger_dossiers


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LEDGER = ROOT / "evidence/v10/gtm-concrete-product-effect-pk-ledger-v1.json"
DEFAULT_OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-challenger-dossiers-v1"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", default=str(DEFAULT_LEDGER))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    report = compile_challenger_dossiers(
        project_root=ROOT,
        ledger_path=Path(args.ledger).expanduser().resolve(),
        output_root=Path(args.output_dir).expanduser().resolve(),
    )
    print(json.dumps({
        "schema": report["schema"],
        "dossier_count": report["dossier_count"],
        "admitted_category_count": report["admitted_category_count"],
        "blocked_category_count": report["blocked_category_count"],
        "content_sha256": report["content_sha256"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
