"""tests/test_determinex_cli.py — DETERMINEX_CLI_LOCK_001

Verifies that the unified ``determinex`` entry point:
  - imports without side effects
  - dispatches all subcommands correctly
  - prints version and help without crashing
  - config subcommands surface settings correctly
  - evidence validate reads the evidence index without mutations
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT, _ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


@pytest.fixture(autouse=True)
def _reset_argv():
    original = sys.argv[:]
    yield
    sys.argv = original


# ---------------------------------------------------------------------------
# Import safety
# ---------------------------------------------------------------------------


def test_import_no_side_effects():
    import determinex_cli as cli

    assert callable(cli.main)
    assert cli.__version__ == "1.0.0"


# ---------------------------------------------------------------------------
# --version
# ---------------------------------------------------------------------------


def test_version_flag(capsys):
    import determinex_cli as cli

    sys.argv = ["determinex", "--version"]
    rc = cli.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert "1.0.0" in out


# ---------------------------------------------------------------------------
# --help / no args
# ---------------------------------------------------------------------------


def test_help_flag(capsys):
    import determinex_cli as cli

    sys.argv = ["determinex"]
    rc = cli.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert "doctor" in out
    assert "status" in out
    assert "config" in out


def test_explicit_help_flag(capsys):
    import determinex_cli as cli

    sys.argv = ["determinex", "--help"]
    rc = cli.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert "determinex" in out.lower()


# ---------------------------------------------------------------------------
# Unknown command
# ---------------------------------------------------------------------------


def test_unknown_command(capsys):
    import determinex_cli as cli

    sys.argv = ["determinex", "nonexistent-command"]
    rc = cli.main()
    out = capsys.readouterr().out
    assert rc == 1
    assert "Unknown command" in out


# ---------------------------------------------------------------------------
# config show
# ---------------------------------------------------------------------------


def test_config_show(capsys):
    import determinex_cli as cli

    sys.argv = ["determinex", "config", "show"]
    rc = cli.main()
    out = capsys.readouterr().out
    assert "repo_root" in out
    assert "safety_mode" in out
    assert "builder_model" in out


def test_config_show_masks_api_keys(monkeypatch, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-real-secret-key")
    import determinex_cli as cli

    # Reset settings singleton so new env is picked up
    from determinex_settings import reset_settings

    reset_settings()
    sys.argv = ["determinex", "config", "show"]
    rc = cli.main()
    out = capsys.readouterr().out
    assert "sk-real-secret-key" not in out
    assert "***" in out
    reset_settings()


# ---------------------------------------------------------------------------
# config doctor
# ---------------------------------------------------------------------------


def test_config_doctor_clean(capsys, monkeypatch):
    monkeypatch.delenv("DETERMINEX_ONLINE_DISCOVERY", raising=False)
    monkeypatch.delenv("DETERMINEX_ALLOW_CLOUD_FALLBACK", raising=False)
    monkeypatch.delenv("DETERMINEX_ALLOW_UNSANDBOXED", raising=False)
    import determinex_cli as cli

    sys.argv = ["determinex", "config", "doctor"]
    rc = cli.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert "closed" in out.lower() or "OK" in out


def test_config_doctor_flags_open_violation(monkeypatch, capsys):
    monkeypatch.setenv("DETERMINEX_ONLINE_DISCOVERY", "1")
    import determinex_cli as cli

    sys.argv = ["determinex", "config", "doctor"]
    rc = cli.main()
    out = capsys.readouterr().out
    assert rc == 1
    assert "ONLINE_DISCOVERY" in out


# ---------------------------------------------------------------------------
# evidence validate
# ---------------------------------------------------------------------------


def test_evidence_validate_passes(capsys):
    import determinex_cli as cli

    sys.argv = ["determinex", "evidence", "validate"]
    rc = cli.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert "entries" in out
    assert "present" in out or "0 missing" in out


def test_evidence_validate_is_read_only(capsys, tmp_path, monkeypatch):
    """validate must not write or modify any file."""

    import determinex_cli as cli

    # Count files before
    evidence_dir = _ROOT / "assurance" / "evidence"
    before = set(str(p) for p in evidence_dir.rglob("*") if p.is_file())

    sys.argv = ["determinex", "evidence", "validate"]
    cli.main()

    after = set(str(p) for p in evidence_dir.rglob("*") if p.is_file())
    assert before == after, f"validate created/deleted files: {before ^ after}"


# ---------------------------------------------------------------------------
# config unknown subcommand
# ---------------------------------------------------------------------------


def test_config_unknown_subcommand(capsys):
    import determinex_cli as cli

    sys.argv = ["determinex", "config", "badcmd"]
    rc = cli.main()
    out = capsys.readouterr().out
    assert rc == 1
    assert "Unknown config subcommand" in out


def test_evidence_unknown_subcommand(capsys):
    import determinex_cli as cli

    sys.argv = ["determinex", "evidence", "badcmd"]
    rc = cli.main()
    out = capsys.readouterr().out
    assert rc == 1
    assert "Unknown evidence subcommand" in out


# ---------------------------------------------------------------------------
# Help and dispatch must agree
# ---------------------------------------------------------------------------
#
# Found 2026-07-31 while wiring `build`. The set of commands was written down TWICE -- once as
# click registrations plus the _USAGE text, and again as a literal tuple in main()'s dispatch
# guard, `elif cmd not in ("doctor", "status")`. Registering `build` and listing it in the help
# left the guard untouched, so the CLI advertised `build` in its own --help and then answered
# "Unknown command: 'build'". The guard now derives its list from the click group; these tests
# pin the agreement rather than the current contents, so the next command added is covered too.


def test_every_advertised_command_is_dispatchable():
    """Anything named in the help must not be rejected as unknown."""
    import determinex_cli as cli

    # Only the "Commands:" block. Scoping matters: an earlier version scanned every indented
    # line and picked up "determinex" from the Example, which is not a command.
    advertised: set[str] = set()
    in_commands = False
    for line in cli._USAGE.splitlines():
        if line.rstrip() == "Commands:":
            in_commands = True
            continue
        if in_commands:
            if not line.strip():
                break
            if line.startswith("  "):
                advertised.add(line.split()[0])
    assert advertised, "could not parse the Commands block out of _USAGE"

    known = set(cli._TOP_LEVEL_COMMANDS) | set(cli._GROUPS_WITH_OWN_SUBCOMMAND_CHECK)
    unreachable = {a for a in advertised if a not in known}
    assert not unreachable, (
        f"the help advertises {sorted(unreachable)} but dispatch would call them unknown"
    )


def test_the_dispatch_list_is_derived_from_the_click_group():
    """A hand-maintained second copy is what caused the drift."""
    import determinex_cli as cli

    expected = {
        name for name in cli._cli.commands if name not in cli._GROUPS_WITH_OWN_SUBCOMMAND_CHECK
    }
    assert set(cli._TOP_LEVEL_COMMANDS) == expected


def test_build_is_registered_reachable_and_named_in_the_help(capsys):
    """The engine entry point. Everything else this CLI exposes is diagnostic, so before this
    an installed Determinex had no way to reach verified search at all."""
    import determinex_cli as cli

    assert "build" in cli._cli.commands
    assert "build" in cli._TOP_LEVEL_COMMANDS
    sys.argv = ["determinex"]
    assert cli.main() == 0
    assert "build" in capsys.readouterr().out


def test_build_dispatches_to_the_engine_module_without_running_a_model(monkeypatch):
    """Dispatch is what regressed; the engine has its own tests. Stub it and assert the wiring,
    including that argv is forwarded so the module's own parser sees the flags."""
    import determinex_cli as cli

    seen: dict[str, object] = {}

    class _Stub:
        @staticmethod
        def main() -> int:
            seen["argv"] = sys.argv[:]
            return 0

    monkeypatch.setitem(sys.modules, "determinex_build_from_idea", _Stub)
    rc = cli._cmd_build(["--idea", "x.md", "--k", "3"])
    assert rc == 0
    assert seen["argv"] == ["determinex build", "--idea", "x.md", "--k", "3"]


def test_an_unknown_command_is_still_rejected_after_deriving_the_list(capsys):
    """Deriving the allow-list must not turn it into "accept anything"."""
    import determinex_cli as cli

    sys.argv = ["determinex", "frobnicate"]
    rc = cli.main()
    out = capsys.readouterr().out
    assert rc == 1
    assert "Unknown command: 'frobnicate'" in out
