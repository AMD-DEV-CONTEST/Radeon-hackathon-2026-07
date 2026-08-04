"""
CLI entrypoint for the RugBuster CIA Intelligence Agent (AMD AI DevMaster
Hackathon, Track 2 submission).

Usage:
    python main.py --chain AVAX --contract 0xTOKEN [--deployer 0xDEPLOYER] \\
        [--deploy-timestamp 1735689600] [--no-llm]

--no-llm runs planning + tool invocation only (fast, no GPU/model needed) —
useful for demoing capabilities #1/#2/#3 without waiting on model load.
Omit it to also run the local Qwen3-14B verdict step (capability requiring
local inference).
"""

from __future__ import annotations

import argparse
import json
import sys

from src.orchestrator import CIAAgent
from src.planner import ScanRequest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="RugBuster CIA Intelligence Agent")
    parser.add_argument("--chain", required=True, help="Chain preset: AVAX, BASE, or BNB")
    parser.add_argument("--contract", required=True, help="Token contract address")
    parser.add_argument("--deployer", default=None, help="Deployer/creator wallet address (optional)")
    parser.add_argument(
        "--deploy-timestamp", type=int, default=None, help="Unix timestamp of contract deployment (optional)"
    )
    parser.add_argument(
        "--no-llm", action="store_true", help="Skip the local LLM verdict step (planning + tools only)"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    request = ScanRequest(
        chain=args.chain,
        contract_address=args.contract,
        deployer_address=args.deployer,
        deploy_timestamp=args.deploy_timestamp,
    )

    agent = CIAAgent()
    if args.no_llm:
        result = agent.scan(request)
    else:
        result = agent.scan_with_verdict(request)

    print(json.dumps(result.__dict__, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
