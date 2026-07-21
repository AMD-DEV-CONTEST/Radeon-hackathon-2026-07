from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from pathlib import Path

import uvicorn

from cortex.console.attack_matrix import AttackMatrixTracker
from cortex.console.backend import create_app_with_broker
from cortex.console.broker_subscriber import BrokerSubscriber
from cortex.console.fanout import Fanout
from cortex.console.node_registry import NodeRegistry
from cortex.console.ring_buffer import EventRingBuffer, MetricsRingBuffer


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="cortex.console")
    p.add_argument("--broker", default="wss://localhost:7432")
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--static", default="frontend/dist")
    p.add_argument("--registry", default="org_registry.json")
    p.add_argument("--host", default="0.0.0.0")
    return p.parse_args(argv)


@dataclass
class Lifecycle:
    subscriber: BrokerSubscriber | None
    async def stop(self):
        if self.subscriber is None:
            return
        await self.subscriber.stop()


def build_app(broker_url: str, static_dir: Path, registry_path: Path):
    fanout = Fanout()
    attack = AttackMatrixTracker()
    events_ring = EventRingBuffer(1000)
    metrics_ring = MetricsRingBuffer(60)
    nodes = NodeRegistry()

    def on_event_sync(payload):
        events_ring.append(payload)
        attack.on_event(payload)

    fanout_with_hooks = Fanout(on_event=on_event_sync)

    sub = BrokerSubscriber(uri=broker_url, fanout=fanout_with_hooks)
    app = create_app_with_broker(static_dir=static_dir, registry_path=registry_path,
                                 fanout=fanout_with_hooks, broker_url=broker_url,
                                 node_registry=nodes, attack_matrix=attack)
    app.state.subscriber = sub
    return app, Lifecycle(subscriber=sub)


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.INFO)
    static_dir = Path(args.static)
    registry_path = Path(args.registry)
    app, lifecycle = build_app(broker_url=args.broker, static_dir=static_dir, registry_path=registry_path)

    @app.on_event("startup")
    async def _start():
        app.state.subscriber.start()

    @app.on_event("shutdown")
    async def _stop():
        await app.state.subscriber.stop()

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
