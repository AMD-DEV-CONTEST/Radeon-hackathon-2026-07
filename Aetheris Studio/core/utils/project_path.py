"""Active project folder: validation + the shared `ACTIVE_PROJECT_PATH` env
var every file/shell tool already reads fresh per-call (`file_controller.py`,
`core/llm.py`, `integrations/aider_client.py`, `core/utils/project_name.py`
-- confirmed, none of them cache it at import time). Ported from
`controllers/chat_controller.py::validate_project_path`/`set_project_path`
(Flet-only, in-process) so the Fase 4.5 HTTP endpoints can do the same job
for a separate-process Flutter client -- same validation rules, same env
var, just reachable over HTTP now.

Persistence + per-chat memory (added after a confirmed real pain: an
in-memory-only env var meant restarting the backend for an unrelated fix
silently forgot the open project mid-session, which broke Cartographer/
search_map for that session with no visible signal why). Persisted to
CHAT_PROJECTS_FILE as `{"current": path, "chats": {chat_id: path}}`.
`ACTIVE_PROJECT_PATH` itself stays a single current value -- every file
tool below `_resolve_in_project` reads it with no chat_id in scope, and
threading one through every tool handler's signature is out of scope here
-- but the client can look up what a SPECIFIC chat last had open via
`get_project_path_for_chat` and re-apply it via `set_active_project_path`
when the user switches chats, which is what "per chat" means in practice
for a UI that's always looking at exactly one chat at a time.
"""

import os
from typing import Optional

_CRITICAL_FOLDERS = [
    "C:\\Windows", "C:\\System32", "C:\\Program Files", "C:\\Program Files (x86)",
    "C:\\Users\\Default", "C:\\PerfLogs", "C:\\$Recycle.Bin", "C:\\Recovery",
]


def validate_project_path(path: str) -> tuple[bool, str]:
    """Garante que o diretório seja válido, absoluto e seguro. Retorna
    (True, caminho_resolvido) ou (False, motivo)."""
    try:
        resolved = os.path.realpath(path)
        resolved_lower = resolved.lower()
        for crit in _CRITICAL_FOLDERS:
            if resolved_lower == crit.lower() or resolved_lower.startswith(crit.lower() + os.sep):
                return False, "Caminho do sistema reservado e protegido."
        if ".." in resolved or resolved_lower == "c:\\":
            return False, "Caminho raiz do sistema ou traversal não permitido."
        if not os.path.isdir(resolved):
            return False, "Caminho não existe ou não é uma pasta."
        return True, resolved
    except Exception as e:
        return False, str(e)


def _load_state() -> dict:
    from core.atomic_io import atomic_read_json
    from core.utils.constants import CHAT_PROJECTS_FILE
    state = atomic_read_json(CHAT_PROJECTS_FILE, default=None)
    if not isinstance(state, dict):
        return {"current": "", "chats": {}}
    state.setdefault("current", "")
    state.setdefault("chats", {})
    return state


def _save_state(state: dict) -> None:
    from core.atomic_io import atomic_write_json
    from core.utils.constants import CHAT_PROJECTS_FILE
    atomic_write_json(CHAT_PROJECTS_FILE, state)


def restore_persisted_active_path() -> None:
    """Repopulates ACTIVE_PROJECT_PATH from disk -- call once at process
    startup (app.py's lifespan), before anything else reads it. A fresh
    process otherwise starts with this env var unset regardless of what
    was open last (confirmed directly: restarting the backend mid-session
    silently reset it to empty and broke Cartographer/search_map for that
    session -- see this module's docstring)."""
    current = _load_state().get("current", "")
    if current and os.path.isdir(current):
        os.environ["ACTIVE_PROJECT_PATH"] = current


def get_active_project_path() -> str:
    return os.environ.get("ACTIVE_PROJECT_PATH", "")


def get_project_path_for_chat(chat_id: str) -> str:
    """The project a specific chat last had active, for the client to
    auto-restore on switching to that chat (see module docstring -- this
    is memory the client acts on, not something the tool-resolution path
    itself consults)."""
    if not chat_id:
        return ""
    return _load_state().get("chats", {}).get(chat_id, "")


def set_active_project_path(path: str, chat_id: Optional[str] = None) -> tuple[bool, str]:
    """Valida e aplica `path` como o projeto ativo. Retorna (True, caminho
    resolvido) em sucesso ou (False, motivo) em falha -- não levanta.

    Persists the resolved path as both the new "current" (survives a
    backend restart) and, when `chat_id` is given, that chat's own
    remembered project (survives switching to a different chat and back)."""
    is_valid, resolved_or_reason = validate_project_path(path)
    if not is_valid:
        return False, resolved_or_reason
    os.environ["ACTIVE_PROJECT_PATH"] = resolved_or_reason
    state = _load_state()
    state["current"] = resolved_or_reason
    if chat_id:
        state["chats"][chat_id] = resolved_or_reason
    _save_state(state)
    return True, resolved_or_reason
