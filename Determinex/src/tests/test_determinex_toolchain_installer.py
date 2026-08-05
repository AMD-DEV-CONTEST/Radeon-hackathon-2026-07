"""tests/test_determinex_toolchain_installer.py

Ryan: "toolchains or toolchain finds should be added for the user if the
user asks for it, like an enablization, but we are also shipping what it
needs to work by itself without them yes?" -- this module is the
user-triggered "enablization" half (determinex_oracle.py's
available()/OracleUnavailable is the other half: it never lies about what's
missing, but it never installs anything on its own).

The one hard rule under test: a successful installer EXIT CODE must never
be reported as `succeeded=True` on its own -- only a re-checked real
Oracle.available() probe counts, since a PATH change frequently doesn't
take effect in the current process even when the underlying install
genuinely worked (confirmed live this session: FreeBASIC installed fine via
winget but `where fbc` in the SAME shell still failed until PATH refreshed).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import determinex_toolchain_installer as installer_mod


def _cp(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def test_already_available_language_is_a_no_op(monkeypatch):
    class _FakeOracle:
        def available(self):
            return True

    monkeypatch.setattr(installer_mod, "get_oracle", lambda lang: _FakeOracle())

    result = installer_mod.install_toolchain("rust")

    assert result.already_available is True
    assert result.attempted is False
    assert result.succeeded is True


def test_winget_install_re_checks_availability_not_just_exit_code(monkeypatch):
    """The classic false-positive: winget exits 0, but the toolchain still
    isn't resolvable in THIS process because PATH hasn't refreshed -- must
    report succeeded=False, not trust the installer's exit code."""
    calls = {"available_calls": 0}

    class _FakeOracle:
        def available(self):
            calls["available_calls"] += 1
            return False  # still false even "after" install, in this process

    monkeypatch.setattr(installer_mod, "get_oracle", lambda lang: _FakeOracle())
    monkeypatch.setattr(
        installer_mod, "platform", type("P", (), {"system": staticmethod(lambda: "Windows")})
    )
    with patch.object(
        installer_mod.subprocess, "run", return_value=_cp(0, stdout="Successfully installed\n")
    ):
        result = installer_mod.install_toolchain("basic")

    assert result.attempted is True
    assert result.installer == "winget"
    assert result.succeeded is False
    assert any("new terminal" in n.lower() for n in result.notes)


def test_winget_install_succeeds_when_oracle_confirms_available_after(monkeypatch):
    class _FakeOracle:
        def __init__(self):
            self.calls = 0

        def available(self):
            self.calls += 1
            return self.calls > 1  # unavailable before, available after "install"

    fake = _FakeOracle()
    monkeypatch.setattr(installer_mod, "get_oracle", lambda lang: fake)
    monkeypatch.setattr(
        installer_mod, "platform", type("P", (), {"system": staticmethod(lambda: "Windows")})
    )
    with patch.object(
        installer_mod.subprocess, "run", return_value=_cp(0, stdout="Successfully installed\n")
    ):
        result = installer_mod.install_toolchain("basic")

    assert result.succeeded is True
    assert result.notes == []


def test_choco_install_needing_admin_reports_it_explicitly_not_a_silent_fail(monkeypatch):
    """Live 2026-07-22: `choco install gnucobol -y` failed on a non-elevated
    shell with 'Access to the path ...lib-bad... is denied.' This must
    surface as an explained needs-admin note, never an unexplained fail.

    cobol now resolves via _PORTABLE_ZIP first (added 2026-07-25, no admin
    needed at all) -- cleared here so this test still exercises choco as
    the fallback path in isolation, in case _PORTABLE_ZIP's mapping for a
    language is ever removed and it needs to fall back to choco again."""

    class _FakeOracle:
        def available(self):
            return False

    monkeypatch.setattr(installer_mod, "get_oracle", lambda lang: _FakeOracle())
    monkeypatch.setattr(
        installer_mod, "platform", type("P", (), {"system": staticmethod(lambda: "Windows")})
    )
    monkeypatch.setattr(
        installer_mod,
        "_PORTABLE_ZIP",
        {k: v for k, v in installer_mod._PORTABLE_ZIP.items() if k != "cobol"},
    )
    denied = "Access to the path 'C:\\ProgramData\\chocolatey\\lib-bad' is denied.\n"
    with patch.object(installer_mod.subprocess, "run", return_value=_cp(1, stderr=denied)):
        result = installer_mod.install_toolchain("cobol")

    assert result.installer == "choco"
    assert result.succeeded is False
    assert any("elevated" in n.lower() or "administrator" in n.lower() for n in result.notes)


def test_no_installer_mapping_reports_the_manual_install_hint(monkeypatch):
    class _FakeOracle:
        install_hint = "some manual install hint"

        def available(self):
            return False

    monkeypatch.setattr(installer_mod, "get_oracle", lambda lang: _FakeOracle())
    monkeypatch.setattr(
        installer_mod, "platform", type("P", (), {"system": staticmethod(lambda: "Windows")})
    )

    result = installer_mod.install_toolchain("swift-but-misspelled-so-no-mapping")

    assert result.attempted is False
    assert "some manual install hint" in result.notes[0]


