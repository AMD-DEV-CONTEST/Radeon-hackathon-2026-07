#!/usr/bin/env python3
"""
seed_knowledge_base.py — One-time vector DB seeding for Determinex IDE.

Ingests coding_laws.md and engineering_knowledge_base.md into the per-persona
fastembed SQLite collections so the IDE's RAG can surface them during sessions.

Collections:
  general      → wisdom / vss_wisdom
  rust         → knowledge_rust / vss_code_rust
  web          → knowledge_web / vss_code_web
  security     → knowledge_security / vss_security
  architecture → knowledge_architecture / vss_architecture

Run once after first `npm run tauri dev` (DB must already exist):
  python scripts/seed_knowledge_base.py

Idempotent: skips if already seeded (checks row count).
"""

from __future__ import annotations

import hashlib
import os
import pathlib
import re
import sqlite3
import struct
import sys
from pathlib import Path

try:
    import sqlite_vec
except ImportError:
    sys.exit("sqlite-vec not installed. Run: pip install sqlite-vec")

try:
    from fastembed import TextEmbedding
except ImportError:
    sys.exit("fastembed not installed. Run: pip install fastembed")

# ── Paths ───────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).parent.parent
DB_PATH = Path(
    os.environ.get(
        "DETERMINEX_DB",
        # run.determinex.app is the Tauri BUNDLE IDENTIFIER, so this directory is the
        # right place -- only the hardcoded user-profile prefix was wrong. Derive it.
        str(
            pathlib.Path(os.environ.get("APPDATA") or pathlib.Path.home() / "AppData" / "Roaming")
            / "run.determinex.app"
            / "determinex.sqlite"
        ),
    )
)
CODING_LAWS = REPO_ROOT / "scripts" / "coding_laws.md"
ENG_KB = REPO_ROOT / "data" / "knowledge_vault" / "engineering_knowledge_base.md"
COMPANION_DIR = REPO_ROOT / "docs" / "companions"
PROGRAMBENCH_DIR = REPO_ROOT / "corpus" / "programbench"
SWEBENCH_DIR = REPO_ROOT / "corpus" / "swebench"
PROGRAMBENCH_FACTORY_DIR = REPO_ROOT / "logs" / "programbench_factory"
PROGRAMBENCH_FAILURE_INVENTORY_DIR = REPO_ROOT / "logs" / "programbench_failure_inventory"

# Max chars per chunk — keeps embeddings focused
CHUNK_CAP = 1200

# ── Table mapping ────────────────────────────────────────────────────────────

COLLECTION_TABLES = {
    "general": ("wisdom", "vss_wisdom"),
    "rust": ("knowledge_rust", "vss_code_rust"),
    "web": ("knowledge_web", "vss_code_web"),
    "security": ("knowledge_security", "vss_security"),
    "architecture": ("knowledge_architecture", "vss_architecture"),
    "companion": ("knowledge_companion", "vss_companion"),
}

COMPANION_SOURCE_TYPE = "companion_doc"
COMPANION_AUTHORITY = "project_companion"
COMPANION_PROOF_STATUS = "context_not_proof"


