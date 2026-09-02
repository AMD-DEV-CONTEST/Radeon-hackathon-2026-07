"""The two closed status-token sets that nothing was enforcing.

WHY THIS EXISTS
---------------
Nine of the eleven `*_STATUS_TOKENS` arrays in the frontend are pinned by a Python
lock test that reads the array out of the source text and asserts the exact set --
the panels declare "MUST refuse to render any token not in this set", and those
tests are what make the declaration real.

Two were not:

  * REACT_USER_LEVEL_TEACHING_MODE_STATUS_TOKENS -- UserLevelTeachingMode.tsx had no
    lock test at all.
  * UNIFIED_PRODUCT_STATUS_TOKENS -- ide-product-shell-api.ts; the unified-navigation
    locks nearby do not read it.

Found 2026-07-28 while removing a blanket knip `ignore` over these directories. Once
knip could see them it reported both as unused exports -- and unlike the other nine,
that was almost true: nothing in TypeScript imports them and no Python test read
them, so a stated closed-set invariant was being enforced by nothing at all.

Deleting them was the wrong fix: the right one is the assertion the other nine
already have. Pinning the current set is the point -- changing a closed set should
require saying so here, which is exactly what the sibling locks do.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]

TEACHING_MODE = (
    _REPO_ROOT
    / "frontend"
    / "src"
    / "components"
    / "ide-product-shell"
    / "UserLevelTeachingMode.tsx"
)
PRODUCT_SHELL_API = _REPO_ROOT / "frontend" / "src" / "lib" / "ide-product-shell-api.ts"

TEACHING_MODE_TOKENS = frozenset(
    {
        "REACT_USER_LEVEL_TEACHING_MODE_PASSED",
        "REACT_USER_LEVEL_TEACHING_MODE_BLOCKED_PROOF_HIDDEN",
        "REACT_USER_LEVEL_TEACHING_MODE_BLOCKED_AUTHORITY_BYPASS",
        "REACT_USER_LEVEL_TEACHING_MODE_BLOCKED_MISSING_BLOCKED_REASON",
    }
)

UNIFIED_PRODUCT_TOKENS = frozenset(
    {
        "TAURI_COMMAND_OK",
        "TAURI_COMMAND_BLOCKED_UNKNOWN",
        "TAURI_RUST_COMMAND_BRIDGE_BLOCKED_BACKEND_MISSING",
    }
)


def _declared(path: Path, const_name: str) -> set[str]:
    src = path.read_text(encoding="utf-8")
    m = re.search(rf"{const_name}\s*=\s*\[([^\]]+)\]\s*as\s*const", src)
    assert m, f"{const_name} not found as an `as const` array in {path.name}"
    return set(re.findall(r'"([^"]+)"', m.group(1)))


def test_teaching_mode_source_exists():
    assert TEACHING_MODE.is_file()


def test_teaching_mode_status_tokens_exact():
    assert _declared(TEACHING_MODE, "REACT_USER_LEVEL_TEACHING_MODE_STATUS_TOKENS") == (
        set(TEACHING_MODE_TOKENS)
    )


def test_product_shell_api_exists():
    assert PRODUCT_SHELL_API.is_file()


def test_unified_product_status_tokens_exact():
    assert _declared(PRODUCT_SHELL_API, "UNIFIED_PRODUCT_STATUS_TOKENS") == (
        set(UNIFIED_PRODUCT_TOKENS)
    )


def test_both_sets_are_non_empty():
    """A closed set that is empty closes nothing -- it would let every token through
    while still reading as an enforced invariant."""
    assert TEACHING_MODE_TOKENS and UNIFIED_PRODUCT_TOKENS


def test_the_blocked_tokens_are_actually_distinguishable():
    """Every one of these sets exists so a panel can refuse to render an unknown
    state. A set with only a success token could not express refusal."""
    assert any(t.endswith("PASSED") or t.endswith("_OK") for t in TEACHING_MODE_TOKENS)
    assert any("BLOCKED" in t for t in TEACHING_MODE_TOKENS)
    assert any("BLOCKED" in t for t in UNIFIED_PRODUCT_TOKENS)


# ── the census, which is what this file got wrong about itself ────────────────
#
# The docstring above says "Nine of the eleven `*_STATUS_TOKENS` arrays in the frontend
# are pinned". Measured 2026-07-29 there are EIGHTEEN, and four were still unguarded:
#
#   REACT_LEARNING_STUDIO_PANEL_STATUS_TOKENS       ide-product-shell/LearningStudioPanel.tsx
#   REACT_MAINTENANCE_BAY_PANEL_STATUS_TOKENS       ide-product-shell/MaintenanceBayPanel.tsx
#   REACT_REPO_CLINIC_PANEL_STATUS_TOKENS           ide-product-shell/RepoClinicPanel.tsx
#   REACT_UNIFIED_NAVIGATION_PANEL_STATUS_TOKENS    ide-product-shell/UnifiedNavigationPanel.tsx
#
# So this lock closed two holes, declared the job done from a count that was wrong, and
# left four open. That is the same failure it was written to fix, one level up: the guard
# was fine, its INVENTORY was incomplete.
#
# Pinning the four by hand would repeat the mistake for the nineteenth set. Instead the
# census is asserted: enumerate every token set in the frontend and require each to be
# read by some test under tests/. A new panel that declares a closed set now fails here
# until somebody pins it, which is the only version of this guard that stays true.

_FRONTEND_SRC = _REPO_ROOT / "frontend" / "src"
_TESTS_DIR = _REPO_ROOT / "tests"

_TOKEN_SET_DECL = re.compile(r"(?:export\s+)?const\s+([A-Z][A-Z0-9_]*STATUS_TOKENS)\s*=")


def _declared_token_sets() -> dict[str, Path]:
    """Every *_STATUS_TOKENS constant declared in frontend source (tests excluded)."""
    found: dict[str, Path] = {}
    for path in list(_FRONTEND_SRC.rglob("*.tsx")) + list(_FRONTEND_SRC.rglob("*.ts")):
        if "__tests__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in _TOKEN_SET_DECL.finditer(text):
            found[match.group(1)] = path
    return found


def _names_read_by_python_tests() -> set[str]:
    """Token-set names that appear anywhere under tests/ -- i.e. are actually pinned."""
    names: set[str] = set()
    for path in _TESTS_DIR.rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="replace")
        names.update(re.findall(r"\b([A-Z][A-Z0-9_]*STATUS_TOKENS)\b", text))
    return names


def test_every_declared_status_token_set_is_pinned_by_some_test():
    """THE census. A panel that declares "MUST refuse to render any token not in this
    set" and has nothing asserting the set is making a promise no code keeps."""
    declared = _declared_token_sets()
    assert len(declared) >= 18, (
        f"expected at least the 18 token sets measured 2026-07-29, found {len(declared)} "
        f"-- if sets were deliberately removed, update this floor in the same commit"
    )
    pinned = _names_read_by_python_tests()
    unguarded = {
        name: path.relative_to(_REPO_ROOT).as_posix()
        for name, path in declared.items()
        if name not in pinned
    }
    assert not unguarded, (
        "closed status-token sets with no test reading them:\n"
        + "\n".join(f"  {n}  ({p})" for n, p in sorted(unguarded.items()))
        + "\nAdd an exact-set assertion (see the sibling locks) rather than deleting the set."
    )