def test_non_windows_platform_reports_manual_install_hint(monkeypatch):
    class _FakeOracle:
        install_hint = "apt-get install gcc"

        def available(self):
            return False

    monkeypatch.setattr(installer_mod, "get_oracle", lambda lang: _FakeOracle())
    monkeypatch.setattr(
        installer_mod, "platform", type("P", (), {"system": staticmethod(lambda: "Linux")})
    )

    result = installer_mod.install_toolchain("c")

    assert result.attempted is False
    assert "apt-get install gcc" in result.notes[0]


def test_portable_zip_installs_and_persists_env_vars_not_just_path(monkeypatch, tmp_path):
    """Live 2026-07-25: extracting GnuCOBOL's portable MinGW build and putting
    bin/ on PATH was NOT enough -- cobc failed with a config-dir error until
    COB_CONFIG_DIR (+ siblings) were persisted too. The install path must set
    both, not just PATH."""
    install_dir = tmp_path / "gnucobol"
    (install_dir / "bin").mkdir(parents=True)
    (install_dir / "bin" / "cobc.exe").write_text("fake")
    (install_dir / "config").mkdir()
    (install_dir / "copy").mkdir()
    # extras/locale deliberately NOT created -- must be skipped, not error

    class _FakeOracle:
        def __init__(self):
            self.calls = 0

        def available(self):
            self.calls += 1
            return self.calls > 1

    fake = _FakeOracle()
    monkeypatch.setattr(installer_mod, "get_oracle", lambda lang: fake)
    monkeypatch.setattr(
        installer_mod, "platform", type("P", (), {"system": staticmethod(lambda: "Windows")})
    )
    monkeypatch.setitem(
        installer_mod._PORTABLE_ZIP,
        "cobol",
        {
            "url": "https://example.invalid/gnucobol.7z",
            "install_dir": str(install_dir),
            "probe_relpath": "bin/cobc.exe",
            "env_subdirs": {
                "COB_CONFIG_DIR": "config",
                "COB_COPY_DIR": "copy",
                "COB_LIBRARY_PATH": "extras",
                "LOCALEDIR": "locale",
            },
        },
    )
    _real_exists = Path.exists
    monkeypatch.setattr(
        installer_mod.Path,
        "exists",
        lambda self: True if "7z.exe" in str(self) else _real_exists(self),
    )
    monkeypatch.setattr(installer_mod.urllib.request, "urlretrieve", lambda url, path: None)
    monkeypatch.setattr(
        installer_mod.subprocess, "run", lambda *a, **k: _cp(0, stdout="Everything is Ok\n")
    )
    persisted = {}
    monkeypatch.setattr(
        installer_mod,
        "_persist_user_env_var",
        lambda name, value: persisted.__setitem__(name, value),
    )
    appended_paths = []
    monkeypatch.setattr(installer_mod, "_append_user_path", appended_paths.append)

    result = installer_mod.install_toolchain("cobol")

    assert result.installer == "portable-zip"
    assert result.succeeded is True
    assert appended_paths == [str(install_dir / "bin")]
    assert persisted["COB_CONFIG_DIR"] == str(install_dir / "config")
    assert persisted["COB_COPY_DIR"] == str(install_dir / "copy")
    assert "COB_LIBRARY_PATH" not in persisted  # extras/ doesn't exist -- must not be invented
    assert "LOCALEDIR" not in persisted


def test_append_user_path_is_a_noop_when_dir_already_present(monkeypatch):
    calls = []
    monkeypatch.setattr(
        installer_mod, "_persist_user_env_var", lambda name, value: calls.append((name, value))
    )

    class _FakeKey:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    fake_winreg = type(
        "W",
        (),
        {
            "HKEY_CURRENT_USER": None,
            "OpenKey": staticmethod(lambda *a, **k: _FakeKey()),
            "QueryValueEx": staticmethod(lambda key, name: (r"C:\already\here;C:\Other", 1)),
        },
    )
    monkeypatch.setitem(sys.modules, "winreg", fake_winreg)

    installer_mod._append_user_path(r"C:\Already\Here")

    assert calls == []


def test_tauri_installs_both_rust_and_node_ids(monkeypatch):
    class _FakeOracle:
        def available(self):
            return False

    monkeypatch.setattr(installer_mod, "get_oracle", lambda lang: _FakeOracle())
    monkeypatch.setattr(
        installer_mod, "platform", type("P", (), {"system": staticmethod(lambda: "Windows")})
    )
    captured = []

    def _fake_run(cmd, capture_output=True, text=True, timeout=600):
        captured.append(cmd)
        return _cp(0, stdout="ok\n")

    with patch.object(installer_mod.subprocess, "run", side_effect=_fake_run):
        installer_mod.install_toolchain("tauri")

    ids_installed = {c[c.index("--id") + 1] for c in captured}
    assert ids_installed == {"Rustlang.Rustup", "OpenJS.NodeJS.LTS"}
