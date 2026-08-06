from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from prooflaunch_remix.files import atomic_write_bytes
from prooflaunch_remix.gtm_organic_breakout_admission import (
    compile_organic_breakout_admissions,
    verify_organic_breakout_admissions,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = (
    ROOT / "evidence/v10/gtm-public-organic-tiktok-pinterest-pack-v1-live"
)
DEFAULT_OUTPUT = ROOT / "evidence/v10/gtm-organic-breakout-admission-v1.json"
DEFAULT_MARKDOWN = ROOT / "docs/product/GTM_ORGANIC_BREAKOUT_ADMISSION_V1.md"


def _load_jsonl(path: Path) -> list[object]:
    rows: list[object] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as error:
            raise ValueError(f"{path}:{line_number} is invalid JSON") from error
    return rows


def build_receipt(input_root: Path = DEFAULT_INPUT) -> dict[str, Any]:
    input_root = input_root.resolve()
    input_root.relative_to(ROOT)
    collection_receipt_path = input_root / "collection-receipt.json"
    collection_receipt = json.loads(collection_receipt_path.read_text(encoding="utf-8"))
    observed_at = str(collection_receipt["captured_at"])
    sources: list[dict[str, Any]] = []
    for index, path in enumerate(
        sorted(input_root.glob("source-*/collector-output.jsonl")), start=1
    ):
        payload = path.read_bytes()
        sources.append(
            {
                "source_id": path.parent.name,
                "capture_sha256": hashlib.sha256(payload).hexdigest(),
                "records": _load_jsonl(path),
                "source_order": index,
            }
        )
    receipt = compile_organic_breakout_admissions(
        sources,
        observed_at=observed_at,
    )
    receipt["collection_receipt_sha256"] = hashlib.sha256(
        collection_receipt_path.read_bytes()
    ).hexdigest()
    unsigned = dict(receipt)
    unsigned.pop("content_sha256", None)
    receipt["content_sha256"] = hashlib.sha256(
        json.dumps(
            unsigned,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    verify_organic_breakout_admissions(receipt)
    return receipt


def render_markdown(receipt: dict[str, Any]) -> str:
    lines = [
        "# GTM organic-breakout admission V1",
        "",
        "## Current result",
        "",
        f"- Normalized timestamped public items: **{receipt['normalized_item_count']}**",
        f"- Candidate-level relative breakouts admitted: **{receipt['admitted_candidate_count']}**",
        f"- Preferred 90-day candidates: **{receipt['preferred_90_day_candidate_count']}**",
        "- Training admitted: **no**",
        "- Automatic strategy or memory mutation: **no**",
        "",
        "## Admission semantics",
        "",
        "Every retained candidate has an HTTPS source, timestamp, same-source baseline of at least ten items, relative attention or interaction evidence, a paid-distribution disclosure, source/capture SHA-256, and no copied creative expression.",
        "",
        "The receipt deliberately calls these `relative_breakout_candidate`, not proven organic winners. Missing platform ad-library or creator-side spend evidence remains disclosed, and a named human must abstract any mechanism before it may enter strategy memory.",
        "",
        "## Top candidates",
        "",
        "| Candidate | Age (days) | Attention index | Interaction index | Paid-status disclosure |",
        "|---|---:|---:|---:|---|",
    ]
    for row in receipt["candidates"][:10]:
        lines.append(
            f"| `{row['candidate_id']}` | {row['age_days']:.1f} | "
            f"{float(row['relative_attention'] or 0):.2f}× | "
            f"{float(row['relative_interactions'] or 0):.2f}× | "
            f"{row['paid_distribution_status']} |"
        )
    lines += ["", "## Truth boundary", "", receipt["truth_boundary"], ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN)
    args = parser.parse_args()
    output = args.output.resolve()
    output.relative_to(ROOT)
    markdown_output = args.markdown_output.resolve()
    markdown_output.relative_to(ROOT)
    receipt = build_receipt(args.input_root)
    atomic_write_bytes(
        output,
        (
            json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n"
        ).encode("utf-8"),
    )
    atomic_write_bytes(markdown_output, render_markdown(receipt).encode("utf-8"))
    print(
        json.dumps(
            {
                "admitted_candidate_count": receipt["admitted_candidate_count"],
                "normalized_item_count": receipt["normalized_item_count"],
                "content_sha256": receipt["content_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
