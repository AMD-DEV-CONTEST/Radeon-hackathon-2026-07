"""Episodic chat history, backed by the SQLite `sessions`/`chat_messages`
tables already defined in `core/database.py` (including the FTS5 index kept
in sync by `_migrate_chat_messages_fts`'s triggers) instead of MongoDB.

Same public function names/signatures as the old MongoDB-backed version on
purpose, so `controllers/chat_controller.py` and everything else that
imports from here needed minimal changes. "chat_id" is `Session.id`.
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("chat_history")

HISTORY_TOKEN_LIMIT = 1000


def get_db():
    """Return a truthy sentinel if the SQLite store is reachable, else
    None. Kept for callers that only check `get_db() is not None`
    (`controllers/chat_controller.py`'s `db_active` flag) -- unlike Mongo,
    a local SQLite file essentially never has a "server offline" state, but
    this still surfaces a real problem (disk full, permissions, corrupt
    file) instead of masking it.
    """
    try:
        from sqlalchemy import text
        from core.database import get_db_session
        with get_db_session() as db:
            db.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.error(f"Erro ao acessar o banco local (SQLite): {e}")
        return None


def create_chat(first_message: str) -> str:
    """Cria uma nova sessão, retorna o chat_id (Session.id)."""
    from core.database import get_db_session, Session
    from core.utils.vte_bridge import VTE_DEFAULT_URL, VTE_DEFAULT_MODEL

    chat_id = str(uuid.uuid4())
    title = " ".join(first_message.split()[:5]) + "..." if first_message and first_message != "Nova Conversa" else "Novo Chat"
    try:
        with get_db_session() as db:
            db.add(Session(
                id=chat_id,
                name=title,
                endpoint_url=VTE_DEFAULT_URL,
                model=VTE_DEFAULT_MODEL,
                message_count=0,
            ))
    except Exception as e:
        logger.error(f"Erro ao criar chat: {e}")
    return chat_id


def append_message(chat_id: str, role: str, content: str, token_count: int) -> None:
    """Salva uma mensagem no histórico da sessão."""
    from core.database import get_db_session, Session, ChatMessage, utcnow_naive

    try:
        with get_db_session() as db:
            db.add(ChatMessage(
                id=str(uuid.uuid4()),
                session_id=chat_id,
                role=role,
                content=content,
                meta_data=json.dumps({"token_count": token_count, "compressed": False}),
                timestamp=utcnow_naive(),
            ))
            session = db.get(Session, chat_id)
            if session is not None:
                session.message_count = (session.message_count or 0) + 1
                session.last_message_at = utcnow_naive()
    except Exception as e:
        logger.error(f"Erro ao salvar mensagem: {e}")


def load_chat_history(chat_id: str) -> list[dict]:
    """Carrega mensagens mais recentes que cabem em 1000 tokens no total.
    Nunca retorna mais do que esse budget permite."""
    from core.database import get_db_session, ChatMessage

    try:
        with get_db_session() as db:
            rows = (
                db.query(ChatMessage)
                .filter(ChatMessage.session_id == chat_id)
                .order_by(ChatMessage.timestamp.desc())
                .all()
            )
            messages = []
            total_tokens = 0
            for row in rows:
                meta = {}
                if row.meta_data:
                    try:
                        meta = json.loads(row.meta_data)
                    except (json.JSONDecodeError, TypeError):
                        meta = {}
                tokens = meta.get("token_count", 0)
                if total_tokens + tokens <= HISTORY_TOKEN_LIMIT:
                    messages.append({
                        "role": row.role,
                        "content": row.content,
                        "token_count": tokens,
                        "compressed": meta.get("compressed", False),
                    })
                    total_tokens += tokens
                else:
                    break
            messages.reverse()
            return messages
    except Exception as e:
        logger.error(f"Erro ao carregar histórico: {e}")
        return []


def list_chats() -> list[dict]:
    """Lista todas as sessões com id, título, data e contagem de mensagens."""
    from core.database import get_db_session, Session

    try:
        with get_db_session() as db:
            rows = db.query(Session).order_by(Session.last_accessed.desc()).all()
            return [
                {
                    "chat_id": s.id,
                    "title": s.name,
                    "created_at": s.created_at,
                    "updated_at": s.last_accessed,
                    "message_count": s.message_count or 0,
                    "summary": None,
                }
                for s in rows
            ]
    except Exception as e:
        logger.error(f"Erro ao listar chats: {e}")
        return []


def update_chat_summary(chat_id: str, summary: str) -> None:
    """Atualiza o resumo de compactação da sessão (guardado em headers,
    já que Session não tem uma coluna 'summary' dedicada)."""
    from core.database import get_db_session, Session

    try:
        with get_db_session() as db:
            session = db.get(Session, chat_id)
            if session is not None:
                headers = dict(session.headers or {})
                headers["summary"] = summary
                session.headers = headers
    except Exception as e:
        logger.error(f"Erro ao atualizar summary do chat: {e}")


def rename_chat(chat_id: str, new_title: str) -> None:
    """Atualiza o título da sessão."""
    from core.database import get_db_session, Session

    try:
        with get_db_session() as db:
            session = db.get(Session, chat_id)
            if session is not None:
                session.name = new_title
    except Exception as e:
        logger.error(f"Erro ao renomear chat: {e}")


def delete_chat(chat_id: str) -> None:
    """Remove a sessão e todas as suas mensagens (cascade)."""
    from core.database import get_db_session, Session

    try:
        with get_db_session() as db:
            session = db.get(Session, chat_id)
            if session is not None:
                db.delete(session)
    except Exception as e:
        logger.error(f"Erro ao deletar chat: {e}")
