"""The public authority boundary must not assert an invariant it never checked.

This module is a no-overclaim governance surface: it reads two evidence blobs and reports
whether a set of "X remains false / unchanged at zero" invariants still hold. It had no test
coverage at all, and carried a latent hole found on 2026-08-02 by an AST scan for
`.get(..., <success literal>)`:

    for k in _REQUIRED_PRESERVED_TRUE_FLAGS:
        if k in ab and ab[k] is not True:   # <- only checked when PRESENT
            return _block(...)
    ...
    release_support_unchanged_at_zero=bool(ab.get("release_support_unchanged_at_zero", True))

A flag absent from the evidence passed the gate and was then REPORTED as True. The surface
whose job is to prevent overclaiming would have claimed an invariant held on evidence that
never mentioned it.

Latent, not live: both current evidence blobs carry all six flags, which is what made the
fix safe to land. These tests pin both directions so it stays that way.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
for _p in (str(_SCRIPTS), str(_SCRIPTS / "ide")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import public_authority_boundary_status as M  # noqa: E402


def _staged(mutate_flagship=None, mutate_export=None) -> tuple[Path, Path]:
    """Copy the real evidence into temp dirs, optionally mutating it."""
    out = []
    for src_dir, mutate in ((M._FLAGSHIP_DIR, mutate_flagship), (M._EXPORT_DIR, mutate_export)):
        dst = Path(tempfile.mkdtemp())
        chosen = M._locate_latest_evidence(src_dir)
        assert chosen is not None, f"no evidence in {src_dir}"
        blob = json.loads(chosen.read_text(encoding="utf-8"))
        if mutate:
            mutate(blob)
        (dst / chosen.name).write_text(json.dumps(blob), encoding="utf-8")
        out.append(dst)
    return out[0], out[1]


def test_the_real_evidence_still_passes():
    """The load-bearing negative control. Tightening a release gate is only safe if the
    genuine artifacts still clear it, and that has to be asserted, not assumed."""
    assert M.load().decision.endswith("PASSED")


def test_all_six_required_flags_are_actually_present_in_the_real_evidence():
    """Documents WHY the fix was safe. If a future evidence generator stops emitting one of
    these, this test says so directly instead of the gate mysteriously starting to block."""
    for src_dir in (M._FLAGSHIP_DIR, M._EXPORT_DIR):
        blob = json.loads(M._locate_latest_evidence(src_dir).read_text(encoding="utf-8"))
        ab = blob.get("authority_boundary") or {}
        missing = [k for k in M._REQUIRED_PRESERVED_TRUE_FLAGS if k not in ab]
        assert not missing, f"{src_dir.name} evidence is missing {missing}"


def test_an_absent_required_flag_blocks_rather_than_being_assumed_true():
    """THE BUG. `if k in ab and ...` meant a missing flag was never checked, and the status
    it fed defaulted to True."""
    fdir, edir = _staged(
        mutate_flagship=lambda b: b["authority_boundary"].pop(
            "training_eligibility_remains_false", None
        )
    )
    st = M.load(flagship_dir=fdir, export_dir=edir)
    assert "BLOCKED" in st.decision, st.decision
    assert any("training_eligibility_remains_false" in str(n) for n in st.notes), st.notes
    assert any("cannot be assumed" in str(n) for n in st.notes), st.notes


def test_a_required_flag_set_to_false_still_blocks():
    """The original check did catch this case. Keeping it pinned so the presence fix does
    not accidentally replace the value check instead of adding to it."""
    fdir, edir = _staged(
        mutate_flagship=lambda b: b["authority_boundary"].update(
            {"broad_claims_remain_false": False}
        )
    )
    st = M.load(flagship_dir=fdir, export_dir=edir)
    assert "BLOCKED" in st.decision
    assert any("broad_claims_remain_false" in str(n) for n in st.notes)


def test_the_export_side_is_checked_too_not_only_the_flagship():
    """The loop covers both sources; an asymmetry here would mean half the evidence was
    unguarded while the report still said PASSED."""
    fdir, edir = _staged(
        mutate_export=lambda b: b["authority_boundary"].pop(
            "source_mutation_remains_unauthorized", None
        )
    )
    st = M.load(flagship_dir=fdir, export_dir=edir)
    assert "BLOCKED" in st.decision, st.decision
    assert any("export" in str(n) for n in st.notes), st.notes


def test_absent_evidence_is_awaiting_not_passing():
    """A missing evidence directory must never read as compliance."""
    empty = Path(tempfile.mkdtemp())
    st = M.load(flagship_dir=empty, export_dir=empty)
    assert not st.decision.endswith("PASSED"), st.decision
