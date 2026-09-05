"""Fail-closed security tests for the read-only tool layer (2026-08-04).

Two P1 fixes are locked down here:

1. shell_readonly used shell=True + a *blocklist* regex. Anything not listed
   (``echo $(cat /etc/passwd)``, ``cat /etc/passwd | grep root``, ``ls; rm -rf /``,
   backticks, $IFS, absolute paths) ran arbitrary shell. The gate is now
   fail-closed: allowlist + shell-metacharacter ban + git/find subcommand
   restrictions + workspace-path escape ban.

2. grep walked the workspace directly, bypassing PermissionGate.check_path --
   so BLOCKED_PATH_PATTERNS (.env / .ssh / id_rsa / credentials) were silently
   readable through grep, and a symlink escaping the workspace was followed.
   grep now resolves + gates every candidate file like read_file does.
"""
from __future__ import annotations

import os

import pytest

from screwshell.safety.permissions import AuditLog, PermissionGate
from screwshell.tools.toolkit import Toolkit


@pytest.fixture
def tkit(tmp_path):
    (tmp_path / "notes.txt").write_text("hello world\n", encoding="utf-8")
    (tmp_path / "data.txt").write_text("count me\n", encoding="utf-8")
    audit = AuditLog(str(tmp_path / "audit.jsonl"))
    gate = PermissionGate(str(tmp_path),
                          allowed_tools=["grep", "shell_readonly"],
                          audit=audit)
    return Toolkit(gate=gate, workspace=str(tmp_path))


def _shell(tkit, cmd: str):
    return tkit.run("shell_readonly", cmd=cmd)


# ---------------------------------------------------------------- allowlist
def test_shell_readonly_blocks_shell_metacharacters(tkit):
    # command chaining / substitution / pipes / redirection / newlines
    for cmd in [
        "ls; rm -rf /",
        "ls && whoami",
        "echo $(cat /etc/passwd)",
        "echo `whoami`",
        "cat /etc/passwd | grep root",
        "ls > /tmp/pwn",
        "ls\nwhoami",
        "echo $HOME",
    ]:
        r = _shell(tkit, cmd)
        assert r.ok is False, cmd
        assert "DENIED" in r.digest, (cmd, r.digest)


def test_shell_readonly_blocks_unknown_commands(tkit):
    r = _shell(tkit, "sudo whoami")
    assert r.ok is False and "DENIED" in r.digest
    r = _shell(tkit, "python3 -c 'print(1)'")
    assert r.ok is False and "DENIED" in r.digest


def test_shell_readonly_blocks_absolute_and_traversal_paths(tkit):
    for cmd in ["cat /etc/passwd", "wc -l /etc/passwd",
                "cat ~/.ssh/id_rsa", "head ../outside.txt",
                "tail /var/log/syslog"]:
        r = _shell(tkit, cmd)
        assert r.ok is False, cmd
        assert "DENIED" in r.digest, (cmd, r.digest)


def test_shell_readonly_blocks_mutating_git_and_find(tkit):
    r = _shell(tkit, "git push origin main")
    assert r.ok is False and "DENIED" in r.digest
    r = _shell(tkit, "git commit -m x")
    assert r.ok is False and "DENIED" in r.digest
    r = _shell(tkit, "find . -delete")
    assert r.ok is False and "DENIED" in r.digest


def test_shell_readonly_allows_benign_readonly_commands(tkit):
    r = _shell(tkit, "wc -l notes.txt")
    assert r.ok is True, r.digest
    r = _shell(tkit, "ls -la")
    assert r.ok is True, r.digest
    # git read-only subcommand is allowed (runs inside the workspace)
    r = _shell(tkit, "git status --short")
    assert "DENIED" not in r.digest


@pytest.mark.skipif(os.name == "nt",
                    reason="shell globbing is a POSIX shell feature; "
                           "Windows subprocess shell=True runs cmd.exe")
def test_shell_readonly_glob_still_works(tkit):
    # globbing still works (that is why the gate bans metacharacters instead
    # of switching to shell=False argv)
    r = _shell(tkit, "du -sh *")
    assert r.ok is True, r.digest


# ------------------------------------------------------------------- grep
def test_grep_does_not_read_blocked_secret_files(tmp_path):
    (tmp_path / ".env").write_text("SECRET_KEY=super-secret-1\n",
                                   encoding="utf-8")
    (tmp_path / "notes.txt").write_text("SECRET_KEY=super-secret-1\n",
                                        encoding="utf-8")
    # audit log lives OUTSIDE the workspace: the pattern string would
    # otherwise be searchable inside audit.jsonl and pollute the assertion
    audit = AuditLog(str(tmp_path.parent / "audit.jsonl"))
    gate = PermissionGate(str(tmp_path), allowed_tools=["grep"], audit=audit)
    tkit = Toolkit(gate=gate, workspace=str(tmp_path))

    r = tkit.run("grep", pattern="super-secret-1")
    assert r.ok is True
    # only notes.txt may surface; the .env hit must be suppressed
    assert "super-secret-1" in r.digest
    assert ".env" not in r.digest, r.digest


def test_grep_does_not_follow_symlinks_out_of_workspace(tmp_path):
    outside = tmp_path.parent / "outside-secret.txt"
    outside.write_text("ESCAPED-CONTENT-42\n", encoding="utf-8")
    try:
        (tmp_path / "link.txt").symlink_to(outside)
    except (OSError, NotImplementedError) as e:
        pytest.skip(f"symlinks not permitted on this host: {e}")
    audit = AuditLog(str(tmp_path.parent / "audit.jsonl"))
    gate = PermissionGate(str(tmp_path), allowed_tools=["grep"], audit=audit)
    tkit = Toolkit(gate=gate, workspace=str(tmp_path))

    r = tkit.run("grep", pattern="ESCAPED-CONTENT-42")
    assert r.ok is True
    assert "ESCAPED-CONTENT-42" not in r.digest, \
        "symlink escaping the workspace must not be searchable"
