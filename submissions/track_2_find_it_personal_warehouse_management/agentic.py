"""Agentic retrieval chat over video/audio transcriptions.

This module implements the *backend* of the agentic chat: an LLM agent that
reasons over the frame-description + audio-transcription store, decides query
terms, calls search/list/summary/memory tools, and answers with timestamp
back-references (play_url).  See ``reference/agentic-retrieval-plan.txt`` for
the design notes this builds on.

The agent runs a prompt-based **JSON ReAct** loop (portable across any
OpenAI-compatible chat/completions endpoint):

    {"action":"tool","tool":"search_transcriptions","arguments":{"q":"..."}}
    {"action":"reply","content":"..."}
    {"action":"ask","content":"..."}

Persistence uses SQLite tables created next to the existing video catalogue
(``agent_sessions``, ``agent_messages``, ``agent_memory``).

This module deliberately does **not** import ``main`` — the tool callables are
injected by the app (see ``main.py``), keeping the loop unit-testable.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ai_clients import AgentProtocolError


def _setup_logging() -> logging.Logger:
    """Configure the shared 'agentic' logger with a stderr handler.

    Verbose by default (DEBUG, controllable via AGENT_LOG_LEVEL) so the backend
    shows the live streamed LLM output and parsing details.
    """
    log = logging.getLogger("agentic")
    if not log.handlers:
        handler = logging.StreamHandler()
        level = os.environ.get("AGENT_LOG_LEVEL", "DEBUG").upper()
        handler.setFormatter(logging.Formatter(
            "[agentic] %(asctime)s %(levelname)s %(message)s"
        ))
        log.addHandler(handler)
        log.setLevel(getattr(logging, level, logging.DEBUG))
        log.propagate = False
    return log


log = _setup_logging()

# --------------------------------------------------------------------------- #
# System prompt
# --------------------------------------------------------------------------- #

SYSTEM_PROMPT = """\
You are a video-retrieval agent for a personal video library. Every video has
been processed into:

  * frame_descriptions — short vision-model captions of what is visible, each
    tagged with a timestamp (seconds).
  * audio_transcriptions — speech-to-text segments with start/end timestamps.

Your job is to answer the user's question about what is in the videos, where an
object or moment is, and when it happened.

Attached context:
When the user attaches images or audio, they are transcribed to text and
included in the user message under "--- attached context ---". Those
descriptions/transcriptions describe what the user is currently looking at or
hearing, so they are strong evidence of the user's intent. Use them to
understand exactly which object, moment, or event the user is referring to.

Rules:
1. FIRST understand the user's intent — from their words and any attached
   context — before you start searching. If the intent is ambiguous, use "ask"
   to clarify rather than guessing.
2. Always call the tools you need BEFORE giving a final answer. You have access
   to search_transcriptions, list_videos, get_video_keywords,
   get_video_transcriptions, get_media_url, get_feedback_history,
   suggest_likely_moments, and the memory_* / feedback_* tools.
