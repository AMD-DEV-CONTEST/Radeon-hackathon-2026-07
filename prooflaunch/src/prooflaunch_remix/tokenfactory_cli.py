from __future__ import annotations

import argparse
import json
from pathlib import Path

from .files import atomic_write_text
from .inference_gateway import (
    InferenceGatewayCallError,
    InferenceScope,
    OpenAICompatibleThirdPartyClient,
    ResilientInferenceGateway,
    load_third_party_provider_specs,
)
from .tokenfactory import (
    TOKEN_FACTORY_PUBLIC_MODELS,
    TokenFactoryCallError,
    TokenFactoryClient,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run official-first AMD Radeon Token Factory inference with an "
            "optional audited third-party fallback."
        )
    )
    parser.add_argument(
        "--request",
        required=True,
        help="UTF-8 JSON file containing a non-empty messages array.",
    )
    parser.add_argument("--purpose", required=True)
    parser.add_argument(
        "--model",
        action="append",
        choices=TOKEN_FACTORY_PUBLIC_MODELS,
        help="Official model preference; repeat for ordered failover.",
    )
    parser.add_argument("--output", required=True)
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--max-tokens", type=int, default=1024)
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--retry-rounds", type=int, default=1)
    parser.add_argument(
        "--fallback-config",
        help="Approved third-party fallback configuration.",
    )
    parser.add_argument(
        "--scope",
        choices=tuple(item.value for item in InferenceScope),
        default=InferenceScope.DEVELOPMENT_CORE.value,
    )
    args = parser.parse_args()

    request_path = Path(args.request).expanduser().resolve()
    request = json.loads(request_path.read_text(encoding="utf-8"))
    messages = request.get("messages")
    client = TokenFactoryClient()
    if args.fallback_config:
        specs = load_third_party_provider_specs(args.fallback_config)
        gateway = ResilientInferenceGateway(
            official_client=client,
            third_party_clients=tuple(
                OpenAICompatibleThirdPartyClient(spec) for spec in specs
            ),
        )
        try:
            result = gateway.complete(
                messages,
                scope=InferenceScope(args.scope),
                purpose=args.purpose,
                temperature=args.temperature,
                max_tokens=args.max_tokens,
                official_models=tuple(
                    args.model or TOKEN_FACTORY_PUBLIC_MODELS
                ),
                official_retry_rounds=args.retry_rounds,
            )
        except InferenceGatewayCallError as error:
            atomic_write_text(
                args.receipt,
                json.dumps(
                    error.receipt,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
            )
            raise SystemExit(str(error)) from error
        atomic_write_text(
            args.output,
            json.dumps(
                {
                    "provider": result.provider,
                    "model": result.model,
                    "route": result.route,
                    "content": result.content,
                    "response_id": result.response_id,
                    "finish_reason": result.finish_reason,
                    "usage": result.usage,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
        )
        atomic_write_text(
            args.receipt,
            json.dumps(
                result.receipt,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
        )
        return
    try:
        result = client.complete(
            messages,
            models=tuple(args.model or TOKEN_FACTORY_PUBLIC_MODELS),
            purpose=args.purpose,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
            retry_rounds=args.retry_rounds,
        )
    except TokenFactoryCallError as error:
        atomic_write_text(
            args.receipt,
            json.dumps(
                error.receipt,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
        )
        raise SystemExit(str(error)) from error

    atomic_write_text(
        args.output,
        json.dumps(
            {
                "provider": result.provider,
                "model": result.model,
                "content": result.content,
                "response_id": result.response_id,
                "finish_reason": result.finish_reason,
                "usage": result.usage,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )
    atomic_write_text(
        args.receipt,
        json.dumps(
            result.receipt,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )


if __name__ == "__main__":
    main()
