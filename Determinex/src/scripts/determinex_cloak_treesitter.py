"""
scripts/determinex_cloak_treesitter.py — Real AST identifier extraction via tree-sitter

Replaces regex-based _build_cloak_context_regex in determinex_cloak.py with
proper parse-tree traversal for Rust, Java, Ruby, PHP, C, C++, Go, TypeScript,
and JavaScript.  Python continues to use the stdlib ast module.

Architecture:
  - Lazy-load language grammars (one Parser per language, cached for the process)
  - Per-language S-expression queries target definition-site nodes only
  - Same safe-list + single-char + dunder filters as the Python path
  - Falls back gracefully if tree-sitter can't parse a file (partial results kept)

API used (tree-sitter 0.24+):
    q  = Query(lang, query_str)              # compile
    m  = QueryCursor(q).matches(root_node)   # execute → [(pat_idx, {name: [Node]})]

Import contract (called from determinex_cloak.py):
    from determinex_cloak_treesitter import (
        extract_treesitter_identifiers,   # (source_bytes, language, safe) → frozenset
        TS_SUPPORTED_LANGUAGES,           # frozenset of language names
        resolve_python_star_imports,      # (py_files, repo_root, safe, collector)
    )
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tree_sitter import Language, Parser, Query

log = logging.getLogger("determinex_cloak")

# The languages this module has QUERIES for. This is a declaration of intent, NOT a statement
# that the grammar is installed -- _load_language_obj imports tree_sitter_<lang> lazily and
# returns None when the package is absent. Use loadable_languages() for what actually works.
#
# The two drifted badly and silently: this set advertises 9, while pyproject's [cloak] extra
# declares only 4 grammars (rust, go, python, javascript). A 2026-07-26 audit "verified
# tree-sitter live" by printing THIS CONSTANT, which proved nothing -- 6 of the 9 had no
# grammar installed. See tests/test_cloak_language_coverage.py.
TS_SUPPORTED_LANGUAGES: frozenset[str] = frozenset(
    [
        "rust",
        "java",
        "ruby",
        "php",
        "c",
        "cpp",
        "go",
        "typescript",
        "javascript",
    ]
)


def loadable_languages() -> frozenset[str]:
    """The languages whose grammar actually imports AND whose query compiles, right now.

    Always prefer this over TS_SUPPORTED_LANGUAGES when reporting capability or deciding
    whether AST extraction is genuinely available. Result is not cached here because
    _load_language_obj and _get_query already memoise.
    """
    return frozenset(
        lang
        for lang in TS_SUPPORTED_LANGUAGES
        if _load_language_obj(lang) is not None and _get_query(lang) is not None
    )


# ── grammar language object loaders ───────────────────────────────────────────


def _load_language_obj(language: str):
    """Return the raw tree-sitter language binding object, or None."""
    try:
        if language == "rust":
            import tree_sitter_rust as m

            return m.language()
        if language == "java":
            import tree_sitter_java as m

            return m.language()
        if language == "ruby":
            import tree_sitter_ruby as m

            return m.language()
        if language == "php":
            import tree_sitter_php as m

            return m.language_php()
        if language == "c":
            import tree_sitter_c as m

            return m.language()
        if language in ("cpp", "c++"):
            import tree_sitter_cpp as m

            return m.language()
        if language == "go":
            import tree_sitter_go as m

            return m.language()
        if language in ("typescript", "ts"):
            import tree_sitter_typescript as m

            return m.language_typescript()
        if language in ("javascript", "js"):
            import tree_sitter_javascript as m

            return m.language()
    except Exception as e:
        log.debug("tree-sitter grammar not available for %s: %s", language, e)
    return None


# ── per-language definition-site queries (verified against tree-sitter 0.25.x) ──
# Queries use tree-sitter S-expression syntax.
# `name: (node_type)` uses the grammar's named field where available.
# Each capture is named @n and collected into frozenset[str].

_QUERIES: dict[str, str] = {
    "rust": """
        (function_item name: (identifier) @n)
        (struct_item name: (type_identifier) @n)
        (enum_item name: (type_identifier) @n)
        (trait_item name: (type_identifier) @n)
        (impl_item type: (type_identifier) @n)
        (type_item name: (type_identifier) @n)
        (const_item name: (identifier) @n)
        (static_item name: (identifier) @n)
        (mod_item name: (identifier) @n)
        (field_declaration name: (field_identifier) @n)
        (enum_variant name: (identifier) @n)
        (let_declaration pattern: (identifier) @n)
        (parameter pattern: (identifier) @n)
    """,
    "java": """
        (class_declaration name: (identifier) @n)
        (interface_declaration name: (identifier) @n)
        (enum_declaration name: (identifier) @n)
        (record_declaration name: (identifier) @n)
        (annotation_type_declaration name: (identifier) @n)
        (method_declaration name: (identifier) @n)
        (constructor_declaration name: (identifier) @n)
        (variable_declarator name: (identifier) @n)
        (formal_parameter name: (identifier) @n)
        (field_declaration declarator: (variable_declarator name: (identifier) @n))
    """,
    "ruby": """
        (method name: (identifier) @n)
        (singleton_method name: (identifier) @n)
        (class name: (constant) @n)
        (module name: (constant) @n)
        (method_parameters (identifier) @n)
        (assignment left: (identifier) @n)
        ; `@ivar = x` -- Ruby instance variables were never captured at all, so every
        ; one reached the cloud model in plaintext (measured 2026-07-28). The sigil is
        ; part of the token, so _filter_add strips it (same treatment as PHP's `$`):
        ; the map key is the bare name, which lets the existing word-boundary replacer
        ; rewrite `@zzq_ivar` to `@x_NNNN` and keep the sigil intact. Capturing the
        ; token WITH the `@` put "@zzq_ivar" in the map, which the replacer could
        ; never match -- an inert entry that still leaked.
        (assignment left: (instance_variable) @n)
    """,
    "php": """
        (function_definition name: (name) @n)
        (method_declaration name: (name) @n)
        (class_declaration name: (name) @n)
        (interface_declaration name: (name) @n)
        (trait_declaration name: (name) @n)
        (property_element (variable_name (name) @n))
        (simple_parameter name: (variable_name (name) @n))
        (assignment_expression
          left: (variable_name (name) @n))
        ; `$this->field = x` is a member_access_expression, not a property_element,
        ; so fields assigned in a constructor leaked (measured 2026-07-28).
        ; Restricted to $this via #eq? for the same reason as the JS/TS fix: an
        ; unrestricted member_access capture would rewrite `$other->prop` on objects
        ; whose property names may be an external contract.
        (assignment_expression
          left: (member_access_expression
                  object: (variable_name (name) @_obj)
                  name: (name) @n)
          (#eq? @_obj "this"))
    """,
    "c": """
        (function_definition
          declarator: (function_declarator
            declarator: (identifier) @n))
        (declaration
          declarator: (function_declarator
            declarator: (identifier) @n))
        (struct_specifier name: (type_identifier) @n)
        (union_specifier name: (type_identifier) @n)
        (enum_specifier name: (type_identifier) @n)
        (type_definition declarator: (type_identifier) @n)
        (field_declaration declarator: (field_identifier) @n)
        (field_declaration
          declarator: (pointer_declarator declarator: (field_identifier) @n))
        (parameter_declaration declarator: (identifier) @n)
        (parameter_declaration
          declarator: (pointer_declarator declarator: (identifier) @n))
        (init_declarator declarator: (identifier) @n)
        (init_declarator
          declarator: (pointer_declarator declarator: (identifier) @n))
    """,
    "cpp": """
        (function_definition
          declarator: (function_declarator
            declarator: (identifier) @n))
        (function_definition
          declarator: (function_declarator
            declarator: (qualified_identifier name: (identifier) @n)))
        ; A method defined INLINE in the class body -- `class C { void m(){} } ` --
        ; has declarator: (field_identifier), not (identifier), so the rule above
        ; never matched it and the method name reached the cloud model in plaintext.
        ; Measured leaking 2026-07-28 (zzqSet survived).
        (function_definition
          declarator: (function_declarator
            declarator: (field_identifier) @n))
        (declaration
          declarator: (function_declarator
            declarator: (identifier) @n))
        (struct_specifier name: (type_identifier) @n)
        (class_specifier name: (type_identifier) @n)
        (union_specifier name: (type_identifier) @n)
        (enum_specifier name: (type_identifier) @n)
        (namespace_definition (namespace_identifier) @n)
        (type_definition declarator: (type_identifier) @n)
        (field_declaration declarator: (field_identifier) @n)
        (field_declaration
          declarator: (pointer_declarator declarator: (field_identifier) @n))
        (parameter_declaration declarator: (identifier) @n)
        (parameter_declaration
          declarator: (pointer_declarator declarator: (identifier) @n))
        (parameter_declaration
          declarator: (reference_declarator (identifier) @n))
        (init_declarator declarator: (identifier) @n)
        (init_declarator
          declarator: (pointer_declarator declarator: (identifier) @n))
    """,
    "go": """
        (function_declaration name: (identifier) @n)
        (method_declaration name: (field_identifier) @n)
        (type_spec name: (type_identifier) @n)
        (var_spec name: (identifier) @n)
        (const_spec name: (identifier) @n)
        (short_var_declaration
          left: (expression_list (identifier) @n))
        (parameter_declaration name: (identifier) @n)
        (field_declaration name: (field_identifier) @n)
    """,
    "typescript": """
        (function_declaration name: (identifier) @n)
        (class_declaration name: (type_identifier) @n)
        (interface_declaration name: (type_identifier) @n)
        (type_alias_declaration name: (type_identifier) @n)
        (enum_declaration name: (identifier) @n)
        (method_definition name: (property_identifier) @n)
        (variable_declarator name: (identifier) @n)
        (lexical_declaration
          (variable_declarator name: (identifier) @n))
        (required_parameter pattern: (identifier) @n)
        (optional_parameter pattern: (identifier) @n)
        (public_field_definition name: (property_identifier) @n)
        (property_signature name: (property_identifier) @n)
        ; Same leak as JavaScript, same fix -- TypeScript shares the grammar family,
        ; so `this.field = x` in a constructor is an assignment to a
        ; member_expression and public_field_definition never saw it. Measured
        ; leaking 2026-07-28. Scoped to `object: (this)` so external property
        ; access (res.status, JSON.parse) is untouched.
        (assignment_expression
          left: (member_expression object: (this) property: (property_identifier) @n))
    """,
    "javascript": """
        (function_declaration name: (identifier) @n)
        (generator_function_declaration name: (identifier) @n)
        (class_declaration name: (identifier) @n)
        (method_definition name: (property_identifier) @n)
        (variable_declarator name: (identifier) @n)
        (lexical_declaration
          (variable_declarator name: (identifier) @n))
        (formal_parameters (identifier) @n)
        (field_definition property: (property_identifier) @n)
        ; `this.zzqField = 0` in a constructor is an assignment to a
        ; member_expression, NOT a field_definition -- field_definition only covers
        ; the modern `class X { field = 0 }` form. So instance fields declared the
        ; conventional way survived obfuscation and reached the cloud model in
        ; plaintext (measured 2026-07-28: of ZzqCls/zzqField/zzqMethod/zzqParam/
        ; zzqLocal, zzqField was the single survivor).
        ;
        ; Scoped to `object: (this)` deliberately. A general
        ; `(member_expression property: ...)` capture -- the reason this gap was
        ; left open -- would also rewrite external API property access like
        ; `res.status` or `JSON.parse`. `this.X` is by construction a field of the
        ; project's own class, so it cannot be an external contract, and known
        ; framework names (props/state/...) are still filtered by the safe-list
        ; every other capture goes through.
        (assignment_expression
          left: (member_expression object: (this) property: (property_identifier) @n))
    """,
}

# ── caches (process-level) ────────────────────────────────────────────────────

_LANG_OBJECTS: dict[str, Language | None] = {}
_PARSERS: dict[str, Parser | None] = {}
_COMPILED_QUERIES: dict[str, Query | None] = {}

_SINGLE_CHAR = re.compile(r"^[a-zA-Z_]$")
_DUNDER = re.compile(r"^__[a-zA-Z_][a-zA-Z0-9_]*__$")

# Ruby names the runtime calls for you. Renaming any of these changes behaviour:
# `initialize` stops being the constructor, `each` breaks Enumerable, `<=>` breaks
# Comparable, `hash`/`eql?` break Hash keys. Deliberately conservative -- only
# names with a language or core-protocol contract, not every convention.
_RUBY_HOOKS: frozenset[str] = frozenset(
    {
        "initialize",
        "initialize_copy",
        "method_missing",
        "respond_to_missing?",
        "to_s",
        "to_str",
        "to_a",
        "to_ary",
        "to_h",
        "to_hash",
        "to_i",
        "to_proc",
        "inspect",
        "hash",
        "eql?",
        "coerce",
        "each",
        "call",
        "<=>",
        "==",
        "===",
    }
)


def _get_lang_and_parser(language: str):
    """Return (Language, Parser) pair, or (None, None) on failure."""
    if language not in _PARSERS:
        try:
            from tree_sitter import Language, Parser  # type: ignore[import]

            raw = _load_language_obj(language)
            if raw is None:
                _PARSERS[language] = None
                _LANG_OBJECTS[language] = None
            else:
                lang_obj = Language(raw)
                _LANG_OBJECTS[language] = lang_obj
                _PARSERS[language] = Parser(lang_obj)
        except Exception as e:
            log.debug("tree-sitter init failed (%s): %s", language, e)
            _PARSERS[language] = None
            _LANG_OBJECTS[language] = None
    return _LANG_OBJECTS.get(language), _PARSERS.get(language)


def _get_query(language: str):
    """Return a compiled Query for the language, or None."""
    if language in _COMPILED_QUERIES:
        return _COMPILED_QUERIES[language]
    lang_obj, _ = _get_lang_and_parser(language)
    if lang_obj is None:
        _COMPILED_QUERIES[language] = None
        return None
    query_src = _QUERIES.get(language, "").strip()
    if not query_src:
        _COMPILED_QUERIES[language] = None
        return None
    try:
        from tree_sitter import Query  # type: ignore[import]

        q = Query(lang_obj, query_src)
        _COMPILED_QUERIES[language] = q
        return q
    except Exception as e:
        log.warning("tree-sitter query compile failed (%s): %s", language, e)
        _COMPILED_QUERIES[language] = None
        return None


# ── main extraction function ──────────────────────────────────────────────────


def extract_treesitter_identifiers(
    source: str | bytes,
    language: str,
    safe: frozenset[str],
) -> frozenset[str]:
    """
    Parse source with tree-sitter and return definition-site private identifiers.

    Parameters
    ----------
    source:   str or bytes — source text of the file
    language: language key matching TS_SUPPORTED_LANGUAGES
    safe:     frozenset of known-safe names (stdlib, builtins, framework APIs)

    Returns
    -------
    frozenset[str] of private identifiers not in safe.
    Returns empty frozenset on parse failure (caller should fall back to regex).
    """
    _, parser = _get_lang_and_parser(language)
    query = _get_query(language)
    if parser is None or query is None:
        return frozenset()

    raw = source if isinstance(source, bytes) else source.encode("utf-8", errors="replace")
    try:
        tree = parser.parse(raw)
    except Exception as e:
        log.debug("tree-sitter parse failed (%s): %s", language, e)
        return frozenset()

    try:
        from tree_sitter import QueryCursor  # type: ignore[import]

        matches = list(QueryCursor(query).matches(tree.root_node))
    except Exception as e:
        log.debug("tree-sitter query exec failed (%s): %s", language, e)
        return frozenset()

    found: set[str] = set()
    for _pat_idx, capture_dict in matches:
        for cap_name, nodes in capture_dict.items():
            # Only @n is a name to obfuscate. A capture whose key starts with "_"
            # exists to CONSTRAIN a pattern (e.g. PHP's `@_obj` bound so an
            # `#eq? "this"` predicate can restrict a member access to $this) and its
            # text must never enter the symbol map -- doing so obfuscated the `$this`
            # keyword itself and emitted syntactically broken PHP.
            if cap_name.startswith("_"):
                continue
            for node in nodes:
                name = raw[node.start_byte : node.end_byte].decode("utf-8", errors="replace")
                _filter_add(name, safe, language, found)

    return frozenset(found)


def _filter_add(name: str, safe: frozenset[str], language: str, found: set[str]) -> None:
    """Apply safe-list, length, and shape filters — mirrors the Python AST path."""
    name = name.strip()
    if not name or len(name) < 2:
        return
    if _SINGLE_CHAR.match(name):
        return
    if _DUNDER.match(name):
        return
    # PHP: strip leading $ from variable names
    if name.startswith("$"):
        name = name[1:]
        if not name or len(name) < 2:
            return
    # Ruby: strip @ / @@ so the map key is the bare name. The replacer matches
    # identifier tokens, so a key of "@ivar" never applies; a key of "ivar"
    # rewrites the name inside `@ivar` and leaves the sigil in place.
    if name.startswith("@"):
        name = name.lstrip("@")
        if not name or len(name) < 2:
            return
    # Language magic / hook names must NEVER be renamed: they are called by the
    # runtime, not by the project, so obfuscating them emits code that no longer
    # works and the model is handed a broken file to patch. _DUNDER above only
    # matches the Python `__x__` shape, so these all slipped through -- measured
    # 2026-07-28: PHP `__construct` and Ruby `initialize`/`to_s` were all renamed.
    if language == "php" and name.startswith("__"):
        # PHP reserves every function name beginning with __ as magical (language
        # spec), so this is a rule about PHP rather than a guessed list.
        return
    if language == "ruby" and name in _RUBY_HOOKS:
        return
    # Go: exported names start with uppercase — they're the public API, not proprietary.
    # Unexported (lowercase) are the private identifiers we want to obfuscate.
    if language == "go" and name and name[0].isupper():
        return
    if name in safe:
        return
    found.add(name)


# ── Python star-import resolution ─────────────────────────────────────────────


def resolve_python_star_imports(
    py_files: list[Path],
    repo_path: Path,
    safe_names: frozenset[str],
    collector,  # _IdentifierCollector instance from determinex_cloak
) -> list[str]:
    """
    Fix the star-import privacy hole:

    For each `from module import *` found in py_files, if the module resolves
    to a file within repo_path, parse it and add its exported identifiers to
    collector.found (same as if those names had been defined in-place).

    Previously these names leaked to the cloud API uncloaked.  After this fix
    they're obfuscated along with everything else.

    Returns list of warning strings for modules that couldn't be resolved
    (still external / third-party).
    """
    import ast as _ast

    resolved_modules: set[Path] = set()  # avoid double-parsing
    unresolved: list[str] = []

    for py_file in py_files:
        try:
            source = py_file.read_text(encoding="utf-8", errors="ignore")
            tree = _ast.parse(source, filename=str(py_file))
        except Exception:
            continue

        for node in _ast.walk(tree):
            if not isinstance(node, _ast.ImportFrom):
                continue
            if not any(alias.name == "*" for alias in node.names):
                continue

            module_name = node.module or ""
            level = node.level  # 0=absolute, 1+=relative

            resolved = _resolve_module_path(module_name, level, py_file.parent, repo_path)

            if resolved is None or resolved in resolved_modules:
                if resolved is None:
                    rel = (
                        py_file.relative_to(repo_path)
                        if py_file.is_relative_to(repo_path)
                        else py_file
                    )
                    unresolved.append(f"{rel}: from {module_name} import *")
                continue

            resolved_modules.add(resolved)
            try:
                src = resolved.read_text(encoding="utf-8", errors="ignore")
                mod_tree = _ast.parse(src, filename=str(resolved))

                all_names = _extract_dunder_all(mod_tree)
                if all_names is not None:
                    # Module defines __all__: only those names are exported
                    for name in all_names:
                        collector._add(name)
                else:
                    # No __all__: all top-level public definitions are exported.
                    # Re-use the same collector type from determinex_cloak.
                    try:
                        from determinex_cloak import _IdentifierCollector  # type: ignore[import]
                    except ImportError:
                        continue
                    sub = _IdentifierCollector(safe_names)
                    sub.visit(mod_tree)
                    for name in sub.found:
                        collector._add(name)

                log.debug(
                    "Star-import: resolved %s → %d names added", resolved.name, len(all_names or [])
                )
            except Exception as e:
                log.debug("Star-import: failed to parse %s: %s", resolved, e)

    return unresolved


def _resolve_module_path(
    module_name: str,
    level: int,
    file_dir: Path,
    repo_root: Path,
) -> Path | None:
    """
    Attempt to resolve a Python module reference to a .py file within repo_root.
    Returns None if external or cannot be found.
    """
    parts = module_name.split(".") if module_name else []

    if level > 0:
        # Relative import: walk up `level - 1` directories
        base = file_dir
        for _ in range(level - 1):
            base = base.parent
        if parts:
            candidate = base.joinpath(*parts)
        else:
            candidate = base
    else:
        # Absolute import from repo root
        if not parts:
            return None
        candidate = repo_root.joinpath(*parts)

    for suffix in (candidate.with_suffix(".py"), candidate / "__init__.py"):
        try:
            if suffix.exists() and suffix.is_relative_to(repo_root):
                return suffix
        except Exception:
            pass
    return None


def _extract_dunder_all(tree) -> list[str] | None:
    """Return __all__ contents as list[str], or None if not defined / not literal."""
    import ast as _ast

    for node in _ast.walk(tree):
        if not isinstance(node, _ast.Assign):
            continue
        if any(isinstance(t, _ast.Name) and t.id == "__all__" for t in node.targets):
            if isinstance(node.value, (_ast.List, _ast.Tuple)):
                return [
                    elt.value
                    for elt in node.value.elts
                    if isinstance(elt, _ast.Constant) and isinstance(elt.value, str)
                ]
    return None