3. Choose query terms carefully: the transcriptions may be multilingual
   (Chinese and English), and captions/ASR may be approximate. search_transcriptions
   splits your query on whitespace and searches each token with OR semantics by
   default, so a multi-word query returns moments matching ANY of the words
   (ranked by how many match). Use operand=AND only when you need every word to
   appear together. Use operand=EXPR for precise boolean expressions such as
   (mouse OR keyboard) AND (screen OR display OR \"credit card\"). Try a few
   synonyms, alternate spellings, or both languages before concluding "not
   found".
4. Cite your sources: when you answer, reference the video name/location and
   the timestamp, and include the play_url so the user can jump straight to the
   moment (e.g. "/media/<video_id>#t=<seconds>").
5. Use the memory tools to remember useful term mappings across conversations
   (e.g. a correct term <-> an ambiguous description the model mis-heard), and
   consult memory before searching.
6. Learn from feedback history: users rate retrieved items with a thumbs up
   (correct) or thumbs down (wrong), stored with the question and your answer.
   Before finalizing, you may call get_feedback_history to see which terms and
   items were confirmed or rejected in the past, and refine your search terms
   accordingly.
7. The user can ask you to edit or delete their feedback and memory by
   describing it in natural language (e.g. "discard every feedback and memory
   related to ipod"). Use feedback_delete / feedback_set and
   memory_delete_where / memory_store to carry out such cleanup before
   continuing to search.
8. PHENOMENOLOGICAL FALLBACK (never refuse): if a direct keyword search for
   the object's NAME finds nothing, do NOT say "not found". Reason about where
   the object usually is and what it usually looks like — spatial anchors
   (e.g. "above the display", "top of the monitor", "on the desk") and visual
   primitives (lens, clip/mount, small, circular, dark, cables, protruding).
   Call suggest_likely_moments with those descriptors to find the most likely
   candidates. In your answer, present the top candidates and EXPLICITLY
   express your uncertainty, e.g. "This is likely a <target> — it matches
   typical <target> features (lens, mounted above the display), but I can't be
   certain; please verify visually."

If you cannot emit a structured tool call, simply answer conversationally in
plain text — the system will run a keyword search on the user's words for you.

Respond in this exact JSON format, and nothing else:

  To call a tool:    {"action":"tool","tool":"<name>","arguments":{...}}
  To answer:         {"action":"reply","content":"<your answer>"}
  To clarify:        {"action":"ask","content":"<your question>"}

Never produce text outside the JSON object.
"""


SYSTEM_PROMPT_INCOGNITO = """\
You are a video-retrieval agent for a personal video library. Every video has
been processed into:

  * frame_descriptions — short vision-model captions of what is visible, each
    tagged with a timestamp (seconds).
  * audio_transcriptions — speech-to-text segments with start/end timestamps.

You are in INCOGNITO mode: you have ONLY read-only access to the video
transcription store. You cannot read or write any memory or feedback, and you
must answer strictly from the transcriptions themselves.

Attached context:
When the user attaches images or audio, they are transcribed to text and
included in the user message under "--- attached context ---". Those
descriptions/transcriptions describe what the user is currently looking at or
hearing, so they are strong evidence of the user's intent.

Rules:
1. FIRST understand the user's intent — from their words and any attached
   context — before you start searching. If the intent is ambiguous, use "ask"
   to clarify rather than guessing.
2. You only have these tools: search_transcriptions, list_videos,
   get_video_keywords, get_video_transcriptions, get_media_url,
   suggest_likely_moments. You have NO access to memory or feedback — do not
   attempt to use them.
3. Choose query terms carefully: the transcriptions may be multilingual
   (Chinese and English), and captions/ASR may be approximate. search_transcriptions
   splits your query on whitespace and searches each token with OR semantics by
   default, so a multi-word query returns moments matching ANY of the words
   (ranked by how many match). Use operand=AND only when you need every word to
   appear together. Use operand=EXPR for precise boolean expressions such as
   (mouse OR keyboard) AND (screen OR display OR \"credit card\"). Try a few
   synonyms, alternate spellings, or both languages before concluding "not
   found".
4. Cite your sources: when you answer, reference the video name/location and
   the timestamp, and include the play_url so the user can jump straight to the
   moment (e.g. "/media/<video_id>#t=<seconds>").
5. PHENOMENOLOGICAL FALLBACK (never refuse): if a direct name search finds
   nothing, do NOT say "not found". Reason about where the object usually is
   and what it usually looks like (spatial anchors + visual primitives) and
   call suggest_likely_moments with those descriptors. Present the top
   candidates and explicitly express your uncertainty.

If you cannot emit a structured tool call, simply answer conversationally in
plain text — the system will run a keyword search on the user's words for you.

Respond in this exact JSON format, and nothing else:

  To call a tool:    {"action":"tool","tool":"<name>","arguments":{...}}
  To answer:         {"action":"reply","content":"<your answer>"}
  To clarify:        {"action":"ask","content":"<your question>"}

Never produce text outside the JSON object.
"""


# Stopwords / question words dropped when building the plain-conversation
# fallback search query (the raw user question is too noisy for keyword search).
_FALLBACK_STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "in", "on", "at", "to", "for", "is",
    "are", "was", "were", "be", "this", "that", "it", "with", "from", "by",
    "as", "not", "no", "so", "but", "find", "where", "what", "when", "how",
    "why", "can", "you", "me", "my", "your", "there", "do", "did", "does",
    "i", "we", "they", "he", "she", "about", "like", "find me", "tell",
}


def _fallback_query(raw: str) -> str:
    """Extract the meaningful search terms from a user message.

    Drops stopwords / question words and caps the length so the keyword search
    actually matches the transcriptions.
    """
    text = (raw or "").strip().lower()
    tokens = [t for t in re.split(r"[^a-z0-9一-鿿]+", text) if t]
    keep = [t for t in tokens if t not in _FALLBACK_STOPWORDS and len(t) > 1]
    return " ".join(keep[:4])


# Tool results fed back to the model are capped (huge transcriptions can blow
# the context and cause truncated/malformed model output).
_TOOL_RESULT_MAX = int(os.environ.get("AGENT_LLM_TOOL_RESULT_MAX", "8000"))


def _first_user_title(text: str) -> str:
    """A placeholder session title from the user's first prompt."""
    s = " ".join((text or "").split())
    if not s:
        return ""
    return s[:48] + ("…" if len(s) > 48 else "")


# Ask the model to condense the FIRST assistant answer into a short title.
_TITLE_PROMPT = (
    "Write a short title for this chat — at most 6 words, plain text, no "
    "quotes, no punctuation, no JSON. Base it on what the conversation is "
    "about. Only output the title.\n\nConversation so far:\n{reply}"
)


class Attachment:
    """One image or audio segment attached by the user, already transcribed.

    kind: "image" (VLM caption) or "audio" (ASR transcription).
    text: the transcription/description of the attachment.
    name: original filename, for the agent's reference (optional).
    """

    __slots__ = ("kind", "text", "name")

    def __init__(self, kind: str, text: str, name: str = "") -> None:
        if kind not in ("image", "audio"):
            raise ValueError(f"unknown attachment kind: {kind!r}")
        self.kind = kind
        self.text = text
        self.name = name


# --------------------------------------------------------------------------- #
# SQLite storage
# --------------------------------------------------------------------------- #

AGENT_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_sessions (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL DEFAULT '',
    incognito   INTEGER NOT NULL DEFAULT 0,  -- 1 = no memory/feedback, read-only
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_messages (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id     TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    role           TEXT NOT NULL,          -- user | assistant | tool
    content        TEXT NOT NULL DEFAULT '',
    tool_call_json TEXT,                   -- JSON {tool, arguments} (assistant/tool rows)
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agent_messages_session
    ON agent_messages(session_id, id);

CREATE TABLE IF NOT EXISTS agent_memory (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_feedback (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id     TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    video_id       TEXT NOT NULL,
    source         TEXT NOT NULL,            -- frame | audio
    timestamp      REAL NOT NULL,
    end_timestamp  REAL,
    rating         INTEGER NOT NULL,         -- +1 thumbs up, -1 thumbs down
    user_message   TEXT,                     -- chat context captured at rating time
    agent_reply    TEXT,
    tool_arguments TEXT,                     -- JSON: query terms the agent used
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_feedback_anchor
    ON agent_feedback(session_id, video_id, source, timestamp);
CREATE INDEX IF NOT EXISTS idx_agent_feedback_global
    ON agent_feedback(video_id, source, timestamp);
"""


def create_agent_tables(conn: sqlite3.Connection) -> None:
    """Create the agentic-chat tables if they do not exist."""
    conn.executescript(AGENT_SCHEMA)
    # Lightweight migration for databases created before incognito existed.
    # PRAGMA table_info columns: (cid, name, type, notnull, dflt_value, pk).
    cols = {row[1] for row in conn.execute("PRAGMA table_info(agent_sessions)")}
    if "incognito" not in cols:
        conn.execute(
            "ALTER TABLE agent_sessions ADD COLUMN incognito INTEGER NOT NULL DEFAULT 0"
        )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# Session store
# --------------------------------------------------------------------------- #

class AgentSessionStore:
    """Persists agent chat sessions + messages in SQLite."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def create(self, title: str = "", incognito: bool = False) -> dict[str, Any]:
        session_id = uuid.uuid4().hex
        now = _now_iso()
        with closing(self._conn()) as conn, conn:
            conn.execute(
                "INSERT INTO agent_sessions (id, title, incognito, created_at, updated_at)"
                " VALUES (?,?,?,?,?)",
                (session_id, title.strip(), 1 if incognito else 0, now, now),
            )
        return {
            "session_id": session_id,
            "title": title.strip(),
            "incognito": bool(incognito),
            "created_at": now,
        }

    def list(self) -> list[dict[str, Any]]:
        with closing(self._conn()) as conn:
            rows = conn.execute(
                "SELECT * FROM agent_sessions ORDER BY updated_at DESC"
            ).fetchall()
        out = [dict(r) for r in rows]
        for d in out:
            d["incognito"] = bool(d.get("incognito"))
        return out

    def get(self, session_id: str) -> dict[str, Any] | None:
        with closing(self._conn()) as conn:
            row = conn.execute(
                "SELECT * FROM agent_sessions WHERE id = ?", (session_id,)
            ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["incognito"] = bool(d.get("incognito"))
        return d

    def touch(self, session_id: str) -> None:
        with closing(self._conn()) as conn, conn:
            conn.execute(
                "UPDATE agent_sessions SET updated_at = ? WHERE id = ?",
                (_now_iso(), session_id),
            )

    def set_title(self, session_id: str, title: str) -> None:
        """Update a session's title (and bump updated_at)."""
        with closing(self._conn()) as conn, conn:
            conn.execute(
                "UPDATE agent_sessions SET title = ?, updated_at = ? WHERE id = ?",
                (title.strip(), _now_iso(), session_id),
            )

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        tool_call_json: str | None = None,
    ) -> None:
        with closing(self._conn()) as conn, conn:
            conn.execute(
                "INSERT INTO agent_messages"
                " (session_id, role, content, tool_call_json, created_at)"
                " VALUES (?,?,?,?,?)",
                (session_id, role, content, tool_call_json, _now_iso()),
            )

    def get_messages(self, session_id: str) -> list[dict[str, Any]]:
        with closing(self._conn()) as conn:
            rows = conn.execute(
                "SELECT * FROM agent_messages WHERE session_id = ? ORDER BY id",
                (session_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def delete(self, session_id: str) -> bool:
        with closing(self._conn()) as conn, conn:
            cur = conn.execute("DELETE FROM agent_sessions WHERE id = ?", (session_id,))
        return cur.rowcount > 0


# --------------------------------------------------------------------------- #
# Retrieval-enhancement memory
# --------------------------------------------------------------------------- #

class AgentMemory:
    """Persistent term/mapping memory the agent can read and write."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def store(self, key: str, value: str) -> dict[str, str]:
        now = _now_iso()
        with closing(self._conn()) as conn, conn:
            conn.execute(
                "INSERT INTO agent_memory (key, value, created_at, updated_at)"
                " VALUES (?,?,?,?)"
                " ON CONFLICT(key) DO UPDATE SET value=excluded.value,"
                " updated_at=excluded.updated_at",
                (key, value, now, now),
            )
        return {"key": key, "value": value}

    def get(self, key: str) -> dict[str, Any] | None:
        with closing(self._conn()) as conn:
            row = conn.execute(
                "SELECT key, value FROM agent_memory WHERE key = ?", (key,)
            ).fetchone()
        return dict(row) if row else None

    def list(self) -> list[dict[str, Any]]:
        with closing(self._conn()) as conn:
            rows = conn.execute(
                "SELECT key, value, created_at, updated_at FROM agent_memory"
                " ORDER BY updated_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def delete(self, key: str) -> bool:
        with closing(self._conn()) as conn, conn:
            cur = conn.execute("DELETE FROM agent_memory WHERE key = ?", (key,))
        return cur.rowcount > 0

    def delete_where(self, contains: str) -> int:
        """Delete every memory entry whose key or value contains the substring."""
        like = f"%{contains}%"
        with closing(self._conn()) as conn, conn:
            cur = conn.execute(
                "DELETE FROM agent_memory WHERE key LIKE ? OR value LIKE ?",
                (like, like),
            )
        return cur.rowcount


# --------------------------------------------------------------------------- #
# Item feedback (thumbs up / down)
# --------------------------------------------------------------------------- #

def _anchor_ts(value: float) -> float:
    """Normalize a timestamp for use as an item anchor."""
    return round(float(value), 3)


class AgentFeedback:
    """Per-item retrieval feedback (thumbs up/down) with the chat context.

    Each row anchors to one search result item: (video_id, source, timestamp).
    The user's thumbs rating is stored together with the user question and the
    agent's answer, so the agent can later review this history globally to
    improve search terms.
    """

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def upsert(
        self,
        *,
        session_id: str,
        video_id: str,
        source: str,
        timestamp: float,
        rating: int,
        user_message: str = "",
        agent_reply: str = "",
        tool_arguments: str = "",
        end_timestamp: float | None = None,
    ) -> dict[str, Any]:
        """Create or update feedback for one item (rating toggles in place)."""
        if rating not in (1, -1):
            raise ValueError("rating must be +1 (up) or -1 (down)")
        ts = _anchor_ts(timestamp)
        now = _now_iso()
        with closing(self._conn()) as conn, conn:
            conn.execute(
                """
                INSERT INTO agent_feedback
                  (session_id, video_id, source, timestamp, end_timestamp,
                   rating, user_message, agent_reply, tool_arguments,
                   created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(session_id, video_id, source, timestamp)
                DO UPDATE SET
                  rating = excluded.rating,
                  end_timestamp = excluded.end_timestamp,
                  user_message = excluded.user_message,
                  agent_reply = excluded.agent_reply,
                  tool_arguments = excluded.tool_arguments,
                  updated_at = excluded.updated_at
                """,
                (session_id, video_id, source, ts, end_timestamp,
                 rating, user_message, agent_reply, tool_arguments,
                 now, now),
            )
            row = conn.execute(
                "SELECT * FROM agent_feedback"
                " WHERE session_id = ? AND video_id = ? AND source = ? AND timestamp = ?",
                (session_id, video_id, source, ts),
            ).fetchone()
        return dict(row)

    def get_for_session(self, session_id: str) -> list[dict[str, Any]]:
        with closing(self._conn()) as conn:
            rows = conn.execute(
                "SELECT * FROM agent_feedback WHERE session_id = ?"
                " ORDER BY updated_at DESC",
                (session_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def list(
        self,
        *,
        query: str = "",
        video_id: str = "",
        source: str = "",
        rating: int | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Global feedback history (across sessions) with optional filters.

        Used by the agent's ``get_feedback_history`` tool to learn from past
        confirmed/rejected items.
        """
        clauses: list[str] = []
        params: list[Any] = []
        if video_id:
            clauses.append("video_id = ?")
            params.append(video_id)
        if source in ("frame", "audio"):
            clauses.append("source = ?")
            params.append(source)
        if rating in (1, -1):
            clauses.append("rating = ?")
            params.append(rating)
        if query:
            clauses.append(
                "(user_message LIKE ? OR agent_reply LIKE ? OR tool_arguments LIKE ?)"
            )
            like = f"%{query}%"
            params.extend([like, like, like])
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        sql = (
            "SELECT * FROM agent_feedback " + where
            + " ORDER BY updated_at DESC LIMIT ?"
        )
        params.append(int(limit))
        with closing(self._conn()) as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def delete(self, session_id: str, video_id: str, source: str, timestamp: float) -> bool:
        with closing(self._conn()) as conn, conn:
            cur = conn.execute(
                "DELETE FROM agent_feedback"
                " WHERE session_id = ? AND video_id = ? AND source = ? AND timestamp = ?",
                (session_id, video_id, source, _anchor_ts(timestamp)),
            )
        return cur.rowcount > 0

    def delete_many(
        self,
        *,
        query: str = "",
        video_id: str = "",
        source: str = "",
        session_id: str = "",
    ) -> int:
        """Bulk-delete feedback rows matching the given filters.

        Used by the agent's ``feedback_delete`` tool so the user can say
        "discard every feedback related to X". At least one filter is required
        (we never nuke the whole table by accident).
        """
        clauses: list[str] = []
        params: list[Any] = []
        if session_id:
            clauses.append("session_id = ?")
            params.append(session_id)
        if video_id:
            clauses.append("video_id = ?")
            params.append(video_id)
        if source in ("frame", "audio"):
            clauses.append("source = ?")
            params.append(source)
        if query:
            clauses.append(
                "(user_message LIKE ? OR agent_reply LIKE ? OR tool_arguments LIKE ?)"
            )
            like = f"%{query}%"
            params.extend([like, like, like])
        if not clauses:
            raise ValueError("at least one filter is required to delete feedback")
        where = "WHERE " + " AND ".join(clauses)
        with closing(self._conn()) as conn, conn:
            cur = conn.execute("DELETE FROM agent_feedback " + where, params)
        return cur.rowcount


# --------------------------------------------------------------------------- #
# Tool execution
# --------------------------------------------------------------------------- #

class ToolError(RuntimeError):
    """Raised by a tool implementation when it cannot produce a result."""


# HTTP/network-style exception names (checked by type name so agentic.py does
# not need to import requests). These mean the agent LLM service is unreachable
# or misconfigured — a distinct message from "bad model output".
_LLM_NETWORK_ERRORS = {
    "HTTPError", "ConnectionError", "ConnectTimeout", "ReadTimeout",
    "Timeout", "SSLError", "ProxyError", "ChunkedEncodingError",
}


def _llm_error_reply(exc: Exception) -> str:
    """Build a user-facing reply when the agent LLM call fails.

    Distinguishes "the agent LLM service is unreachable/misconfigured" from
    "the model returned malformed output" — in the latter case it reports the
    retry count and a snippet of the raw output so the user (and the verbose
    backend log) can diagnose it.
    """
    name = type(exc).__name__
    raw = getattr(exc, "raw", "")
    retries = getattr(exc, "retries", 0)
    if isinstance(exc, AgentProtocolError):
        snippet = (raw or "").strip()
        if len(snippet) > 200:
            snippet = snippet[:200] + "…"
        msg = (
            "The agent model returned malformed output"
            + (f" after {retries} attempt(s)" if retries else "")
            + "."
        )
        if snippet:
            msg += f" Raw output: {snippet!r}."
        msg += " I've logged the full details to the backend log."
        log.warning("[agent] protocol error surfaced to user: %s", msg)
        return msg
    if name in _LLM_NETWORK_ERRORS:
        return (
            "The agent LLM service could not be reached. Check the "
            "AGENT_LLM_API_URL / AGENT_LLM_MODEL / AGENT_LLM_API_KEY settings "
            "(or set AGENT_LLM_MOCK=true to run with a mock agent) and try again."
        )
    return (
        f"An error occurred while contacting the agent model ({name}): {exc} "
        "I've logged the full details to the backend log."
    )


class AgentRuntime:
    """Runs the JSON-ReAct agent loop against injected tools.

    tool_schemas: list of OpenAI-style function definitions sent to the LLM.
    tool_impls:   dict {tool_name: callable(**arguments) -> JSON-serializable}.
    """

    def __init__(
        self,
        *,
        llm_client: Any,
        tool_schemas: list[dict],
        tool_impls: dict[str, Callable[..., Any]],
        store: AgentSessionStore,
        memory: AgentMemory,
        max_turns: int = 8,
        system_prompt: str = SYSTEM_PROMPT,
    ) -> None:
        self.llm_client = llm_client
        self.tool_schemas = tool_schemas
        self.tool_impls = tool_impls
        self.store = store
        self.memory = memory
        self.max_turns = max_turns
        self.system_prompt = system_prompt

    # -- history serialization --------------------------------------------- #

    @staticmethod
    def _to_llm_messages(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Map stored messages to OpenAI-style messages.

        Emits NATIVE OpenAI ``tool_calls`` / ``tool`` role so models with real
        function-calling (DeepSeek, vLLM, OpenAI) round-trip correctly.  The
        JSON-ReAct text is kept in ``content`` (and a ``[Tool result: <name>]``
        marker on tool rows) so models that only read text still work too.
        """
        out: list[dict[str, Any]] = []
        for row in rows:
            role = row["role"]
            if role == "tool":
                meta = json.loads(row["tool_call_json"] or "{}")
                name = meta.get("tool", "tool")
                tid = meta.get("tool_call_id")
                msg: dict[str, Any] = {
                    "role": "tool",
                    "content": f"[Tool result: {name}]\n{row['content']}",
                }
                if tid:
                    msg["tool_call_id"] = tid
                out.append(msg)
            elif role == "assistant" and row["tool_call_json"]:
                meta = json.loads(row["tool_call_json"] or "{}")
                msg = {"role": "assistant", "content": row["content"]}
                name = meta.get("tool") or "tool"
                args = meta.get("arguments") or {}
                tid = meta.get("tool_call_id") or f"call_{len(out)}"
                msg["tool_calls"] = [{
                    "id": tid,
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": json.dumps(args, ensure_ascii=False),
                    },
                }]
                out.append(msg)
            else:
                out.append({"role": "user" if role == "user" else "assistant",
                            "content": row["content"]})
        return out

    # -- tool execution ----------------------------------------------------- #

    def _execute_tool(self, name: str, arguments: dict) -> Any:
        impl = self.tool_impls.get(name)
        if impl is None:
            raise ToolError(f"unknown tool: {name}")
        try:
            return impl(**arguments)
        except (ToolError, TypeError, ValueError) as exc:
            raise ToolError(f"tool {name} failed: {exc}") from exc

    def _plain_fallback_enrich(self, raw_query: str, reply: str) -> str:
        """Append best-effort search results to a plain-text reply.

        Used when the model answered conversationally WITHOUT issuing a
        structured tool call (``plain=True``).  We run a keyword search with
        the meaningful words from the user's message and append the matching
        moments so the "agentic" retrieval still happens even when function
        calling is not used.
        """
        q = _fallback_query(raw_query)
        if not q:
            return reply
        impl = self.tool_impls.get("search_transcriptions")
        if impl is None:
            return reply
        try:
            hits = impl(q=q, limit=3)
        except Exception:
            return reply
        if not hits:
            return reply
        lines = [
            f"- {h['play_url']}  ({h['source']} @ {h['timestamp']}s) {h['text'][:80]}"
            for h in hits
        ]
        return (
            reply.rstrip()
            + "\n\n"
            + f"(I searched for '{q}' and found these moments:)\n"
            + "\n".join(lines)
        )

    # -- session title ------------------------------------------------------ #

    def _llm_title(self, reply: str) -> str:
        """Ask the LLM to condense the first answer into a short session title."""
        try:
            resp = self.llm_client.chat(
                [
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": _TITLE_PROMPT.format(reply=(reply or "")[:4000])},
                ],
                [],  # no tools — it must reply with just a title
            )
        except Exception as exc:
            log.warning("[agent] title LLM call failed: %s", exc, exc_info=True)
            return ""
        if resp.kind != "reply":
            return ""
        t = " ".join((resp.content or "").strip().strip('"').split())
        return t[:60]

    def _maybe_generate_title(self, session_id: str, reply: str, explicit_title: bool) -> None:
        """Set the session title once, after the FIRST assistant final reply.

        ``explicit_title`` is True when the session was created with a
        user-provided title — those are never overwritten.  The title comes from
        the LLM condensing the first answer (tool calls are ignored — only the
        final response text is used); on any failure it degrades to a truncated
        version of the reply.  Best-effort: never raises.
        """
        if explicit_title:
            return
        if not (reply or "").strip():
            return
        try:
            rows = self.store.get_messages(session_id)
            has_prior_reply = any(
                m["role"] == "assistant" and not m.get("tool_call_json")
                and (m.get("content") or "").strip()
                for m in rows[:-1]  # exclude the reply just persisted
            )
            if has_prior_reply:
                return
            title = self._llm_title(reply) or _first_user_title(reply)
            if title and title.strip():
                self.store.set_title(session_id, title.strip())
                log.info("[agent] session %s title set to %r", session_id, title.strip())
        except Exception as exc:  # a title must never break the turn
            log.warning("[agent] title generation failed: %s", exc, exc_info=True)

    # -- the loop ----------------------------------------------------------- #

    @staticmethod
    def _build_user_content(text: str, attachments: list[Attachment] | None) -> str:
        """Compose a user message, appending transcribed attachments as a
        labelled, structured block so the agent can tell them apart."""
        parts = [text]
        if attachments:
            blocks = ["--- attached context (transcribed to text) ---"]
            for i, att in enumerate(attachments, 1):
                label = f"attached {att.kind}"
                if att.name:
                    label += f" ({att.name})"
                blocks.append(f"[{label} #{i}]\n{att.text}")
            parts.append("\n".join(blocks))
        return "\n\n".join(parts)

    def run(
        self,
        session_id: str,
        user_text: str,
        attachments: list[Attachment] | None = None,
        on_token=None,
        on_tool=None,
    ) -> dict[str, Any]:
        """Process one user message, running the agent loop to a final answer.

        ``attachments`` are already-transcribed image/audio segments that are
        folded into the user context in a structured block (see
        ``_build_user_content``).  ``on_token`` is called with each streamed
        content token of the model output; ``on_tool`` with each tool call as
        it happens (both used by the streaming chat endpoint).  Returns
        ``{reply, kind, turns, tool_calls, truncated}``.
        """
        user_text = (user_text or "").strip()
        if not user_text:
            raise ValueError("empty user message")
        sess0 = self.store.get(session_id)
        if sess0 is None:
            raise KeyError(f"unknown session: {session_id}")

        # A user-provided title at creation is never overwritten.
        explicit_title = bool((sess0.get("title") or "").strip())

        content = self._build_user_content(user_text, attachments or [])
        is_first = not self.store.get_messages(session_id)
        self.store.add_message(session_id, "user", content)
        # First prompt becomes an immediate placeholder title until the agent's
        # first answer is summarized.
        if is_first and not explicit_title and not (sess0.get("title") or "").strip():
            placeholder = _first_user_title(user_text)
            if placeholder:
                self.store.set_title(session_id, placeholder)
        tool_trace: list[dict[str, Any]] = []

        for turn in range(self.max_turns):
            rows = self.store.get_messages(session_id)
            messages = [{"role": "system", "content": self.system_prompt}] + self._to_llm_messages(rows)
            log.debug("[agent] --- turn %d/%d --- %d history messages",
                      turn + 1, self.max_turns, len(messages))

            try:
                resp = self.llm_client.chat(messages, self.tool_schemas, on_token=on_token)
            except Exception as exc:
                log.warning("[agent] LLM call failed on turn %d: %s",
                            turn + 1, exc, exc_info=True)
                reply = _llm_error_reply(exc)
                self.store.add_message(session_id, "assistant", reply)
                return {
                    "reply": reply,
                    "kind": "reply",
                    "turns": turn + 1,
                    "tool_calls": tool_trace,
                    "error": str(exc),
                }

            if resp.kind == "tool_call":
                tool_trace.append({"tool": resp.tool, "arguments": resp.arguments})
                log.debug("[agent] LLM wants tool %r args=%s",
                          resp.tool, json.dumps(resp.arguments, ensure_ascii=False))
                if on_tool:
                    on_tool(resp.tool, resp.arguments)
                # Persist the assistant's decision to call a tool.  The
                # tool_call_id lets native-function-calling models round-trip.
                tool_call_id = uuid.uuid4().hex
                self.store.add_message(
                    session_id, "assistant",
                    content=json.dumps(resp.to_dict()),
                    tool_call_json=json.dumps({
                        "tool": resp.tool, "arguments": resp.arguments,
                        "tool_call_id": tool_call_id,
                    }),
                )
                # Execute and feed the result back (errors become tool results).
                try:
                    result = self._execute_tool(resp.tool, resp.arguments)
                except ToolError as exc:
                    result = {"error": str(exc)}
                result_json = json.dumps(result, ensure_ascii=False, default=str)
                if len(result_json) > _TOOL_RESULT_MAX:
                    log.debug("[agent] truncating tool result %d -> %d chars",
                              len(result_json), _TOOL_RESULT_MAX)
                    result_json = result_json[:_TOOL_RESULT_MAX] + "\n…(truncated)"
                log.debug("[agent] tool %r result (%d chars): %s",
                          resp.tool, len(result_json), result_json[:500])
                self.store.add_message(
                    session_id, "tool",
                    content=result_json,
                    tool_call_json=json.dumps({
                        "tool": resp.tool, "tool_call_id": tool_call_id,
                    }),
                )
                continue

            # reply / ask.  If the model answered in plain natural language
            # (no structured tool call), do a best-effort keyword search so
            # retrieval still works without function calling.
            reply = resp.content or ""
            if getattr(resp, "plain", False):
                reply = self._plain_fallback_enrich(user_text, reply)
            log.debug("[agent] final response (kind=%s, %d chars): %s",
                      resp.kind, len(reply), reply[:300])
            self.store.add_message(session_id, "assistant", reply)
            self._maybe_generate_title(session_id, reply, explicit_title)
            self.store.touch(session_id)
            return {
                "reply": reply,
                "kind": resp.kind,
                "turns": turn + 1,
                "tool_calls": tool_trace,
            }

        # Turn limit reached without a final answer.  Never refuse: force a final
        # answer from the evidence gathered so far, with tools DISABLED so the
        # model cannot burn more turns.  The reply is persisted so it always
        # shows up in the transcript (previously it was dropped).
        reply = self._forced_final_answer(session_id, tool_trace, on_token=on_token)
        self.store.add_message(session_id, "assistant", reply)
        self._maybe_generate_title(session_id, reply, explicit_title)
        self.store.touch(session_id)
        return {
            "reply": reply,
            "kind": "reply",
            "turns": self.max_turns,
            "tool_calls": tool_trace,
            "truncated": True,
        }

    def _forced_final_answer(self, session_id: str, tool_trace: list[dict], on_token=None) -> str:
        """Force a final answer once the turn limit is hit — no more tool calls.

        The model has already gathered tool results in the conversation.  We
        append an instruction that NO tools are available anymore and it MUST
        write its answer now using only the evidence already collected, then
        call the LLM with ``tools=[]`` so the endpoint cannot return a tool
        call.  On any failure, degrade to the deterministic
        ``_turn_limit_fallback`` (best evidence recovered from the trace).
        """
        rows = self.store.get_messages(session_id)
        messages = (
            [{"role": "system", "content": self.system_prompt}]
            + self._to_llm_messages(rows)
            + [{
                "role": "user",
                "content": (
                    "[You have reached your maximum iteration limit "
                    f"({self.max_turns} tool calls). Tools are now DISABLED — "
                    "you may NOT call any tool. Write your final answer to the "
                    "user RIGHT NOW using only the evidence already gathered in "
                    "this conversation. If you could not confirm an exact match, "
                    "present the most likely candidates you found and clearly "
                    "state they are inferences, not confirmed matches, and that "
                    "you reached your turn limit.]"
                ),
            }]
        )
        try:
            resp = self.llm_client.chat(messages, [], on_token=on_token)  # [] -> no tools
        except Exception as exc:
            log.warning("[agent] forced-answer LLM call failed: %s", exc, exc_info=True)
            return self._turn_limit_fallback(session_id, tool_trace)
        if resp.kind == "tool_call":
            # Defensive: the endpoint insisted on a tool even with tools=[].
            log.warning("[agent] forced-answer still returned a tool call; using fallback")
            return self._turn_limit_fallback(session_id, tool_trace)
        reply = (resp.content or "").strip()
        return reply or self._turn_limit_fallback(session_id, tool_trace)

    def _turn_limit_fallback(self, session_id: str, tool_trace: list[dict]) -> str:
        """Build a best-effort answer when the agent loop runs out of turns.

        If the agent called ``suggest_likely_moments``, surface its top
        candidates with the uncertainty note (or an honest "nothing matched"
        message when the feature search came up empty) instead of a generic
        refusal.
        """
        # Recover any suggest_likely_moments tool result from this turn.
        for row in reversed(self.store.get_messages(session_id)):
            if row["role"] != "tool":
                continue
            meta = {}
            try:
                meta = json.loads(row["tool_call_json"] or "{}")
            except json.JSONDecodeError:
                continue
            if meta.get("tool") != "suggest_likely_moments":
                continue
            try:
                data = json.loads(row["content"])
            except json.JSONDecodeError:
                continue
            target = data.get("target") or "the object"
            feats_searched = data.get("features_searched") or []
            candidates = data.get("candidates") or []
            if candidates:
                lines = []
                for c in candidates[:5]:
                    ts = c.get("timestamp")
                    url = c.get("play_url") or f"/media/{c.get('video_id')}#t={ts}"
                    text = (c.get("text") or "")[:90]
                    feats = ", ".join(c.get("matched_features") or [])[:120]
                    lines.append(
                        f"- **~{round(ts, 1)}s** ({c.get('video_name') or c.get('location') or 'video'}): "
                        f"{text} — matches: {feats}. Play: {url}"
                    )
                note = (
                    f"I reached my maximum iteration limit ({self.max_turns} tool calls) "
                    f"without confirming an exact match for **{target}**, so this is the "
                    "best answer I can give from what I gathered. Based on typical "
                    f"**{target}** features, these are the most likely moments. "
                    "This is an inference, not a confirmed match — please verify visually."
                )
                return note + "\n\n" + "\n".join(lines)
            # No feature matches at all — report what was searched, honestly.
            terms = ", ".join(repr(f) for f in feats_searched[:8])
            return (
                f"I searched for **{target}** by name and by its typical features "
                f"({terms}) across all videos, but found no matching moments. "
                "It's likely not present in these recordings. If you can share an "
                "image or audio of it, I can look again."
            )
        return (
            f"I reached my maximum iteration limit ({self.max_turns} tool calls) without "
            "reaching a confident answer, so this is the best I can give from the "
            "evidence gathered so far. Try rephrasing or narrowing the question."
        )
