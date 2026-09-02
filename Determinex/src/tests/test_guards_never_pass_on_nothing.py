"""A guard may not report PASS having examined nothing.

WHY THIS EXISTS
---------------
This repo's guards are the last line between a claim and the truth of it, and the way
they fail is not by raising -- it is by finding nothing to check and calling that clean.
CLAUDE.md already records one instance as history:

    "regenerating the stale verified_locks.json (was 64, missing 35 locks -> the
     provenance_guard never checked them) EXPOSED 4 illegitimate locks"

A guard whose input list is short does not complain about the entries missing from it.
Measured 2026-07-29 across the four guards that print a verdict -- by RUNNING each with
its input pointed at a path that does not exist, not by reading the code, which is how
the two false positives below got caught:

  DEFECTIVE (silent PASS):
  * determinex_pb_provenance_guard -- registry absent => `reg = []`, loop runs zero
    times, prints "PROVENANCE GUARD PASSED: no unjustified test-gaming on any lock"
    and exits 0. Worse in the real tree: 2 of the 5 registry entries
    (`cheat__cheat.b8098dc`, `lymphatus__caesium-clt`) had NEITHER a submission tarball
    nor a tracked source/ dir on disk, so 40% of the registry was certified clean having
    been examined not at all. `cheat__cheat.b8098dc` is also a registry/disk NAME
    mismatch -- disk has `cheat__cheat/`, holding only a ceiling cert.
  * pb_senses_guard -- WAL dir absent => `return []`, prints "OK: no static-RE tool
    references found", exits 0.

  ALREADY CORRECT, kept as POSITIVE CONTROLS so a bug in this test that made everything
  pass would be visible -- the controls assert it can tell right from wrong, not merely
  detect failure:
  * pb_board_guard  -- missing index => explicit exit 1.
  * pb_override_scan -- missing locked/overrides dir => raises FileNotFoundError. Ugly,
    but it fails closed, which is the property that matters. Reading the code suggested
    it would silently pass on "0 tools scanned"; running it showed otherwise.

THE INVARIANT: in --guard mode, "I examined nothing" must never render as PASS. It is
the same doctrine the Compiler Oracle follows -- CLAUDE.md: "an oracle never silently
passes" -- applied to the things that audit the oracle.

These tests never touch the real corpus: each guard's input constant is monkeypatched to
a path that does not exist, which is exactly the state being tested.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
for p in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)


# (module, attribute holding the input path, argv for guard mode)
GUARDS = [
    ("determinex_pb_provenance_guard", "REG", ["prog", "--guard"]),
    ("pb_senses_guard", "DEFAULT_WAL_DIR", ["prog", "--guard"]),
    ("pb_board_guard", "INDEX_PATH", ["prog", "--guard"]),  # positive control
    ("pb_override_scan", "LOCKED_DIR", ["prog", "--guard"]),  # positive control
]


def _run_guard(monkeypatch, capsys, module_name: str, attr: str, argv: list[str]):
    """Point a guard at a nonexistent input and return (exit_code, stdout)."""
    mod = importlib.import_module(module_name)
    monkeypatch.setattr(mod, attr, Path("C:/tmp/_determinex_guard_probe_absent/nope.json"))
    monkeypatch.setattr(sys, "argv", argv)

    code = 0
    try:
        result = mod.main()
        # A guard may return its code or exit with it; normalise both.
        code = result if isinstance(result, int) else 0
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 0
    except Exception:  # noqa: BLE001
        # Crashing on absent input is not elegant, but it FAILS CLOSED, which is the
        # property under test. pb_override_scan does exactly this. Treating a raise as
        # a pass here would mean demanding a specific failure style rather than the
        # invariant, and would flag a guard that already behaves correctly.
        code = 1
    out = capsys.readouterr().out
    return code, out


@pytest.mark.parametrize("module_name,attr,argv", GUARDS, ids=[g[0] for g in GUARDS])
def test_a_guard_with_no_input_does_not_report_pass(monkeypatch, capsys, module_name, attr, argv):
    """The whole invariant, for every guard in the table including the control."""
    code, out = _run_guard(monkeypatch, capsys, module_name, attr, argv)

    assert code != 0, (
        f"{module_name} exited 0 with no input to examine -- in CI that reads as a "
        f"clean verdict on nothing. Output:\n{out[-600:]}"
    )
    lowered = out.lower()
    assert "guard passed" not in lowered and "no unjustified" not in lowered, (
        f"{module_name} printed a PASS verdict having examined nothing:\n{out[-600:]}"
    )


def test_the_provenance_guard_reports_unscannable_locks():
    """A registry entry with no artifact on disk cannot be certified clean.

    scan_tool returns [] both when a tool is genuinely clean and when its tarball is
    absent or unreadable (`except Exception: pass`). Those are opposite facts sharing one
    representation, and the guard read the pair as "clean". Measured: 2 of 5 registry
    entries had neither artifact, and the guard passed.
    """
    import determinex_pb_provenance_guard as pg

    result = pg.audit()
    assert "unscannable" in result, (
        "audit() must distinguish 'examined and clean' from 'could not examine' -- "
        "without that, a missing archive is indistinguishable from a passing one"
    )


def test_the_provenance_guard_fails_when_a_lock_cannot_be_examined(monkeypatch, tmp_path):
    """End to end: a registry naming a tool with no artifacts must not exit 0."""
    import determinex_pb_provenance_guard as pg

    reg = tmp_path / "verified_locks.json"
    reg.write_text('{"locks": ["tool-with-no-archive-anywhere"]}', encoding="utf-8")
    monkeypatch.setattr(pg, "REG", reg)
    monkeypatch.setattr(pg, "LOCKED", tmp_path / "locked-that-does-not-exist")
    monkeypatch.setattr(sys, "argv", ["prog", "--guard"])

    code = pg.main()
    assert code != 0, "a lock with no archive on disk was certified clean"
