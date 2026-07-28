"""Resolves an `@file` or `@folder` chat reference into real file content,
scoped to the active project (`ACTIVE_PROJECT_PATH`, see project_path.py).

Ported from the old Flet `controllers/file_controller.py::resolve_at_reference`
with one real bug fixed: that version resolved paths relative to the
Aetheris Studio app's OWN directory, not the user's selected active
project -- `@teste.txt` would only ever find a file if it happened to sit
inside the app's install folder, never inside the project the user actually
picked in the sidebar. This version resolves against
`project_path.get_active_project_path()`, matching every other project-file
tool (`read_project_file`, `list_project_files`, etc.).
"""

import os

from core.utils.project_path import get_active_project_path

_SKIP_DIR_NAMES = {
    "__pycache__", "venv", ".venv", "node_modules", ".git",
    "build", ".dart_tool", "ephemeral",
}
_MAX_TOKENS = 800


def _estimate_tokens(text: str) -> int:
    return int(len(text.split()) * 1.3)


def _truncate_to_tokens(text: str, max_tokens: int) -> str:
    words = text.split()
    max_words = int(max_tokens / 1.3)
    if len(words) > max_words:
        return " ".join(words[:max_words]) + "\n... (truncado por limite de tokens)"
    return text


def resolve_at_reference(tag: str) -> tuple[bool, str]:
    """Retorna (True, conteúdo) se `tag` (caminho relativo ao projeto ativo)
    resolveu para um arquivo ou pasta real; (False, motivo) caso contrário
    -- inclusive quando não há projeto ativo selecionado, ou `tag` não é um
    caminho de projeto de verdade (ex.: um e-mail digitado no chat)."""
    project_root = get_active_project_path()
    if not project_root:
        return False, "Nenhum projeto ativo selecionado."

    project_root = os.path.realpath(project_root)
    full_path = os.path.realpath(os.path.join(project_root, tag.strip("/\\")))

    if full_path != project_root and not full_path.startswith(project_root + os.sep):
        return False, f"Referência fora do projeto ativo: {tag}"

    if not os.path.exists(full_path):
        return False, f"Referência não encontrada: {tag}"

    if os.path.isfile(full_path):
        try:
            with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            return True, _truncate_to_tokens(content, _MAX_TOKENS)
        except Exception as e:
            return False, f"Erro ao ler {tag}: {e}"

    if os.path.isdir(full_path):
        tree = []
        contents = []
        tokens_used = 0

        for root, dirs, files in os.walk(full_path):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in _SKIP_DIR_NAMES]
            rel_root = os.path.relpath(root, project_root)
            tree.append(f"[dir] {rel_root}")

            for name in sorted(files):
                if name.startswith("."):
                    continue
                f_path = os.path.join(root, name)
                tree.append(f"  {name}")

                if (name.endswith(".py") or name.endswith(".md")) and tokens_used < _MAX_TOKENS:
                    try:
                        with open(f_path, "r", encoding="utf-8", errors="replace") as file_obj:
                            text = file_obj.read()
                        available = _MAX_TOKENS - tokens_used
                        if _estimate_tokens(text) > available:
                            text = _truncate_to_tokens(text, available)
                        contents.append(f"--- {os.path.relpath(f_path, project_root)} ---\n{text}")
                        tokens_used += _estimate_tokens(text)
                    except Exception:
                        pass

        result = "ÁRVORE DE DIRETÓRIOS:\n" + "\n".join(tree) + "\n\nCONTEÚDO:\n" + "\n\n".join(contents)
        return True, _truncate_to_tokens(result, _MAX_TOKENS)

    return False, f"Referência inválida: {tag}"
