# -*- coding: utf-8 -*-
"""Audit train/dev with the pinned Qwen3-14B tokenizer; never read sealed test."""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any

import train_lora_rocm


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def audit_rows(tokenizer: Any, rows: list[dict[str, Any]], max_length: int) -> dict[str, Any]:
    lengths: list[int] = []
    loss_tokens = 0
    for row in rows:
        encoded = train_lora_rocm.encode_example(tokenizer, row, max_length)
        lengths.append(int(encoded["sequence_length"]))
        loss_tokens += int(encoded["loss_tokens"])
    lengths.sort()
    if not lengths:
        raise ValueError("token audit split is empty")
    return {
        "examples": len(lengths),
        "min": lengths[0],
        "max": lengths[-1],
        "p50": lengths[len(lengths) // 2],
        "p95": lengths[min(len(lengths) - 1, int(len(lengths) * .95))],
        "assistantLossTokens": loss_tokens,
        "silentTruncation": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--train", type=Path, required=True)
    parser.add_argument("--dev", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default="Qwen/Qwen3-14B")
    parser.add_argument("--model-revision", default=train_lora_rocm.QWEN3_14B_REVISION)
    parser.add_argument("--max-length", type=int, default=1536)
    args = parser.parse_args()

    # This validates only the manifest-bound train/dev artifacts. There is
    # intentionally no sealed-test argument, so test data cannot enter audit.
    manifest = train_lora_rocm._validate_manifest(args.manifest, args.train, args.dev)
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(
        args.model, revision=args.model_revision, use_fast=True,
    )
    splits = {
        "train": audit_rows(tokenizer, read_jsonl(args.train), args.max_length),
        "dev": audit_rows(tokenizer, read_jsonl(args.dev), args.max_length),
    }
    report = {
        "schemaVersion": "yijian-agent-token-audit-v1",
        "passed": True,
        "createdAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "model": args.model,
        "modelRevision": args.model_revision,
        "maxLength": args.max_length,
        "manifestSha256": train_lora_rocm.sha256_file(args.manifest),
        "trainSha256": train_lora_rocm.sha256_file(args.train),
        "devSha256": train_lora_rocm.sha256_file(args.dev),
        "sealedTestAccessed": False,
        "splits": splits,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
