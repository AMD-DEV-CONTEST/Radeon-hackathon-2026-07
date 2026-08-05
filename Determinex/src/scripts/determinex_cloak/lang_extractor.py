"""
determinex_cloak/lang_extractor.py — Multi-language identifier extraction + pipeline entry.

Covers:
  - Regex-based extraction for Java/Rust/Ruby/PHP/C/C++ (definition-site patterns)
  - tree-sitter real AST extraction (preferred when grammar available)
  - Go and TypeScript/JavaScript bridge to dedicated extractor modules
  - build_cloak_context() — the main pipeline entry point
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from ._treesitter_bridge import (
    _ALLOW_DEGRADED,
    _TS_AVAILABLE,
    TS_SUPPORTED_LANGUAGES,
    extract_treesitter_identifiers,
)
from .classifier import build_private_identifier_set
from .context import CloakContext
from .safe_list import _build_safe_list
from .symbol_map import SymbolMap

log = logging.getLogger("determinex_cloak")

# ── Multi-language regex-based identifier extractor ──────────────────────────

_COMMENT_STRIP: dict[str, re.Pattern] = {
    "java": re.compile(r"//[^\n]*|/\*.*?\*/", re.DOTALL),
    "rust": re.compile(r"//[^\n]*|/\*.*?\*/", re.DOTALL),
    "ruby": re.compile(r"#[^\n]*"),
    "php": re.compile(r"//[^\n]*|#[^\n]*|/\*.*?\*/", re.DOTALL),
    "c": re.compile(r"//[^\n]*|/\*.*?\*/", re.DOTALL),
    "cpp": re.compile(r"//[^\n]*|/\*.*?\*/", re.DOTALL),
}
_STR_STRIP = re.compile(r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|`[^`]*`')

_LANG_KEYWORDS: dict[str, frozenset] = {
    "java": frozenset(
        [
            "abstract",
            "assert",
            "boolean",
            "break",
            "byte",
            "case",
            "catch",
            "char",
            "class",
            "const",
            "continue",
            "default",
            "do",
            "double",
            "else",
            "enum",
            "extends",
            "final",
            "finally",
            "float",
            "for",
            "goto",
            "if",
            "implements",
            "import",
            "instanceof",
            "int",
            "interface",
            "long",
            "native",
            "new",
            "package",
            "private",
            "protected",
            "public",
            "return",
            "short",
            "static",
            "strictfp",
            "super",
            "switch",
            "synchronized",
            "this",
            "throw",
            "throws",
            "transient",
            "try",
            "var",
            "void",
            "volatile",
            "while",
            "true",
            "false",
            "null",
            "String",
            "Object",
            "Integer",
            "Long",
            "Double",
            "Float",
            "Boolean",
            "Byte",
            "Short",
            "Character",
            "StringBuilder",
            "StringBuffer",
            "System",
            "Math",
            "Arrays",
            "List",
            "Map",
            "Set",
            "ArrayList",
            "HashMap",
            "HashSet",
            "LinkedList",
            "Optional",
            "Stream",
            "Collectors",
            "Exception",
            "RuntimeException",
            "Error",
            "Throwable",
            "Override",
            "Deprecated",
            "SuppressWarnings",
            "FunctionalInterface",
            "main",
            "args",
            "toString",
            "equals",
            "hashCode",
            "compareTo",
            "length",
            "size",
            "get",
            "set",
            "add",
            "remove",
            "contains",
            "iterator",
            "next",
            "hasNext",
            "println",
            "print",
            "format",
            "valueOf",
            "parseInt",
            "getClass",
            "getName",
            "getSimpleName",
            "out",
            "err",
            "in",
        ]
    ),
    "rust": frozenset(
        [
            "as",
            "async",
            "await",
            "break",
            "const",
            "continue",
            "crate",
            "dyn",
            "else",
            "enum",
            "extern",
            "false",
            "fn",
            "for",
            "if",
            "impl",
            "in",
            "let",
            "loop",
            "match",
            "mod",
            "move",
            "mut",
            "pub",
            "ref",
            "return",
            "self",
            "Self",
            "static",
            "struct",
            "super",
            "trait",
            "true",
            "type",
            "union",
            "unsafe",
            "use",
            "where",
            "while",
            "abstract",
            "become",
            "box",
            "do",
            "final",
            "macro",
            "override",
            "priv",
            "try",
            "typeof",
            "unsized",
            "virtual",
            "yield",
            "bool",
            "i8",
            "i16",
            "i32",
            "i64",
            "i128",
            "isize",
            "u8",
            "u16",
            "u32",
            "u64",
            "u128",
            "usize",
            "f32",
            "f64",
            "char",
            "str",
            "String",
            "Vec",
            "Option",
            "Result",
            "Box",
            "Rc",
            "Arc",
            "Cell",
            "RefCell",
            "HashMap",
            "HashSet",
            "BTreeMap",
            "BTreeSet",
            "Ok",
            "Err",
            "Some",
            "None",
            "true",
            "false",
            "println",
            "eprintln",
            "panic",
            "assert",
            "unreachable",
            "todo",
            "unimplemented",
            "Default",
            "Clone",
            "Debug",
            "Display",
            "From",
            "Into",
            "Iterator",
            "len",
            "new",
            "push",
            "pop",
            "iter",
            "map",
            "filter",
            "collect",
            "unwrap",
            "expect",
            "is_some",
            "is_none",
            "is_ok",
            "is_err",
        ]
    ),
    "ruby": frozenset(
        [
            "BEGIN",
            "END",
            "__ENCODING__",
            "__LINE__",
            "__FILE__",
            "alias",
            "and",
            "begin",
            "break",
            "case",
            "class",
            "def",
            "defined",
            "do",
            "else",
            "elsif",
            "end",
            "ensure",
            "false",
            "for",
            "if",
            "in",
            "module",
            "next",
            "nil",
            "not",
            "or",
            "redo",
            "rescue",
            "retry",
            "return",
            "self",
            "super",
            "then",
            "true",
            "undef",
            "unless",
            "until",
            "when",
            "while",
            "yield",
            "puts",
            "print",
            "raise",
            "require",
            "require_relative",
            "attr_accessor",
            "attr_reader",
            "attr_writer",
            "initialize",
            "new",
            "to_s",
            "to_i",
            "to_f",
            "to_a",
            "length",
            "size",
            "each",
            "map",
            "select",
            "reject",
            "include",
            "extend",
            "prepend",
            "freeze",
            "dup",
            "clone",
            "nil?",
            "empty?",
            "respond_to?",
        ]
    ),
    "php": frozenset(
        [
            "abstract",
            "and",
            "array",
            "as",
            "break",
            "callable",
            "case",
            "catch",
            "class",
            "clone",
            "const",
            "continue",
            "declare",
            "default",
            "die",
            "do",
            "echo",
            "else",
            "elseif",
            "empty",
            "enddeclare",
            "endfor",
            "endforeach",
            "endif",
            "endswitch",
            "endwhile",
            "eval",
            "exit",
            "extends",
            "final",
            "finally",
            "fn",
            "for",
            "foreach",
            "function",
            "global",
            "goto",
            "if",
            "implements",
            "include",
            "include_once",
            "instanceof",
            "insteadof",
            "interface",
            "isset",
            "list",
            "match",
            "namespace",
            "new",
            "or",
            "print",
            "private",
            "protected",
            "public",
            "readonly",
            "require",
            "require_once",
            "return",
            "static",
            "switch",
            "throw",
            "trait",
            "try",
            "unset",
            "use",
            "var",
            "while",
            "xor",
            "yield",
            "true",
            "false",
            "null",
            "TRUE",
            "FALSE",
            "NULL",
            "string",
            "int",
            "float",
            "bool",
            "array",
            "object",
            "callable",
            "void",
            "never",
            "self",
            "parent",
            "__CLASS__",
            "__DIR__",
            "__FILE__",
            "__FUNCTION__",
            "__LINE__",
            "__METHOD__",
            "__NAMESPACE__",
            "__TRAIT__",
            "count",
            "strlen",
            "in_array",
            "array_push",
            "array_pop",
            "array_merge",
            "isset",
            "empty",
            "unset",
            "echo",
            "var_dump",
            "print_r",
            "sprintf",
            "printf",
            "json_encode",
            "json_decode",
        ]
    ),
    "c": frozenset(
        [
            "auto",
            "break",
            "case",
            "char",
            "const",
            "continue",
            "default",
            "do",
            "double",
            "else",
            "enum",
            "extern",
            "float",
            "for",
            "goto",
            "if",
            "inline",
            "int",
            "long",
            "register",
            "restrict",
            "return",
            "short",
            "signed",
            "sizeof",
            "static",
            "struct",
            "switch",
            "typedef",
            "union",
            "unsigned",
            "void",
            "volatile",
            "while",
            "NULL",
            "true",
            "false",
            "bool",
            "_Bool",
            "_Complex",
            "_Imaginary",
            "printf",
            "scanf",
            "malloc",
            "free",
            "calloc",
            "realloc",
            "memcpy",
            "memmove",
            "memset",
            "strcmp",
            "strcpy",
            "strncpy",
            "strlen",
            "fprintf",
            "sprintf",
            "fopen",
            "fclose",
            "fread",
            "fwrite",
            "exit",
            "abort",
            "assert",
            "main",
            "FILE",
            "EOF",
            "NULL",
            "size_t",
            "uint8_t",
            "uint16_t",
            "uint32_t",
            "uint64_t",
            "int8_t",
            "int16_t",
            "int32_t",
            "int64_t",
        ]
    ),
    "cpp": frozenset(
        [
            "alignas",
            "alignof",
            "and",
            "and_eq",
            "asm",
            "auto",
            "bitand",
            "bitor",
            "bool",
            "break",
            "case",
            "catch",
            "char",
            "char8_t",
            "char16_t",
            "char32_t",
            "class",
            "compl",
            "concept",
            "const",
            "consteval",
            "constexpr",
            "constinit",
            "const_cast",
            "continue",
            "co_await",
            "co_return",
            "co_yield",
            "decltype",
            "default",
            "delete",
            "do",
            "double",
            "dynamic_cast",
            "else",
            "enum",
            "explicit",
            "export",
            "extern",
            "false",
            "float",
            "for",
            "friend",
            "goto",
            "if",
            "inline",
            "int",
            "long",
            "mutable",
            "namespace",
            "new",
            "noexcept",
            "not",
            "not_eq",
            "nullptr",
            "operator",
            "or",
            "or_eq",
            "private",
            "protected",
            "public",
            "register",
            "reinterpret_cast",
            "requires",
            "return",
            "short",
            "signed",
            "sizeof",
            "static",
            "static_assert",
            "static_cast",
            "struct",
            "switch",
            "template",
            "this",
            "thread_local",
            "throw",
            "true",
            "try",
            "typedef",
            "typeid",
            "typename",
            "union",
            "unsigned",
            "using",
            "virtual",
            "void",
            "volatile",
            "wchar_t",
            "while",
            "xor",
            "xor_eq",
            "override",
            "final",
            "string",
            "vector",
            "map",
            "set",
            "unordered_map",
            "unordered_set",
            "shared_ptr",
            "unique_ptr",
            "make_shared",
            "make_unique",
            "cout",
            "cin",
            "cerr",
            "endl",
            "printf",
            "std",
            "size_t",
            "nullptr",
            "NULL",
            "main",
            "int8_t",
            "int16_t",
            "int32_t",
            "int64_t",
            "uint8_t",
            "uint16_t",
            "uint32_t",
            "uint64_t",
            "begin",
            "end",
            "size",
            "empty",
            "push_back",
            "pop_back",
            "front",
            "back",
            "find",
            "insert",
            "erase",
            "clear",
        ]
    ),
}

_LANG_DEF_PATTERNS: dict[str, list[re.Pattern]] = {
    "java": [
        re.compile(r"\bclass\s+([A-Za-z_]\w*)"),
        re.compile(r"\binterface\s+([A-Za-z_]\w*)"),
        re.compile(r"\benum\s+([A-Za-z_]\w*)"),
        re.compile(
            r"(?:public|private|protected|static|final|abstract|synchronized)\s+(?:[\w<>\[\],\s]+\s+)?([a-z_]\w*)\s*\("
        ),
        re.compile(r"(?:private|protected)\s+[\w<>\[\]]+\s+([a-z_]\w*)\s*[;=]"),
    ],
    "rust": [
        re.compile(r"\bfn\s+([a-z_]\w*)"),
        re.compile(r"\bstruct\s+([A-Za-z_]\w*)"),
        re.compile(r"\benum\s+([A-Za-z_]\w*)"),
        re.compile(r"\btrait\s+([A-Za-z_]\w*)"),
        re.compile(r"\bimpl(?:\s+\w+\s+for)?\s+([A-Za-z_]\w*)"),
        re.compile(r"\blet\s+(?:mut\s+)?([a-z_]\w*)\s*[=:]"),
        re.compile(r"\bconst\s+([A-Z_]\w*)\s*:"),
        re.compile(r"\btype\s+([A-Za-z_]\w*)\s*="),
    ],
    "ruby": [
        re.compile(r"\bdef\s+([a-z_]\w*[!?]?)"),
        re.compile(r"\bclass\s+([A-Z]\w*)"),
        re.compile(r"\bmodule\s+([A-Z]\w*)"),
        re.compile(r"\b([a-z_]\w*)\s*=\s*(?:proc\s*\{|lambda\s*\{|Proc\.new)"),
        re.compile(r"\battr_(?:accessor|reader|writer)\s+:([a-z_]\w*)"),
    ],
    "php": [
        re.compile(r"\bfunction\s+([a-zA-Z_]\w*)"),
        re.compile(r"\bclass\s+([A-Za-z_]\w*)"),
        re.compile(r"\binterface\s+([A-Za-z_]\w*)"),
        re.compile(r"\btrait\s+([A-Za-z_]\w*)"),
        re.compile(r"\$([a-zA-Z_]\w*)\s*="),
    ],
    "c": [
        re.compile(r"\btypedef\s+(?:struct\s+\w+\s+)?(\w+)\s*;"),
        re.compile(r"\bstruct\s+([A-Za-z_]\w*)"),
        re.compile(r"\benum\s+([A-Za-z_]\w*)"),
        re.compile(
            r"^(?:static\s+|extern\s+|inline\s+)*\w[\w\s\*]+\s+([a-z_]\w*)\s*\(", re.MULTILINE
        ),
    ],
    "cpp": [
        re.compile(r"\bclass\s+([A-Za-z_]\w*)"),
        re.compile(r"\bstruct\s+([A-Za-z_]\w*)"),
        re.compile(r"\benum(?:\s+class)?\s+([A-Za-z_]\w*)"),
        re.compile(r"\bnamespace\s+([a-zA-Z_]\w*)"),
        re.compile(r"\btemplate\s*<[^>]*>\s*(?:class|struct)\s+([A-Za-z_]\w*)"),
        re.compile(
            r"^(?:static\s+|virtual\s+|explicit\s+|inline\s+|constexpr\s+)*[\w:]+[\w\s\*&<>:,]+\s+([a-z_]\w*)\s*\(",
            re.MULTILINE,
        ),
    ],
}

_SINGLE_CHAR_RE = re.compile(r"^[a-zA-Z_]$")


def _extract_lang_identifiers(
    source: str,
    language: str,
    safe: frozenset,
) -> frozenset:
    """
    Regex-based private identifier extraction for non-Python languages.
    Strips comments and string literals before matching to avoid false positives.
    """
    strip_re = _COMMENT_STRIP.get(language)
    cleaned = strip_re.sub(" ", source) if strip_re else source
    cleaned = _STR_STRIP.sub('""', cleaned)

    keywords = _LANG_KEYWORDS.get(language, frozenset())
    patterns = _LANG_DEF_PATTERNS.get(language, [])

    found: set[str] = set()
    for pat in patterns:
        for m in pat.finditer(cleaned):
            name = m.group(1).strip()
            if not name:
                continue
            if _SINGLE_CHAR_RE.match(name):
                continue
            if len(name) < 3:
                continue
            if name in keywords or name in safe:
                continue
            found.add(name)

    return frozenset(found)


def _build_cloak_context_nonpython(
    instance_id: str,
    repo_path: Path,
    language: str,
) -> CloakContext:
    """
    Scan all source files for a non-Python language and build a CloakContext.

    Extraction priority:
      1. tree-sitter (real AST — handles macros, generics, templates correctly)
      2. regex patterns (fallback when tree-sitter grammar unavailable)
    """
    _SKIP = {
        "vendor",
        "node_modules",
        "target",
        "build",
        "dist",
        ".git",
        "site-packages",
        "__pycache__",
        ".gradle",
        ".mvn",
        "testdata",
    }
    _EXT_MAP = {
        "java": [".java"],
        "rust": [".rs"],
        "ruby": [".rb"],
        "php": [".php"],
        "c": [".c", ".h"],
        "cpp": [".cpp", ".cc", ".cxx", ".hpp", ".h"],
        "go": [".go"],
        "typescript": [".ts", ".tsx"],
        "javascript": [".js", ".jsx"],
    }
    extensions = _EXT_MAP.get(language, [])
    safe: frozenset[str] = frozenset()

    ts_available = _TS_AVAILABLE and language in TS_SUPPORTED_LANGUAGES
    all_private: set[str] = set()
    files_scanned = 0
    ts_hits = 0
    regex_hits = 0

    for ext in extensions:
        for src_file in repo_path.rglob(f"*{ext}"):
            if any(part in _SKIP for part in src_file.parts):
                continue
            if src_file.stat().st_size > 500_000:
                continue
            try:
                source = src_file.read_text(encoding="utf-8", errors="replace")
                files_scanned += 1

                if ts_available:
                    ids = extract_treesitter_identifiers(source, language, safe)
                    if ids:
                        all_private |= ids
                        ts_hits += 1
                        continue

                ids = _extract_lang_identifiers(source, language, safe)
                all_private |= ids
                regex_hits += 1
            except Exception as e:
                log.debug("Cloak(%s): skipping %s: %s", language, src_file.name, e)

    backend = "tree-sitter" if ts_available else "regex"
    if ts_available and regex_hits:
        backend = f"tree-sitter({ts_hits})+regex({regex_hits})"
    log.info(
        "Cloak(%s): scanned %d files via %s, found %d private identifiers",
        language,
        files_scanned,
        backend,
        len(all_private),
    )

    # FAIL-CLOSED: scanning real source files and extracting NOTHING means obfuscate_source()
    # becomes an identity function -- the caller ships plaintext believing it is cloaked. That
    # is the exact leak CloakObfuscationError exists to prevent, so it must be loud.
    #
    # This is reachable today, not hypothetical. TS_SUPPORTED_LANGUAGES is a hardcoded frozenset
    # of 9 languages, but pyproject's [cloak] extra declares only 4 grammars, and
    # _LANG_DEF_PATTERNS has regex for a different 6. TypeScript falls in the gap with NO
    # extraction path at all: `ts_available` is True (the language IS in the advertised set),
    # extract_treesitter_identifiers returns empty (grammar not installed), the regex fallback
    # has no typescript entry, and a .ts file used to sail through untouched.
    # Measured 2026-07-26; see tests/test_cloak_language_coverage.py.
    if files_scanned and not all_private:
        from . import CloakObfuscationError

        if not _ALLOW_DEGRADED:
            log.error(
                "Cloak(%s): scanned %d file(s) via %s and extracted 0 identifiers — failing "
                "closed rather than sending plaintext.",
                language,
                files_scanned,
                backend,
            )
            raise CloakObfuscationError(
                path=str(repo_path),
                cause=RuntimeError(
                    f"no identifier-extraction path for language {language!r}: "
                    f"tree-sitter grammar loaded={ts_available and bool(ts_hits)}, "
                    f"regex patterns={'yes' if language in _LANG_DEF_PATTERNS else 'no'}. "
                    f"Install the grammar (pip install tree-sitter-{language}) or set "
                    f"DETERMINEX_CLOAK_ALLOW_DEGRADED=1 to accept reduced privacy."
                ),
                source_len=0,
            )
        log.warning(
            "Cloak(%s): 0 identifiers extracted from %d file(s); "
            "DETERMINEX_CLOAK_ALLOW_DEGRADED=1 set — proceeding with NO obfuscation.",
            language,
            files_scanned,
        )

    symbol_map = SymbolMap.build(frozenset(all_private))
    log.info(
        "Cloak(%s): symbol map ready — %d identifiers mapped", language, len(symbol_map.forward)
    )
    return CloakContext(
        instance_id=instance_id,
        symbol_map=symbol_map,
        star_import_warnings=[],
    )


_build_cloak_context_regex = _build_cloak_context_nonpython


def build_cloak_context(
    instance_id: str,
    repo_path: Path,
    language: str = "python",
) -> CloakContext:
    """
    Build a complete CloakContext for one solve() call.
    Scans the WHOLE REPO to build a consistent symbol map (Broad Scope guarantee).

    language routing:
      python                       → stdlib ast module (most precise)
      go/ts/js/java/rust/ruby/...  → tree-sitter real AST (preferred)
                                     → per-language regex module (fallback)
    """
    log.info("Cloak: building context for %s (language=%s)", instance_id, language)

    lang_norm = {"ts": "typescript", "js": "javascript", "c++": "cpp"}.get(language, language)

    if lang_norm in ("java", "rust", "ruby", "php", "c", "cpp"):
        return _build_cloak_context_nonpython(instance_id, repo_path, lang_norm)

    if lang_norm == "go":
        if _TS_AVAILABLE and "go" in TS_SUPPORTED_LANGUAGES:
            return _build_cloak_context_nonpython(instance_id, repo_path, "go")
        return _build_cloak_context_go(instance_id, repo_path)

    if lang_norm in ("typescript", "javascript"):
        if _TS_AVAILABLE and lang_norm in TS_SUPPORTED_LANGUAGES:
            return _build_cloak_context_nonpython(instance_id, repo_path, lang_norm)
        return _build_cloak_context_ts(instance_id, repo_path)

    safe_names = _build_safe_list(repo_path)
    log.info("Cloak: safe-list = %d names", len(safe_names))
    private_ids, star_warnings = build_private_identifier_set(repo_path, safe_names)
    symbol_map = SymbolMap.build(private_ids)
    log.info("Cloak: symbol map ready — %d identifiers mapped", len(symbol_map.forward))
    if star_warnings:
        log.warning(
            "Cloak: %d star-import holes (names pass through uncloaked):", len(star_warnings)
        )
        for w in star_warnings[:5]:
            log.warning("  %s", w)
        if len(star_warnings) > 5:
            log.warning("  ... and %d more", len(star_warnings) - 5)
    return CloakContext(
        instance_id=instance_id,
        symbol_map=symbol_map,
        star_import_warnings=star_warnings,
    )


def _build_cloak_context_go(instance_id: str, repo_path: Path) -> CloakContext:
    """Build CloakContext for a Go repository (legacy regex bridge)."""
    try:
        from determinex_cloak_go import (  # type: ignore[import]
            GO_BUILTIN_SAFE,
            GoStdlibManifest,
            extract_go_private_identifiers,
        )
    except ImportError as e:
        log.error("determinex_cloak_go not available: %s — falling back to empty map", e)
        return CloakContext(
            instance_id=instance_id,
            symbol_map=SymbolMap.build(frozenset()),
            star_import_warnings=[],
        )

    manifest = GoStdlibManifest.build()
    combined_safe = manifest.safe_names | GO_BUILTIN_SAFE

    all_private: set[str] = set()
    go_files_scanned = 0
    for go_file in repo_path.rglob("*.go"):
        if any(part.startswith(".") for part in go_file.parts):
            continue
        if "vendor" in go_file.parts or "testdata" in go_file.parts:
            continue
        try:
            source = go_file.read_text(encoding="utf-8", errors="replace")
            ids = extract_go_private_identifiers(source)
            all_private |= ids
            go_files_scanned += 1
        except Exception as e:
            log.debug("Cloak(go): skipping %s: %s", go_file.name, e)

    all_private -= combined_safe
    log.info(
        "Cloak(go): scanned %d files, found %d private identifiers",
        go_files_scanned,
        len(all_private),
    )
    symbol_map = SymbolMap.build(frozenset(all_private))
    log.info("Cloak(go): symbol map ready — %d identifiers mapped", len(symbol_map.forward))
    return CloakContext(
        instance_id=instance_id,
        symbol_map=symbol_map,
        star_import_warnings=[],
    )


def _build_cloak_context_ts(instance_id: str, repo_path: Path) -> CloakContext:
    """Build CloakContext for a TypeScript/JavaScript repository (legacy bridge)."""
    try:
        from determinex_cloak_ts import (  # type: ignore[import]
            TS_BUILTIN_SAFE,
            extract_ts_private_identifiers,
        )
    except ImportError as e:
        log.error("determinex_cloak_ts not available: %s — falling back to empty map", e)
        return CloakContext(
            instance_id=instance_id,
            symbol_map=SymbolMap.build(frozenset()),
            star_import_warnings=[],
        )

    all_private: set[str] = set()
    ts_files_scanned = 0
    for ts_file in repo_path.rglob("*"):
        if not ts_file.is_file():
            continue
        if ts_file.suffix not in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"):
            continue
        if any(part.startswith(".") for part in ts_file.parts):
            continue
        if any(skip in ts_file.parts for skip in ("node_modules", "dist", "build", "__pycache__")):
            continue
        if ts_file.stem.endswith((".min", ".bundle")):
            continue
        try:
            source = ts_file.read_text(encoding="utf-8", errors="replace")
            ids = extract_ts_private_identifiers(source)
            all_private |= ids
            ts_files_scanned += 1
        except Exception as e:
            log.debug("Cloak(ts): skipping %s: %s", ts_file.name, e)

    all_private -= TS_BUILTIN_SAFE
    log.info(
        "Cloak(ts): scanned %d files, found %d private identifiers",
        ts_files_scanned,
        len(all_private),
    )
    symbol_map = SymbolMap.build(frozenset(all_private))
    log.info("Cloak(ts): symbol map ready — %d identifiers mapped", len(symbol_map.forward))
    return CloakContext(
        instance_id=instance_id,
        symbol_map=symbol_map,
        star_import_warnings=[],
    )
