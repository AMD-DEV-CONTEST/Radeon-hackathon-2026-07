from __future__ import annotations

import asyncio
import contextlib
import datetime as _dt
import json
import logging
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np

from cortex.core.article import MemoryArticle, Provenance, Scope
from cortex.core.canonical import article_canonical_bytes, compute_article_id
from cortex.core.crypto import sign
from cortex.core.envelope import EnvelopeType
from cortex.core.errors import ArticleState, transition
from cortex.node.broker_client import BrokerClient
from cortex.node.config import NodeConfig, load_config
from cortex.node.embedder import Embedder
from cortex.node.keys import load_keys
from cortex.node.provenance import ProvenanceGraph
from cortex.node.query import QueryResult, retrieve
from cortex.node.receiver import receive_publish_envelope
from cortex.node.store import ArticleStore
from cortex.node.trust import TrustEngine
from cortex.node.vector_index import FAISSGPUIndex, HNSWIndex, NumpyIndex

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
        backend = self.config.vector_index.backend
        if backend == "faiss-gpu":
            self.vector_index = FAISSGPUIndex(dim=384)
        elif backend == "numpy":
            self.vector_index = NumpyIndex(dim=384)
        else:
            self.vector_index = HNSWIndex(dim=384,
                                          M=self.config.vector_index.hnsw.M,
                                          ef_construction=self.config.vector_index.hnsw.ef_construction,
                                          ef_search=self.config.vector_index.hnsw.ef_search)
        vec_path = self.data_dir / "vectors"
        if self.vector_index is not None:
            try:
                self.vector_index.load(vec_path)
            except Exception:
                log.info("no existing vector index at %s, starting fresh", vec_path)
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
            on_publish=self._on_broker_publish,
            on_query=self._on_broker_query,
            on_derive=self._on_broker_derive,
            on_subscribe=self._on_broker_subscribe,
        )
        await self.broker.connect()
        self._health_task = asyncio.create_task(self._health_loop())

    async def stop(self) -> None:
        if self._health_task:
            self._health_task.cancel()
        if self.broker:
            await self.broker.stop()
        if self.vector_index is not None:
            try:
                self.vector_index.save(self.data_dir / "vectors")
            except Exception as exc:
                log.warning("vector index save failed: %s", exc)
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

    def _on_broker_derive(self, env: dict) -> None:
        payload = env.get("payload", {})
        art_id = payload.get("article_id")
        cites = payload.get("cites", [])
        if self.provenance and art_id:
            for cited_id in cites:
                self.provenance.add_citation(art_id, cited_id)
            if self.store:
                for cited_id in cites:
                    self.store.set_state(cited_id, "cited")
                self.store.event_log_append("inbound.derive.received", art_id,
                                            {"cites": cites, "src": env.get("src", "")})

    def _on_broker_subscribe(self, env: dict) -> None:
        if self.store:
            self.store.event_log_append("inbound.subscribe.received", None,
                                        {"src": env.get("src", "")})

    async def _on_broker_publish(self, env: dict) -> None:
        payload = env.get("payload", {})
        canonical_hex = payload.get("canonical", "")
        article_dict = payload.get("article")
        if not canonical_hex or not article_dict:
            log.warning("received publish envelope missing canonical or article")
            return
        expected_canonical = bytes.fromhex(canonical_hex)
        article = MemoryArticle.from_dict(article_dict)
        embedding_list = payload.get("embedding")
        try:
            reg_path = Path(self.config.broker.registry)
            reg_data = json.loads(reg_path.read_text()) if reg_path.exists() else {}
            registry = _RegistryAdapter(reg_data)
            receive_publish_envelope(article, expected_canonical, registry, self.store)
        except Exception as exc:
            log.warning("inbound publish rejected: %s", exc)
            if self.store:
                self.store.event_log_append(
                    "inbound.publish.rejected", article.id, {"error": str(exc)},
                )
            return
        if self.embedder is not None and self.vector_index is not None:
            try:
                if embedding_list is not None:
                    embedding = np.asarray(embedding_list, dtype=np.float16).astype(np.float32)
                else:
                    embedding = self.embedder.embed_one(article.content)
                self.vector_index.add(article.id, embedding)
                self.store.set_state(article.id, "indexed")
            except Exception as exc:
                log.warning("inbound publish embed/index failed: %s", exc)
                self.store.event_log_append(
                    "inbound.publish.index_failed", article.id, {"error": str(exc)},
                )
                return
        if self.trust is not None:
            now = _dt.datetime.now(_dt.UTC)
            gv = self.provenance.graph_version if self.provenance is not None else 0
            score = self.trust.trust_for(article, now, _StoreAdapter(self.store), graph_version=gv)
            trust_expires = now + _dt.timedelta(days=self.config.trust.half_life_days)
            self.store.update_trust(article.id, score, trust_expires)
            self.store.set_state(article.id, "published")
            self.store.event_log_append("inbound.publish.received", article.id,
                                        {"trust_score": score, "src": env.get("src", "")})

    async def _health_loop(self) -> None:
        while True:
            await asyncio.sleep(5)
            if self.embedder is None:
                continue
            if not self.embedder._check_gpu() and not self.embedder.fallback_to_cpu:
                self.embedder.fallback_to_cpu = True
                self.embedder._device = "cpu"
                with contextlib.suppress(Exception):
                    self.embedder._model = self.embedder._model.to("cpu")
                self._on_embed_failed("healthcheck:no_gpu")
                self.store.event_log_append(
                    "node.embed.fallback_cpu", None, {"reason": "healthcheck"},
                )

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
        article = replace(article, embedding=embedding.tolist(),
                          embedding_model=self.config.embedder.model)
        now = _dt.datetime.now(_dt.UTC)
        trust_score = self.trust.trust_for(
            article, now, _StoreAdapter(self.store),
            graph_version=self.provenance.graph_version,
        )
        trust_expires = now + _dt.timedelta(days=self.config.trust.half_life_days)
        article = replace(article, trust_score=trust_score, trust_expiration=trust_expires)
        transition(article, ArticleState.DRAFTED, ArticleState.SIGNED)
        self.store.put(article, state="signed")
        transition(article, ArticleState.SIGNED, ArticleState.INDEXED)
        self.vector_index.add(art_id, embedding)
        self.store.set_state(art_id, "indexed")
        if article.scope != Scope.PRIVATE:
            import uuid
            env_dict = {
                "type": EnvelopeType.PUBLISH.value, "msg_id": str(uuid.uuid4()),
                "src": self.org_did, "dst": "*",
                "ts": _dt.datetime.now(_dt.UTC).isoformat(),
                "payload": {
                    "article_id": art_id,
                    "canonical": canonical.hex(),
                    "embedding": embedding.astype("float16").tolist(),
                    "article": article.to_dict(),
                },
            }
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.broker.publish_envelope(env_dict))
            except RuntimeError:
                asyncio.run(self.broker.publish_envelope(env_dict))
            transition(article, ArticleState.INDEXED, ArticleState.PUBLISHED)
            self.store.set_state(art_id, "published")
            self.store.event_log_append("node.article.published", art_id, {"scope": article.scope})
        else:
            self.store.event_log_append("node.article.indexed_private", art_id, {})
        return art_id

    def _on_broker_query(self, env: dict) -> list[dict]:
        payload = env.get("payload", {})
        results = self._local_retrieve(
            query_text=payload.get("query_text", ""),
            topic_filter=payload.get("topic_filter", []),
            scope_filter=payload.get("scope_filter", []),
            top_k=int(payload.get("top_k", 5)),
            min_trust=float(payload.get("min_trust", 0.3)),
            deadline_ms=int(payload.get("deadline_ms", 400)),
        )
        return [
            {
                "article_id": r.article_id,
                "score": r.hybrid_score,
                "trust_score": r.trust_score,
                "content": r.article.content[:200],
                "producer_org": getattr(r.article.provenance, "producer_org", None),
                "timestamp": (getattr(r.article.provenance, "timestamp", None).isoformat()
                              if getattr(r.article.provenance, "timestamp", None) else None),
                "source_data_hash": getattr(r.article.provenance, "source_data_hash", None),
            }
            for r in results
        ]

    def _local_retrieve(self, query_text: str, topic_filter: list[str],
                        scope_filter: list[str], top_k: int, min_trust: float,
                        deadline_ms: int) -> list[QueryResult]:
        assert self.store and self.vector_index and self.embedder
        adapter = _StoreAdapter(self.store)
        return retrieve(
            store=adapter, vector_index=self.vector_index, embedder=self.embedder,
            query_text=query_text, topic_filter=topic_filter, scope_filter=scope_filter,
            top_k=top_k, min_trust=min_trust, deadline_ms=deadline_ms,
        )

    def query(self, query_text: str, topic_filter: list[str], scope_filter: list[str],
              top_k: int, min_trust: float, deadline_ms: int) -> list[QueryResult]:
        local = self._local_retrieve(query_text, topic_filter, scope_filter,
                                     top_k, min_trust, deadline_ms)
        if self.broker is None:
            return local
        remote_results = self._fanout_query(query_text, topic_filter,
                                            scope_filter, top_k, min_trust, deadline_ms)
        seen: set[str] = set(r.article_id for r in local)
        merged = list(local)
        for r in remote_results:
            rid = r.get("article_id", "")
            if rid not in seen:
                seen.add(rid)
                merged.append(QueryResult(
                    article=None, article_id=rid,
                    hybrid_score=r.get("score", 0.0),
                    trust_score=r.get("trust_score", 0.0),
                    provenance_summary={
                        "producer_org": r.get("producer_org"),
                        "timestamp": r.get("timestamp"),
                        "source_data_hash": r.get("source_data_hash"),
                        "content": r.get("content"),
                        "n_cites": 0,
                    },
                ))
        merged.sort(key=lambda r: -r.hybrid_score)
        return merged[:top_k]

    def _fanout_query(self, query_text: str, topic_filter: list[str],
                      scope_filter: list[str], top_k: int, min_trust: float,
                      deadline_ms: int) -> list[dict]:
        import uuid
        qid = str(uuid.uuid4())
        env = {
            "type": EnvelopeType.QUERY.value, "msg_id": qid,
            "src": self.org_did, "dst": "*",
            "ts": _dt.datetime.now(_dt.UTC).isoformat(),
            "payload": {
                "query_id": qid, "query_text": query_text,
                "topic_filter": topic_filter or [],
                "scope_filter": scope_filter or [],
                "top_k": top_k, "min_trust": min_trust, "deadline_ms": deadline_ms,
            },
        }
        loop = getattr(self.broker, "_loop", None)
        if loop is None or loop.is_closed():
            return []
        timeout = (deadline_ms / 1000.0) + 2.0
        try:
            fut = asyncio.run_coroutine_threadsafe(self.broker.query_fanout(env), loop)
        except RuntimeError:
            return []
        try:
            result = fut.result(timeout=timeout)
        except Exception:
            return []
        if isinstance(result, dict):
            return (result.get("payload") or {}).get("results", [])
        return []

    def derive(self, new_article: MemoryArticle, cited_article_ids: list[str]) -> str:
        assert self.provenance and self.store
        new_article = replace(new_article, cites=list(cited_article_ids))
        art_id = self.publish(new_article)
        for cited_id in cited_article_ids:
            self.provenance.add_citation(art_id, cited_id)
            self.store.set_state(cited_id, "cited")
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


