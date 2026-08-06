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
from cortex.console.ring_buffer import EventRingBuffer


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
    subscribers: list[BrokerSubscriber]
    async def stop(self):
        for sub in self.subscribers:
            await sub.stop()


def _channel_url(broker_url: str, channel: str) -> str:
    sep = "?" if "?" not in broker_url else "&"
    return f"{broker_url}{sep}channel={channel}"


def build_app(broker_url: str, static_dir: Path, registry_path: Path):
    attack = AttackMatrixTracker()
    events_ring = EventRingBuffer(1000)
    nodes = NodeRegistry()

    def on_event_sync(payload):
        events_ring.append(payload)
        attack.on_event(payload)

    fanout_with_hooks = Fanout(on_event=on_event_sync)

    event_url = _channel_url(broker_url, "event")
    metrics_url = _channel_url(broker_url, "metrics")
    event_sub = BrokerSubscriber(uri=event_url, fanout=fanout_with_hooks)
    metrics_sub = BrokerSubscriber(uri=metrics_url, fanout=fanout_with_hooks)
    app = create_app_with_broker(static_dir=static_dir, registry_path=registry_path,
                                 fanout=fanout_with_hooks, broker_url=event_url,
                                 node_registry=nodes, attack_matrix=attack,
                                 events_ring=events_ring)
    app.state.subscribers = [event_sub, metrics_sub]
    app.state._seed_fn = lambda: _seed_ring_buffer(events_ring, attack)
    return app, Lifecycle(subscribers=[event_sub, metrics_sub])


def _seed_ring_buffer(events_ring: EventRingBuffer, attack: AttackMatrixTracker) -> None:
    import glob
    import json
    import sqlite3
    db_paths = glob.glob("/workspace/cortex/**/articles.sqlite", recursive=True)
    db_paths += glob.glob("/tmp/*/cortex-node/articles.sqlite")
    seen_ids: set[str] = set()
    for db_path in db_paths:
        try:
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cur.execute(
                "SELECT id, type, content, scope, payload_json, producer_org "
                "FROM articles ORDER BY rowid"
            )
            for row in cur.fetchall():
                art_id, art_type, content, scope, payload_json, producer_org = row
                if art_id in seen_ids:
                    continue
                seen_ids.add(art_id)
                payload = json.loads(payload_json) if payload_json else {}
                env = {
                    "event": "article.published",
                    "data": {
                        "article": {
                            "id": art_id,
                            "type": art_type,
                            "content": content,
                            "scope": scope,
                            "payload": payload,
                        },
                        "src_org": producer_org or "",
                    }
                }
                events_ring.append(env)
                attack.on_event(env)
            conn.close()
        except Exception:
            pass


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.INFO)
    static_dir = Path(args.static)
    registry_path = Path(args.registry)
    app, lifecycle = build_app(broker_url=args.broker, static_dir=static_dir,
                               registry_path=registry_path)

    @app.on_event("startup")
    async def _start():
        app.state._seed_fn()
        for sub in app.state.subscribers:
            sub.start()

    @app.on_event("shutdown")
    async def _stop():
        for sub in app.state.subscribers:
            await sub.stop()

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
