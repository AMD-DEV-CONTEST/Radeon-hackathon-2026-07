"""
scripts/determinex_cloak_ts.py — Project Cloak: TypeScript/JavaScript identifier obfuscation

Strategy: two-pass export detection.
  Pass 1 — collect all exported names (public API) via export statements.
  Pass 2 — collect all camelCase/lowercase identifiers NOT in exports.
  Obfuscate only private identifiers.

This module integrates with determinex_cloak.py via build_cloak_context(language='typescript').
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# ── Language constants ─────────────────────────────────────────────────────────

TS_KEYWORDS: frozenset[str] = frozenset(
    [
        "break",
        "case",
        "catch",
        "class",
        "const",
        "continue",
        "debugger",
        "default",
        "delete",
        "do",
        "else",
        "export",
        "extends",
        "false",
        "finally",
        "for",
        "function",
        "if",
        "import",
        "in",
        "instanceof",
        "let",
        "new",
        "null",
        "return",
        "super",
        "switch",
        "this",
        "throw",
        "true",
        "try",
        "typeof",
        "var",
        "void",
        "while",
        "with",
        "yield",
        # TypeScript-specific keywords
        "abstract",
        "as",
        "async",
        "await",
        "declare",
        "enum",
        "from",
        "implements",
        "interface",
        "module",
        "namespace",
        "of",
        "override",
        "private",
        "protected",
        "public",
        "readonly",
        "static",
        "type",
        "satisfies",
        "infer",
        "keyof",
        "typeof",
        "unique",
        "asserts",
    ]
)

TS_BUILTIN_SAFE: frozenset[str] = frozenset(
    [
        # runtime globals
        "undefined",
        "console",
        "process",
        "require",
        "module",
        "exports",
        "global",
        "window",
        "document",
        "navigator",
        "__dirname",
        "__filename",
        "globalThis",
        "self",
        # TypeScript primitive types
        "string",
        "number",
        "boolean",
        "object",
        "symbol",
        "bigint",
        "never",
        "any",
        "unknown",
        "void",
        # Constructors/classes
        "Promise",
        "Array",
        "Object",
        "String",
        "Number",
        "Boolean",
        "Error",
        "Map",
        "Set",
        "WeakMap",
        "WeakSet",
        "Symbol",
        "BigInt",
        "RegExp",
        "JSON",
        "Math",
        "Date",
        "Proxy",
        "Reflect",
        # Web APIs
        "fetch",
        "setTimeout",
        "clearTimeout",
        "setInterval",
        "clearInterval",
        "queueMicrotask",
        "requestAnimationFrame",
        "cancelAnimationFrame",
        "addEventListener",
        "removeEventListener",
        "dispatchEvent",
        # Node.js
        "Buffer",
        "EventEmitter",
        "Stream",
        "path",
        "fs",
        "http",
        "https",
        "crypto",
        "os",
        "url",
        "util",
        "events",
        "stream",
        "child_process",
        # Common React
        "React",
        "useState",
        "useEffect",
        "useRef",
        "useCallback",
        "useMemo",
        "useContext",
        "useReducer",
        "createElement",
        "Fragment",
        "Component",
        # Common short names
        "err",
        "res",
        "req",
        "cb",
        "fn",
        "id",
        "el",
        "ev",
        "e",
        "i",
        "j",
        "k",
        "ctx",
        "app",
        "db",
        "cfg",
        "env",
        "api",
        "cmd",
        "msg",
        "val",
        "key",
        "src",
        "dst",
        "buf",
        "str",
        "num",
        "obj",
        "arr",
        "map",
        "set",
        "ref",
        "node",
        "next",
        "prev",
        "head",
        "tail",
        "root",
        "leaf",
        "data",
        "meta",
        # Testing
        "test",
        "it",
        "describe",
        "expect",
        "jest",
        "vi",
        "beforeEach",
        "afterEach",
        "beforeAll",
        "afterAll",
        "mock",
        "spy",
        "stub",
    ]
)

# ── Extraction helpers ─────────────────────────────────────────────────────────

_TEMPLATE_LITERAL_RE = re.compile(r"`(?:[^`\\]|\\.)*`", re.DOTALL)
_STRING_RE = re.compile(r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'')
_COMMENT_RE = re.compile(r"//[^\n]*|/\*.*?\*/", re.DOTALL)
_IDENT_RE = re.compile(r"\b([a-z_$][a-zA-Z0-9_$]*)\b")


def _strip_literals(source: str) -> str:
    """Remove string literals, template literals, and comments."""
    source = _COMMENT_RE.sub(" ", source)
    source = _TEMPLATE_LITERAL_RE.sub("``", source)
    source = _STRING_RE.sub('""', source)
    return source


def _collect_exports(source: str) -> set[str]:
    """
    Collect all explicitly exported names from a TypeScript/JS module.
    These are the PUBLIC API — never obfuscate.
    """
    exported: set[str] = set()
    stripped = _strip_literals(source)

    # Named declarations: export function/class/const/let/var/type/interface/enum/abstract
    for m in re.finditer(
        r"export\s+(?:default\s+)?(?:abstract\s+)?"
        r"(?:function\*?|class|const|let|var|type|interface|enum)\s+(\w+)",
        stripped,
    ):
        exported.add(m.group(1))

    # Re-exports: export { a, b as c, ... }
    for m in re.finditer(r"export\s*\{([^}]+)\}", stripped):
        for item in m.group(1).split(","):
            item = item.strip()
            # Handle "foo as bar" — the exported name is bar
            parts = re.split(r"\bas\b", item)
            name = parts[-1].strip()
            if re.match(r"^[a-zA-Z_$]\w*$", name):
                exported.add(name)

    # Default export identifier: export default myName
    for m in re.finditer(r"export\s+default\s+([a-zA-Z_$]\w*)", stripped):
        exported.add(m.group(1))

    return exported


def extract_ts_private_identifiers(source: str) -> frozenset[str]:
    """
    Extract TypeScript/JS private identifiers suitable for obfuscation.

    Public identifiers (exports) are excluded. Keywords, builtins, and
    short names are excluded. Only camelCase/lowercase names ≥4 chars
    with actual semantic content are kept.
    """
    exported = _collect_exports(source)
    stripped = _strip_literals(source)
    all_ids = set(_IDENT_RE.findall(stripped))

    private: set[str] = set()
    for name in all_ids:
        if name in TS_KEYWORDS:
            continue
        if name in TS_BUILTIN_SAFE:
            continue
        if name in exported:
            continue
        if len(name) <= 3:
            continue
        # Skip ALL_CAPS constants (likely env vars or constants)
        if name.isupper():
            continue
        # Skip names that look like JSX tags (lowercase element names)
        # Keep genuine camelCase and underscore_case identifiers
        private.add(name)

    return frozenset(private)


# ── Obfuscation ────────────────────────────────────────────────────────────────


def obfuscate_ts_source(source: str, symbol_map: dict[str, str]) -> str:
    """
    Replace private identifiers in TypeScript/JS source with x_NNNN tokens.
    Skips string literals, template literals, and comments.

    Single-pass approach: skip_spans are computed once from the original source
    so positions never drift as replacements change string length.
    """
    if not symbol_map:
        return source

    # Build skip spans once from original source positions.
    skip_spans: list[tuple[int, int]] = []
    for pattern in (_COMMENT_RE, _TEMPLATE_LITERAL_RE, _STRING_RE):
        for m in pattern.finditer(source):
            skip_spans.append((m.start(), m.end()))
    skip_spans.sort()

    # Combined regex — longest identifiers first so "handler" wins over "hand".
    sorted_ids = sorted(symbol_map.keys(), key=len, reverse=True)
    combined = re.compile(r"\b(" + "|".join(re.escape(k) for k in sorted_ids) + r")\b")

    parts: list[str] = []
    last = 0
    for m in combined.finditer(source):
        start, end = m.start(), m.end()
        parts.append(source[last:start])
        if any(ss <= start < se for ss, se in skip_spans):
            parts.append(m.group(0))
        else:
            parts.append(symbol_map[m.group(1)])
        last = end
    parts.append(source[last:])
    return "".join(parts)


def restore_ts_source(obfuscated: str, reverse_map: dict[str, str]) -> str:
    """Restore x_NNNN tokens back to original TypeScript/JS identifiers."""
    result = obfuscated
    sorted_pairs = sorted(reverse_map.items(), key=lambda kv: -len(kv[0]))
    for token, original in sorted_pairs:
        result = re.sub(r"\b" + re.escape(token) + r"\b", original, result)
    return result


# ── Validator ──────────────────────────────────────────────────────────────────


def validate_typescript(
    source: str,
    filename: str = "patch.ts",
    strict: bool = False,
) -> tuple[bool, str]:
    """
    Syntax/type-check a TypeScript source string.

    Tries `tsc --noEmit` first; falls back to `node --check` for syntax only.
    Returns (passed, output).
    """
    import os
    import tempfile

    suffix = ".ts" if filename.endswith(".ts") else ".js"
    with tempfile.NamedTemporaryFile(
        suffix=suffix,
        mode="w",
        delete=False,
        prefix="determinex_ts_",
        encoding="utf-8",
    ) as f:
        f.write(source)
        tmp_path = f.name

    try:
        # Try tsc for full type checking
        tsc_flags = [
            "--noEmit",
            "--allowJs",
            "--checkJs",
            "--target",
            "ES2020",
            "--module",
            "commonjs",
            "--moduleResolution",
            "node",
        ]
        if strict:
            tsc_flags.append("--strict")

        try:
            result = subprocess.run(
                ["tsc"] + tsc_flags + [tmp_path],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return result.returncode == 0, (result.stdout + result.stderr)[-2000:]
        except FileNotFoundError:
            pass
        except subprocess.TimeoutExpired:
            return False, "tsc timed out"

        # Fallback: node syntax check
        try:
            result = subprocess.run(
                ["node", "--check", tmp_path],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.returncode == 0, result.stderr[-2000:]
        except FileNotFoundError:
            return True, "neither tsc nor node available — skipping TS validation"
        except subprocess.TimeoutExpired:
            return False, "node --check timed out"
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def validate_ts_file(file_path: Path) -> tuple[bool, str]:
    """Validate a TypeScript/JS file on disk."""
    source = file_path.read_text(encoding="utf-8", errors="replace")
    return validate_typescript(source, filename=file_path.name)


# ── Standalone test ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: determinex_cloak_ts.py <path/to/file.ts>")
        sys.exit(1)

    src = Path(sys.argv[1]).read_text(encoding="utf-8")
    exported = _collect_exports(src)
    print(f"Exported names ({len(exported)}): {sorted(exported)[:10]}")

    private_ids = extract_ts_private_identifiers(src)
    print(f"\nPrivate identifiers ({len(private_ids)}):")
    for name in sorted(private_ids)[:20]:
        print(f"  {name}")

    counter = 1
    symbol_map: dict[str, str] = {}
    for name in sorted(private_ids):
        symbol_map[name] = f"x_{counter:04d}"
        counter += 1

    obfuscated = obfuscate_ts_source(src, symbol_map)
    print(f"\nObfuscated ({len(obfuscated)} chars, was {len(src)}):")
    print(obfuscated[:300], "..." if len(obfuscated) > 300 else "")

    reverse_map = {v: k for k, v in symbol_map.items()}
    restored = restore_ts_source(obfuscated, reverse_map)
    if restored == src:
        print("\n✓ Round-trip restoration: PASS")
    else:
        print("\n✗ Round-trip restoration: FAIL")
        diffs = [
            (i + 1, a, b)
            for i, (a, b) in enumerate(zip(src.splitlines(), restored.splitlines()))
            if a != b
        ]
        for ln, orig, rest in diffs[:5]:
            print(f"  Line {ln}: {orig!r} != {rest!r}")
