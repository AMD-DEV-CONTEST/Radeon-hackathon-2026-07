"""
determinex_cloak — Project Cloak: Bidirectional AST Identifier Obfuscation.

Semantically obfuscates repositories before sending context to cloud AI APIs.
Every private identifier visible to the AI is deterministically mapped to x_NNNN.
After the AI generates a patch, the restoration engine maps x_NNNN tokens back.

Architecture (7 components across 6 submodules):
  safe_list      — StdlibManifest: stdlib + builtins + packages + always-safe set
  classifier     — IdentifierClassifier: AST walker, frozenset of private identifiers
  symbol_map     — SymbolMap: deterministic alphabetical assignment, bidirectional
  transformer    — ASTTransformer + IssueTextTransformer: forward obfuscation
  restoration    — RestorationEngine: x_NNNN → original on AI output
  context        — CloakContext + AuditLogger: per-solve() session objects
  lang_extractor — Multi-language extraction + pipeline entry point (build_cloak_context)
"""

from __future__ import annotations

from typing import Optional


class CloakObfuscationError(RuntimeError):
    """Raised when obfuscation of a source file or string fails.

    Privacy invariant: when Cloak is enabled, NO plaintext source ever reaches a
    cloud LLM API call. Any failure during forward obfuscation must therefore
    fail closed — the caller is expected to abort the API call rather than send
    unredacted source. Returning the original source on error (the previous
    silent-fallthrough behavior) would have silently leaked proprietary
    identifiers under any obfuscation crash.

    Carries structured fields so the SWE-bench / ProgramBench agent loops can
    record the failure in the cloak audit log without ambiguity:

        path      file path the obfuscation was attempting (or "" for raw string)
        cause     the underlying exception
        source_len  size of the source being obfuscated (for diagnostics)
    """

    def __init__(
        self,
        *,
        path: str = "",
        cause: BaseException | None = None,
        source_len: int = 0,
    ):
        self.path = path
        self.cause = cause
        self.source_len = source_len
        msg = "CloakObfuscationError: failed to obfuscate"
        if path:
            msg += f" {path!r}"
        if cause is not None:
            msg += f" ({type(cause).__name__}: {cause})"
        msg += " — refusing to send plaintext source to API (fail-closed)"
        super().__init__(msg)

    def to_dict(self) -> dict:
        return {
            "error": "CloakObfuscationError",
            "path": self.path,
            "cause_type": type(self.cause).__name__ if self.cause else None,
            "cause_msg": str(self.cause) if self.cause else None,
            "source_len": self.source_len,
        }


from ._treesitter_bridge import _TS_AVAILABLE, TS_SUPPORTED_LANGUAGES
from .classifier import _IdentifierCollector, build_private_identifier_set
from .context import CloakAuditLogger, CloakContext
from .lang_extractor import (
    _build_cloak_context_nonpython,
    _build_cloak_context_regex,
    build_cloak_context,
)
from .restoration import restore_file_content, restore_patch
from .safe_list import _ALWAYS_SAFE, FRAMEWORK_KEEP_LIST, _build_safe_list
from .symbol_map import SymbolMap
from .transformer import obfuscate_issue_text, obfuscate_source

__all__ = [
    "CloakContext",
    "CloakAuditLogger",
    "CloakObfuscationError",
    "SymbolMap",
    "build_cloak_context",
    "build_private_identifier_set",
    "obfuscate_source",
    "obfuscate_issue_text",
    "restore_file_content",
    "restore_patch",
    "FRAMEWORK_KEEP_LIST",
]
