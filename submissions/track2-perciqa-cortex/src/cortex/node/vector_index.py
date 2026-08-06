from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

import numpy as np


class VectorIndexProtocol(Protocol):
    def add(self, article_id: str, embedding: np.ndarray) -> None: ...
    def search(self, query_vec: np.ndarray, top_k: int) -> list[tuple[str, float]]: ...
    def size(self) -> int: ...
    def save(self, path: Path) -> None: ...
    def load(self, path: Path) -> None: ...


class HNSWIndex:
    def __init__(self, dim: int = 384, M: int = 32,
                 ef_construction: int = 200, ef_search: int = 64) -> None:
        import hnswlib
        self._hnswlib = hnswlib
        self.dim = dim
        self.M = M
        self.ef_construction = ef_construction
        self.ef_search = ef_search
        self._index = hnswlib.Index(space="cosine", dim=dim)
        self._index.init_index(max_elements=max(1024, M * 10), M=M,
                               ef_construction=ef_construction, random_seed=100)
        self._index.set_ef(ef_search)
        self._id_to_row: dict[str, int] = {}
        self._row_to_id: dict[int, str] = {}
        self._next = 0

    def add(self, article_id: str, embedding: np.ndarray) -> None:
        v = np.asarray(embedding, dtype=np.float32).reshape(1, -1)
        if article_id in self._id_to_row:
            row = self._id_to_row[article_id]
        else:
            row = self._next
            self._next += 1
            self._id_to_row[article_id] = row
            self._row_to_id[row] = article_id
            if row >= self._index.get_current_count():
                self._index.resize_index(max(row + 1, self._index.get_max_elements()))
        self._index.add_items(v, np.array([row], dtype=np.int64))

    def search(self, query_vec: np.ndarray, top_k: int) -> list[tuple[str, float]]:
        v = np.asarray(query_vec, dtype=np.float32).reshape(1, -1)
        if self._index.get_current_count() == 0:
            return []
        labels, distances = self._index.knn_query(v, k=min(top_k, self._index.get_current_count()))
        out: list[tuple[str, float]] = []
        for lbl, dist in zip(labels[0], distances[0], strict=True):
            out.append((self._row_to_id[int(lbl)], float(1.0 - dist)))
        return out

    def size(self) -> int:
        return self._index.get_current_count()

    def save(self, path: Path) -> None:
        p = Path(path)
        p.mkdir(parents=True, exist_ok=True)
        self._index.save_index(str(p / "index.bin"))
        meta = {
            "id_to_row": self._id_to_row,
            "row_to_id": {str(k): v for k, v in self._row_to_id.items()},
            "next": self._next,
        }
        with open(p / "meta.json", "w", encoding="utf-8") as fh:
            json.dump(meta, fh)

    def load(self, path: Path) -> None:
        p = Path(path)
        index = self._hnswlib.Index(space="cosine", dim=self.dim)
        index.load_index(str(p / "index.bin"))
        index.set_ef(self.ef_search)
        with open(p / "meta.json", encoding="utf-8") as fh:
            meta = json.load(fh)
        self._id_to_row = {k: int(v) for k, v in meta["id_to_row"].items()}
        self._row_to_id = {int(k): v for k, v in meta["row_to_id"].items()}
        self._next = int(meta["next"])
        self._index = index


