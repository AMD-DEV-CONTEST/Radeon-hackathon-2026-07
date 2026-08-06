from __future__ import annotations

import math
import pickle
import uuid
from pathlib import Path
from typing import List, Dict


class VectorStore:
    def __init__(self, dimension: int, *, milvus_uri: str = "", path: str = ""):
        self.dimension = dimension
        self._path = Path(path) if path else None
        self._chunks: List[Dict] = []
        self._vectors: List[List[float]] = []
        self._client = self._init_milvus(milvus_uri) if milvus_uri else None
        if not self._client:
            self._load_local()

    def _init_milvus(self, uri: str):
        from pymilvus import MilvusClient, DataType
        c = MilvusClient(uri=uri)
        if "rag" not in c.list_collections():
            schema = c.create_schema(auto_id=False, enable_dynamic_field=False)
            schema.add_field("id", DataType.VARCHAR, is_primary=True, max_length=64)
            schema.add_field("vector", DataType.FLOAT_VECTOR, dim=self.dimension)
            schema.add_field("content", DataType.VARCHAR, max_length=65535)
            schema.add_field("source", DataType.VARCHAR, max_length=512)
            schema.add_field("chunk_index", DataType.INT64)
            idx = c.prepare_index_params()
            idx.add_index(field_name="vector", index_type="AUTOINDEX", metric_type="COSINE")
            c.create_collection(collection_name="rag", schema=schema, index_params=idx)
        return c

    def _load_local(self):
        if self._path and self._path.exists():
            data = pickle.loads(self._path.read_bytes())
            self._chunks, self._vectors = data.get("chunks", []), data.get("vectors", [])

    def _save_local(self):
        if self._path:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_bytes(pickle.dumps({"chunks": self._chunks, "vectors": self._vectors}))

    def add(self, vectors: List[List[float]], chunks: List[Dict]):
        if self._client:
            self._client.insert(collection_name="rag", data=[
                {"id": str(uuid.uuid4()), "vector": v, "content": c.get("text", ""),
                 "source": c.get("source", ""), "chunk_index": c.get("chunk_index", 0)}
                for v, c in zip(vectors, chunks)
            ])
        else:
            self._vectors.extend(vectors)
            self._chunks.extend(chunks)
        self._save_local()

    def search(self, query_vector: List[float], top_k: int = 5, source_filter: str = "") -> List[Dict]:
        if self._client:
            expr = f'source == "{source_filter}"' if source_filter else None
            res = self._client.search(
                collection_name="rag", data=[query_vector], limit=top_k,
                output_fields=["content", "source"],
                filter=expr,
            )[0]
            return [{"text": h["entity"]["content"], "source": h["entity"]["source"], "score": h["distance"]} for h in res]

        def cosine(a, b):
            dot = sum(x * y for x, y in zip(a, b))
            na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
            return dot / (na * nb) if na and nb else 0

        idxs = list(range(len(self._vectors)))
        if source_filter:
            idxs = [i for i in idxs if self._chunks[i].get("source") == source_filter]
        scored = sorted([(cosine(query_vector, self._vectors[i]), i) for i in idxs], reverse=True)[:top_k]
        return [{"text": self._chunks[i].get("text", ""), "source": self._chunks[i].get("source", ""), "score": s}
                for s, i in scored]