def ensure_memory_provenance_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS memory_sources (
            source_id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_path TEXT NOT NULL UNIQUE,
            source_sha256 TEXT NOT NULL,
            source_type TEXT NOT NULL,
            authority TEXT NOT NULL,
            proof_status TEXT NOT NULL,
            chunk_count INTEGER NOT NULL DEFAULT 0,
            indexed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            is_stale BOOLEAN NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS memory_chunks (
            chunk_id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id INTEGER NOT NULL,
            collection TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            chunk_sha256 TEXT NOT NULL,
            metadata TEXT NOT NULL,
            knowledge_rowid INTEGER,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(source_id) REFERENCES memory_sources(source_id) ON DELETE CASCADE,
            UNIQUE(source_id, chunk_index)
        );

        CREATE INDEX IF NOT EXISTS idx_memory_sources_type
            ON memory_sources(source_type, is_stale);

        CREATE INDEX IF NOT EXISTS idx_memory_chunks_source
            ON memory_chunks(source_id, collection);
        """
    )
    conn.commit()


# ── Section → collection routing for engineering_knowledge_base.md ──────────

_WEB_PATTERNS = re.compile(r"react|next\.js|typescript|javascript|css|html|node", re.I)
_SEC_PATTERNS = re.compile(r"security|auth|encrypt|hash|password|jwt|cors|ssl|xss|csrf", re.I)
_ARCH_PATTERNS = re.compile(r"architecture|docker|deployment|database|sql|best practice", re.I)


def route_section(header: str) -> str:
    if _SEC_PATTERNS.search(header):
        return "security"
    if _WEB_PATTERNS.search(header):
        return "web"
    if _ARCH_PATTERNS.search(header):
        return "architecture"
    return "general"


# ── Chunking ─────────────────────────────────────────────────────────────────


def chunk_by_h2(text: str, file_label: str) -> list[tuple[str, str]]:
    """
    Split markdown into (chunk_text, metadata) pairs.
    Splits on ## headers. Each chunk includes its header.
    Long chunks are further split at paragraph boundaries.
    """
    sections: list[tuple[str, str]] = []
    parts = re.split(r"\n(?=## )", text)

    for part in parts:
        part = part.strip()
        if not part:
            continue
        header_match = re.match(r"^(## .+?)$", part, re.MULTILINE)
        header = header_match.group(1) if header_match else file_label

        if len(part) <= CHUNK_CAP:
            sections.append((part, f"{file_label} | {header}"))
        else:
            # Split oversized sections at blank lines
            paragraphs = re.split(r"\n\n+", part)
            current = ""
            for para in paragraphs:
                if current and len(current) + len(para) + 2 > CHUNK_CAP:
                    sections.append((current.strip(), f"{file_label} | {header}"))
                    current = para
                else:
                    current = (current + "\n\n" + para) if current else para
            if current.strip():
                sections.append((current.strip(), f"{file_label} | {header}"))

    return sections


def chunks_for_coding_laws(text: str) -> list[tuple[str, str, str]]:
    """Returns (chunk, metadata, collection) for coding_laws.md."""
    chunks = chunk_by_h2(text, "coding_laws")
    return [(chunk, meta, "general") for chunk, meta in chunks]


def chunks_for_eng_kb(text: str) -> list[tuple[str, str, str]]:
    """Returns (chunk, metadata, collection) for engineering_knowledge_base.md."""
    chunks = chunk_by_h2(text, "eng_kb")
    result = []
    for chunk, meta in chunks:
        # Use the header part of meta for routing
        header = meta.split("|", 1)[-1].strip()
        collection = route_section(header)
        result.append((chunk, meta, collection))
    return result


# ── COMPANION doc parsing ───────────────────────────────────────────────────

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _strip_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """
    Splits YAML frontmatter from body.
    Returns ({key: value}, body_text).
    Only handles simple scalar fields (name, description) — not full YAML.
    """
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text

    front_text = m.group(1)
    body = text[m.end() :]

    # Parse name: and description: manually (no external YAML dep required)
    meta: dict[str, str] = {}
    current_key: str | None = None
    current_lines: list[str] = []

    for line in front_text.splitlines():
        if re.match(r"^(\w[\w-]*):\s*(\|)?\s*$", line):
            if current_key:
                meta[current_key] = " ".join(current_lines).strip()
            key_match = re.match(r"^([\w-]+):", line)
            current_key = key_match.group(1) if key_match else None
            current_lines = []
        elif current_key and (line.startswith("  ") or line.startswith("\t")):
            current_lines.append(line.strip())
        elif re.match(r"^([\w-]+):\s+(.+)$", line):
            kv = re.match(r"^([\w-]+):\s+(.+)$", line)
            if kv:
                if current_key:
                    meta[current_key] = " ".join(current_lines).strip()
                meta[kv.group(1)] = kv.group(2).strip()
                current_key = None
                current_lines = []

    if current_key and current_lines:
        meta[current_key] = " ".join(current_lines).strip()

    return meta, body


def chunks_for_companion_doc(path: Path) -> list[tuple[str, str, str]]:
    """
    Parse a COMPANION_*.md file.
    - Strips YAML frontmatter (uses name: as skill identifier).
    - Injects the description: field as the first chunk so the router's
      semantic search can match on the trigger text.
    - Chunks the body by h2 section.
    All chunks go to the 'companion' collection.
    """
    text = path.read_text(encoding="utf-8")
    front, body = _strip_frontmatter(text)

    skill_name = front.get("name", path.stem.lower().replace("_", "-"))
    description = front.get("description", "")
    file_label = f"companion | {skill_name}"

    chunks: list[tuple[str, str, str]] = []

    # Ingest the routing description as its own chunk so similarity search
    # against "Load when..." trigger phrases surfaces this Skill.
    if description:
        trigger_text = f"Skill: {skill_name}\nRouting trigger: {description}"
        chunks.append((trigger_text, f"{file_label} | routing-trigger", "companion"))

    # Chunk the body by section
    for chunk, meta in chunk_by_h2(body, file_label):
        chunks.append((chunk, meta, "companion"))

    return chunks


# ── ProgramBench corpus parsing ─────────────────────────────────────────────


def _walk_md_tree(root: Path, label_prefix: str) -> list[tuple[str, str, str]]:
    """Walk a markdown tree, chunk by h2, return (text, metadata, collection)."""
    if not root.exists():
        return []
    chunks: list[tuple[str, str, str]] = []
    for md in sorted(root.rglob("*.md")):
        rel = md.relative_to(root).as_posix()
        text = md.read_text(encoding="utf-8")
        if text.startswith("---"):
            _, body = _strip_frontmatter(text)
        else:
            body = text
        file_label = f"{label_prefix} | {rel}"
        for chunk, meta in chunk_by_h2(body, file_label):
            chunks.append((chunk, meta, "general"))
    return chunks


def chunks_for_swebench() -> list[tuple[str, str, str]]:
    """Walk corpus/swebench/**/*.md → general collection with `swebench |` prefix."""
    return _walk_md_tree(SWEBENCH_DIR, "swebench")


def chunks_for_programbench() -> list[tuple[str, str, str]]:
    """
    Walk corpus/programbench/**/*.md, strip frontmatter, chunk by h2.
    All chunks routed to 'general' collection so the existing wisdom/vss_wisdom
    tables hold them — no schema migration required.
    Metadata prefix `programbench | <relative_path> | <header>` lets the RAG
    surface programbench material on tool-build-related queries.
    """
    if not PROGRAMBENCH_DIR.exists():
        return []

    chunks: list[tuple[str, str, str]] = []
    for md in sorted(PROGRAMBENCH_DIR.rglob("*.md")):
        rel = md.relative_to(PROGRAMBENCH_DIR).as_posix()
        # Skip per_tool_overrides test fixtures (e.g. lnav UTF-8-test.md is deliberately
        # invalid UTF-8) — they are tool assets, not knowledge. Read robustly otherwise.
        if "per_tool_overrides/" in rel:
            continue
        text = md.read_text(encoding="utf-8", errors="replace")
        if text.startswith("---"):
            _, body = _strip_frontmatter(text)
        else:
            body = text
        file_label = f"programbench | {rel}"
        for chunk, meta in chunk_by_h2(body, file_label):
            chunks.append((chunk, meta, "general"))
    return chunks


def chunks_for_pb_knowledge() -> list[tuple[str, str, str]]:
    """
    Ingest the MACHINE-READABLE PB knowledge that the .md walk misses:
      - build_knowledge.json : official metric, class_patterns, repair techniques, lessons,
        and the roadmap of what is still needed (so models can RETRIEVE it, not just the
        system self-apply it). This is the fix for 'the corpus can't SEE its own knowledge'.
      - verified_locks.json  : a SUMMARY (count + integrity rule), so retrieval surfaces the
        single source of truth for what is genuinely locked and how it is proven.
    Each top-level section becomes one chunk, routed to 'general' with a distinct prefix so
    reseeding replaces it cleanly.
    """
    import json as _json

    chunks: list[tuple[str, str, str]] = []
    bk = PROGRAMBENCH_DIR / "build_knowledge.json"
    if bk.exists():
        try:
            data = _json.loads(bk.read_text(encoding="utf-8"))
            for section, body in data.items():
                if section.startswith("_"):
                    continue
                text = f"# ProgramBench knowledge: {section}\n\n{_json.dumps(body, indent=2, ensure_ascii=False)}"
                chunks.append((text, f"programbench | build_knowledge.json | {section}", "general"))
        except Exception as e:
            print(f"  [WARN] build_knowledge.json not ingested: {e}")
    reg = PROGRAMBENCH_DIR / "verified_locks.json"
    if reg.exists():
        try:
            r = _json.loads(reg.read_text(encoding="utf-8"))
            locks = r.get("locks", {})
            summ = (
                f"# ProgramBench verified-lock registry (single source of truth)\n\n"
                f"{r.get('note', '')}\n\nRegistered locks: {len(locks)}. "
                f"A lock is genuine ONLY if its archived eval is passed==total (0 not_run/skipped/failed) "
                f"AND the pinned submission_sha256 still matches the archive tarball; otherwise it is "
                f"UNVERIFIED (run determinex_pb_lock_registry.py check-integrity). Tools: "
                + ", ".join(sorted(locks)[:80])
            )
            chunks.append(
                (summ, "programbench | verified_locks.json | registry-summary", "general")
            )
        except Exception as e:
            print(f"  [WARN] verified_locks.json not ingested: {e}")
    return chunks


def chunks_for_programbench_factory_logs() -> list[tuple[str, str, str]]:
    """
    Walk accepted factory markdown artifacts and failure inventories.

    These files are local operator state rather than lock archives, but they
    contain the live packet specs, gate lessons, and cluster reports that make
    the next model attempt more informed. They stay in the general collection
    with distinct metadata prefixes so reseeding can replace them cleanly.
    """
    chunks: list[tuple[str, str, str]] = []
    chunks.extend(_walk_md_tree(PROGRAMBENCH_FACTORY_DIR, "pb_factory"))
    chunks.extend(_walk_md_tree(PROGRAMBENCH_FAILURE_INVENTORY_DIR, "pb_failure_inventory"))
    return chunks


# ── Embedding + insert ────────────────────────────────────────────────────────


def embed_and_insert(
    conn: sqlite3.Connection,
    model: TextEmbedding,
    chunks: list[tuple[str, str, str]],
) -> int:
    inserted = 0
    for text, metadata, collection in chunks:
        rel_table, vss_table = COLLECTION_TABLES[collection]

        # Generate 384-dim AllMiniLML6V2 embedding
        vecs = list(model.embed([text]))
        vec = vecs[0]
        if len(vec) != 384:
            print(f"  [WARN] unexpected dim {len(vec)}, skipping chunk")
            continue

        embedding_bytes = struct.pack(f"{len(vec)}f", *vec)

        cur = conn.execute(
            f"INSERT INTO {rel_table} (content, metadata) VALUES (?, ?)",
            (text, metadata),
        )
        rowid = cur.lastrowid
        conn.execute(
            f"INSERT INTO {vss_table} (rowid, embedding_vector) VALUES (?, ?)",
            (rowid, embedding_bytes),
        )
        inserted += 1

    conn.commit()
    return inserted


def embed_and_insert_one(
    conn: sqlite3.Connection,
    model: TextEmbedding,
    text: str,
    metadata: str,
    collection: str,
) -> int | None:
    rel_table, vss_table = COLLECTION_TABLES[collection]
    vecs = list(model.embed([text]))
    vec = vecs[0]
    if len(vec) != 384:
        print(f"  [WARN] unexpected dim {len(vec)}, skipping chunk")
        return None

    embedding_bytes = struct.pack(f"{len(vec)}f", *vec)
    cur = conn.execute(
        f"INSERT INTO {rel_table} (content, metadata) VALUES (?, ?)",
        (text, metadata),
    )
    rowid = cur.lastrowid
    conn.execute(
        f"INSERT INTO {vss_table} (rowid, embedding_vector) VALUES (?, ?)",
        (rowid, embedding_bytes),
    )
    return int(rowid)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _source_path(path: Path) -> str:
    try:
        return path.resolve().as_posix()
    except OSError:
        return path.as_posix()


def _companion_manifest(paths: list[Path]) -> dict[str, str]:
    return {_source_path(path): _sha256_bytes(path.read_bytes()) for path in paths}


def companion_manifest_current(conn: sqlite3.Connection, paths: list[Path]) -> bool:
    ensure_memory_provenance_schema(conn)
    if not paths:
        return False
    row = conn.execute("SELECT 1 FROM knowledge_companion LIMIT 1").fetchone()
    if row is None:
        return False

    expected = _companion_manifest(paths)
    stored_rows = conn.execute(
        """
        SELECT source_path, source_sha256
        FROM memory_sources
        WHERE source_type = ? AND is_stale = 0
        """,
        (COMPANION_SOURCE_TYPE,),
    ).fetchall()
    stored = {path: digest for path, digest in stored_rows}
    return stored == expected


def clear_companion_rows(conn: sqlite3.Connection) -> int:
    rowids = [
        row[0]
        for row in conn.execute(
            "SELECT rowid FROM knowledge_companion WHERE metadata LIKE ?",
            ("companion |%",),
        ).fetchall()
    ]
    if rowids:
        placeholders = ",".join("?" for _ in rowids)
        conn.execute(f"DELETE FROM vss_companion WHERE rowid IN ({placeholders})", rowids)
        conn.execute(f"DELETE FROM knowledge_companion WHERE rowid IN ({placeholders})", rowids)

    source_ids = [
        row[0]
        for row in conn.execute(
            "SELECT source_id FROM memory_sources WHERE source_type = ?",
            (COMPANION_SOURCE_TYPE,),
        ).fetchall()
    ]
    if source_ids:
        placeholders = ",".join("?" for _ in source_ids)
        conn.execute(f"DELETE FROM memory_chunks WHERE source_id IN ({placeholders})", source_ids)
        conn.execute(f"DELETE FROM memory_sources WHERE source_id IN ({placeholders})", source_ids)

    conn.commit()
    return len(rowids)


def seed_companions(model: TextEmbedding, *, reseed: bool = False) -> int:
    companion_files = sorted(COMPANION_DIR.glob("COMPANION_*.md"))
    if not companion_files:
        print(f"[WARN] No COMPANION_*.md files found in {COMPANION_DIR}")
        return 0

    conn = _open_db()
    try:
        ensure_memory_provenance_schema(conn)
        if companion_manifest_current(conn, companion_files):
            if not reseed:
                print("Companion docs already seeded with current source hashes")
                return 0
        cleared = clear_companion_rows(conn)
        if cleared:
            print(f"Cleared {cleared} prior companion rows for reseed")

        total = 0
        for companion_path in companion_files:
            print(f"Reading {companion_path.name}...")
            chunks = chunks_for_companion_doc(companion_path)
            source_path = _source_path(companion_path)
            source_sha256 = _sha256_bytes(companion_path.read_bytes())
            source_cur = conn.execute(
                """
                INSERT INTO memory_sources
                (source_path, source_sha256, source_type, authority, proof_status, chunk_count, is_stale)
                VALUES (?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    source_path,
                    source_sha256,
                    COMPANION_SOURCE_TYPE,
                    COMPANION_AUTHORITY,
                    COMPANION_PROOF_STATUS,
                    len(chunks),
                ),
            )
            source_id = int(source_cur.lastrowid)

            inserted = 0
            for chunk_index, (text, metadata, collection) in enumerate(chunks):
                rowid = embed_and_insert_one(conn, model, text, metadata, collection)
                if rowid is None:
                    continue
                conn.execute(
                    """
                    INSERT INTO memory_chunks
                    (source_id, collection, chunk_index, chunk_sha256, metadata, knowledge_rowid)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source_id,
                        collection,
                        chunk_index,
                        _sha256_bytes(text.encode("utf-8")),
                        metadata,
                        rowid,
                    ),
                )
                inserted += 1
            conn.commit()
            print(f"  -> inserted {inserted} companion rows with provenance")
            total += inserted
        return total
    finally:
        conn.close()


# ── Already-seeded guard ──────────────────────────────────────────────────────

SEED_MARKER = "seed_knowledge_base.py"
PB_METADATA_PREFIX = "programbench |"
SB_METADATA_PREFIX = "swebench |"
PB_FACTORY_METADATA_PREFIXES = ("pb_factory |", "pb_failure_inventory |")


def already_seeded(conn: sqlite3.Connection) -> bool:
    """Returns True if seeding has run before (checks for marker row in wisdom)."""
    try:
        row = conn.execute(
            "SELECT 1 FROM wisdom WHERE metadata LIKE ? LIMIT 1",
            (f"%{SEED_MARKER}%",),
        ).fetchone()
        return row is not None
    except sqlite3.OperationalError:
        return False


def already_seeded_pb(conn: sqlite3.Connection) -> bool:
    """Returns True if programbench corpus has been seeded (checks for any pb metadata row)."""
    try:
        row = conn.execute(
            "SELECT 1 FROM wisdom WHERE metadata LIKE ? LIMIT 1",
            (f"{PB_METADATA_PREFIX}%",),
        ).fetchone()
        return row is not None
    except sqlite3.OperationalError:
        return False


def already_seeded_pb_factory(conn: sqlite3.Connection) -> bool:
    """Returns True if ProgramBench factory logs have been seeded."""
    try:
        for prefix in PB_FACTORY_METADATA_PREFIXES:
            row = conn.execute(
                "SELECT 1 FROM wisdom WHERE metadata LIKE ? LIMIT 1",
                (f"{prefix}%",),
            ).fetchone()
            if row is not None:
                return True
        return False
    except sqlite3.OperationalError:
        return False


def already_seeded_sb(conn: sqlite3.Connection) -> bool:
    try:
        row = conn.execute(
            "SELECT 1 FROM wisdom WHERE metadata LIKE ? LIMIT 1",
            (f"{SB_METADATA_PREFIX}%",),
        ).fetchone()
        return row is not None
    except sqlite3.OperationalError:
        return False


def _clear_rows_with_prefix(conn: sqlite3.Connection, prefix: str) -> int:
    try:
        cur = conn.execute(
            "SELECT rowid FROM wisdom WHERE metadata LIKE ?",
            (f"{prefix}%",),
        )
        rowids = [r[0] for r in cur.fetchall()]
        if not rowids:
            return 0
        placeholders = ",".join("?" for _ in rowids)
        conn.execute(f"DELETE FROM vss_wisdom WHERE rowid IN ({placeholders})", rowids)
        conn.execute(f"DELETE FROM wisdom WHERE rowid IN ({placeholders})", rowids)
        conn.commit()
        return len(rowids)
    except sqlite3.OperationalError:
        return 0


def clear_programbench_rows(conn: sqlite3.Connection) -> int:
    """Delete prior programbench rows so a reseed produces a clean state."""
    try:
        cur = conn.execute(
            "SELECT rowid FROM wisdom WHERE metadata LIKE ?",
            (f"{PB_METADATA_PREFIX}%",),
        )
        rowids = [r[0] for r in cur.fetchall()]
        if not rowids:
            return 0
        placeholders = ",".join("?" for _ in rowids)
        conn.execute(f"DELETE FROM vss_wisdom WHERE rowid IN ({placeholders})", rowids)
        conn.execute(f"DELETE FROM wisdom WHERE rowid IN ({placeholders})", rowids)
        conn.commit()
        return len(rowids)
    except sqlite3.OperationalError:
        return 0


def clear_programbench_factory_rows(conn: sqlite3.Connection) -> int:
    """Delete prior ProgramBench factory rows for idempotent reseeding."""
    return sum(_clear_rows_with_prefix(conn, prefix) for prefix in PB_FACTORY_METADATA_PREFIXES)


def insert_marker(conn: sqlite3.Connection, model: TextEmbedding) -> None:
    """Insert a sentinel row so the idempotency check finds it next run."""
    marker = f"Determinex knowledge base seeded by {SEED_MARKER}"
    vecs = list(model.embed([marker]))
    vec = vecs[0]
    embedding_bytes = struct.pack(f"{len(vec)}f", *vec)
    cur = conn.execute(
        "INSERT INTO wisdom (content, metadata) VALUES (?, ?)",
        (marker, SEED_MARKER),
    )
    conn.execute(
        "INSERT INTO vss_wisdom (rowid, embedding_vector) VALUES (?, ?)",
        (cur.lastrowid, embedding_bytes),
    )
    conn.commit()


# ── Main ─────────────────────────────────────────────────────────────────────


def _open_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    return conn


def seed_swebench(model: TextEmbedding, *, reseed: bool = False) -> int:
    """Independently ingest corpus/swebench/ into the wisdom collection (`swebench |` prefix)."""
    if not SWEBENCH_DIR.exists():
        print(f"[INFO] {SWEBENCH_DIR} not found - skipping swebench corpus")
        return 0
    conn = _open_db()
    try:
        if already_seeded_sb(conn):
            if not reseed:
                print("SWE-bench corpus already seeded (use --reseed-swebench to re-ingest)")
                return 0
            cleared = _clear_rows_with_prefix(conn, SB_METADATA_PREFIX)
            print(f"Cleared {cleared} prior swebench rows for reseed")
        chunks = chunks_for_swebench()
        if not chunks:
            print(f"[WARN] no markdown found under {SWEBENCH_DIR}")
            return 0
        print("Reading corpus/swebench/...")
        print(f"  -> {len(chunks)} chunks (collection=general, prefix={SB_METADATA_PREFIX})")
        n = embed_and_insert(conn, model, chunks)
        print(f"  -> inserted {n} rows")
        return n
    finally:
        conn.close()


def seed_programbench(model: TextEmbedding, *, reseed: bool = False) -> int:
    """
    Independently ingest the corpus/programbench/ tree into the wisdom collection.
    Idempotent: bails if any pb metadata row exists, unless reseed=True.
    Returns rows inserted.
    """
    if not PROGRAMBENCH_DIR.exists():
        print(f"[INFO] {PROGRAMBENCH_DIR} not found - skipping programbench corpus")
        return 0

    conn = _open_db()
    try:
        if already_seeded_pb(conn):
            if not reseed:
                print("ProgramBench corpus already seeded (use --reseed-programbench to re-ingest)")
                return 0
            cleared = clear_programbench_rows(conn)
            print(f"Cleared {cleared} prior programbench rows for reseed")

        chunks = chunks_for_programbench()
        chunks.extend(chunks_for_pb_knowledge())  # JSON knowledge: build_knowledge + lock registry
        if not chunks:
            print(f"[WARN] no markdown found under {PROGRAMBENCH_DIR}")
            return 0
        print("Reading corpus/programbench/...")
        print(f"  -> {len(chunks)} chunks (collection=general, prefix={PB_METADATA_PREFIX})")
        n = embed_and_insert(conn, model, chunks)
        print(f"  -> inserted {n} rows")
        return n
    finally:
        conn.close()


def seed_programbench_factory_logs(model: TextEmbedding, *, reseed: bool = False) -> int:
    """
    Ingest ProgramBench factory packets, lessons, and failure inventories.

    This is intentionally tied to the ProgramBench reseed path so an accepted
    gate can refresh both stable corpus docs and the latest local factory
    lessons in one command.
    """
    if not PROGRAMBENCH_FACTORY_DIR.exists() and not PROGRAMBENCH_FAILURE_INVENTORY_DIR.exists():
        print("[INFO] no ProgramBench factory logs found - skipping factory-log corpus")
        return 0

    conn = _open_db()
    try:
        if already_seeded_pb_factory(conn):
            if not reseed:
                print(
                    "ProgramBench factory logs already seeded (use --reseed-programbench to re-ingest)"
                )
                return 0
            cleared = clear_programbench_factory_rows(conn)
            print(f"Cleared {cleared} prior ProgramBench factory rows for reseed")

        chunks = chunks_for_programbench_factory_logs()
        if not chunks:
            print("[WARN] no markdown found under ProgramBench factory log roots")
            return 0
        print("Reading ProgramBench factory logs...")
        print(
            "  -> "
            f"{len(chunks)} chunks (collection=general, prefixes={', '.join(PB_FACTORY_METADATA_PREFIXES)})"
        )
        n = embed_and_insert(conn, model, chunks)
        print(f"  -> inserted {n} rows")
        return n
    finally:
        conn.close()


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Determinex knowledge-base seeder")
    ap.add_argument(
        "--reseed-programbench",
        action="store_true",
        help="Wipe & re-ingest corpus/programbench/ even if already seeded",
    )
    ap.add_argument(
        "--programbench-only",
        action="store_true",
        help="Skip core seeding; only refresh the programbench corpus",
    )
    ap.add_argument(
        "--reseed-swebench",
        action="store_true",
        help="Wipe & re-ingest corpus/swebench/ even if already seeded",
    )
    ap.add_argument(
        "--swebench-only",
        action="store_true",
        help="Skip core seeding; only refresh the swebench corpus",
    )
    ap.add_argument(
        "--reseed-companions",
        action="store_true",
        help="Wipe & re-ingest docs/companions/ even if source hashes match",
    )
    ap.add_argument(
        "--companions-only",
        action="store_true",
        help="Skip other seeding; only refresh companion project memory",
    )
    args = ap.parse_args()

    if not DB_PATH.exists():
        sys.exit(
            f"DB not found at {DB_PATH}\n"
            "Start the Determinex app at least once first so Tauri creates the DB."
        )

    if args.swebench_only:
        print("Loading fastembed AllMiniLML6V2 (384-dim)...")
        model = TextEmbedding(model_name="sentence-transformers/all-MiniLM-L6-v2")
        n = seed_swebench(model, reseed=args.reseed_swebench)
        print(f"\nDone. {n} swebench entries seeded.")
        return

    if args.companions_only:
        print("Loading fastembed AllMiniLML6V2 (384-dim)...")
        model = TextEmbedding(model_name="sentence-transformers/all-MiniLM-L6-v2")
        n = seed_companions(model, reseed=args.reseed_companions)
        print(f"\nDone. {n} companion entries seeded.")
        return

    if args.programbench_only:
        print("Loading fastembed AllMiniLML6V2 (384-dim)...")
        model = TextEmbedding(model_name="sentence-transformers/all-MiniLM-L6-v2")
        n_pb = seed_programbench(model, reseed=args.reseed_programbench)
        n_pf = seed_programbench_factory_logs(model, reseed=args.reseed_programbench)
        n_sb = seed_swebench(model, reseed=args.reseed_swebench)
        n_comp = seed_companions(model, reseed=args.reseed_companions)
        print(
            f"\nDone. {n_pb} programbench + {n_pf} factory + {n_sb} swebench "
            f"+ {n_comp} companion entries seeded."
        )
        return

    conn = _open_db()

    if already_seeded(conn):
        print("Knowledge base already seeded - core skipped.")
        conn.close()
        # Still try the bench corpora — they have their own markers.
        print("Loading fastembed AllMiniLML6V2 (384-dim)...")
        model = TextEmbedding(model_name="sentence-transformers/all-MiniLM-L6-v2")
        n_pb = seed_programbench(model, reseed=args.reseed_programbench)
        n_pf = seed_programbench_factory_logs(model, reseed=args.reseed_programbench)
        n_sb = seed_swebench(model, reseed=args.reseed_swebench)
        n_comp = seed_companions(model, reseed=args.reseed_companions)
        print(
            f"\nDone. {n_pb} programbench + {n_pf} factory + {n_sb} swebench "
            f"+ {n_comp} companion entries seeded."
        )
        return

    print("Loading fastembed AllMiniLML6V2 (384-dim)...")
    model = TextEmbedding(model_name="sentence-transformers/all-MiniLM-L6-v2")

    total = 0

    # ── coding_laws.md ───────────────────────────────────────────────────────
    if CODING_LAWS.exists():
        print(f"Reading {CODING_LAWS.name}...")
        text = CODING_LAWS.read_text(encoding="utf-8")
        chunks = chunks_for_coding_laws(text)
        print(f"  -> {len(chunks)} chunks, collection=general")
        n = embed_and_insert(conn, model, chunks)
        print(f"  -> inserted {n} rows")
        total += n
    else:
        print(f"[WARN] {CODING_LAWS} not found - skipping")

    # ── engineering_knowledge_base.md ────────────────────────────────────────
    if ENG_KB.exists():
        print(f"Reading {ENG_KB.name}...")
        text = ENG_KB.read_text(encoding="utf-8")
        chunks = chunks_for_eng_kb(text)
        by_coll: dict[str, int] = {}
        for _, _, col in chunks:
            by_coll[col] = by_coll.get(col, 0) + 1
        print(f"  -> {len(chunks)} chunks: {by_coll}")
        n = embed_and_insert(conn, model, chunks)
        print(f"  -> inserted {n} rows")
        total += n
    else:
        print(f"[WARN] {ENG_KB} not found - skipping")

    insert_marker(conn, model)
    conn.close()

    # ── COMPANION_*.md skill documents ─────────────────────────────────────────────────
    total += seed_companions(model, reseed=args.reseed_companions)

    # ── ProgramBench corpus ──────────────────────────────────────────────────
    n_pb = seed_programbench(model, reseed=args.reseed_programbench)
    total += n_pb
    n_pf = seed_programbench_factory_logs(model, reseed=args.reseed_programbench)
    total += n_pf

    # ── SWE-bench corpus ─────────────────────────────────────────────────────
    n_sb = seed_swebench(model, reseed=args.reseed_swebench)
    total += n_sb

    print(f"\nDone. {total} entries seeded into Determinex vector DB.")
    print(f"DB: {DB_PATH}")


if __name__ == "__main__":
    main()
