"""Runtime wiring for the diary app.

Holds the process-wide singletons the diary needs — a shared Bionic-Graph client
and a per-session :class:`DiaryAgent` — so the server does not recreate them on
every turn. This is the single seam where the rest of the app (``server.py``,
``audio/stream_handler.py``) talks to the diary; nothing else imports
``BionicGraphClient`` / ``DiaryAgent`` directly.
"""

from __future__ import annotations

import datetime
from typing import Optional

from diary import config
from diary.agent import DiaryAgent
from diary.tools import DiaryContext

# One graph client for the whole process. Bionic-Graph is a single shared engine,
# and its HTTP client is cheap + stateless, so sharing it is both safe and the
# only sane thing to do across concurrent WebSocket sessions.
_client = None

# DiaryAgent keeps a short in-memory conversation history, so it is per session.
_agents: dict[str, DiaryAgent] = {}


def get_client():
    """Return the shared Bionic-Graph client, creating it on first use."""
    global _client
    if _client is None:
        from database.bionic_graph_client import BionicGraphClient

        _client = BionicGraphClient(
            base_url=config.GRAPH_URL,
            graph=config.GRAPH_NAME,
        )
    return _client


def today_iso() -> str:
    """Return today's date as YYYY-MM-DD (the diary's canonical day key)."""
    return datetime.date.today().isoformat()


def get_or_create_diary_agent(session_id: Optional[str] = None):
    """Return ``(DiaryAgent, DiaryContext)`` for a session.

    The agent is cached by ``session_id`` so its conversation history survives
    across turns. The context wraps the shared graph client and is rebuilt each
    call (it is immutable + cheap).
    """
    agent = _agents.get(session_id) if session_id else None
    if agent is None:
        agent = DiaryAgent()
        if session_id:
            _agents[session_id] = agent
    return agent, DiaryContext(client=get_client())
