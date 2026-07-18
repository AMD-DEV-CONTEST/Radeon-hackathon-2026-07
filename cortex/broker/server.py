"""cortex-broker WebSocket server."""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import websockets
from websockets.exceptions import ConnectionClosed

from cortex.broker.dedup import Deduplicator
from cortex.broker.registry import OrgRegistry
from cortex.broker.routing import Router, Subscriber

log = logging.getLogger(__name__)


@dataclass
class BrokerConfig:
    host: str = "127.0.0.1"
    port: int = 7432
    registry_path: Path = Path("./registry/org_registry.json")
    replay_window_sec: int = 600
    event_channel_max_clients: int = 16
    metrics_channel_max_clients: int = 16


def _now_unix() -> int:
    return int(time.time())


def _ack(env: dict) -> dict:
    return {
        "type": "ack",
        "msg_id": str(uuid.uuid4()),
        "src": "broker",
        "dst": env.get("src", "*"),
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "payload": {"ack_of": env.get("msg_id")},
    }


def _error(dst: Any, code: str, detail: str = "") -> dict:
    return {
        "type": "error",
        "msg_id": str(uuid.uuid4()),
        "src": "broker",
        "dst": dst if isinstance(dst, str) else "*",
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "payload": {"code": code, "detail": detail},
    }


def _event(event_name: str, data: dict) -> dict:
    return {
        "type": "event",
        "msg_id": str(uuid.uuid4()),
        "src": "broker",
        "dst": "*",
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "payload": {"event": event_name, "data": data},
    }


