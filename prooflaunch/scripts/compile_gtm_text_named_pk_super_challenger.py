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
from prooflaunch_remix.gtm_text_named_pk_challenger import (  # noqa: E402
    compile_candidate,
    compile_row_portfolio,
    verify_row_portfolio,
)


CONFIG = ROOT / "config/codex-text-named-pk-super-challenger-v1.json"
LEDGER = ROOT / "evidence/v10/gtm-concrete-product-effect-pk-ledger-v1.json"
DEFAULT_OUTPUT = ROOT / "evidence/v10/gtm-text-named-pk-super-challenger-v1.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Compile the ten-row text-product PK super challenger.")
    parser.add_argument("--config", type=Path, default=CONFIG)
    parser.add_argument("--ledger", type=Path, default=LEDGER)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    config = json.loads(args.config.resolve().read_text(encoding="utf-8"))
    ledger = json.loads(args.ledger.resolve().read_text(encoding="utf-8"))
    payload = compile_row_portfolio(compile_candidate(config), ledger)
    verify_row_portfolio(payload)
    atomic_write_text(args.output.resolve(), json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({
        "output": str(args.output.resolve()),
        "row_count": payload["row_count"],
        "asset_count": payload["candidate"]["asset_count"],
        "candidate_level_1_pass_count": payload["candidate_level_1_pass_count"],
        "completed_named_product_pk_count": payload["completed_named_product_pk_count"],
        "content_sha256": payload["content_sha256"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
