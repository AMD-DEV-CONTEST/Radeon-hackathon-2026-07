"""Perciqa Cortex agent SDK — quickstart.

Run with:

    python -m examples.quickstart --broker ws://localhost:8765

Requires a running cortex-broker + cortex-node. Prints a friendly error
when the broker is unreachable so the demo operator knows what's missing.
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from cortex.core.article import Scope
from cortex.node.node import CortexNode
from cortex.sdk.client import CortexClient
from cortex.sdk.exceptions import CortexSDKError
from cortex.sdk.langchain_adapter import CortexRetriever


def main() -> int:
    parser = argparse.ArgumentParser(description="Cortex SDK quickstart")
    parser.add_argument("--broker", default="ws://localhost:8765",
                        help="broker WebSocket URL")
    parser.add_argument("--org", default="did:org:alpha")
    parser.add_argument("--agent", default="did:org:alpha#agent-1")
    args = parser.parse_args()

    async def run():
        node = CortexNode(
            org_did=args.org,
            agent_did=args.agent,
            key_paths="keys",
            broker_url=args.broker,
            config_path="config.yaml",
        )
        try:
            await node.start()
        except Exception as exc:
            print(f"[quickstart] could not reach broker at {args.broker}: {exc}",
                  file=sys.stderr)
            print("[quickstart] Is cortex-broker running? (deploy/Makefile up-broker)",
                  file=sys.stderr)
            return 1

        try:
            client = CortexClient(node)
            art_id = client.publish_finding(
                content="Demo finding: anomalous DNS tunnel from garage-12.",
                payload={"asset": "garage-12"},
                scope=Scope.PUBLIC,
            )
            print(f"[quickstart] published finding -> {art_id}")

            retriever = CortexRetriever(node=node, top_k=5, min_trust=0.3,
                                       topics={"soc"}, scopes={"PUBLIC"})
            docs = retriever._get_relevant_documents(
                "DNS tunnel", run_manager=None
            )
            for d in docs:
                print(f"[quickstart] doc trust={d.metadata['trust']}: {d.page_content[:80]}")
        except CortexSDKError as exc:
            print(f"[quickstart] SDK error: {exc}", file=sys.stderr)
            return 2
        finally:
            await node.stop()
        return 0

    return asyncio.run(run())


if __name__ == "__main__":
    raise SystemExit(main())
