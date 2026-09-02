"""
determinex_cloak/_treesitter_bridge.py — tree-sitter backend for Cloak identifier extraction.

PRIVACY REQUIREMENT: tree-sitter is the authoritative identifier extractor for
all non-Python languages (Go, Rust, TypeScript, JavaScript, C, C++, Ruby, PHP).
Regex fallback is available ONLY when DETERMINEX_CLOAK_ALLOW_DEGRADED=1 is set
by an explicit operator decision — it is NEVER silent.

Rationale: regex-based extraction has known false-negative rates for:
  - Rust macros and proc-macros (macro_rules!, derive attributes)
  - Go generic type parameters (introduced in 1.18)
  - TypeScript decorators and template literals
  - C/C++ preprocessor-generated identifiers

A false negative (missed identifier) in the FORWARD obfuscation pass = a real
private symbol leaks to the cloud API in plaintext. The system's privacy
guarantee requires 100% coverage of declared private identifiers.

To use Cloak with regex fallback (e.g. in a test environment without tree-sitter):
    export DETERMINEX_CLOAK_ALLOW_DEGRADED=1
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

log = logging.getLogger("determinex_cloak")

_ALLOW_DEGRADED = os.environ.get("DETERMINEX_CLOAK_ALLOW_DEGRADED", "").strip() == "1"

try:
    from determinex_cloak_treesitter import (  # type: ignore[import]
        TS_SUPPORTED_LANGUAGES,
        extract_treesitter_identifiers,
        resolve_python_star_imports,
    )

    _TS_AVAILABLE = True
except ImportError:
    _TS_AVAILABLE = False
    TS_SUPPORTED_LANGUAGES: frozenset[str] = frozenset()

    if _ALLOW_DEGRADED:
        log.warning(
            "[CLOAK] tree-sitter not installed; DETERMINEX_CLOAK_ALLOW_DEGRADED=1 "
            "set — proceeding with regex fallback. Privacy coverage is REDUCED for "
            "Rust macros, Go generics, and TypeScript decorators. "
            "Install: pip install 'determinex[cloak]' to restore full coverage."
        )

        def extract_treesitter_identifiers(*_a, **_k) -> frozenset:  # type: ignore[misc]
            return frozenset()

        def resolve_python_star_imports(*_a, **_k) -> list:  # type: ignore[misc]
            return []

    else:
        # Hard fail: regex fallback is not safe without explicit operator opt-in.
        # The privacy moat requires tree-sitter for non-Python languages.
        raise ImportError(
            "[CLOAK] tree-sitter is not installed but DETERMINEX_CLOAK_ALLOW_DEGRADED "
            "is not set. Refusing to proceed with regex fallback to prevent silent "
            "private identifier leakage.\n\n"
            "Fix options:\n"
            "  1. Install tree-sitter: pip install 'determinex[cloak]'\n"
            "     (adds tree-sitter, tree-sitter-rust, tree-sitter-go, etc.)\n"
            "  2. Use regex fallback (REDUCED PRIVACY): "
            "export DETERMINEX_CLOAK_ALLOW_DEGRADED=1\n\n"
            "The 'determinex[cloak]' extra is required for production Cloak deployments."
        )
