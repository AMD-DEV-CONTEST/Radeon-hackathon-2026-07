from __future__ import annotations

import asyncio
import datetime as _dt
import json
import logging
from dataclasses import replace
from pathlib import Path
from typing import Any

from cortex.core.article import MemoryArticle, Provenance, Scope
from cortex.core.canonical import article_canonical_bytes, compute_article_id
from cortex.core.crypto import sign
from cortex.core.envelope import EnvelopeType
from cortex.node.broker_client import BrokerClient
from cortex.node.config import NodeConfig, load_config
from cortex.node.embedder import Embedder
from cortex.node.keys import load_keys
from cortex.node.provenance import ProvenanceGraph
from cortex.node.query import QueryResult, retrieve
from cortex.node.store import ArticleStore
from cortex.node.trust import TrustEngine
from cortex.node.vector_index import HNSWIndex

log = logging.getLogger("cortex.node")


class CortexNode:
    def __init__(
        self,
        org_did: str,
        agent_did: str,
        key_paths: dict[str, Path],
        broker_url: str,
        config_path: Path,
        embedder_backend_override: str | None = None,
    ) -> None:
        self.org_did = org_did
        self.agent_did = agent_did
        self.key_paths = {k: Path(v) for k, v in key_paths.items()}
        self.broker_url = broker_url
        self.config_path = Path(config_path)
        self.config: NodeConfig = load_config(self.config_path)
        if embedder_backend_override:
            self.config.embedder.backend = embedder_backend_override
        self.data_dir = self.config_path.parent / "cortex-node"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.store: ArticleStore | None = None
        self.embedder: Embedder | None = None
        self.vector_index: HNSWIndex | None = None
        self.provenance: ProvenanceGraph | None = None
        self.trust: TrustEngine | None = None
        self.broker: BrokerClient | None = None
        self._broker_override: Any = None
        self._org_priv: str = ""
        self._agent_priv: str = ""
        self._health_task: asyncio.Task | None = None

    async def start(self) -> None:
        self.store = ArticleStore(self.data_dir / "articles.sqlite")
        self.provenance = ProvenanceGraph(self.data_dir / "provenance.sqlite")
        self.vector_index = HNSWIndex(dim=384)
        self.trust = TrustEngine(
            default_org_reputation=self.config.trust.default_org_reputation,
            reputation_overrides=self.config.trust.reputation_overrides,
            half_life_days=self.config.trust.half_life_days,
            min_trust_default=self.config.trust.min_trust_default,
        )
        self._org_priv, self._agent_priv = load_keys(self.key_paths["org"], self.key_paths["agent"])
        self.embedder = Embedder(
            model=self.config.embedder.model, backend=self.config.embedder.backend,
            batch_size=self.config.embedder.batch_size,
            fallback_on_oom=self.config.embedder.fallback_on_oom,
            on_embed_failed=self._on_embed_failed,
        )
        self.broker = self._broker_override or BrokerClient(
            url=self.broker_url, org_did=self.org_did,
            registry_path=Path(self.config.broker.registry),
            replay_window_sec=self.config.broker.replay_window_sec,
            on_event=self._on_broker_event,
        )
        await self.broker.connect()
        self._health_task = asyncio.create_task(self._health_loop())

    async def stop(self) -> None:
        if self._health_task:
            self._health_task.cancel()
        if self.broker:
            await self.broker.stop()
        if self.store:
            self.store.close()
        if self.provenance:
            self.provenance.close()

    def _on_embed_failed(self, reason: str) -> None:
        log.warning("embed failed: %s", reason)
        if self.store:
            self.store.event_log_append("node.embed.fallback_cpu", None, {"reason": reason})

    def _on_broker_event(self, event: str, article_id: str | None, payload: dict) -> None:
        if self.store:
            self.store.event_log_append(event, article_id, payload)

    async def _health_loop(self) -> None:
        while True:
            await asyncio.sleep(5)
            if self.embedder is None:
                continue
            if not self.embedder._check_gpu() and not self.embedder.fallback_to_cpu:
                self.embedder.fallback_to_cpu = True
                self.embedder._device = "cpu"
                try:
                    self.embedder._model = self.embedder._model.to("cpu")
                except Exception:
                    pass
                self._on_embed_failed("healthcheck:no_gpu")
                self.store.event_log_append("node.embed.fallback_cpu", None, {"reason": "healthcheck"})

    def publish(self, article: MemoryArticle) -> str:
        assert self.store and self.embedder and self.vector_index and self.trust and self.provenance
        if len(article.content) > 2000:
            raise ValueError("content exceeds 2000 chars")
        canonical = article_canonical_bytes(article)
        agent_sig = sign(canonical, self._agent_priv)
        if article.org_signature is None and self._org_priv:
            org_sig = sign(canonical, self._org_priv)
        else:
            org_sig = article.org_signature
        art_id = compute_article_id(canonical)
        article = replace(article, id=art_id, agent_signature=agent_sig, org_signature=org_sig)
        embedding = self.embedder.embed_one(article.content)
        article = replace(article, embedding=embedding.tolist(), embedding_model=self.config.embedder.model)
        now = _dt.datetime.now(_dt.UTC)
        trust_score = self.trust.trust_for(article, now, _StoreAdapter(self.store), graph_version=self.provenance.graph_version)
        trust_expires = now + _dt.timedelta(days=self.config.trust.half_life_days)
        article = replace(article, trust_score=trust_score, trust_expiration=trust_expires)
        self.store.put(article, state="signed")
        self.vector_index.add(art_id, embedding)
        self.store.set_state(art_id, "indexed")
        if article.scope != Scope.PRIVATE:
            import uuid
            env_dict = {
                "type": EnvelopeType.PUBLISH.value, "msg_id": str(uuid.uuid4()),
                "src": self.org_did, "dst": "*",
                "ts": _dt.datetime.now(_dt.UTC).isoformat(),
                "payload": {"article_id": art_id, "canonical": canonical.hex(),
                            "embedding": embedding.astype("float16").tolist()},
            }
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.broker.publish_envelope(env_dict))
            except RuntimeError:
                asyncio.run(self.broker.publish_envelope(env_dict))
            self.store.set_state(art_id, "published")
            self.store.event_log_append("node.article.published", art_id, {"scope": article.scope})
        else:
            self.store.event_log_append("node.article.indexed_private", art_id, {})
        return art_id

    def query(self, query_text: str, topic_filter: list[str], scope_filter: list[str],
              top_k: int, min_trust: float, deadline_ms: int) -> list[QueryResult]:
        assert self.store and self.vector_index and self.embedder
        adapter = _StoreAdapter(self.store)
        return retrieve(
            store=adapter, vector_index=self.vector_index, embedder=self.embedder,
            query_text=query_text, topic_filter=topic_filter, scope_filter=scope_filter,
            top_k=top_k, min_trust=min_trust, deadline_ms=deadline_ms,
        )

    def derive(self, new_article: MemoryArticle, cited_article_ids: list[str]) -> str:
        assert self.provenance
        new_article = replace(new_article, cites=list(cited_article_ids))
        art_id = self.publish(new_article)
        for cited_id in cited_article_ids:
            self.provenance.add_citation(art_id, cited_id)
        import uuid
        env_dict = {
            "type": EnvelopeType.DERIVE.value, "msg_id": str(uuid.uuid4()),
            "src": self.org_did, "dst": "*",
            "ts": _dt.datetime.now(_dt.UTC).isoformat(),
            "payload": {"article_id": art_id, "cites": list(cited_article_ids)},
        }
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.broker.publish_envelope(env_dict))
        except RuntimeError:
            asyncio.run(self.broker.publish_envelope(env_dict))
        return art_id


class _StoreAdapter:
    def __init__(self, store: ArticleStore) -> None:
        self._store = store

    def get(self, art_id: str) -> MemoryArticle | None:
        row = self._store.get(art_id)
        return _row_to_article(row) if row else None


def _row_to_article(row: Any) -> MemoryArticle | None:
    prov = Provenance(
        producer_agent="", producer_org="",
        computation_ref=None, source_data_hash=None,
        source_data_schema=None, run_id="",
        timestamp=_dt.datetime.fromisoformat(row["created_at"]),
    )
    cites = json.loads(row["cites_json"] or "[]")
    return MemoryArticle(
        id=row["id"], type=row["type"], content=row["content"],
        payload={}, embedding=None, embedding_model=None,
        provenance=prov, scope=row["scope"], agent_signature=b"", org_signature=row["org_sig"],
        cites=cites, trust_score=row["trust_score"], trust_expiration=None,
    )
