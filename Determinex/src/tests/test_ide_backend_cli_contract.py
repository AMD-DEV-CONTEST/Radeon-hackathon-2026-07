"""The editor-facing CLI's exit-code contract.

`scripts/ide/determinex_backend_cli.py` is what every non-Tauri frontend shells to -- the
VS Code extension, a web app, a shell script. Its docstring promises a stable,
transport-agnostic entry point. Two things must hold for a caller to be able to trust it:

  1. A command that does not exist must FAIL. On 2026-08-02 it returned exit 0 with a
     well-formed JSON envelope whose payload said the command was unknown. Sweeping all 31
     names in ide/backend_command_surface.py through this CLI produced 24 such responses --
     every one a success as far as `if subprocess.run(...).returncode == 0` is concerned.

  2. A governance REFUSAL must still succeed. NOT_OPTED_IN, NO_MODEL and friends are real,
     correct answers from a system designed to refuse; turning them into process failures
     would make callers treat a working safety gate as a crash.

The distinction is caller-bug versus system-answer, and it is the whole contract.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_CLI = _ROOT / "scripts" / "ide" / "determinex_backend_cli.py"


def _run(*argv: str) -> tuple[int, dict]:
    p = subprocess.run(
        [sys.executable, str(_CLI), *argv],
        capture_output=True, text=True, timeout=600, cwd=str(_ROOT),
    )
    try:
        return p.returncode, json.loads((p.stdout or "").strip())
    except Exception:  # pragma: no cover - only on a genuinely broken CLI
        pytest.fail(f"CLI produced non-JSON output (rc={p.returncode}):\n{p.stdout}\n{p.stderr}")


def test_an_unknown_command_exits_non_zero():
    """THE BUG. Exit 0 for a command that does not exist means a shell caller cannot detect
    the difference between 'done' and 'that is not a thing'."""
    rc, doc = _run("definitely_not_a_command")
    assert rc != 0, "an unknown command must not report success"
    assert doc["status"] == "TAURI_COMMAND_BLOCKED_UNKNOWN"


def test_the_error_names_the_commands_that_do_exist():
    """A caller that guessed wrong needs the list, not just a denial -- especially because
    the surface implements names this CLI does not bridge."""
    _, doc = _run("definitely_not_a_command")
    joined = " ".join(doc.get("notes", ()))
    assert "get_governance_status" in joined, "the note must enumerate the real commands"
    assert "backend_command_surface" in joined, (
        "and must point at where the unbridged commands live, since that mismatch is the "
        "reason a caller lands here"
    )


def test_a_real_command_succeeds():
    rc, doc = _run("get_governance_status")
    assert rc == 0
    assert doc["status"] == "TAURI_COMMAND_OK"
    assert doc["payload"], "a successful command must carry a payload, not an empty envelope"


def test_a_governance_refusal_is_not_a_process_failure():
    """Negative control for the fix above. `build_idea` without opt-in is BLOCKED by design.
    If the exit-code change had keyed on 'status != OK' instead of on 'command exists',
    every correct refusal in the system would look like a crash to its caller."""
    rc, doc = _run("build_idea", "--json", json.dumps({"idea_text": ""}))
    assert doc["status"].startswith("TAURI_COMMAND_BLOCKED"), doc["status"]
    assert rc == 0, "a designed refusal is an answer, not a failure"


def test_the_advertised_command_list_is_what_the_cli_accepts():
    """`commands` is how a frontend discovers the surface. If it lists something the CLI
    then rejects, discovery is worse than useless."""
    rc, doc = _run("commands")
    assert rc == 0
    listed = doc["commands"]
    assert listed, "the CLI must advertise its commands"
    _, err = _run("definitely_not_a_command")
    advertised_in_error = " ".join(err.get("notes", ()))
    for name in listed:
        assert name in advertised_in_error, (
            f"{name!r} is advertised by `commands` but missing from the unknown-command "
            f"help text -- the two lists must come from the same source"
        )
