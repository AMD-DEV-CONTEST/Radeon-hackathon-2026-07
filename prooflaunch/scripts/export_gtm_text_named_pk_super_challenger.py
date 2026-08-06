#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from prooflaunch_remix.gtm_text_super_challenger_export import export_text_super_challenger


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PORTFOLIO = ROOT / "evidence/v10/gtm-text-named-pk-super-challenger-v1.json"
DEFAULT_OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/text-super-challenger-v1"


def main() -> int:
    parser = argparse.ArgumentParser(description="Export the source-hidden four-asset text challenger.")
    parser.add_argument("--portfolio", default=str(DEFAULT_PORTFOLIO))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    portfolio = json.loads(Path(args.portfolio).expanduser().resolve().read_text(encoding="utf-8"))
    output = Path(args.output_dir).expanduser().resolve()
    output.relative_to(ROOT)
    manifest = export_text_super_challenger(portfolio=portfolio, output_root=output)
    print(json.dumps({
        "output": str(output),
        "asset_count": manifest["asset_count"],
        "named_product_target_count": manifest["named_product_target_count"],
        "completed_named_product_pk_count": manifest["completed_named_product_pk_count"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
