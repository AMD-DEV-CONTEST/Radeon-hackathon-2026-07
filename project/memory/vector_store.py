# project/memory/vector_store.py
"""
R.A.G.E. Phase 3 - Module 2: Robotic RAG (Milvus Vector DB)

Purpose
-------
Give the cell a small retrieval-augmented-generation memory of factory
Standard Operating Procedures (SOPs) - e.g. "how to insert a cable without
scoring the port wall", "what to do if a cable misaligns on approach". A
supervisor policy (or, later, an LLM-driven recovery agent) can query this
store in natural language and get back the most relevant SOP text to
condition its next action on.

Storage backend: Milvus Lite (`pymilvus`'s embedded, file-backed mode) -
no separate Milvus server/Docker container needed, which matters for a
time-boxed hackathon. Data lives at project/memory/milvus_data/*.db.

Embeddings
----------
We do not have a production embedding model wired in yet, so
`_embed_text()` uses a deterministic hashing-trick bag-of-words embedding:
each token is hashed into one of `dim` buckets, bucket counts are
L2-normalized. This is NOT semantically rich (no real "meaning" is
captured - it's closer to reproducible fuzzy keyword matching), but it:
  - requires zero extra model downloads / GPU memory,
  - is fully deterministic (same text -> same vector, always),
  - is good enough to prove the insert/index/search plumbing end-to-end.
Swap in a real sentence-embedding model (e.g. a ROCm-accelerated
sentence-transformers model) by replacing `_embed_text()` - every other
method is embedding-implementation-agnostic.

Graceful degradation
---------------------
If `pymilvus` isn't installed in this environment, `SOPVectorStore` falls
back to a tiny in-memory brute-force cosine-similarity index with the
*exact same public API*, so this module (and its __main__ test) still run
on a machine that hasn't installed the Milvus Lite dependency yet.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from typing import List, Optional

import numpy as np

try:
    from pymilvus import MilvusClient
    _PYMILVUS_AVAILABLE = True
except ImportError:
    _PYMILVUS_AVAILABLE = False


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #

DEFAULT_DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "milvus_data")
DEFAULT_DB_PATH = os.path.join(DEFAULT_DB_DIR, "rage_sop_memory.db")
DEFAULT_COLLECTION = "factory_sops"
EMBED_DIM = 128


@dataclass
class SOPRecord:
    sop_id: int
    title: str
    category: str   # e.g. "cable_insertion" | "defect_recovery"
    text: str


@dataclass
class SOPResult:
    sop_id: int
    title: str
    category: str
    text: str
    score: float  # cosine similarity, higher = more relevant


# --------------------------------------------------------------------------- #
# Seed SOPs - the factory knowledge Robot B / the supervisor policy should
# already have "read" before the cell starts running.
# --------------------------------------------------------------------------- #

SEED_SOPS: List[SOPRecord] = [
    SOPRecord(
        sop_id=1,
        title="Cable Insertion - Standard Approach",
        category="cable_insertion",
        text=(
            "Align the cable connector plug's centroid with the port bin's "
            "centroid before descending. Approach along the port's normal "
            "axis (straight down for top-mounted ports). Descend slowly "
            "for the final 10mm to avoid scraping the port wall. Confirm "
            "seating by checking that connector height matches the port "
            "wall height within 2mm tolerance."
        ),
    ),
    SOPRecord(
        sop_id=2,
        title="Cable Insertion - Shape/Color Matching",
        category="cable_insertion",
        text=(
            "Every cable connector plug must be matched to the port bin "
            "sharing its color AND shape: red square plug to red square "
            "port, blue circle plug to blue circle port, yellow triangle "
            "plug to yellow triangle port. Never force a mismatched plug "
            "into a bin even if it is physically smaller than the opening."
        ),
    ),
    SOPRecord(
        sop_id=3,
        title="Defect Recovery - Misaligned Insertion",
        category="defect_recovery",
        text=(
            "If a connector plug contacts the port wall instead of the "
            "opening (misalignment > 5mm), immediately retract the arm "
            "along the approach axis by at least 20mm before attempting a "
            "corrective re-alignment. Do not attempt lateral correction "
            "while the plug is still in contact with the wall, as this "
            "risks damaging both the port wall and the cable's MPM "
            "jacketing."
        ),
    ),
    SOPRecord(
        sop_id=4,
        title="Defect Recovery - Dropped Cable",
        category="defect_recovery",
        text=(
            "If force feedback indicates the gripper has lost contact with "
            "a cable mid-transfer, halt arm motion immediately, re-run the "
            "vision pipeline to re-localize the dropped cable's connector "
            "plug, and re-plan a fresh grasp pose before resuming. Do not "
            "continue the original planned trajectory blind."
        ),
    ),
    SOPRecord(
        sop_id=5,
        title="Active Fixturing - Hold Stability",
        category="fixturing",
        text=(
            "While Robot A is actively fixturing the GPU block for Robot "
            "B's insertion pass, re-assert the held joint target every "
            "control step rather than issuing a one-shot move command. "
            "This keeps the PD controller actively resisting disturbance "
            "torque from Robot B's insertion contact forces."
        ),
    ),
    SOPRecord(
        sop_id=6,
        title="Multi-Arm Coordination - Collision Avoidance",
        category="coordination",
        text=(
            "Robot A's fixturing workspace and Robot B's insertion "
            "workspace overlap directly above the GPU block. Robot B "
            "should not enter the shared volume until Robot A reports a "
            "stable hold (zero net joint velocity for at least 10 "
            "consecutive control steps)."
        ),
    ),
]


# --------------------------------------------------------------------------- #
# Embedding function (hashing-trick placeholder - see module docstring)
# --------------------------------------------------------------------------- #

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _embed_text(text: str, dim: int = EMBED_DIM) -> np.ndarray:
    """Deterministic hashing-trick bag-of-words embedding. Replace with a
    real sentence-embedding model when one is wired in; every caller in
    this file only assumes "same text in -> same fixed-length unit vector
    out", so the swap is a one-function change.
    """
    vec = np.zeros(dim, dtype=np.float32)
    tokens = _TOKEN_RE.findall(text.lower())
    if not tokens:
        return vec
    for tok in tokens:
        # md5 is only used here as a fast, stable string->int hash - NOT
        # for any security purpose.
        h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
        bucket = h % dim
        vec[bucket] += 1.0
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec = vec / norm
    return vec


# --------------------------------------------------------------------------- #
# In-memory fallback index (used automatically if pymilvus isn't installed)
# --------------------------------------------------------------------------- #

class _InMemoryIndex:
    """Brute-force cosine-similarity index with the same shape of API as
    the Milvus-backed path, so SOPVectorStore can use either one
    interchangeably."""

    def __init__(self):
        self._ids: List[int] = []
        self._vectors: List[np.ndarray] = []
        self._records: dict[int, SOPRecord] = {}

    def upsert(self, record: SOPRecord, vector: np.ndarray):
        if record.sop_id in self._records:
            idx = self._ids.index(record.sop_id)
            self._vectors[idx] = vector
        else:
            self._ids.append(record.sop_id)
            self._vectors.append(vector)
        self._records[record.sop_id] = record

    def search(self, query_vector: np.ndarray, top_k: int) -> List[SOPResult]:
        if not self._ids:
            return []
        mat = np.stack(self._vectors, axis=0)  # (N, dim)
        # Vectors are already unit-normalized, so dot product == cosine sim.
        scores = mat @ query_vector
        order = np.argsort(-scores)[:top_k]
        results = []
        for i in order:
            rec = self._records[self._ids[int(i)]]
            results.append(SOPResult(
                sop_id=rec.sop_id, title=rec.title, category=rec.category,
                text=rec.text, score=float(scores[int(i)]),
            ))
        return results


# --------------------------------------------------------------------------- #
# Public class
# --------------------------------------------------------------------------- #

class SOPVectorStore:
    """Robotic RAG memory over factory SOPs, backed by Milvus Lite
    (falls back to an in-memory index if pymilvus isn't installed).
    """

    def __init__(self, db_path: str = DEFAULT_DB_PATH,
                 collection_name: str = DEFAULT_COLLECTION,
                 dim: int = EMBED_DIM):
        self.dim = dim
        self.collection_name = collection_name
        self._backend = None
        self._fallback: Optional[_InMemoryIndex] = None

        if _PYMILVUS_AVAILABLE:
            os.makedirs(os.path.dirname(db_path), exist_ok=True)
            # Milvus Lite: pointing MilvusClient at a local *.db file path
            # (instead of a server URI like "http://host:19530") runs the
            # embedded, file-backed engine - no separate server process.
            self._backend = MilvusClient(uri=db_path)
            self._ensure_collection()
            self._backend.load_collection(self.collection_name)
            print(f"[vector_store] Using Milvus Lite at '{db_path}', "
                  f"collection '{collection_name}'.")
        else:
            self._fallback = _InMemoryIndex()
            print("[vector_store] WARNING: pymilvus not installed - using "
                  "in-memory fallback index. Install with "
                  "`pip install pymilvus --break-system-packages` for "
                  "persistent Milvus Lite storage.")

    # -- collection setup ------------------------------------------------- #

    def _ensure_collection(self):
        if not self._backend.has_collection(self.collection_name):
            self._backend.create_collection(
                collection_name=self.collection_name,
                dimension=self.dim,
                metric_type="COSINE",
                auto_id=False,
            )

    # -- ingestion ---------------------------------------------------------- #

    def add_sop(self, record: SOPRecord):
        """Embed and upsert one SOP record."""
        vector = _embed_text(record.text, self.dim)
        if self._backend is not None:
            self._backend.upsert(
                collection_name=self.collection_name,
                data=[{
                    "id": record.sop_id,
                    "vector": vector.tolist(),
                    "title": record.title,
                    "category": record.category,
                    "text": record.text,
                }],
            )
        else:
            self._fallback.upsert(record, vector)

    def add_sops(self, records: List[SOPRecord]):
        for record in records:
            self.add_sop(record)

    def seed_if_empty(self):
        """Populate the collection with SEED_SOPS if it currently has no
        rows, so a fresh .db file (or fresh fallback index) is immediately
        useful without a separate ingestion step."""
        if self.count() == 0:
            print(f"[vector_store] Collection '{self.collection_name}' is "
                  f"empty - seeding {len(SEED_SOPS)} factory SOPs.")
            self.add_sops(SEED_SOPS)

    def count(self) -> int:
        if self._backend is not None:
            stats = self._backend.get_collection_stats(self.collection_name)
            return int(stats.get("row_count", 0))
        return len(self._fallback._ids)

    # -- retrieval ---------------------------------------------------------- #

    def retrieve_sop(self, query: str, top_k: int = 1) -> List[SOPResult]:
        """Return the `top_k` SOPs most relevant to `query`, ranked by
        cosine similarity, highest first."""
        query_vector = _embed_text(query, self.dim)

        if self._backend is not None:
            hits = self._backend.search(
                collection_name=self.collection_name,
                data=[query_vector.tolist()],
                limit=top_k,
                output_fields=["title", "category", "text"],
            )
            results = []
            for hit in hits[0]:
                entity = hit.get("entity", hit)
                results.append(SOPResult(
                    sop_id=int(hit["id"]),
                    title=entity["title"],
                    category=entity["category"],
                    text=entity["text"],
                    score=float(hit["distance"]),
                ))
            return results

        return self._fallback.search(query_vector, top_k)


# --------------------------------------------------------------------------- #
# Standalone test block
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    print("=" * 70)
    print("[vector_store] Standalone test")
    print("=" * 70)

    # Use a throwaway DB file for the smoke test so repeated runs during
    # development don't accumulate duplicate collections on disk.
    test_db_path = os.path.join(DEFAULT_DB_DIR, "rage_sop_memory_TEST.db")
    store = SOPVectorStore(db_path=test_db_path)
    store.seed_if_empty()

    print(f"\n[vector_store] Collection now has {store.count()} SOPs.\n")

    test_queries = [
        "the cable connector hit the wall instead of going into the port",
        "how do I know which cable color goes in which port shape",
        "robot B lost grip and dropped the cable mid transfer",
    ]

    for query in test_queries:
        print(f"Query: {query!r}")
        results = store.retrieve_sop(query, top_k=1)
        for res in results:
            print(f"    -> [{res.category}] {res.title} (score={res.score:.3f})")
            print(f"       {res.text[:120]}...")
        print()

    assert store.count() >= len(SEED_SOPS), "Expected all seed SOPs to be present"
    print("[vector_store] OK: seeded and queried successfully.")