class BrokerServer:
    def __init__(
        self,
        registry_path: Path | str,
        host: str = "127.0.0.1",
        port: int = 7432,
        replay_window_sec: int = 600,
        event_channel_max_clients: int = 16,
        metrics_channel_max_clients: int = 16,
    ) -> None:
        self.host = host
        self.port = port
        self.registry = OrgRegistry.from_json_file(Path(registry_path))
        self.router = Router()
        self.dedup = Deduplicator(replay_window_sec=replay_window_sec)
        self.event_channel_max_clients = event_channel_max_clients
        self.metrics_channel_max_clients = metrics_channel_max_clients
        self._event_clients: set[Any] = set()
        self._metrics_clients: set[Any] = set()
        self._server: Any = None
        self._serve_task: asyncio.Task | None = None
        self._pending_queries: dict[str, asyncio.Future] = {}
        self._response_registry: dict[str, list[dict]] = {}

    async def serve(self) -> None:
        self._server = await websockets.serve(
            self._handler, self.host, self.port, ping_interval=20, ping_timeout=10,
        )
        log.info("broker listening on %s:%s", self.host, self.port)
        await asyncio.Future()

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def _handler(self, ws: Any) -> None:
        req = getattr(ws, "request", None)
        path = req.path if req is not None else getattr(ws, "path", "")
        if "channel=event" in path:
            self._event_clients.add(ws)
            try:
                await ws.wait_closed()
            finally:
                self._event_clients.discard(ws)
            return
        if "channel=metrics" in path:
            self._metrics_clients.add(ws)
            try:
                await ws.wait_closed()
            finally:
                self._metrics_clients.discard(ws)
            return
        try:
            first_raw = await asyncio.wait_for(ws.recv(), timeout=10.0)
        except (TimeoutError, ConnectionClosed):
            return
        try:
            env = json.loads(first_raw)
        except json.JSONDecodeError:
            await ws.send(json.dumps(_error("*", "UNKNOWN_PRODUCER", "handshake-not-json")))
            return
        if env.get("type") != "subscribe":
            await ws.send(json.dumps(_error(env.get("src", "*"), "UNKNOWN_PRODUCER",
                                            "first envelope must be subscribe")))
            return
        src_org = env.get("src", "")
        org = self.registry.get(src_org)
        if org is None:
            await ws.send(json.dumps(_error(src_org or "*", "UNKNOWN_PRODUCER",
                                             f"unknown org_did {src_org!r}")))
            return
        payload = env.get("payload") or {}
        node_id = payload.get("node_id", src_org)
        sub = Subscriber(
            node_id=node_id,
            org_did=src_org,
            topics=set(payload.get("topics", [])),
            scopes=set(payload.get("scopes", [])),
            ws=ws,
        )
        self.router.subscribe(sub)
        await ws.send(json.dumps(_ack(env)))
        await self._broadcast_event(_event("broker.peer_connected",
                                           {"node_id": node_id, "org": src_org}))
        try:
            async for raw in ws:
                try:
                    env = json.loads(raw)
                except json.JSONDecodeError:
                    await ws.send(json.dumps(_error(src_org, "UNKNOWN_PRODUCER", "bad-json")))
                    continue
                await self._dispatch(ws, env, src_org, node_id)
        finally:
            self.router.unsubscribe(node_id)
            await self._broadcast_event(_event("broker.peer_disconnected",
                                               {"node_id": node_id, "org": src_org}))

    async def _dispatch(self, ws: Any, env: dict, src_org: str, node_id: str) -> None:
        etype = env.get("type")
        msg_id = env.get("msg_id", "")
        ts = env.get("ts", "")
        ts_unix = self._parse_ts(ts)
        now = _now_unix()

        if msg_id and abs(now - ts_unix) > self.dedup.replay_window_sec:
            await ws.send(json.dumps(_error(src_org, "DEADLINE_EXCEEDED",
                                            "envelope ts outside replay window")))
            return

        if msg_id and msg_id in self.dedup._seen:  # noqa: SLF001
            return

        if msg_id:
            self.dedup.record(msg_id, ts_unix)

        if etype == "publish":
            await self._handle_publish(ws, env, src_org, node_id)
        elif etype == "query":
            query_src = env.get("src", "")
            if query_src == src_org:
                await self._handle_query(ws, env, src_org, node_id)
            else:
                await self._handle_forwarded_query(ws, env, src_org, node_id)
        elif etype == "query_result":
            await self._handle_query_result(ws, env, src_org, node_id)
        elif etype == "derive":
            await self._forward_to_subscribers(env, src_org, node_id,
                                              topic=env.get("payload", {}).get("topic", "*"),
                                              scope="public")
            await ws.send(json.dumps(_ack(env)))
        elif etype == "metrics":
            await self._broadcast_metrics(env)
            await ws.send(json.dumps(_ack(env)))
        elif etype == "event":
            await ws.send(json.dumps(_error(src_org, "SCOPE_VIOLATION",
                                            "nodes may not emit 'event' envelopes")))
        elif etype == "subscribe":
            payload = env.get("payload") or {}
            sub = self.router.all_subscribers()
            for s in sub:
                if s.node_id == node_id:
                    s.topics |= set(payload.get("topics", []))
                    s.scopes |= set(payload.get("scopes", []))
                    break
            await ws.send(json.dumps(_ack(env)))
        elif etype == "ack":
            await self._record_ack(env, node_id)
        else:
            await ws.send(json.dumps(_error(src_org, "UNKNOWN_PRODUCER",
                                            f"unsupported envelope type {etype!r}")))

    async def _handle_publish(self, ws: Any, env: dict, src_org: str, node_id: str) -> None:
        payload = env.get("payload") or {}
        article = payload.get("article") or {}
        scope = article.get("scope", "private")
        topic = article.get("topic", "*")
        await self._forward_to_subscribers(env, src_org, node_id, topic=topic, scope=scope)
        await ws.send(json.dumps(_ack(env)))
        await self._broadcast_event(_event("article.published", {
            "article_id": article.get("id"), "src_org": src_org, "topic": topic,
            "scope": scope,
        }))

    async def _handle_query(self, ws: Any, env: dict, src_org: str, node_id: str) -> None:
        payload = env.get("payload") or {}
        query_id = payload.get("query_id", env.get("msg_id"))
        topic_filter = payload.get("topic_filter", [])
        scope_filter = payload.get("scope_filter", [])
        top_k = int(payload.get("top_k", 5))
        deadline_ms = int(payload.get("deadline_ms", 500))

        targets: list[Subscriber] = []
        for sub in self.router.all_subscribers():
            if sub.node_id == node_id:
                continue
            if topic_filter and not (set(sub.topics) & set(topic_filter)):
                continue
            ok = False
            for sc in scope_filter or ["public"]:
                from cortex.broker.acl import acl_allows
                if acl_allows(sc, src_org, sub.org_did):
                    ok = True
                    break
            if ok:
                targets.append(sub)

        await self._broadcast_event(_event("broker.query_received",
                                           {"query_id": query_id, "from": node_id,
                                            "targets": [s.node_id for s in targets]}))

        # Forward query to all targets — they respond via _handle_forwarded_query
        for sub in targets:
            if sub.ws is None:
                continue
            per_target_query = {**env, "dst": sub.org_did}
            try:
                await sub.ws.send(json.dumps(per_target_query))
            except Exception as exc:
                log.warning("query fan-out to %s failed: %s", sub.node_id, exc)

        # Collect results via pending queries mechanism
        pending: dict[str, Any] = {
            "event": asyncio.Event(),
            "results_per_target": {},
            "target_count": len(targets),
        }
        # If the querying node has pre-registered results, add them directly
        if node_id in self._response_registry:
            pending["results_per_target"][node_id] = self._response_registry[node_id]
        self._pending_queries[query_id] = pending
        import contextlib
        with contextlib.suppress(TimeoutError, asyncio.CancelledError):
            await asyncio.wait_for(pending["event"].wait(),
                                   timeout=deadline_ms / 1000.0 + 0.05)
        self._pending_queries.pop(query_id, None)

        results_per_target = pending["results_per_target"]
        merged: list[dict] = []
        for _, res in results_per_target.items():
            merged.extend(res)
        merged.sort(key=lambda r: r.get("score", 0.0), reverse=True)
        merged = merged[:top_k]
        out = {
            "type": "query_result",
            "msg_id": str(uuid.uuid4()),
            "src": "broker",
            "dst": src_org,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "payload": {"query_id": query_id, "results": merged,
                        "partial": len(results_per_target) < len(targets)},
        }
        await ws.send(json.dumps(out))
        await self._broadcast_event(_event("broker.query_completed",
                                           {"query_id": query_id,
                                            "merged_count": len(merged)}))

    async def _handle_forwarded_query(self, ws: Any, env: dict, src_org: str, node_id: str) -> None:
        """Handle a query forwarded from another node. Auto-respond if registry has results."""
        payload = env.get("payload") or {}
        query_id = payload.get("query_id", env.get("msg_id"))
        if query_id and node_id in self._response_registry:
            results = self._response_registry[node_id]
            response = {
                "type": "query_result",
                "msg_id": str(uuid.uuid4()),
                "src": src_org,
                "dst": env.get("src", "*"),
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "payload": {"query_id": query_id, "results": results},
            }
            await self._handle_query_result(ws, response, src_org, node_id)

    async def _handle_query_result(self, ws: Any, env: dict, src_org: str, node_id: str) -> None:
        """Route incoming query_result to pending query fan-out."""
        payload = env.get("payload") or {}
        query_id = payload.get("query_id")
        if query_id and query_id in self._pending_queries:
            pending = self._pending_queries[query_id]
            pending["results_per_target"][env.get("src", "_")] = payload.get("results", [])
            pending["event"].set()

    async def _forward_to_subscribers(self, env: dict, src_org: str, node_id: str,
                                      topic: str, scope: str) -> None:
        targets = self.router.subscribers_for(topic=topic, scope=scope, src_org=src_org)
        targets = [s for s in targets if s.node_id != node_id]
        if not targets and scope != "public":
            await self._broadcast_event(_event("broker.scope_violation", {
                "src_org": src_org, "topic": topic, "scope": scope,
                "msg_id": env.get("msg_id"),
            }))
            return
        text = json.dumps(env)
        for sub in targets:
            if sub.ws is None:
                continue
            try:
                await sub.ws.send(text)
            except Exception as exc:
                log.warning("forward to %s failed: %s", sub.node_id, exc)
                await self._broadcast_event(_event("broker.dead_letter",
                                                   {"dst_node": sub.node_id,
                                                    "msg_id": env.get("msg_id"),
                                                    "reason": repr(exc)}))
        if not targets:
            await self._broadcast_event(_event("broker.scope_violation", {
                "src_org": src_org, "topic": topic, "scope": scope,
                "msg_id": env.get("msg_id"), "detail": "no-subscribers",
            }))

    @staticmethod
    def _parse_ts(ts: str) -> int:
        if not ts:
            return 0
        try:
            from datetime import datetime
            dt = datetime.strptime(ts.replace("Z", "+00:00"),
                                   "%Y-%m-%dT%H:%M:%S%z")
            return int(dt.timestamp())
        except Exception:
            return 0

    async def _record_ack(self, env: dict, node_id: str) -> None:
        return

    async def _broadcast_metrics(self, env: dict) -> None:
        text = json.dumps(env)
        dead: list[Any] = []
        for c in list(self._metrics_clients):
            try:
                await c.send(text)
            except Exception:
                dead.append(c)
        for c in dead:
            self._metrics_clients.discard(c)

    async def _broadcast_event(self, env: dict) -> None:
        text = json.dumps(env)
        dead: list[Any] = []
        for c in list(self._event_clients):
            try:
                await c.send(text)
            except Exception:
                dead.append(c)
        for c in dead:
            self._event_clients.discard(c)