def test_the_census_can_actually_find_the_sets_it_checks():
    """A census that silently matched nothing would pass this file forever. Anchors it to
    two sets known to exist, so a broken regex fails loudly instead of vacuously."""
    declared = _declared_token_sets()
    assert "REACT_USER_LEVEL_TEACHING_MODE_STATUS_TOKENS" in declared
    assert "REPAIR_PANEL_STATUS_TOKENS" in declared


# ── the four sets this lock had missed ────────────────────────────────────────

_PRODUCT_SHELL = _FRONTEND_SRC / "components" / "ide-product-shell"

# The EXACT membership, restated here on purpose.
#
# My first version of this block held these four to properties only -- non-empty, has a
# success token, has a BLOCKED token -- and left a comment claiming "the current on-disk
# set IS the baseline". It was not: nothing recorded the baseline, so a token could be
# added or dropped and every test here would still pass. That is the identical defect this
# whole file is about, reproduced one level down while fixing it. The other nine locks
# assert exact sets; so do these now. Changing a closed set has to mean editing this list.
_NEWLY_PINNED: dict[str, tuple[Path, frozenset[str]]] = {
    "REACT_LEARNING_STUDIO_PANEL_STATUS_TOKENS": (
        _PRODUCT_SHELL / "LearningStudioPanel.tsx",
        frozenset(
            {
                "REACT_LEARNING_STUDIO_PANEL_PASSED",
                "REACT_LEARNING_STUDIO_PANEL_BLOCKED_MUTATION_CONFUSION",
                "REACT_LEARNING_STUDIO_PANEL_BLOCKED_FALSE_SUCCESS",
                "REACT_LEARNING_STUDIO_PANEL_BLOCKED_MISSING_TEACHING_LEVELS",
            }
        ),
    ),
    "REACT_MAINTENANCE_BAY_PANEL_STATUS_TOKENS": (
        _PRODUCT_SHELL / "MaintenanceBayPanel.tsx",
        frozenset(
            {
                "REACT_MAINTENANCE_BAY_PANEL_PASSED",
                "REACT_MAINTENANCE_BAY_PANEL_BLOCKED_FALSE_UPDATED_LABEL",
                "REACT_MAINTENANCE_BAY_PANEL_BLOCKED_MISSING_COMPATIBILITY_VERIFIER",
                "REACT_MAINTENANCE_BAY_PANEL_BLOCKED_RISK_HIDDEN",
            }
        ),
    ),
    "REACT_REPO_CLINIC_PANEL_STATUS_TOKENS": (
        _PRODUCT_SHELL / "RepoClinicPanel.tsx",
        frozenset(
            {
                "REACT_REPO_CLINIC_PANEL_PASSED",
                "REACT_REPO_CLINIC_PANEL_BLOCKED_FALSE_FIXED_LABEL",
                "REACT_REPO_CLINIC_PANEL_BLOCKED_SOURCE_MUTATION_CONFUSION",
                "REACT_REPO_CLINIC_PANEL_BLOCKED_VERIFIER_MISSING_HIDDEN",
            }
        ),
    ),
    "REACT_UNIFIED_NAVIGATION_PANEL_STATUS_TOKENS": (
        _PRODUCT_SHELL / "UnifiedNavigationPanel.tsx",
        frozenset(
            {
                "REACT_UNIFIED_NAVIGATION_PANEL_PASSED",
                "REACT_UNIFIED_NAVIGATION_PANEL_BLOCKED_MISSING_SURFACE",
                "REACT_UNIFIED_NAVIGATION_PANEL_BLOCKED_AUTHORITY_CONFUSION",
                "REACT_UNIFIED_NAVIGATION_PANEL_BLOCKED_HIDDEN_BLOCKED_STATE",
            }
        ),
    ),
}


@pytest.mark.parametrize("const_name", sorted(_NEWLY_PINNED), ids=sorted(_NEWLY_PINNED))
def test_newly_pinned_set_matches_exactly(const_name):
    """Exact membership, the way the sibling locks do it."""
    path, expected = _NEWLY_PINNED[const_name]
    assert path.is_file(), f"{path} missing"
    assert _declared(path, const_name) == set(expected)


@pytest.mark.parametrize("const_name", sorted(_NEWLY_PINNED), ids=sorted(_NEWLY_PINNED))
def test_newly_pinned_set_can_express_refusal(const_name):
    """The property the exact-set check cannot state: a set that can only say "passed"
    cannot refuse an unknown state, which is the entire purpose of a closed set."""
    _path, tokens = _NEWLY_PINNED[const_name]
    assert any(t.endswith("PASSED") or t.endswith("_OK") for t in tokens), sorted(tokens)
    assert any("BLOCKED" in t for t in tokens), sorted(tokens)
