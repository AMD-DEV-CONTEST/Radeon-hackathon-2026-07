"""Per-language identifier-leak regression net for Project Cloak.

tests/test_cloak_smoke.py has 11 tests and every one is Python-only. Cloak's whole claim is
whole-repo obfuscation across 10 languages before source reaches a cloud LLM, so the nine
NON-Python languages -- the ones the privacy moat actually depends on -- had no leak assertion
behind them at all. Nothing failed loudly if a grammar stopped matching a declaration form,
or was never installed in the first place.

What this file pinned when first written, measured 2026-07-26 (before the fix in this same
commit series):

  * ACTUALLY AST-covered (tree-sitter grammar installed and its query compiles):
        go, javascript, rust   (only 3 of 9 -- pyproject's [cloak] extra declared just these)
  * Advertised by TS_SUPPORTED_LANGUAGES but NO grammar installed:
        c, cpp, java, php, ruby, typescript
  * NEITHER a working grammar NOR a regex fallback:  typescript  -- silent plaintext leak

Fixed same day: the 6 missing grammars were installed (pip install tree-sitter-{typescript,
java,ruby,php,c,cpp}), and every language's query was missing parameter/field/local captures
entirely -- not a per-language quirk, a systematic gap in every _QUERIES entry. Both fixed.
Current state (2026-07-28): all 9 languages obfuscate their fixture completely. The last
gap -- javascript instance fields assigned as `this.X = ...` -- was closed by scoping a
member_expression capture to `object: (this)`; see _KNOWN_GAPS for why that is safe.

TS_SUPPORTED_LANGUAGES is a hardcoded frozenset of 9, not a probe of what loads, so printing
it "verifies" nothing -- that was the original audit's mistake. test_advertised_languages_are_
actually_loadable is the standing guard against that gap reopening silently.

Fixtures deliberately use zzq-prefixed names: nonsense to any safe-list, so anything surviving
into the output is a genuine leak and not a stdlib/framework keep-list hit.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import determinex_cloak_treesitter as ts_mod  # noqa: E402
from determinex_cloak import (  # noqa: E402
    CloakObfuscationError,
    _build_cloak_context_nonpython,
    obfuscate_source,
)
from determinex_cloak._treesitter_bridge import TS_SUPPORTED_LANGUAGES  # noqa: E402
from determinex_cloak.lang_extractor import _LANG_DEF_PATTERNS  # noqa: E402

# language -> (filename, source, identifiers that MUST NOT survive obfuscation)
#
# Go is the one language where case is semantic: the extractor deliberately skips
# uppercase/exported names as public API, so the Go fixture uses unexported names only.
# Using exported names here would report a designed behavior as a leak.
CASES: dict[str, tuple[str, str, list[str]]] = {
    "rust": (
        "lib.rs",
        "pub struct ZzqRec { pub zzq_field: i64 }\n"
        "pub fn zzq_fn(zzq_param: &ZzqRec) -> i64 {\n"
        "    let zzq_local = zzq_param.zzq_field;\n"
        "    zzq_local\n"
        "}\n",
        ["ZzqRec", "zzq_field", "zzq_fn", "zzq_param", "zzq_local"],
    ),
    "go": (
        "m.go",
        "package main\n"
        "type zzqRec struct { zzqField int64 }\n"
        "func zzqFn(zzqParam zzqRec) int64 { zzqLocal := zzqParam.zzqField; return zzqLocal }\n",
        ["zzqRec", "zzqField", "zzqFn", "zzqParam", "zzqLocal"],
    ),
    "javascript": (
        "a.js",
        "class ZzqRec { constructor() { this.zzqField = 0; } }\n"
        "function zzqFn(zzqParam) { const zzqLocal = zzqParam.zzqField; return zzqLocal; }\n",
        ["ZzqRec", "zzqField", "zzqFn", "zzqParam", "zzqLocal"],
    ),
    "typescript": (
        "a.ts",
        "class ZzqRec { zzqField: number = 0; }\n"
        "function zzqFn(zzqParam: ZzqRec): number { const zzqLocal = zzqParam.zzqField; "
        "return zzqLocal; }\n",
        ["ZzqRec", "zzqField", "zzqFn", "zzqParam", "zzqLocal"],
    ),
    "java": (
        "A.java",
        "public class ZzqRec {\n"
        "  private long zzqField;\n"
        "  public long zzqFn(long zzqParam) { long zzqLocal = zzqParam; return zzqLocal; }\n"
        "}\n",
        ["ZzqRec", "zzqField", "zzqFn", "zzqParam", "zzqLocal"],
    ),
    "c": (
        "a.c",
        "struct ZzqRec { long zzq_field; };\n"
        "long zzq_fn(struct ZzqRec *zzq_param) {\n"
        "    long zzq_local = zzq_param->zzq_field;\n"
        "    return zzq_local;\n"
        "}\n",
        ["ZzqRec", "zzq_field", "zzq_fn", "zzq_param", "zzq_local"],
    ),
    "cpp": (
        "a.cpp",
        "class ZzqRec { public: long zzqField; };\n"
        "long zzqFn(ZzqRec* zzqParam) { long zzqLocal = zzqParam->zzqField; return zzqLocal; }\n",
        ["ZzqRec", "zzqField", "zzqFn", "zzqParam", "zzqLocal"],
    ),
    "ruby": (
        "a.rb",
        "class ZzqRec\n"
        "  def zzq_fn(zzq_param)\n"
        "    zzq_local = zzq_param\n"
        "    zzq_local\n"
        "  end\n"
        "end\n",
        ["ZzqRec", "zzq_fn", "zzq_param", "zzq_local"],
    ),
    "php": (
        "a.php",
        "<?php\nclass ZzqRec { public $zzqField = 0;\n"
        "  function zzqFn($zzqParam) { $zzqLocal = $zzqParam; return $zzqLocal; } }\n",
        ["ZzqRec", "zzqField", "zzqFn", "zzqParam", "zzqLocal"],
    ),
}

# Languages whose grammar genuinely loads AND whose query compiles right now.
_AST_REAL = sorted(
    lang for lang in TS_SUPPORTED_LANGUAGES if ts_mod._load_language_obj(lang) is not None
)


def _cloak(tmp_path: Path, language: str) -> tuple[str | None, list[str]]:
    """Run the documented public path.

    Returns (output, leaked). A CloakObfuscationError is SAFE, not a failure: refusing to
    produce output is the fail-closed behavior, and nothing reaches an API. It is reported as
    (None, []) so the leak assertions below treat a refusal as clean.
    """
    filename, source, declared = CASES[language]
    (tmp_path / filename).write_text(source, encoding="utf-8")
    try:
        ctx = _build_cloak_context_nonpython(f"t-{language}", tmp_path, language)
        out = obfuscate_source(source, ctx.symbol_map)
    except CloakObfuscationError:
        return None, []
    return out, [name for name in declared if name in out]


# Known, MEASURED coverage gaps. xfail(strict=True) rather than a weakened fixture: the
# assertion stays honest, CI stays green, and the moment a gap is actually closed the test
# XPASSes and forces this list to be updated. Never soften a fixture to make one of these pass.
#
# 2026-07-26: all 9 tree-sitter grammars installed (were 3 of 9), plus parameter/field/local
# query captures added for every one of them. All 9 languages are now a clean fixture pass.
# javascript was here until 2026-07-28 and is now CLOSED, not softened. The gap was real:
# `this.zzqField = 0` is an assignment to a member_expression, so field_definition (which only
# covers `class X { field = 0 }`) never saw it, and instance fields declared the conventional
# way reached the cloud model in plaintext. The blocker recorded here was that a general
# `(member_expression property: ...)` capture would also rewrite external API property access.
# Resolved by scoping the capture to `object: (this)`: a `this.X` field cannot be an external
# contract, while `res.status` and `JSON.parse` are untouched -- verified on a fixture that
# contains both. strict=True is what surfaced the fix: closing the gap XPASSed and failed the
# suite until this entry was removed, exactly as intended.
_KNOWN_GAPS: dict[str, str] = {}


def test_advertised_languages_are_actually_loadable():
    """TS_SUPPORTED_LANGUAGES is a hardcoded list, so it CAN advertise grammars that are not
    installed -- and callers gate on it (`lang in TS_SUPPORTED_LANGUAGES`) to decide whether
    AST extraction applies. When they disagree, a language silently drops to regex (or to
    nothing at all) while still reporting as covered. Green now that all 9 are installed; if
    this ever regresses (a fresh environment, a dependency removed), it should fail loudly.
    """
    advertised = set(TS_SUPPORTED_LANGUAGES)
    loadable = set(_AST_REAL)
    missing = sorted(advertised - loadable)
    assert not missing, (
        f"advertised as tree-sitter-covered but no grammar installed: {missing}. "
        f"pyproject.toml [cloak] declares only rust/go/python/javascript. "
        f"Install: pip install " + " ".join(f"tree-sitter-{m}" for m in missing)
    )


def test_every_advertised_language_has_some_extraction_path():
    """A language with neither a working grammar nor a regex fallback extracts NOTHING, so
    obfuscation is an identity function and the file goes to the cloud API in plaintext."""
    uncovered = sorted(
        lang
        for lang in TS_SUPPORTED_LANGUAGES
        if lang not in _AST_REAL and lang not in _LANG_DEF_PATTERNS
    )
    assert not uncovered, (
        f"advertised languages with NO extraction path at all (silent plaintext "
        f"passthrough): {uncovered}"
    )


@pytest.mark.parametrize(
    "language",
    [
        pytest.param(
            lang,
            marks=pytest.mark.xfail(strict=True, reason=_KNOWN_GAPS[lang]),
        )
        if lang in _KNOWN_GAPS
        else lang
        for lang in sorted(CASES)
    ],
)
def test_no_declared_identifier_survives_obfuscation(tmp_path, language):
    """The core privacy assertion, per language: every identifier the fixture DECLARES must be
    absent from the obfuscated output. Green for go/rust/typescript; the rest are xfail with a
    measured reason in _KNOWN_GAPS."""
    _, leaked = _cloak(tmp_path, language)
    assert not leaked, f"{language}: identifiers leaked in plaintext: {leaked}"


@pytest.mark.parametrize("language", _AST_REAL)
def test_ast_covered_languages_extract_something(tmp_path, language):
    """Narrower guard that stays green even where full coverage is still incomplete: a language
    with a working grammar must extract SOMETHING. Zero means the query stopped matching."""
    if language not in CASES:
        pytest.skip(f"no fixture for {language}")
    filename, source, _ = CASES[language]
    (tmp_path / filename).write_text(source, encoding="utf-8")
    ctx = _build_cloak_context_nonpython(f"t-{language}", tmp_path, language)
    assert ctx.symbol_map.forward, (
        f"{language}: grammar loads but extracted 0 identifiers -- query no longer matches"
    )


@pytest.mark.parametrize("language", sorted(CASES))
def test_obfuscation_is_not_an_identity_function(tmp_path, language):
    """The single most dangerous silent failure: extraction yields nothing, obfuscate_source
    returns the input unchanged, and the caller ships plaintext believing it is cloaked.

    A refusal (out is None) passes -- that IS the fail-closed path. Only a successful return of
    the untouched input is a defect, because that is indistinguishable from real obfuscation to
    every caller.
    """
    out, _ = _cloak(tmp_path, language)
    if out is None:
        return  # failed closed -- nothing was emitted, nothing can leak
    _, source, _ = CASES[language]
    assert out.strip() != source.strip(), (
        f"{language}: obfuscated output is byte-identical to the input -- nothing was cloaked"
    )


@pytest.fixture()
def _force_zero_extraction(monkeypatch):
    """Simulate "no extraction path" for a language that DOES have one today.

    All 9 languages now extract something for real (2026-07-26), so there is no longer a
    naturally-uncovered language to point this test at -- and pinning it to one that happens to
    still be broken would make the test fragile (it'd need rewriting the next time a gap
    closes, same as the _KNOWN_GAPS entries do). Instead this monkeypatches BOTH extraction
    paths to empty, which exercises the guard's actual trigger condition directly: real files
    scanned, zero identifiers found, regardless of why.
    """
    import determinex_cloak.lang_extractor as lx

    monkeypatch.setattr(lx, "extract_treesitter_identifiers", lambda *a, **k: frozenset())
    monkeypatch.setattr(lx, "_extract_lang_identifiers", lambda *a, **k: frozenset())
    return lx


def test_uncovered_language_fails_closed_instead_of_passing_plaintext(
    tmp_path, _force_zero_extraction
):
    """The guard added 2026-07-26 in _build_cloak_context_nonpython.

    Before it, a language with no extraction path produced an EMPTY symbol map, obfuscate_source
    returned the input verbatim, and the agent loop shipped proprietary source to a cloud LLM
    believing Cloak had run. TypeScript was in exactly that state at the time this was written
    (since fixed -- see the module docstring). Cloak's documented invariant is 'NO plaintext
    source ever reaches a cloud LLM API call', so extracting nothing from real source files must
    raise, not return.
    """
    (tmp_path / "lib.rs").write_text("pub struct ZzqRec { pub zzq_field: i64 }\n", encoding="utf-8")
    with pytest.raises(CloakObfuscationError) as exc:
        _build_cloak_context_nonpython("t", tmp_path, "rust")
    assert "rust" in str(exc.value)


def test_empty_repo_does_not_trip_the_fail_closed_guard(tmp_path, _force_zero_extraction):
    """Zero identifiers because there were zero FILES is not a leak -- there is nothing to leak.
    The guard keys on files_scanned so a legitimately empty scan stays a normal empty context."""
    ctx = _build_cloak_context_nonpython("t", tmp_path, "rust")
    assert ctx.symbol_map.forward == {}


def test_degraded_opt_out_downgrades_the_refusal_to_a_warning(
    tmp_path, monkeypatch, _force_zero_extraction
):
    """DETERMINEX_CLOAK_ALLOW_DEGRADED=1 is the operator's explicit accept-reduced-privacy
    switch, and it must keep working for the new guard exactly as it does for the import-time
    tree-sitter check -- otherwise the guard is unbypassable and would strand real runs."""
    import determinex_cloak.lang_extractor as lx

    monkeypatch.setattr(lx, "_ALLOW_DEGRADED", True)
    (tmp_path / "lib.rs").write_text("pub struct ZzqRec { pub zzq_field: i64 }\n", encoding="utf-8")
    ctx = lx._build_cloak_context_nonpython("t", tmp_path, "rust")
    assert ctx.symbol_map.forward == {}  # proceeds, uncloaked, by explicit operator choice


# ─────────────────────────────────────────────────────────────────────────────
# Instance fields, and the names the runtime owns
#
# The JavaScript `this.field = 0` leak (fixed 2026-07-28) was found because the
# fixture above happened to plant that form. Nothing else did -- typescript declared
# `zzqField: number = 0`, php `public $zzqField = 0`, java `private long zzqField`,
# and ruby planted no field at all. Probing every OO language for the same shape
# found FOUR more live plaintext leaks:
#
#   typescript  this.zzqCtorField = 1        (shares JS's grammar family)
#   php         $this->zzqCtorField = 1
#   ruby        @zzq_ivar = 1                (instance variables never captured)
#   cpp         void zzqSet(...) {}          (method defined INLINE in a class body
#                                             has declarator: (field_identifier),
#                                             not (identifier))
#
# The same probe surfaced a correctness bug in the other direction: names the
# LANGUAGE owns were being renamed. `_DUNDER` only matches Python's `__x__` shape, so
# PHP `__construct` and Ruby `initialize`/`to_s` were all obfuscated -- which does not
# leak anything, but hands the cloud model a file whose constructor no longer runs.
# A wrong patch from correct-looking input is its own failure mode.
# ─────────────────────────────────────────────────────────────────────────────

# language -> (filename, source, must_not_survive, must_survive)
FIELD_CASES: dict[str, tuple[str, str, list[str], list[str]]] = {
    "javascript": (
        "a.js",
        "class ZzqRec {\n"
        "  constructor() { this.zzqCtorField = 1; }\n"
        "  zzqM(zzqP) { this.zzqCtorField = zzqP; return JSON.parse(String(zzqP)); }\n"
        "}\n",
        ["ZzqRec", "zzqCtorField", "zzqM", "zzqP"],
        ["JSON.parse"],
    ),
    "typescript": (
        "a.ts",
        "class ZzqRec {\n"
        "  constructor() { this.zzqCtorField = 1; }\n"
        "  zzqM(zzqP: number) { this.zzqCtorField = zzqP; return JSON.parse(String(zzqP)); }\n"
        "}\n",
        ["ZzqRec", "zzqCtorField", "zzqM", "zzqP"],
        ["JSON.parse"],
    ),
    "php": (
        "a.php",
        "<?php\nclass ZzqRec {\n"
        "  function __construct() { $this->zzqCtorField = 1; }\n"
        "  function zzqM($zzqP) { $this->zzqCtorField = $zzqP; return $this->zzqCtorField; }\n"
        "}\n",
        ["ZzqRec", "zzqCtorField", "zzqM", "zzqP"],
        # __construct is magical per the PHP spec; $this is a keyword. Renaming either
        # emits code that does not work.
        ["__construct", "$this"],
    ),
    "ruby": (
        "a.rb",
        "class ZzqRec\n"
        "  def initialize(zzq_p)\n"
        "    @zzq_ivar = zzq_p\n"
        "  end\n"
        "  def to_s\n"
        "    @zzq_ivar.to_s\n"
        "  end\n"
        "  def zzq_m\n"
        "    @zzq_ivar\n"
        "  end\n"
        "end\n",
        ["ZzqRec", "zzq_ivar", "zzq_m", "zzq_p"],
        # The runtime calls these; renaming initialize stops it being the constructor.
        ["initialize", "to_s"],
    ),
    "cpp": (
        "a.cpp",
        "class ZzqRec {\n public:\n  long zzqField;\n"
        "  ZzqRec() : zzqField(0) {}\n"
        "  ~ZzqRec() {}\n"
        "  bool operator==(const ZzqRec& zzqOther) const "
        "{ return zzqField == zzqOther.zzqField; }\n"
        "  void zzqSet(long zzqP) { this->zzqField = zzqP; }\n};\n",
        ["ZzqRec", "zzqField", "zzqSet", "zzqP", "zzqOther"],
        # `operator` is a C++ keyword, not an identifier -- renaming it would not
        # compile. The constructor and destructor are the opposite case and get
        # their own test below, because they MUST be renamed, in lockstep with the
        # class name.
        ["operator=="],
    ),
}


def _obfuscate_field_case(tmp_path, language: str) -> str:
    filename, source, _, _ = FIELD_CASES[language]
    (tmp_path / filename).write_text(source, encoding="utf-8")
    ctx = _build_cloak_context_nonpython(f"f-{language}", tmp_path, language)
    return obfuscate_source(source, ctx.symbol_map)


@pytest.mark.parametrize("language", sorted(FIELD_CASES))
def test_instance_fields_do_not_survive_obfuscation(tmp_path, language):
    """Fields assigned through this / $this / @ are the project's own private state.
    Every one of these forms leaked in plaintext before 2026-07-28."""
    if ts_mod._load_language_obj(language) is None:
        pytest.skip(f"{language} grammar not installed")
    out = _obfuscate_field_case(tmp_path, language)
    _, _, must_not, _ = FIELD_CASES[language]
    leaked = [n for n in must_not if n in out]
    assert not leaked, f"{language}: leaked {leaked}"


@pytest.mark.parametrize("language", sorted(FIELD_CASES))
def test_runtime_owned_names_are_not_renamed(tmp_path, language):
    """Obfuscating a name the LANGUAGE calls produces a file that no longer works.
    That is not a leak, it is worse in a different way: the model reasons about, and
    patches, code whose semantics we broke on the way out."""
    if ts_mod._load_language_obj(language) is None:
        pytest.skip(f"{language} grammar not installed")
    _, _, _, must_survive = FIELD_CASES[language]
    if not must_survive:
        pytest.skip(f"no runtime-owned names in the {language} fixture")
    out = _obfuscate_field_case(tmp_path, language)
    renamed = [n for n in must_survive if n not in out]
    assert not renamed, f"{language}: renamed runtime-owned {renamed}"


def test_cpp_constructor_and_destructor_track_the_class_name(tmp_path):
    """C++ is the one case where a runtime-owned name MUST be renamed -- and must be
    renamed to exactly the same token as something else.

    A constructor and destructor are spelled with the class name, so obfuscating the
    class without them, or to a different token, yields a file that cannot compile.
    Asserting "these names survive" would be wrong here; the invariant is that all
    three move together. That is why the cpp fixture had an empty must-survive list
    and skipped the runtime-owned check entirely -- an exclusion standing in for an
    assertion nobody had worked out how to write.
    """
    if ts_mod._load_language_obj("cpp") is None:
        pytest.skip("cpp grammar not installed")
    out = _obfuscate_field_case(tmp_path, "cpp")

    m = re.search(r"class\s+(x_\d+)\s*\{", out)
    assert m, f"the class name was not obfuscated at all:\n{out}"
    cls = m.group(1)
    assert f"{cls}() :" in out, f"constructor does not match the class name {cls}:\n{out}"
    assert f"~{cls}()" in out, f"destructor does not match the class name {cls}:\n{out}"
