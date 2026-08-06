"""CLI entry point for Cortex nodes (used by docker-compose)."""
from __future__ import annotations

import argparse
import asyncio
import logging
import signal
from pathlib import Path

from cortex.node.config import load_config
from cortex.node.keys import ensure_keys
from cortex.node.node import CortexNode


def _start(args: argparse.Namespace) -> int:
    config_path = Path(args.config)
    cfg = load_config(config_path)

    logging.basicConfig(
        level=getattr(logging, cfg.logging.level.upper(), logging.INFO),
        filename=cfg.logging.file if cfg.logging.file != "stdout" else None,
    )

    keys = {
        "org": ensure_keys(Path(cfg.node.key_paths["org"])),
        "agent": ensure_keys(Path(cfg.node.key_paths["agent"]), kind="agent"),
    }

    health_file = config_path.parent / f"{config_path.stem}.node-healthy"
    node = CortexNode(
        org_did=cfg.node.org_did,
        agent_did=cfg.node.agent_did,
        key_paths=keys,
        broker_url=cfg.broker.url or args.broker_url,
        config_path=config_path,
        embedder_backend_override=args.embed_backend,
    )

    async def _run():
        stop_event = asyncio.Event()

        def _handle_sig(*_):
            stop_event.set()

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, _handle_sig)

        await node.start()
        health_file.write_text("healthy")
        logging.getLogger("cortex.cli").info(
            "Node %s started, broker=%s", cfg.node.agent_did, cfg.broker.url
        )
        await stop_event.wait()
        health_file.write_text("stopped")
        logging.getLogger("cortex.cli").info("Shutting down...")
        await node.stop()

    asyncio.run(_run())
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="cortex.cli")
    sub = ap.add_subparsers(dest="command", required=True)

    start_p = sub.add_parser("start", help="Start a Cortex node")
    start_p.add_argument("--config", "-c", required=True, type=str)
    start_p.add_argument("--broker-url", default="ws://localhost:7432")
    start_p.add_argument("--embed-backend", default=None)
    start_p.set_defaults(func=_start)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
