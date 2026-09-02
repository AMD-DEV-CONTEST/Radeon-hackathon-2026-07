"""One answer to "which download manifest describes what we ship".

Every rebuild of the installers writes a new `assurance/evidence/determinex_download_bundle_*/`
directory, so that question has a moving answer and it must be asked in exactly one place.
It was not. On 2026-07-31 the same rule was written out by hand six times and skipped entirely
by two scripts that hardcoded `determinex_download_bundle_20260707` as a default, and the
consequence was a clean-host transcript reporting `installer_sha256_verified: true` for an
installer that appeared in no manifest that script could see. The transcript was internally
consistent and attested to the wrong artifact.

These tests fail if any of that comes back.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path

import pytest

from scripts.release import clean_host_kit, determinex_release_gates, full_release_closure

ROOT = Path(__file__).resolve().parent.parent
SMOKE = ROOT / "scripts" / "release" / "run_windows_clean_host_install_smoke.ps1"

# Release tooling that must not name a specific bundle date.
RELEASE_SOURCES = (
    "scripts/release/run_windows_clean_host_install_smoke.ps1",
    "scripts/release/windows_trust_packet.py",
    "scripts/release/clean_host_kit.py",
    "scripts/release/full_release_closure.py",
)

DATED_BUNDLE = re.compile(r"determinex_download_bundle_\d{8}")


def _manifest(tmp_path: Path, name: str, artifacts: list[dict]) -> Path:
    d = tmp_path / "assurance" / "evidence" / name
    d.mkdir(parents=True, exist_ok=True)
    p = d / "download_manifest.json"
    p.write_text(json.dumps({"artifacts": artifacts}), encoding="utf-8")
    return p


class TestCanonicalResolver:
    def test_picks_newest_by_mtime_not_by_name(self, tmp_path: Path) -> None:
        """The original bug: sorting by `p.name`, which is identical for every candidate."""
        older = _manifest(tmp_path, "determinex_download_bundle_20991231", [{"sha256": "old"}])
        time.sleep(0.01)
        newer = _manifest(tmp_path, "determinex_download_bundle_20000101", [{"sha256": "new"}])
        # Name ordering would prefer 20991231; mtime ordering must prefer 20000101.
        assert older.name == newer.name, (
            "precondition: names are identical, so name sort is a no-op"
        )
        assert determinex_release_gates.newest_download_manifest_path(tmp_path) == newer

    def test_returns_none_when_no_manifest_exists(self, tmp_path: Path) -> None:
        (tmp_path / "assurance" / "evidence").mkdir(parents=True)
        assert determinex_release_gates.newest_download_manifest_path(tmp_path) is None

    def test_skips_a_directory_with_no_manifest_inside(self, tmp_path: Path) -> None:
        (tmp_path / "assurance" / "evidence" / "determinex_download_bundle_20260101").mkdir(
            parents=True
        )
        real = _manifest(tmp_path, "determinex_download_bundle_20250101", [{"sha256": "x"}])
        assert determinex_release_gates.newest_download_manifest_path(tmp_path) == real


class TestEveryCallerAgrees:
    """A second implementation is a second answer. These must all be the same file."""

    def test_gates_closure_and_kit_resolve_identically(self, tmp_path: Path) -> None:
        _manifest(tmp_path, "determinex_download_bundle_20260101", [{"sha256": "a"}])
        time.sleep(0.01)
        expected = _manifest(tmp_path, "determinex_download_bundle_20260202", [{"sha256": "b"}])

        assert determinex_release_gates.newest_download_manifest_path(tmp_path) == expected
        assert full_release_closure._latest_download_manifest(tmp_path) == expected

        original = clean_host_kit.ROOT
        try:
            clean_host_kit.ROOT = tmp_path
            assert clean_host_kit._newest_manifest() == expected
        finally:
            clean_host_kit.ROOT = original

    def test_on_the_real_repo_all_callers_agree(self) -> None:
        """Not a tautology: these were three separate implementations that did disagree."""
        expected = determinex_release_gates.newest_download_manifest_path(ROOT)
        if expected is None:
            pytest.skip("no download bundle packaged in this checkout")
        assert full_release_closure._latest_download_manifest(ROOT) == expected
        assert clean_host_kit._newest_manifest() == expected


def _prose_lines(relpath: str, source: str) -> set[int]:
    """Line numbers that are commentary, not code.

    Needed because a guard that greps raw lines flags the very docstrings explaining the bug it
    guards against -- which is how this test first failed. The distinction that matters is not
    "is it a string" but "is it a DOCSTRING": an argparse `default=Path(".../bundle_20260707/...")`
    is also a string literal, and it is precisely the offender being hunted.
    """
    prose: set[int] = set()

    if relpath.endswith(".ps1"):
        in_block = False
        for lineno, line in enumerate(source.splitlines(), start=1):
            stripped = line.strip()
            if in_block:
                prose.add(lineno)
                if "#>" in stripped:
                    in_block = False
                continue
            if stripped.startswith("<#"):
                prose.add(lineno)
                in_block = "#>" not in stripped
                continue
            if stripped.startswith("#"):
                prose.add(lineno)
        return prose

    import ast

    for lineno, line in enumerate(source.splitlines(), start=1):
        if line.strip().startswith("#"):
            prose.add(lineno)

    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", [])
        if not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
            and first.end_lineno is not None
        ):
            prose.update(range(first.lineno, first.end_lineno + 1))
    return prose


class TestNoHardcodedBundleDate:
    @pytest.mark.parametrize("relpath", RELEASE_SOURCES)
    def test_release_tooling_does_not_name_a_bundle_date(self, relpath: str) -> None:
        source = (ROOT / relpath).read_text(encoding="utf-8")
        prose = _prose_lines(relpath, source)
        offenders = [
            f"{relpath}:{lineno}: {line.strip()}"
            for lineno, line in enumerate(source.splitlines(), start=1)
            if DATED_BUNDLE.search(line) and lineno not in prose
        ]
        assert not offenders, (
            "a dated download-bundle directory is hardcoded outside commentary; resolve it via "
            "determinex_release_gates.newest_download_manifest_path instead:\n  "
            + "\n  ".join(offenders)
        )

    def test_the_guard_would_catch_a_real_default(self, tmp_path: Path) -> None:
        """The exemption must not be so wide it exempts the bug.

        An argparse default IS a string literal. If _prose_lines exempted every string, this
        guard would pass on the exact line it exists to catch.
        """
        sample = tmp_path / "sample.py"
        sample.write_text(
            '"""A docstring mentioning determinex_download_bundle_20260707 harmlessly."""\n'
            "import argparse\n"
            "\n"
            "def main():\n"
            "    p = argparse.ArgumentParser()\n"
            '    p.add_argument("--manifest", default="assurance/evidence/'
            'determinex_download_bundle_20260707/download_manifest.json")\n',
            encoding="utf-8",
        )
        text = sample.read_text(encoding="utf-8")
        prose = _prose_lines("sample.py", text)
        hits = [
            lineno
            for lineno, line in enumerate(text.splitlines(), start=1)
            if DATED_BUNDLE.search(line) and lineno not in prose
        ]
        assert hits == [6], f"the argparse default must be flagged, the docstring must not: {hits}"


class TestPowerShellTwinMatchesPython:
    """The smoke runs on a clean host with no repo venv, so it needs its own resolver.

    Two implementations of one rule is a drift risk, so the rule is pinned here: both must
    return the same file for the same tree.
    """

    @pytest.mark.skipif(not SMOKE.is_file(), reason="smoke script absent")
    def test_powershell_resolver_picks_the_same_manifest(self, tmp_path: Path) -> None:
        powershell = _find_powershell()
        if powershell is None:
            pytest.skip("no PowerShell available")

        _manifest(tmp_path, "determinex_download_bundle_20991231", [{"sha256": "old"}])
        time.sleep(0.05)
        newer = _manifest(tmp_path, "determinex_download_bundle_20000101", [{"sha256": "new"}])

        # Dot-source the smoke script's own function rather than reimplementing it here: a copy
        # in the test would pass while the script stayed wrong.
        script = (
            "$ErrorActionPreference='Stop'\n"
            f"$src = Get-Content -Raw -LiteralPath '{SMOKE.as_posix()}'\n"
            "$start = $src.IndexOf('function Resolve-NewestManifest')\n"
            "if ($start -lt 0) { throw 'Resolve-NewestManifest not found in the smoke script' }\n"
            '$end = $src.IndexOf("`n}", $start)\n'
            "if ($end -lt 0) { throw 'could not delimit Resolve-NewestManifest' }\n"
            "Invoke-Expression $src.Substring($start, $end - $start + 3)\n"
            f"Resolve-NewestManifest -Root '{tmp_path.as_posix()}'\n"
        )
        result = subprocess.run(
            [powershell, "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, f"resolver failed: {result.stdout}\n{result.stderr}"
        got = Path(result.stdout.strip())
        assert got == newer, (
            "the PowerShell resolver in the smoke script disagrees with "
            f"newest_download_manifest_path: got {got}, expected {newer}"
        )
        assert determinex_release_gates.newest_download_manifest_path(tmp_path) == got


class TestSha256VerificationFailsClosed:
    """`installer_sha256_verified` must never be true because nothing was compared.

    That is what it did: the `-InstallerPath` branch set Artifact to $null, and the else-branch
    read `$installerSha256Verified = $true`. The release gate requires this field to be true, so
    the one field standing between the gate and a wrong artifact was hardcoded to satisfy it.
    """

    def test_the_unconditional_true_is_gone(self) -> None:
        source = SMOKE.read_text(encoding="utf-8")
        body = "\n".join(line for line in source.splitlines() if not line.strip().startswith("#"))
        assert "$installerSha256Verified = $true\n} else" not in body.replace("\r", "")
        # The else-branch must attempt a real lookup against the manifest.
        assert "$manifest.artifacts" in body, "the no-artifact branch must consult the manifest"

    def test_the_gate_still_requires_the_field(self) -> None:
        """If this stops being required, failing closed buys nothing."""
        gates = (ROOT / "scripts" / "release" / "determinex_release_gates.py").read_text(
            encoding="utf-8"
        )
        assert 'bundle.get("installer_sha256_verified") is not True' in gates

    def test_transcript_records_the_basis_for_the_boolean(self) -> None:
        source = SMOKE.read_text(encoding="utf-8")
        assert "installer_sha256_basis" in source, (
            "a reader must be able to tell a real hash match from 'nothing to compare against'"
        )


def _find_powershell() -> str | None:
    import shutil

    for name in ("pwsh", "powershell"):
        found = shutil.which(name)
        if found:
            return found
    return None
