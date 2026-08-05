"""tests/test_three_speed_gate.py — three-speed gate micro tests.

Builds a fake executable as a Python script, runs the gate's micro phase
against it, and verifies:

  - a scaffold that DOES NOT implement the iter-1 clap wording fails on the
    rc_2_unknown_option family micro tests (negative test — gate catches the
    regression)
  - a scaffold that DOES implement clap-style errors with rc=1 passes (≥85%)
  - the gate halts at micro on a broken executable (does NOT escalate to
    shard / full)

Shard and full phases call the real programbench eval harness; we don't
exercise those in this test (covered by manual end-to-end via the CLI).
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import run_ledger as rl  # noqa: E402
import three_speed_gate as gate  # noqa: E402

# ---------------------------------------------------------------------------
# Fake-scaffold helpers
# ---------------------------------------------------------------------------

_BROKEN_TEMPLATE = """\
#!/usr/bin/env python3
'''Broken scaffold: returns wrong error wording (old style) on unknown flags
and uses exit code 2 instead of 1.'''
import sys
TOOL_NAME = "broken"
if "--help" in sys.argv or "-h" in sys.argv:
    print(f"usage: {TOOL_NAME} [OPTIONS]")
    sys.exit(0)
if "--version" in sys.argv or "-V" in sys.argv:
    print(f"{TOOL_NAME} 0.1.0")
    sys.exit(0)
for a in sys.argv[1:]:
    if a.startswith("-") and a != "-":
        print(f"{TOOL_NAME}: unknown option: {a}", file=sys.stderr)
        sys.exit(2)
sys.exit(0)
"""

_CLAP_TEMPLATE = """\
#!/usr/bin/env python3
'''Iter-1 scaffold: clap-style 'error: unexpected argument' + rc=1.'''
import sys
TOOL_NAME = "clapok"
if "--help" in sys.argv or "-h" in sys.argv:
    print(f"Usage: {TOOL_NAME} [OPTIONS]")
    sys.exit(0)
if "--version" in sys.argv or "-V" in sys.argv:
    print(f"{TOOL_NAME} 0.1.0")
    sys.exit(0)
known_bool = {"--no-color", "--color"}
known_arg = {"-o", "--output"}
i = 1
while i < len(sys.argv):
    a = sys.argv[i]
    if a == "--":
        break
    if a == "-":
        i += 1
        continue
    if a.startswith("-") and len(a) > 1:
        if a in known_bool:
            i += 1; continue
        if a in known_arg:
            i += 2; continue
        if "=" in a and a.split("=",1)[0] in known_arg:
            i += 1; continue
        print(f"error: unexpected argument '{a}' found", file=sys.stderr)
        print("", file=sys.stderr)
        print(f"Usage: {TOOL_NAME} [OPTIONS]", file=sys.stderr)
        print("", file=sys.stderr)
        print("For more information, try '--help'.", file=sys.stderr)
        sys.exit(1)
    i += 1
sys.exit(0)
"""


def _write_script(dir_: Path, name: str, body: str) -> Path:
    p = dir_ / name
    p.write_text(body, encoding="utf-8", newline="\n")
    # Make executable bit a no-op on Windows; harmless
    try:
        os.chmod(p, p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except OSError:
        pass
    return p


@pytest.fixture
def fresh_ledger(tmp_path, monkeypatch):
    """Each gate invocation writes ledger events; isolate them per test."""
    tmp_db = tmp_path / "ledger.db"
    tmp_jsonl = tmp_path / "ledger_jsonl"
    tmp_jsonl.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(rl, "LEDGER_DIR", tmp_jsonl)
    monkeypatch.setattr(rl, "SQLITE_PATH", tmp_db)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("fresh_ledger")
def test_micro_passes_for_clap_scaffold(tmp_path):
    """The iter-1 scaffold (clap wording, rc=1) must pass micro at ≥85%."""
    exe = _write_script(tmp_path, "clap_main.py", _CLAP_TEMPLATE)
    results = gate.run_micro(exe)
    summary = gate.micro_summary(results)
    assert summary["pass_rate"] >= 0.85, (
        f"clap scaffold should pass ≥85%: got {summary['pass_rate'] * 100:.0f}% — failures: {summary['failures']}"
    )


@pytest.mark.usefixtures("fresh_ledger")
def test_micro_fails_for_broken_scaffold(tmp_path):
    """The pre-iter1 scaffold (old wording, rc=2) must fail micro on the
    rc_2_unknown_option family cases."""
    exe = _write_script(tmp_path, "broken_main.py", _BROKEN_TEMPLATE)
    results = gate.run_micro(exe)
    summary = gate.micro_summary(results)
    rc_fam = summary["by_family"].get("rc_2_unknown_option", {})
    # At least one rc_2_unknown_option case must fail (gate would otherwise let
    # the regression through to a 6-hour full eval).
    assert rc_fam.get("failed", 0) >= 1, (
        f"broken scaffold should fail at least one rc_2_unknown_option case: {rc_fam}"
    )


@pytest.mark.usefixtures("fresh_ledger")
def test_micro_failure_halts_escalation(tmp_path):
    """If micro fails, run_gate must return verdict='halted_at_micro' and NOT
    attempt to run shard/full — even when given a scaffold_root."""
    exe = _write_script(tmp_path, "broken_main.py", _BROKEN_TEMPLATE)
    report = gate.run_gate(
        gate="full",  # request the full chain
        executable=exe,
        scaffold_root=tmp_path,
        shard_tools=["fake__tool.deadbeef"],
        run_id="halt_test",
    )
    assert report["verdict"] == "halted_at_micro"
    assert "shard" not in report
    assert "full" not in report
    assert report["micro"]["pass_rate"] < gate.GATE_MICRO_PASS_RATE


@pytest.mark.usefixtures("fresh_ledger")
def test_micro_writes_ledger_event(tmp_path):
    """Each gate phase writes one ledger event so the cockpit shows progress."""
    exe = _write_script(tmp_path, "clap_main.py", _CLAP_TEMPLATE)
    gate.run_gate(gate="micro", executable=exe, run_id="ledger_test")
    # Read back via the ledger query path
    from run_ledger import SQLITE_PATH, _open_db

    conn = _open_db(SQLITE_PATH)
    try:
        rows = conn.execute(
            "SELECT phase, status FROM events WHERE run_id = ?",
            ("ledger_test",),
        ).fetchall()
    finally:
        conn.close()
    phases = [(p, s) for p, s in rows]
    assert ("gate_micro", "passed") in phases, f"expected gate_micro passed event in {phases}"


def test_micro_cases_cover_universal_patterns():
    """Every Tier-1 universal CLI pattern must have at least one micro case."""
    families_covered = {c.family for c in gate.MICRO_CASES}
    expected = {
        "rc_2_unknown_option",
        "help",
        "version",
        "empty_input",
        "stdin_handling",
        "no_color_negation",
        "file_not_found",
        "output_flag",
        "multiple_inputs",
    }
    missing = expected - families_covered
    assert not missing, f"micro coverage missing families: {missing}"


def test_micro_count_matches_doc():
    """The module docstring promises 20 cases — keep them in sync."""
    assert len(gate.MICRO_CASES) == 20, (
        f"expected 20 micro cases (doc says 20), got {len(gate.MICRO_CASES)}"
    )
