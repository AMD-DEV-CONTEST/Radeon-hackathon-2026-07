from __future__ import annotations

import sqlite3
from collections import deque
from pathlib import Path

import networkx as nx

SCHEMA = """
CREATE TABLE IF NOT EXISTS provenance_edges (
  source_id TEXT NOT NULL,
  cited_id  TEXT NOT NULL,
  PRIMARY KEY (source_id, cited_id)
);
"""


class ProvenanceGraph:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, isolation_level=None)
        self._conn.executescript(SCHEMA)
        self._graph = nx.DiGraph()
        self.graph_version = 0
        self._rehydrate()

    def _rehydrate(self) -> None:
        for row in self._conn.execute("SELECT source_id, cited_id FROM provenance_edges"):
            self._graph.add_edge(row[0], row[1])
        self.graph_version = 0

    def add_citation(self, new_id: str, cited_id: str) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO provenance_edges (source_id, cited_id) VALUES (?, ?)",
            (new_id, cited_id),
        )
        self._graph.add_edge(new_id, cited_id)
        self.graph_version += 1

    def cited_by(self, article_id: str) -> list[str]:
        return [s for s, _ in self._graph.in_edges(article_id)]

    def descendants(self, article_id: str) -> list[str]:
        seen: list[str] = []
        q = deque(self._graph.predecessors(article_id))
        visited: set[str] = set()
        while q:
            n = q.popleft()
            if n in visited:
                continue
            visited.add(n)
            seen.append(n)
            q.extend(self._graph.predecessors(n))
        return seen

    def ancestors(self, article_id: str) -> list[str]:
        seen: list[str] = []
        q = deque(self._graph.successors(article_id))
        visited: set[str] = set()
        while q:
            n = q.popleft()
            if n in visited:
                continue
            visited.add(n)
            seen.append(n)
            q.extend(self._graph.successors(n))
        return seen

    def close(self) -> None:
        self._conn.close()
