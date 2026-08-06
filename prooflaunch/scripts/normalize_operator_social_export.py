#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.operator_social_export import compile_operator_social_export


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Normalize a public-only Zeeschuimer, 4CAT, Facepager, or platform export."
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--attestation", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    payload = compile_operator_social_export(
        args.input,
        platform=args.platform,
        operator_attestation=args.attestation,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        args.output,
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    print(
        json.dumps(
            {
                key: payload[key]
                for key in (
                    "platform",
                    "input_row_count",
                    "accepted_public_item_count",
                    "private_item_rejected_count",
                    "recent_item_count_180d",
                    "content_sha256",
                )
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