class NumpyIndex:
    """Pure-NumPy brute-force cosine-similarity index. No C extensions.

    Suitable for dev, demo, and CI where hnswlib/faiss are unavailable.
    Uses O(n) linear scan — fine for datasets up to ~100K vectors.
    """

    def __init__(self, dim: int = 384, **kwargs):
        self.dim = dim
        self._vectors: dict[str, np.ndarray] = {}

    def add(self, article_id: str, embedding: np.ndarray) -> None:
        self._vectors[article_id] = np.asarray(embedding, dtype=np.float32).flatten()

    def search(self, query_vec: np.ndarray, top_k: int) -> list[tuple[str, float]]:
        q = np.asarray(query_vec, dtype=np.float32).flatten()
        q_norm = np.linalg.norm(q)
        if q_norm == 0 or not self._vectors:
            return [(aid, 0.5) for aid in list(self._vectors.keys())[:top_k]]
        scores = []
        for aid, vec in self._vectors.items():
            dot = np.dot(q, vec)
            norm = np.linalg.norm(vec)
            sim = dot / (q_norm * norm) if norm > 0 else 0.0
            scores.append((aid, float(sim)))
        scores.sort(key=lambda x: -x[1])
        return scores[:top_k]

    def size(self) -> int:
        return len(self._vectors)

    def save(self, path: Path) -> None:
        p = Path(path)
        p.mkdir(parents=True, exist_ok=True)
        meta = {
            aid: vec.tolist() for aid, vec in self._vectors.items()
        }
        (p / "vectors.json").write_text(
            json.dumps(meta, sort_keys=True, separators=(",", ":"))
        )

    def load(self, path: Path) -> None:
        p = Path(path)
        vec_file = p / "vectors.json"
        if vec_file.exists():
            raw = json.loads(vec_file.read_text())
            self._vectors = {
                aid: np.asarray(v, dtype=np.float32)
                for aid, v in raw.items()
            }


class FAISSGPUIndex:
    def __init__(self, dim: int = 384, M: int = 32,
                 ef_construction: int = 200, ef_search: int = 64) -> None:
        try:
            import faiss
        except ImportError as e:
            raise ImportError("faiss-gpu not installed; use HNSWIndex") from e
        self._faiss = faiss
        self.dim = dim
        self._res = faiss.StandardGpuResources()
        cpu = faiss.IndexFlatIP(dim)
        self._index = faiss.index_cpu_to_gpu(self._res, 0, cpu)
        self._id_to_row: dict[str, int] = {}
        self._row_to_id: dict[int, str] = {}
        self._next = 0

    def add(self, article_id: str, embedding: np.ndarray) -> None:
        v = np.asarray(embedding, dtype=np.float32).reshape(1, -1)
        if article_id not in self._id_to_row:
            self._id_to_row[article_id] = self._next
            self._row_to_id[self._next] = article_id
            self._next += 1
        self._index.add(v)

    def search(self, query_vec: np.ndarray, top_k: int) -> list[tuple[str, float]]:
        if self._index.ntotal == 0:
            return []
        v = np.asarray(query_vec, dtype=np.float32).reshape(1, -1)
        D, idx = self._index.search(v, min(top_k, self._index.ntotal))
        out: list[tuple[str, float]] = []
        for score, row in zip(D[0], idx[0], strict=True):
            if row < 0:
                continue
            out.append((self._row_to_id[int(row)], float(score)))
        return out

    def size(self) -> int:
        return int(self._index.ntotal)

    def save(self, path: Path) -> None:
        p = Path(path)
        p.mkdir(parents=True, exist_ok=True)
        cpu = self._faiss.index_gpu_to_cpu(self._index)
        self._faiss.write_index(cpu, str(p / "index.bin"))
        meta = {
            "id_to_row": self._id_to_row,
            "row_to_id": {str(k): v for k, v in self._row_to_id.items()},
            "next": self._next,
        }
        with open(p / "meta.json", "w", encoding="utf-8") as fh:
            json.dump(meta, fh)

    def load(self, path: Path) -> None:
        p = Path(path)
        cpu = self._faiss.read_index(str(p / "index.bin"))
        self._index = self._faiss.index_cpu_to_gpu(self._res, 0, cpu)
        with open(p / "meta.json", encoding="utf-8") as fh:
            meta = json.load(fh)
        self._id_to_row = {k: int(v) for k, v in meta["id_to_row"].items()}
        self._row_to_id = {int(k): v for k, v in meta["row_to_id"].items()}
        self._next = int(meta["next"])
