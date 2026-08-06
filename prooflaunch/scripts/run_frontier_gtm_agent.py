#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_frontier_cloud_agent import execute_frontier_gtm_agent
from prooflaunch_remix.gtm_recent_organic_signal_pack import verify_recent_organic_signal_pack
from prooflaunch_remix.inference_gateway import (
    OpenAICompatibleThirdPartyClient,
    load_third_party_provider_specs,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the cloud-frontier GTM employee with no local-model fallback.")
    parser.add_argument("--brief", required=True, type=Path)
    parser.add_argument("--provider-config", required=True, type=Path)
    parser.add_argument("--named-capability-distillation", required=True, type=Path)
    parser.add_argument("--human-capability-kernel", required=True, type=Path)
    parser.add_argument("--learning-memory", type=Path)
    parser.add_argument("--signal-pack", type=Path, help="Verified 90–180 day public organic signal pack; overrides the two manual signal fields")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--provider", help="Provider id; defaults to the first credential-ready route")
    parser.add_argument("--timeout-seconds", type=float, default=90.0)
    args = parser.parse_args()
    brief = json.loads(args.brief.read_text(encoding="utf-8"))
    signal_pack = None
    if args.signal_pack is not None:
        signal_pack = json.loads(args.signal_pack.read_text(encoding="utf-8"))
        verify_recent_organic_signal_pack(signal_pack)
    distillation = json.loads(args.named_capability_distillation.read_text(encoding="utf-8"))
    human_capability_kernel = json.loads(args.human_capability_kernel.read_text(encoding="utf-8"))
    learning_memory = None if args.learning_memory is None else json.loads(args.learning_memory.read_text(encoding="utf-8"))
    specs = load_third_party_provider_specs(args.provider_config)
    ready = [spec for spec in specs if os.environ.get(spec.api_key_env)]
    if args.provider:
        ready = [spec for spec in ready if spec.provider == args.provider]
    if not ready:
        raise SystemExit("No requested cloud-frontier credential is present; local fallback is intentionally forbidden.")
    client = OpenAICompatibleThirdPartyClient(ready[0])
    result = execute_frontier_gtm_agent(
        brief,
        client,
        named_capability_distillation=distillation,
        human_capability_kernel=human_capability_kernel,
        recent_signal_pack=signal_pack,
        learning_memory=learning_memory,
        timeout_seconds=args.timeout_seconds,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(args.output, json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "output": str(args.output), "provider": ready[0].provider, "model": ready[0].model,
        "cloud_model_call_count": result["cloud_model_call_count"], "local_model_call_count": 0,
        "content_sha256": result["content_sha256"],
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
