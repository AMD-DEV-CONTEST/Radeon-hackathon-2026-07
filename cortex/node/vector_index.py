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
    def __init__(self, dim: int = 384, M: int = 32, ef_construction: int = 200, ef_search: int = 64) -> None:
        import hnswlib
        self._hnswlib = hnswlib
        self.dim = dim
        self.M = M
        self.ef_construction = ef_construction
        self.ef_search = ef_search
        self._index = hnswlib.Index(space="cosine", dim=dim)
        self._index.init_index(max_elements=max(1024, M * 10), M=M, ef_construction=ef_construction, random_seed=100)
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
        for lbl, dist in zip(labels[0], distances[0]):
            out.append((self._row_to_id[int(lbl)], float(1.0 - dist)))
        return out

    def size(self) -> int:
        return self._index.get_current_count()

    def save(self, path: Path) -> None:
        p = Path(path)
        p.mkdir(parents=True, exist_ok=True)
        self._index.save_index(str(p / "index.bin"))
        with open(p / "meta.json", "w", encoding="utf-8") as fh:
            json.dump({"id_to_row": self._id_to_row, "row_to_id": {str(k): v for k, v in self._row_to_id.items()}, "next": self._next}, fh)

    def load(self, path: Path) -> None:
        p = Path(path)
        self._index = self._hnswlib.Index(space="cosine", dim=self.dim)
        self._index.load_index(str(p / "index.bin"))
        with open(p / "meta.json", encoding="utf-8") as fh:
            meta = json.load(fh)
        self._id_to_row = {k: int(v) for k, v in meta["id_to_row"].items()}
        self._row_to_id = {int(k): v for k, v in meta["row_to_id"].items()}
        self._next = int(meta["next"])
        self._index.set_ef(self.ef_search)


class FAISSGPUIndex:
    def __init__(self, dim: int = 384, M: int = 32, ef_construction: int = 200, ef_search: int = 64) -> None:
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
        for score, row in zip(D[0], idx[0]):
            if row < 0:
                continue
            out.append((self._row_to_id[int(row)], float(score)))
        return out

    def size(self) -> int:
        return int(self._index.ntotal)

    def save(self, path: Path) -> None:
        p = Path(path); p.mkdir(parents=True, exist_ok=True)
        cpu = self._faiss.index_gpu_to_cpu(self._index)
        self._faiss.write_index(cpu, str(p / "index.bin"))
        with open(p / "meta.json", "w", encoding="utf-8") as fh:
            json.dump({"id_to_row": self._id_to_row, "row_to_id": {str(k): v for k, v in self._row_to_id.items()}, "next": self._next}, fh)

    def load(self, path: Path) -> None:
        p = Path(path)
        cpu = self._faiss.read_index(str(p / "index.bin"))
        self._index = self._faiss.index_cpu_to_gpu(self._res, 0, cpu)
        with open(p / "meta.json", encoding="utf-8") as fh:
            meta = json.load(fh)
        self._id_to_row = {k: int(v) for k, v in meta["id_to_row"].items()}
        self._row_to_id = {int(k): v for k, v in meta["row_to_id"].items()}
        self._next = int(meta["next"])
