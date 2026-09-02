"""Does the download manifest describe what the files actually are?

WHY THIS EXISTS
---------------
Found 2026-07-29 by the first real Linux release build. `_artifact_type` mapped ANY `.exe`
to "windows_nsis_setup", and `discover_installers` walks the bundle tree with `rglob("*")`.
The Linux bundle contains an unpacked AppDir into which Tauri copies declared resources --
including Microsoft's VC++ redistributable. So the published manifest carried:

    file_name:     vc_redist.x64.exe
    artifact_type: windows_nsis_setup
    source_path:   .../appimage/Determinex.AppDir/usr/lib/Determinex/resources/vc_redist.x64.exe

listed twice. Two consequences, both bad:

  * anyone fetching the advertised Windows installer would have downloaded vc_redist;
  * the release gates count artifact TYPES from this manifest, so a bundle with no Windows
    installer in it at all could satisfy a Windows artifact check.

Extension alone cannot decide this, because the file that broke it IS a .exe. These tests
pin the two things that must both hold: payload inside a package is not an artifact, and a
Windows installer has to look like Tauri's NSIS output rather than merely end in .exe.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
for p in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

from scripts.release.package_download_bundle import (  # noqa: E402
    _artifact_type,
    discover_installers,
)


def test_the_vc_redist_inside_an_appimage_is_not_a_windows_installer():
    """THE regression, at the exact path the real build produced."""
    payload = Path(
        "/tmp/determinex-linux-cargo-target/release/bundle/appimage/Determinex.AppDir/"
        "usr/lib/Determinex/resources/vc_redist.x64.exe"
    )
    assert _artifact_type(payload) is None


@pytest.mark.parametrize(
    "rel",
    [
        "appimage/Determinex.AppDir/usr/lib/Determinex/resources/vc_redist.x64.exe",
        "appimage/Determinex.AppDir/usr/bin/determinex",
        "nsis/resources/some-helper.exe",
    ],
)
def test_package_payload_is_never_an_artifact(rel):
    assert _artifact_type(Path("bundle") / rel) is None


@pytest.mark.parametrize(
    "name,expected",
    [
        ("Determinex_0.1.0_x64-setup.exe", "windows_nsis_setup"),
        ("Determinex_0.1.0_x64_en-US.msi", "windows_msi"),
        ("Determinex_0.1.0_amd64.AppImage", "linux_appimage"),
        ("Determinex_0.1.0_amd64.deb", "linux_deb"),
        ("Determinex-0.1.0-1.x86_64.rpm", "linux_rpm"),
    ],
)
def test_the_real_artifacts_still_classify(name, expected):
    """The fix must not cost us the genuine artifacts -- all five names below are what the
    2026-07-29 builds actually emitted."""
    assert _artifact_type(Path("bundle") / name) == expected


def test_a_stray_exe_is_not_promoted_to_the_windows_installer():
    """An .exe that is not Tauri's NSIS output has no business being published as one."""
    assert _artifact_type(Path("bundle/uninstall.exe")) is None
    assert _artifact_type(Path("bundle/vc_redist.x64.exe")) is None


def test_discovery_skips_payload_but_keeps_packages(tmp_path):
    """End to end over a bundle tree shaped like the real one: the AppImage, deb and rpm
    are found, and the redistributable buried in the AppDir is not."""
    bundle = tmp_path / "bundle"
    appdir = bundle / "appimage" / "Determinex.AppDir" / "usr" / "lib" / "Determinex" / "resources"
    appdir.mkdir(parents=True)
    (appdir / "vc_redist.x64.exe").write_bytes(b"not our installer")

    (bundle / "appimage").mkdir(parents=True, exist_ok=True)
    (bundle / "appimage" / "Determinex_0.1.0_amd64.AppImage").write_bytes(b"appimage")
    (bundle / "deb").mkdir(parents=True, exist_ok=True)
    (bundle / "deb" / "Determinex_0.1.0_amd64.deb").write_bytes(b"deb")
    (bundle / "rpm").mkdir(parents=True, exist_ok=True)
    (bundle / "rpm" / "Determinex-0.1.0-1.x86_64.rpm").write_bytes(b"rpm")

    found = discover_installers(bundle)
    types = sorted(a.artifact_type for a in found)
    assert types == ["linux_appimage", "linux_deb", "linux_rpm"]
    assert all("vc_redist" not in a.file_name for a in found), (
        "the redistributable was published as a release artifact"
    )


@pytest.mark.parametrize(
    "name",
    [
        "Determinex_0.1.0_x64_en-US.msi.zip",
        "Determinex_0.1.0_x64_en-US.msi.sig",
        "Determinex_0.1.0_x64-setup.exe.zip",
        "Determinex_0.1.0_x64-setup.exe.sig",
    ],
)
def test_updater_artifacts_are_not_advertised_as_downloads(name):
    """Enabling bundle.createUpdaterArtifacts (2026-07-29) put update archives and detached
    signatures in the SAME bundler output directory this function scans recursively. The
    fallthrough classifies anything unrecognised as a generic "installer", so a 96-byte `.sig`
    and an update `.zip` would both have been published in the download manifest as things to
    install -- the vc_redist bug in this same function, reopened by a config change nowhere near
    it. These are update payloads for the updater and the GitHub release, not downloads.
    """
    assert _artifact_type(Path("bundle") / name) is None


def test_a_real_zip_download_is_still_recognised():
    """The exclusion must be narrow. Only an archive OF an installer is an update payload; a
    plain zip is not, and blanket-rejecting `.zip` would silently drop a legitimate artifact."""
    assert _artifact_type(Path("bundle/determinex-0.1.0-portable.zip")) is not None


def test_a_tree_with_only_payload_is_an_error_not_an_empty_success(tmp_path):
    """If everything got skipped, the bundle has no artifacts. Returning an empty list
    would let a manifest be written that advertises nothing while reading as a success."""
    bundle = tmp_path / "bundle"
    appdir = bundle / "appimage" / "Determinex.AppDir" / "usr" / "lib" / "app" / "resources"
    appdir.mkdir(parents=True)
    (appdir / "vc_redist.x64.exe").write_bytes(b"payload only")
    with pytest.raises(FileNotFoundError):
        discover_installers(bundle)
