"""Does the UI name the models the system actually runs?

WHY THIS EXISTS
---------------
Two instances in one day, 2026-07-29:

  * /proof-center credited the SHIPPED models (v11/v6/v5) with the scores earned by their
    predecessors (v10/v5/v3), and showed 87% for a Sentinel version that has no eval
    artifact at all.
  * MatrixExecutionDisplay.tsx labelled the three MoA agents
    determinex-sentinel-v3 / engineer-v10-dsl / observer-v5-dsl -- an entire generation
    behind what scripts/hive/ctx_config.py assigns.

Neither was caught by anything, because a model tag is a string: TypeScript cannot tell a
current tag from a superseded one, and the UI renders whichever it was given.

The source of truth here is `scripts/models/model_router.CURRENT_MODEL_IDS`, imported
rather than restated -- a copied list is exactly what drifted in the first place.

WHY THERE IS AN ALLOWLIST. Some UI files must name superseded models on purpose:
LocalModelSettingsPanel mirrors STALE_MODEL_IDS so it can WARN about them, and
work-readiness maps aliases including historical ones. Naming a stale model is only a bug
when the UI presents it as the model in use, so those files are listed explicitly instead
of being silently skipped by a pattern.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_SRC = REPO_ROOT / "frontend" / "src"
for p in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

# Files permitted to name superseded model ids, each for a stated reason.
STALE_ALLOWED = {
    # Mirrors STALE_MODEL_IDS so the panel can warn that a chosen model is superseded.
    "components/ide-repair/LocalModelSettingsPanel.tsx",
    # Alias map: resolves both determinex-* and legacy citadel-* tags, current and old.
    "lib/work-readiness.ts",
}

# Any determinex/citadel model tag with a version suffix.
MODEL_TAG_RE = re.compile(r"\b((?:determinex|citadel)-(?:engineer|observer|sentinel)-v[\w.\-]*)")

_LINE_COMMENT = re.compile(r"//[^\n]*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)


def _code_only(text: str) -> str:
    """Source with comments removed.

    The question is what the UI NAMES, which is a property of code, not of prose. Without
    this the check flags its own documentation: the comment in MatrixExecutionDisplay that
    records which stale tags used to be there tripped this test the first time it ran.
    Penalising an accurate note about a past bug would discourage exactly the kind of
    comment this codebase relies on.

    Crude but adequate: a `//` inside a string literal (a URL) would be over-stripped,
    which can only cause a FALSE PASS on that line, never a false failure -- and no model
    tag in this repo lives inside a URL.
    """
    return _LINE_COMMENT.sub("", _BLOCK_COMMENT.sub("", text))


def _current_and_stale() -> tuple[set[str], set[str]]:
    from scripts.models.model_router import CURRENT_MODEL_IDS, STALE_MODEL_IDS

    return set(CURRENT_MODEL_IDS), set(STALE_MODEL_IDS)


def _ui_files() -> list[Path]:
    out = []
    for p in list(FRONTEND_SRC.rglob("*.tsx")) + list(FRONTEND_SRC.rglob("*.ts")):
        if "__tests__" in p.parts:
            continue
        out.append(p)
    return out


def test_the_source_of_truth_is_importable_and_non_empty():
    """If CURRENT_MODEL_IDS could not be read, every test below would pass vacuously --
    which is the failure mode this file exists to prevent, so check it first."""
    current, stale = _current_and_stale()
    assert current, "CURRENT_MODEL_IDS is empty"
    assert stale, "STALE_MODEL_IDS is empty"
    assert not (current & stale), f"a model is both current and stale: {current & stale}"


def test_no_ui_file_presents_a_superseded_model_as_current():
    """THE regression, generalised. Anything naming a stale tag outside the allowlist is
    presenting a model the system does not run."""
    _current, stale = _current_and_stale()
    offenders: dict[str, set[str]] = {}
    for path in _ui_files():
        rel = path.relative_to(FRONTEND_SRC).as_posix()
        if rel in STALE_ALLOWED:
            continue
        found = set(
            MODEL_TAG_RE.findall(_code_only(path.read_text(encoding="utf-8", errors="replace")))
        )
        # citadel-* is the pre-rename spelling of the same models; normalise before
        # comparing, or a legacy tag would slip past the stale set on a name mismatch.
        bad = {t for t in found if t.replace("citadel-", "determinex-") in stale}
        if bad:
            offenders[rel] = bad
    assert not offenders, (
        "UI files naming superseded models as if current:\n"
        + "\n".join(f"  {f}: {sorted(t)}" for f, t in sorted(offenders.items()))
        + "\nUse model_router.CURRENT_MODEL_IDS, or add the file to STALE_ALLOWED with a reason."
    )


def test_the_allowlisted_files_still_exist():
    """An allowlist entry for a deleted file silently widens the check. If one of these is
    renamed, this fails rather than quietly exempting nothing."""
    for rel in STALE_ALLOWED:
        assert (FRONTEND_SRC / rel).is_file(), f"STALE_ALLOWED names a missing file: {rel}"


def test_the_scan_actually_matches_real_tags():
    """A regex that matched nothing would make the check above pass forever. Anchor it."""
    assert MODEL_TAG_RE.findall("model: 'determinex-engineer-v11-dsl'") == [
        "determinex-engineer-v11-dsl"
    ]
    assert MODEL_TAG_RE.findall("citadel-observer-v6-dsl") == ["citadel-observer-v6-dsl"]
    hits = [
        t
        for p in _ui_files()
        for t in MODEL_TAG_RE.findall(_code_only(p.read_text(encoding="utf-8", errors="replace")))
    ]
    assert hits, "the scan found no model tags anywhere in the UI -- regex is broken"


@pytest.mark.parametrize("role", ["engineer", "observer", "sentinel"])
def test_matrix_execution_display_names_the_assigned_model(role):
    """The specific file that was wrong, held to ctx_config's live assignment. It is
    currently unmounted (page.tsx imports only its AgentStatus type), which is exactly why
    a wrong tag could sit there unnoticed."""
    path = FRONTEND_SRC / "components" / "MatrixExecutionDisplay.tsx"
    if not path.is_file():
        pytest.skip("MatrixExecutionDisplay was removed")
    from hive.ctx_config import _MODEL_TAGS

    expected = _MODEL_TAGS[role]
    text = path.read_text(encoding="utf-8", errors="replace")
    assert f'"{expected}"' in text, (
        f"{role}: expected the assigned model {expected!r} to appear in "
        f"MatrixExecutionDisplay, found {sorted(set(MODEL_TAG_RE.findall(text)))}"
    )
