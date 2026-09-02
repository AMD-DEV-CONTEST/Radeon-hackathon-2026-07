"""
scripts/determinex_cloak_go.py — Project Cloak: Go language identifier obfuscation

Go's exported/unexported distinction IS the public/private boundary:
  - Uppercase first char → exported (public API, visible to callers) → NEVER obfuscate
  - Lowercase first char → unexported (package-internal)            → obfuscate

This module integrates with determinex_cloak.py via build_cloak_context(language='go').
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

# ── Go keywords — never obfuscate ─────────────────────────────────────────────

GO_KEYWORDS: frozenset[str] = frozenset(
    [
        "break",
        "case",
        "chan",
        "const",
        "continue",
        "default",
        "defer",
        "else",
        "fallthrough",
        "for",
        "func",
        "go",
        "goto",
        "if",
        "import",
        "interface",
        "map",
        "package",
        "range",
        "return",
        "select",
        "struct",
        "switch",
        "type",
        "var",
    ]
)

# Predeclared identifiers, universal short names, and test conventions — never obfuscate
GO_BUILTIN_SAFE: frozenset[str] = frozenset(
    [
        # predeclared types
        "bool",
        "byte",
        "complex64",
        "complex128",
        "error",
        "float32",
        "float64",
        "int",
        "int8",
        "int16",
        "int32",
        "int64",
        "uint",
        "uint8",
        "uint16",
        "uint32",
        "uint64",
        "uintptr",
        "rune",
        "string",
        # predeclared functions
        "append",
        "cap",
        "close",
        "complex",
        "copy",
        "delete",
        "imag",
        "len",
        "make",
        "new",
        "panic",
        "print",
        "println",
        "real",
        "recover",
        # predeclared constants/zero values
        "true",
        "false",
        "nil",
        "iota",
        # universal short single-char names (loop variables, err, etc.)
        "err",
        "t",
        "ok",
        "n",
        "i",
        "j",
        "k",
        "v",
        "w",
        "r",
        "b",
        "s",
        "f",
        "p",
        "c",
        "x",
        "y",
        "z",
        "m",
        "a",
        "q",
        "e",
        # common stdlib short names
        "ctx",
        "buf",
        "msg",
        "key",
        "val",
        "res",
        "req",
        "resp",
        "ret",
        "got",
        "want",
        "have",
        "exp",
        "act",
        # test conventions
        "tb",
        "tt",
        "tc",
        "tp",
        # special Go functions
        "init",
        "main",
        # commonly used struct field names (exported, but kept to avoid false positives in slice)
    ]
)

# Common stdlib package BASE names — never obfuscate these short names
GO_STDLIB_SAFE: frozenset[str] = frozenset(
    [
        "fmt",
        "os",
        "io",
        "log",
        "net",
        "http",
        "sync",
        "time",
        "sort",
        "math",
        "rand",
        "bytes",
        "bufio",
        "strings",
        "strconv",
        "errors",
        "context",
        "reflect",
        "encoding",
        "json",
        "xml",
        "path",
        "filepath",
        "runtime",
        "atomic",
        "testing",
        "regexp",
        "flag",
        "signal",
        "exec",
        "template",
        "html",
        "url",
        "tls",
        "crypto",
        "hash",
        "sha256",
        "md5",
        "base64",
        "hex",
        "utf8",
        "unicode",
        "big",
        "sql",
        "driver",
    ]
)

# ── Identifier extraction ──────────────────────────────────────────────────────

_IDENT_RE = re.compile(r"\b([a-z][a-zA-Z0-9_]*)\b")
_STRING_RE = re.compile(r'"(?:[^"\\]|\\.)*"|`[^`]*`|\'(?:[^\'\\]|\\.)*\'')
_COMMENT_RE = re.compile(r"//[^\n]*|/\*.*?\*/", re.DOTALL)


def _strip_literals(source: str) -> str:
    """Strip string literals and comments to avoid false-positive identifier matches."""
    source = _COMMENT_RE.sub(" ", source)
    source = _STRING_RE.sub('""', source)
    return source


def extract_go_private_identifiers(source: str) -> frozenset[str]:
    """
    Extract unexported Go identifiers (lowercase first char) suitable for obfuscation.

    Skips:
    - Keywords
    - Predeclared builtins and safe short names
    - Single-char names (loop vars)
    - Names starting with 'test' or 'bench' or 'example' (Go test convention)
    - Imported package aliases (parsed from import blocks)
    """
    stripped = _strip_literals(source)
    candidates = set(_IDENT_RE.findall(stripped))

    # Extract imported package names to exclude them
    import_names = _extract_import_aliases(source)

    private: set[str] = set()
    for name in candidates:
        if name in GO_KEYWORDS:
            continue
        if name in GO_BUILTIN_SAFE:
            continue
        if name in GO_STDLIB_SAFE:
            continue
        if name in import_names:
            continue
        if len(name) <= 2:
            continue
        if name.startswith(("test", "bench", "example", "Test", "Bench", "Example")):
            continue
        private.add(name)

    return frozenset(private)


def _extract_import_aliases(source: str) -> set[str]:
    """Extract all package aliases and base names from import blocks."""
    aliases: set[str] = set()

    # Single imports: import "pkg" or import alias "pkg"
    for m in re.finditer(r'import\s+(?:(\w+)\s+)?"[^"]*"', source):
        alias = m.group(1)
        if alias:
            aliases.add(alias)
        else:
            # Use base name of the package path
            pkg_m = re.search(r'"([^"]*)"', m.group(0))
            if pkg_m:
                base = pkg_m.group(1).split("/")[-1]
                aliases.add(base)

    # Block imports
    block_m = re.search(r"import\s*\((.*?)\)", source, re.DOTALL)
    if block_m:
        block = block_m.group(1)
        for line in block.splitlines():
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            m = re.match(r'(?:(\w+)\s+)?"([^"]*)"', line)
            if m:
                alias, path = m.group(1), m.group(2)
                if alias and alias != "_" and alias != ".":
                    aliases.add(alias)
                else:
                    base = path.split("/")[-1]
                    aliases.add(base)

    return aliases


# ── Obfuscation ────────────────────────────────────────────────────────────────


def obfuscate_go_source(source: str, symbol_map: dict[str, str]) -> str:
    """
    Replace private identifiers in Go source with x_NNNN tokens.
    String literals and comments are left intact.

    Single-pass approach: skip_spans are computed once from the original source
    so positions never drift as replacements change string length.
    """
    if not symbol_map:
        return source

    # Build skip spans once from original source positions.
    skip_spans: list[tuple[int, int]] = []
    for m in _COMMENT_RE.finditer(source):
        skip_spans.append((m.start(), m.end()))
    for m in _STRING_RE.finditer(source):
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


def restore_go_source(obfuscated: str, reverse_map: dict[str, str]) -> str:
    """Restore x_NNNN tokens back to original Go identifiers."""
    result = obfuscated
    sorted_pairs = sorted(reverse_map.items(), key=lambda kv: -len(kv[0]))
    for token, original in sorted_pairs:
        result = re.sub(r"\b" + re.escape(token) + r"\b", original, result)
    return result


# ── Stdlib manifest ────────────────────────────────────────────────────────────


@dataclass
class GoStdlibManifest:
    """Known-safe Go identifiers from stdlib and language spec."""

    safe_names: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def build(cls) -> GoStdlibManifest:
        """Build from `go list std` if available, otherwise use hardcoded set."""
        safe: set[str] = set(GO_STDLIB_SAFE)
        try:
            result = subprocess.run(
                ["go", "list", "std"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode == 0:
                for pkg in result.stdout.splitlines():
                    base = pkg.split("/")[-1]
                    safe.add(base)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        return cls(safe_names=frozenset(safe))


# ── Validator ──────────────────────────────────────────────────────────────────


def validate_go_build(repo_path: Path) -> tuple[bool, str]:
    """Run `go build ./...` in the repo. Returns (passed, output)."""
    try:
        result = subprocess.run(
            ["go", "build", "./..."],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=120,
        )
        return result.returncode == 0, result.stdout + result.stderr
    except FileNotFoundError:
        return True, "go not in PATH — skipping build validation"
    except subprocess.TimeoutExpired:
        return False, "go build timed out"


def validate_go_tests(
    repo_path: Path,
    fail_tests: list[str] | None = None,
    timeout: int = 120,
) -> tuple[bool, str]:
    """
    Run specific FAIL_TO_PASS Go tests or `go test ./...`.

    fail_tests: list of test function names (e.g. ['TestFoo', 'TestBar'])
    """
    try:
        if fail_tests:
            run_pattern = "|".join(re.escape(t) for t in fail_tests)
            cmd = ["go", "test", "-v", "-run", run_pattern, "./..."]
        else:
            cmd = ["go", "test", "-short", "./..."]

        result = subprocess.run(
            cmd,
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode == 0, result.stdout + result.stderr
    except FileNotFoundError:
        return True, "go not in PATH — skipping test validation"
    except subprocess.TimeoutExpired:
        return False, "go test timed out"


# ── Standalone test ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: determinex_cloak_go.py <path/to/file.go>")
        sys.exit(1)

    src = Path(sys.argv[1]).read_text(encoding="utf-8")
    private_ids = extract_go_private_identifiers(src)
    print(f"Found {len(private_ids)} private identifiers:")

    # Build simple incrementing map
    counter = 1
    symbol_map: dict[str, str] = {}
    for name in sorted(private_ids):
        symbol_map[name] = f"x_{counter:04d}"
        counter += 1

    obfuscated = obfuscate_go_source(src, symbol_map)
    print(f"\nObfuscated source ({len(obfuscated)} chars):")
    print(obfuscated[:500], "..." if len(obfuscated) > 500 else "")

    # Round-trip check
    reverse_map = {v: k for k, v in symbol_map.items()}
    restored = restore_go_source(obfuscated, reverse_map)
    if restored == src:
        print("\n✓ Round-trip restoration: PASS")
    else:
        print("\n✗ Round-trip restoration: FAIL")
        diffs = [
            (i, a, b)
            for i, (a, b) in enumerate(zip(src.splitlines(), restored.splitlines()))
            if a != b
        ]
        for line_no, orig, rest in diffs[:5]:
            print(f"  Line {line_no}: {orig!r} → {rest!r}")