class _RegistryAdapter:
    def __init__(self, data: dict) -> None:
        self._data = data

    def lookup(self, org_did: str) -> bytes | None:
        entry = self._data.get(org_did)
        if entry is None:
            return None
        pubkey = entry.get("pubkey") if isinstance(entry, dict) else entry
        if isinstance(pubkey, str):
            return pubkey.encode("utf-8")
        return pubkey


class _StoreAdapter:
    def __init__(self, store: ArticleStore) -> None:
        self._store = store

    def get(self, art_id: str) -> MemoryArticle | None:
        row = self._store.get(art_id)
        return _row_to_article(row) if row else None


def _row_to_article(row: Any) -> MemoryArticle | None:
    try:
        created = _dt.datetime.fromisoformat(row["created_at"])
    except Exception:
        created = _dt.datetime.now(_dt.UTC)
    data = dict(row)
    def _get_col(key: str, default: Any = None) -> Any:
        return data[key] if key in data and data[key] is not None else default

    prov = Provenance(
        producer_agent=_get_col("producer_agent", ""),
        producer_org=_get_col("producer_org", ""),
        computation_ref=None, source_data_hash=None,
        source_data_schema=None, run_id=_get_col("run_id", ""),
        timestamp=created,
    )
    payload = json.loads(_get_col("payload_json", "{}"))
    cites = json.loads(_get_col("cites_json", "[]"))
    trust_exp = None
    if _get_col("trust_expires"):
        with contextlib.suppress(Exception):
            trust_exp = _dt.datetime.fromisoformat(_get_col("trust_expires"))
    return MemoryArticle(
        id=data["id"], type=data["type"], content=data["content"],
        payload=payload, embedding=None, embedding_model=None,
        provenance=prov, scope=data["scope"], topic=_get_col("topic", "*"),
        agent_signature=_get_col("agent_sig") or b"",
        org_signature=_get_col("org_sig"),
        cites=cites, trust_score=data["trust_score"], trust_expiration=trust_exp,
    )
