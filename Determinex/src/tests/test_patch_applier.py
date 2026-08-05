"""tests/test_patch_applier.py — apply-loop detection + variant writing.

The patch applier closes the advisor → apply → gate loop. The load-bearing
invariants this test pins down:

  - detect_status reports applicable / already_applied / cannot_apply
    correctly so we never silently re-apply or silently misapply a patch
  - apply_patch_to_variant NEVER modifies the source template — it writes
    a variant file next to it. The original is byte-identical after apply.
  - the variant file's content reflects the patch (before → after substitution)
  - already-applied patches are detected even when only the `after` text is
    present (the realistic scenario for shipped iter-N patches)
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import programbench_patch_applier as pa  # noqa: E402
from programbench_patch_advisor import CodeChange, UniversalPatch  # noqa: E402


def _synthetic_patch(*, before: str, after: str, file: str = "template.py") -> UniversalPatch:
    return UniversalPatch(
        family="synthetic",
        title="synthetic patch for tests",
        rationale="testing",
        scaffold_changes=[
            CodeChange(
                file=file,
                locator="test",
                before=before,
                after=after,
                why="test",
            )
        ],
    )


# ---------------------------------------------------------------------------
# detect_status
# ---------------------------------------------------------------------------


def test_detect_reports_applicable_when_before_text_present(tmp_path):
    (tmp_path / "template.py").write_text(
        "def f():\n    return OLD_VALUE\n",
        encoding="utf-8",
    )
    patch = _synthetic_patch(before="return OLD_VALUE", after="return NEW_VALUE")
    status, reasons = pa.detect_status(patch, tmp_path)
    assert status == pa.APPLICABLE
    assert reasons == []


def test_detect_reports_already_applied_when_after_text_present(tmp_path):
    (tmp_path / "template.py").write_text(
        "def f():\n    return NEW_VALUE\n",
        encoding="utf-8",
    )
    patch = _synthetic_patch(before="return OLD_VALUE", after="return NEW_VALUE")
    status, _ = pa.detect_status(patch, tmp_path)
    assert status == pa.ALREADY_APPLIED


def test_detect_reports_cannot_apply_when_neither_present(tmp_path):
    (tmp_path / "template.py").write_text(
        "def f():\n    return SOMETHING_ELSE\n",
        encoding="utf-8",
    )
    patch = _synthetic_patch(before="return OLD_VALUE", after="return NEW_VALUE")
    status, reasons = pa.detect_status(patch, tmp_path)
    assert status == pa.CANNOT_APPLY
    assert any("neither" in r for r in reasons)


def test_detect_reports_cannot_apply_when_target_missing(tmp_path):
    patch = _synthetic_patch(
        before="anything",
        after="something",
        file="does_not_exist.py",
    )
    status, reasons = pa.detect_status(patch, tmp_path)
    assert status == pa.CANNOT_APPLY
    assert any("not found" in r for r in reasons)


def test_detect_returns_cannot_apply_for_patch_with_no_changes(tmp_path):
    patch = UniversalPatch(
        family="info",
        title="informational only",
        rationale="x",
        scaffold_changes=[],  # empty
    )
    status, reasons = pa.detect_status(patch, tmp_path)
    assert status == pa.CANNOT_APPLY
    assert any("no scaffold_changes" in r for r in reasons)


# ---------------------------------------------------------------------------
# apply_patch_to_variant — source must remain byte-identical
# ---------------------------------------------------------------------------


def test_apply_writes_variant_and_leaves_source_byte_identical(tmp_path):
    src = tmp_path / "template.py"
    original = "def f():\n    return OLD_VALUE\n# comment after\n"
    src.write_text(original, encoding="utf-8")
    sha_before = _sha(src)

    patch = _synthetic_patch(before="return OLD_VALUE", after="return NEW_VALUE")
    variant, n = pa.apply_patch_to_variant(patch, tmp_path, "myversion_v1")

    # Original is untouched, byte-identical
    assert _sha(src) == sha_before, "source template must NEVER be modified in place"
    # Variant exists, contains the patched code, NOT the original
    assert variant.is_file()
    vtxt = variant.read_text(encoding="utf-8")
    assert "NEW_VALUE" in vtxt
    assert "OLD_VALUE" not in vtxt
    # Comment after the change still present (we only replaced the targeted span)
    assert "# comment after" in vtxt
    # Variant name embeds scaffold_version
    assert "myversion_v1" in variant.name
    assert variant.name != src.name
    assert n == 1


def test_apply_handles_multiple_changes_to_one_file(tmp_path):
    src = tmp_path / "template.py"
    src.write_text("X1\nY1\n", encoding="utf-8")
    patch = UniversalPatch(
        family="multi",
        title="t",
        rationale="r",
        scaffold_changes=[
            CodeChange(file="template.py", locator="l1", before="X1", after="X2", why="w"),
            CodeChange(file="template.py", locator="l2", before="Y1", after="Y2", why="w"),
        ],
    )
    variant, n = pa.apply_patch_to_variant(patch, tmp_path, "vmulti")
    vtxt = variant.read_text(encoding="utf-8")
    assert "X2" in vtxt and "Y2" in vtxt
    assert "X1" not in vtxt and "Y1" not in vtxt
    assert n == 2


def _sha(p: Path) -> str:
    import hashlib

    return hashlib.sha256(p.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# Real-profile sanity — these are the production patches the cockpit will route
# ---------------------------------------------------------------------------


def test_real_profile_rc_2_unknown_option_already_applied():
    """After the iter-1 commit, the rc_2_unknown_option patch should detect as
    already_applied — proves the profile's template-syntax escaping matches
    production scaffold.py."""
    from programbench_patch_advisor import PROGRAMBENCH_PROFILE

    patch = PROGRAMBENCH_PROFILE["rc_2_unknown_option"]
    repo_root = Path(__file__).resolve().parents[1]
    status, _ = pa.detect_status(patch, repo_root)
    assert status == pa.ALREADY_APPLIED, (
        "rc_2_unknown_option was shipped in iter-1; profile drift means cockpit can't refuse re-apply"
    )


def test_real_profile_help_text_mismatch_applicable():
    """help_text_mismatch should be APPLICABLE — it's iter-2's candidate."""
    from programbench_patch_advisor import PROGRAMBENCH_PROFILE

    patch = PROGRAMBENCH_PROFILE["help_text_mismatch"]
    repo_root = Path(__file__).resolve().parents[1]
    status, reasons = pa.detect_status(patch, repo_root)
    assert status == pa.APPLICABLE, (
        f"help_text_mismatch should be applicable for iter-2; got {status}: {reasons}"
    )
