"""CLI: python -m cortex.broker --config broker.yaml"""
from __future__ import annotations

import argparse
import asyncio
import logging
import signal
from pathlib import Path

from cortex.broker.config import load_config
from cortex.broker.server import BrokerServer


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="cortex.broker", description="Perciqa Cortex broker")
    p.add_argument("--config", required=True, type=Path, help="Path to broker.yaml")
    return p.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    args = parse_args()
    cfg = load_config(args.config)

    server = BrokerServer(
        registry_path=cfg.registry_path,
        host=cfg.host,
        port=cfg.port,
        replay_window_sec=cfg.replay_window_sec,
        event_channel_max_clients=cfg.event_channel_max_clients,
        metrics_channel_max_clients=cfg.metrics_channel_max_clients,
    )

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    stop_event = asyncio.Event()
    loop.add_signal_handler(signal.SIGINT, stop_event.set)
    loop.add_signal_handler(signal.SIGTERM, stop_event.set)

    async def supervised_serve() -> None:
        serve_task = asyncio.create_task(server.serve())
        stop_task = asyncio.create_task(stop_event.wait())
        done, pending = await asyncio.wait({serve_task, stop_task},
                                          return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
        await server.stop()
        if serve_task in done:
            exc = serve_task.exception()
            if exc:
                raise exc

    try:
        loop.run_until_complete(supervised_serve())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
