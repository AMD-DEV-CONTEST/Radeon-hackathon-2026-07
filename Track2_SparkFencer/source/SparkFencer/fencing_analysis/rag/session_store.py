"""Local multi-bout catalog and semantic index.

`events.json` remains the source of truth.  SQLite stores filterable metadata;
the companion vector files index compact bout/event descriptions for semantic
retrieval.  Both stay under outputs/.session_index and never leave the host.
"""

import json
import os
import sqlite3
from datetime import datetime, timezone

import numpy as np

from .store import _embed


class SessionStore:
    def __init__(self, root="outputs", embedder=None):
        self.root = root
        self.dir = os.path.join(root, ".session_index")
        self.db_path = os.path.join(self.dir, "catalog.sqlite")
        self.embedder = embedder or _embed
        os.makedirs(self.dir, exist_ok=True)
        self._init_db()

    def _connect(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        with self._connect() as db:
            db.executescript("""
              CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY, created_at TEXT, weapon TEXT, duration REAL,
                summary TEXT NOT NULL, metrics_json TEXT NOT NULL
              );
              CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY, session_id TEXT NOT NULL, kind TEXT NOT NULL,
                start_sec REAL, end_sec REAL, text TEXT NOT NULL, meta_json TEXT NOT NULL
              );
            """)

    @staticmethod
    def _docs(session_id, events):
        stats = events["stats"]
        pieces = []
        summary = (f"场次 {session_id}，剑种 {events.get('weapon', 'general')}，时长 {events['video']['duration_sec']:.1f} 秒。"
                   f"左方：弓步 {stats['left']['footwork']['lunge_count']}，进攻 {stats['left']['attack_count']}，防守 {stats['left']['defense_count']}。"
                   f"右方：弓步 {stats['right']['footwork']['lunge_count']}，进攻 {stats['right']['attack_count']}，防守 {stats['right']['defense_count']}。")
        pieces.append((f"{session_id}:summary", "summary", None, None, summary, {}))
        for action in events.get("actions", []):
            start, end = action["start_sec"], action["end_sec"]
            text = f"场次 {session_id}，{start:.2f}-{end:.2f} 秒，{action['fencer']} {action['type']}，置信度 {action.get('confidence', 0):.2f}。"
            pieces.append((f"{session_id}:action:{action.get('id', start)}", "action", start, end, text, action))
        for lunge in events.get("footwork", {}).get("lunges", []):
            start, end = lunge["start_sec"], lunge.get("recovery_sec") or lunge["time_sec"]
            text = f"场次 {session_id}，{start:.2f}-{end:.2f} 秒，{lunge['fencer']} 弓步，跨度 {lunge.get('spread_m')}m，置信度 {lunge.get('confidence', 0):.2f}。"
            pieces.append((f"{session_id}:lunge:{lunge['fencer']}:{lunge['time_sec']}", "lunge", start, end, text, lunge))
        return summary, pieces

    def upsert(self, session_id, events):
        summary, docs = self._docs(session_id, events)
        metrics = events.get("scorecard", {})
        with self._connect() as db:
            db.execute("DELETE FROM documents WHERE session_id=?", (session_id,))
            db.execute("INSERT OR REPLACE INTO sessions VALUES (?,?,?,?,?,?)", (
                session_id, datetime.now(timezone.utc).isoformat(), events.get("weapon", "general"),
                events["video"]["duration_sec"], summary, json.dumps(metrics, ensure_ascii=False),
            ))
            db.executemany("INSERT INTO documents VALUES (?,?,?,?,?,?,?)", [
                (doc[0], session_id, doc[1], doc[2], doc[3], doc[4], json.dumps(doc[5], ensure_ascii=False))
                for doc in docs
            ])
        self.rebuild_vectors()

    def rebuild_vectors(self):
        with self._connect() as db:
            rows = db.execute("SELECT id,session_id,kind,start_sec,end_sec,text,meta_json FROM documents").fetchall()
        if not rows:
            return
        vectors = self.embedder([r[5] for r in rows])
        vectors = np.asarray(vectors, dtype=np.float32)
        vectors /= np.linalg.norm(vectors, axis=1, keepdims=True) + 1e-9
        np.save(os.path.join(self.dir, "vectors.npy"), vectors)
        with open(os.path.join(self.dir, "documents.json"), "w", encoding="utf-8") as f:
            json.dump([{"id": r[0], "session_id": r[1], "kind": r[2], "start_sec": r[3],
                        "end_sec": r[4], "text": r[5], "meta": json.loads(r[6])} for r in rows], f,
                      ensure_ascii=False)

    def search(self, query, k=8, weapon=None, kind=None):
        path = os.path.join(self.dir, "vectors.npy")
        if not os.path.exists(path):
            return []
        vectors = np.load(path)
        with open(os.path.join(self.dir, "documents.json"), encoding="utf-8") as f:
            docs = json.load(f)
        q = np.asarray(self.embedder([query])[0], dtype=np.float32)
        q /= np.linalg.norm(q) + 1e-9
        scored = []
        for score, doc in zip(vectors @ q, docs):
            if kind and doc["kind"] != kind:
                continue
            if weapon:
                with self._connect() as db:
                    row = db.execute("SELECT weapon FROM sessions WHERE id=?", (doc["session_id"],)).fetchone()
                if not row or row[0] != weapon:
                    continue
            scored.append({**doc, "score": round(float(score), 3)})
        return sorted(scored, key=lambda x: -x["score"])[:k]
