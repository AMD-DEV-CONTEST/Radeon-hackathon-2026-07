"""Active project folder: validation + the shared `ACTIVE_PROJECT_PATH` env
var every file/shell tool already reads fresh per-call (`file_controller.py`,
`core/llm.py`, `integrations/aider_client.py`, `core/utils/project_name.py`
-- confirmed, none of them cache it at import time). Ported from
`controllers/chat_controller.py::validate_project_path`/`set_project_path`
(Flet-only, in-process) so the Fase 4.5 HTTP endpoints can do the same job
for a separate-process Flutter client -- same validation rules, same env
var, just reachable over HTTP now.
"""

import os

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


def get_active_project_path() -> str:
    return os.environ.get("ACTIVE_PROJECT_PATH", "")


def set_active_project_path(path: str) -> tuple[bool, str]:
    """Valida e aplica `path` como o projeto ativo. Retorna (True, caminho
    resolvido) em sucesso ou (False, motivo) em falha -- não levanta."""
    is_valid, resolved_or_reason = validate_project_path(path)
    if not is_valid:
        return False, resolved_or_reason
    os.environ["ACTIVE_PROJECT_PATH"] = resolved_or_reason
    return True, resolved_or_reason
