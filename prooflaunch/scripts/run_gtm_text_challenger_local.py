#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from prooflaunch_remix.gtm_text_challenger_runner import (
    TextChallengerRunError,
    build_text_blind_review_bundle,
    execute_text_challenger_plan,
    write_text_challenger_bundle,
)
from prooflaunch_remix.inference_gateway import OllamaLocalClient, OllamaLocalSpec


DEFAULT_MODEL_RECEIPT = ROOT / "artifacts/local-gtm-generative-baseline-v1/receipt.json"


def _inside_project(path: str) -> Path:
    resolved = Path(path).expanduser().resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError as error:
        raise argparse.ArgumentTypeError("path must remain inside the project root") from error
    return resolved


def _model_identity(receipt_path: Path) -> tuple[str, str, str]:
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    model = receipt.get("model")
    if not isinstance(model, dict):
        raise SystemExit("local model receipt has no model identity")
    name = str(model.get("name") or "").strip()
    digest = str(model.get("digest") or "").strip()
    if not name or len(digest) != 64 or any(
        character not in "0123456789abcdef" for character in digest
    ):
        raise SystemExit("local model receipt has an invalid pinned model digest")
    if receipt.get("localhost_only") is not True:
        raise SystemExit("local model receipt does not prove a localhost-only route")
    if receipt.get("network_download_performed") is not False:
        raise SystemExit("local model receipt indicates an unapproved model download")
    return name, digest, hashlib.sha256(receipt_path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the three bounded GTM creative challenger requests through an already "
            "installed digest-pinned Ollama model. No model download or cloud call occurs."
        )
    )
    parser.add_argument("--plan", required=True, type=_inside_project)
    parser.add_argument("--channel-copy", required=True, type=_inside_project)
    parser.add_argument("--output-dir", required=True, type=_inside_project)
    parser.add_argument(
        "--model-receipt",
        type=_inside_project,
        default=DEFAULT_MODEL_RECEIPT,
        help="Receipt for an already installed local model; defaults to the frozen baseline.",
    )
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    args = parser.parse_args()

    model_name, model_digest, model_receipt_file_sha256 = _model_identity(
        args.model_receipt
    )
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    channel_copy = json.loads(args.channel_copy.read_text(encoding="utf-8"))
    local = OllamaLocalClient(OllamaLocalSpec(model_name, model_digest))
    try:
        execution = execute_text_challenger_plan(
            plan,
            local,
            timeout_seconds=args.timeout_seconds,
            official_retry_rounds=0,
        )
        if execution["status"] != "generated_validated_unreviewed":
            hashes = write_text_challenger_bundle(
                args.output_dir,
                plan=plan,
                execution=execution,
            )
            print(
                json.dumps(
                    {
                        "status": execution["status"],
                        "route": "local_ollama",
                        "model": model_name,
                        "model_digest": model_digest,
                        "model_receipt_file_sha256": model_receipt_file_sha256,
                        "completed_call_count": execution["completed_call_count"],
                        "output_sha256": hashes,
                        "blind_review_packet_created": False,
                        "network_download_performed": False,
                        "cloud_api_calls": 0,
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
            return 2
        blind = build_text_blind_review_bundle(
            plan,
            execution,
            channel_copy,
            randomization_secret=secrets.token_hex(32),
        )
        hashes = write_text_challenger_bundle(
            args.output_dir,
            plan=plan,
            execution=execution,
            public_packet=blind["public_packet"],
            private_mapping=blind["private_mapping"],
        )
    except TextChallengerRunError as error:
        raise SystemExit(f"local text challenger failed closed: {error}") from error

    print(
        json.dumps(
            {
                "status": execution["status"],
                "route": "local_ollama",
                "model": model_name,
                "model_digest": model_digest,
                "model_receipt_file_sha256": model_receipt_file_sha256,
                "completed_call_count": execution["completed_call_count"],
                "pair_count": blind["public_packet"]["pair_count"],
                "review_task_count": blind["public_packet"]["review_task_count"],
                "output_sha256": hashes,
                "blind_review_completed": False,
                "winner_selected": False,
                "radeon_local_inference_observed": False,
                "network_download_performed": False,
                "cloud_api_calls": 0,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
