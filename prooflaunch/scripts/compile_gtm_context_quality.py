#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_context_quality import compile_gtm_context_quality


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default=str(ROOT / "evidence/v10/gtm-context-quality-v1.json"),
    )
    args = parser.parse_args()
    receipt = compile_gtm_context_quality(ROOT)
    output = Path(args.output).expanduser().resolve()
    atomic_write_text(
        output,
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "observed_calls": receipt["observed_local_call_count"],
                "long_session_evals": receipt["long_session_eval_count"],
                "median_utilization": receipt["median_context_utilization"],
                "p95_utilization": receipt["p95_context_utilization"],
                "content_sha256": receipt["content_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
