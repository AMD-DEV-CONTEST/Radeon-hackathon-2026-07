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
    execute_text_craft_quality_loop,
    write_text_challenger_bundle,
)
from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.inference_gateway import (
    OpenAICompatibleThirdPartyClient,
    ResilientInferenceGateway,
    load_third_party_provider_specs,
)
from prooflaunch_remix.tokenfactory import (
    TOKEN_FACTORY_PUBLIC_MODELS,
    TokenFactoryClient,
    TokenFactoryConfigurationError,
)


def _inside_project(path: str) -> Path:
    resolved = Path(path).expanduser().resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError as error:
        raise argparse.ArgumentTypeError("path must remain inside the project root") from error
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Execute the three evidence-bound GTM text challenger requests through the "
            "official-first gateway and stage a role-hidden human blind-review packet."
        )
    )
    parser.add_argument("--plan", required=True, type=_inside_project)
    parser.add_argument("--channel-copy", required=True, type=_inside_project)
    parser.add_argument("--output-dir", required=True, type=_inside_project)
    parser.add_argument(
        "--model",
        action="append",
        choices=TOKEN_FACTORY_PUBLIC_MODELS,
        help="Ordered official Token Factory model; repeat to enable failover.",
    )
    parser.add_argument(
        "--fallback-config",
        type=_inside_project,
        help="Optional reviewed development-only third-party fallback configuration.",
    )
    parser.add_argument("--timeout-seconds", type=float, default=45.0)
    parser.add_argument("--official-retry-rounds", type=int, default=0)
    parser.add_argument(
        "--skip-craft-quality-loop",
        action="store_true",
        help="Skip the default specialist review/repair/re-review loop.",
    )
    args = parser.parse_args()

    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    channel_copy = json.loads(args.channel_copy.read_text(encoding="utf-8"))
    try:
        official = TokenFactoryClient()
    except TokenFactoryConfigurationError as error:
        raise SystemExit(
            "Official credential preflight failed. Set RADEON_TOKEN_FACTORY_API_KEY in "
            "the process environment; never write it into the project. " + str(error)
        ) from error
    third_party_clients = ()
    if args.fallback_config is not None:
        specs = load_third_party_provider_specs(args.fallback_config)
        third_party_clients = tuple(
            OpenAICompatibleThirdPartyClient(spec) for spec in specs
        )
    gateway = ResilientInferenceGateway(
        official_client=official,
        third_party_clients=third_party_clients,
    )
    try:
        execution = execute_text_challenger_plan(
            plan,
            gateway,
            official_models=tuple(args.model or (TOKEN_FACTORY_PUBLIC_MODELS[0],)),
            timeout_seconds=args.timeout_seconds,
            official_retry_rounds=args.official_retry_rounds,
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
                        "completed_call_count": execution["completed_call_count"],
                        "output_sha256": hashes,
                        "blind_review_packet_created": False,
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
            return 2
        craft_quality = None
        human_review_execution = execution
        if not args.skip_craft_quality_loop:
            craft_quality = execute_text_craft_quality_loop(
                plan,
                execution,
                gateway,
                official_models=tuple(args.model or (TOKEN_FACTORY_PUBLIC_MODELS[0],)),
                timeout_seconds=args.timeout_seconds,
                official_retry_rounds=args.official_retry_rounds,
            )
            if not craft_quality["all_territories_advisory_pass"]:
                hashes = write_text_challenger_bundle(
                    args.output_dir,
                    plan=plan,
                    execution=execution,
                )
                atomic_write_text(
                    args.output_dir / "text-craft-quality-execution.json",
                    json.dumps(
                        craft_quality, ensure_ascii=False, indent=2, sort_keys=True
                    ),
                )
                print(
                    json.dumps(
                        {
                            "status": "blocked_craft_quality_loop",
                            "craft_quality_call_count": craft_quality[
                                "craft_quality_call_count"
                            ],
                            "output_sha256": hashes,
                            "blind_review_packet_created": False,
                        },
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                    )
                )
                return 2
            human_review_execution = craft_quality["human_review_execution"]
        blind = build_text_blind_review_bundle(
            plan,
            human_review_execution,
            channel_copy,
            randomization_secret=secrets.token_hex(32),
        )
        hashes = write_text_challenger_bundle(
            args.output_dir,
            plan=plan,
            execution=human_review_execution,
            public_packet=blind["public_packet"],
            private_mapping=blind["private_mapping"],
        )
        if craft_quality is not None:
            atomic_write_text(
                args.output_dir / "text-craft-quality-execution.json",
                json.dumps(craft_quality, ensure_ascii=False, indent=2, sort_keys=True),
            )
            hashes["text-craft-quality-execution.json"] = hashlib.sha256(
                (args.output_dir / "text-craft-quality-execution.json").read_bytes()
            ).hexdigest()
    except TextChallengerRunError as error:
        raise SystemExit(f"text challenger failed closed: {error}") from error

    print(
        json.dumps(
            {
                "status": execution["status"],
                "completed_call_count": execution["completed_call_count"],
                "craft_quality_call_count": (
                    craft_quality["craft_quality_call_count"]
                    if craft_quality is not None
                    else 0
                ),
                "pair_count": blind["public_packet"]["pair_count"],
                "review_task_count": blind["public_packet"]["review_task_count"],
                "output_sha256": hashes,
                "blind_review_completed": False,
                "winner_selected": False,
                "radeon_local_inference_observed": False,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
