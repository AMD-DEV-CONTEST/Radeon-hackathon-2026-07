"""Codebase RAG: chunk source files, embed via the GPU backend, search with cosine.

Storage is a single SQLite file with vectors as float32 blobs. No vector-DB
dependency, trivially portable between the dev laptop and the ROCm box.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import numpy as np

from .config import Config
from .llm import LLM

SOURCE_EXTS = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".rs", ".go", ".java", ".rb", ".c",
    ".cc", ".cpp", ".h", ".hpp", ".md", ".toml", ".yaml", ".yml", ".json",
    ".sh", ".sql", ".swift", ".kt",
}
SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "dist", "build", "__pycache__", ".next", "target",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "htmlcov",
}

#: JSON earns its place only when it describes the project. Everything else with
#: that extension is data, and data competes with code for the same top-k slots:
#: this repository had fifteen benchmark result files embedded as source, and
#: "record every outbound HTTP request host" returned two of them plus a shell
#: script, while the module that does the recording never appeared at all.
JSON_MANIFESTS = {"package.json", "tsconfig.json", "composer.json", "deno.json"}


def _venv_dirs(root: Path) -> set[Path]:
    """Virtualenvs named anything other than venv/.venv.

    Name matching alone silently indexes every package in site-packages,
    which turns `vulcan index .` into a multi-thousand-file embedding job.
    pyvenv.cfg is the definitive marker, so find those instead of guessing.
    """
    return {cfg.parent for cfg in root.rglob("pyvenv.cfg")}
CHUNK_LINES = 60
CHUNK_OVERLAP = 10
EMBED_BATCH = 32


#: Query terms that carry meaning. Two characters or fewer are noise.
TOKEN = re.compile(r"[a-z_]{3,}")

#: How much the lexical signal counts against dense cosine. 0.25 sat in the
#: middle of a plateau that ran to 0.5, until benchmark JSON and cache files
#: stopped being indexed as source. On the clean index the plateau is gone:
#: 0.15 is the peak and everything above it falls away, 0.5 and 1.0 losing a
#: top-3 hit as well. Cleaning the corpus is what the lexical weight had been
#: quietly paying for.
#:
#: Seven queries decide this, so one of them is the whole difference between
#: 0.0, 0.15 and 0.25. What the sweep supports firmly is the shape rather than
#: the exact value: weight the lexical signal lightly, and never heavily.
LEXICAL_WEIGHT = 0.15


class Index:
    def __init__(self, cfg: Config, llm: LLM, name: str = "default"):
        self.cfg = cfg
        self.llm = llm
        self.db = sqlite3.connect(cfg.data_dir / f"index-{name}.sqlite3")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS chunks ("
            " id INTEGER PRIMARY KEY, path TEXT, start_line INTEGER,"
            " end_line INTEGER, text TEXT, vec BLOB)"
        )

    def build(self, root: Path) -> int:
        self.db.execute("DELETE FROM chunks")
        batch_texts: list[str] = []
        batch_meta: list[tuple[str, int, int]] = []
        count = 0
        skip_roots = _venv_dirs(root)
        for path in sorted(root.rglob("*")):
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            if any(p in skip_roots for p in path.parents):
                continue
            if not path.is_file() or path.suffix not in SOURCE_EXTS:
                continue
            if path.suffix == ".json" and path.name not in JSON_MANIFESTS:
                continue
            try:
                lines = path.read_text(errors="ignore").splitlines()
            except OSError:
                continue
            step = CHUNK_LINES - CHUNK_OVERLAP
            for start in range(0, max(len(lines), 1), step):
                seg = lines[start : start + CHUNK_LINES]
                if not any(s.strip() for s in seg):
                    continue
                rel = str(path.relative_to(root))
                batch_texts.append(f"{rel}\n" + "\n".join(seg))
                batch_meta.append((rel, start + 1, start + len(seg)))
                if len(batch_texts) >= EMBED_BATCH:
                    count += self._flush(batch_texts, batch_meta)
                    batch_texts, batch_meta = [], []
        if batch_texts:
            count += self._flush(batch_texts, batch_meta)
        self.db.commit()
        return count

    def _flush(self, texts: list[str], meta: list[tuple[str, int, int]]) -> int:
        vecs = self.llm.embed(texts)
        for (rel, s, e), text, vec in zip(meta, texts, vecs):
            arr = np.asarray(vec, dtype=np.float32)
            arr /= np.linalg.norm(arr) or 1.0
            self.db.execute(
                "INSERT INTO chunks (path, start_line, end_line, text, vec) VALUES (?,?,?,?,?)",
                (rel, s, e, text, arr.tobytes()),
            )
        return len(texts)

    def _lexical(self, query: str, rows: list) -> np.ndarray:
        """Term overlap with the path and the chunk, normalised to 0..1.

        A path match counts triple. "which module implements the semantic
        index" should reward `vulcan/rag.py` for containing the word, and one
        line of path is otherwise a thin signal inside a 60-line chunk.
        """
        terms = set(TOKEN.findall(query.lower()))
        if not terms:
            return np.zeros(len(rows), dtype=np.float32)
        raw = np.asarray(
            [sum(3 for t in terms if t in r[0].lower())
             + min(sum(1 for t in terms if t in r[3].lower()), len(terms))
             for r in rows],
            dtype=np.float32,
        )
        return raw / (raw.max() or 1.0)

    def search(self, query: str, k: int = 6) -> list[dict]:
        rows = self.db.execute("SELECT path, start_line, end_line, text, vec FROM chunks").fetchall()
        if not rows:
            return []
        q = np.asarray(self.llm.embed([query])[0], dtype=np.float32)
        q /= np.linalg.norm(q) or 1.0
        mat = np.stack([np.frombuffer(r[4], dtype=np.float32) for r in rows])
        # Dense cosine alone bunches everything between about 0.59 and 0.65 on
        # this corpus, because a 60-line chunk is dominated by its file header
        # and every header resembles every question. Measured over seven
        # known-answer queries, adding the lexical term takes top-1 from 4/7 to
        # 6/7 and top-3 from 6/7 to 7/7. `vulcan rag-bench` reproduces it.
        scores = mat @ q + LEXICAL_WEIGHT * self._lexical(query, rows)
        top = np.argsort(-scores)[:k]
        return [
            {"path": rows[i][0], "start": rows[i][1], "end": rows[i][2], "text": rows[i][3], "score": float(scores[i])}
            for i in top
        ]
