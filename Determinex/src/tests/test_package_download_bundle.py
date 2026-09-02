from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

from scripts.release.package_download_bundle import build_download_bundle, discover_installers


def _write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def test_download_bundle_manifest_includes_installers_checksums_and_boundary(tmp_path: Path):
    root = tmp_path / "repo"
    tauri = root / "frontend/src-tauri/tauri.conf.json"
    tauri.parent.mkdir(parents=True)
    tauri.write_text(
        json.dumps({"productName": "Determinex", "version": "0.1.0"}), encoding="utf-8"
    )
    installer_dir = tmp_path / "bundle"
    exe = installer_dir / "nsis/Determinex_0.1.0_x64-setup.exe"
    msi = installer_dir / "msi/Determinex_0.1.0_x64_en-US.msi"
    appimage = installer_dir / "appimage/determinex_0.1.0_amd64.AppImage"
    deb = installer_dir / "deb/determinex_0.1.0_amd64.deb"
    rpm = installer_dir / "rpm/determinex-0.1.0-1.x86_64.rpm"
    _write(exe, b"fake nsis installer")
    _write(msi, b"fake msi installer")
    _write(appimage, b"fake appimage package")
    _write(deb, b"fake deb package")
    _write(rpm, b"fake rpm package")

    manifest = build_download_bundle(
        installer_dir,
        tmp_path / "out",
        root / "assurance/evidence/determinex_download_bundle_20260707",
        root=root,
    )

    assert manifest["schema_version"] == "determinex-download-bundle-v1"
    assert manifest["release_ready"] is False
    assert manifest["public_distribution_ready"] is False
    assert manifest["setup_ready_for_local_operator_testing"] is True
    assert "clean-host install success" in manifest["claim_boundary"]
    assert {artifact["artifact_type"] for artifact in manifest["artifacts"]} == {
        "linux_appimage",
        "linux_deb",
        "linux_rpm",
        "windows_msi",
        "windows_nsis_setup",
    }
    assert manifest["platform"] == "cross-platform"
    assert manifest["package_matrix"]["windows_nsis_setup"] is True
    assert manifest["package_matrix"]["windows_msi"] is True
    assert manifest["package_matrix"]["linux_appimage"] is True
    assert manifest["package_matrix"]["linux_deb"] is True
    assert manifest["package_matrix"]["linux_rpm"] is True
    assert hashlib.sha256(exe.read_bytes()).hexdigest() in (
        root / "assurance/evidence/determinex_download_bundle_20260707/CHECKSUMS.sha256"
    ).read_text(encoding="utf-8")

    zip_path = Path(manifest["bundle_zip_path"])
    assert zip_path.is_file()
    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
        assert "SETUP.md" in names
        assert "CHECKSUMS.sha256" in names
        assert "download_manifest.json" in names
        assert "installers/Determinex_0.1.0_x64-setup.exe" in names
        assert "installers/Determinex_0.1.0_x64_en-US.msi" in names
        assert "installers/determinex_0.1.0_amd64.AppImage" in names
        assert "installers/determinex_0.1.0_amd64.deb" in names
        assert "installers/determinex-0.1.0-1.x86_64.rpm" in names
        bundled_manifest = json.loads(zf.read("download_manifest.json").decode("utf-8"))
    assert bundled_manifest["schema_version"] == "determinex-download-bundle-v1"
    assert bundled_manifest["setup_ready_for_local_operator_testing"] is True
    msi_packets = list((root / "assurance/evidence/windows_msi").glob("windows_msi_*.json"))
    assert len(msi_packets) == 1
    msi_packet = json.loads(msi_packets[0].read_text(encoding="utf-8"))
    assert msi_packet["schema_version"] == "determinex-windows-msi-evidence-v1"
    # These four used to be unconditional `True` LITERALS in the packet writer, and
    # `_windows_msi_errors` checks exactly them -- so dropping any file named *.msi into the
    # installer directory turned the windows_msi gate green. Asserting True here made this test
    # confirm the literal rather than any property of the artifact. They are now derived, and this
    # fixture's MSI is a stub with arbitrary bytes, so the honest expectations are:
    #
    #   wix_toolset_used            -> False  (not an OLE compound file, no WiX authoring)
    #   msi_built                   -> True   (an MSI artifact really was collected)
    #   msi_sha256_verified         -> True   (a real 64-hex digest was recorded)
    #   msi_installer_smoke_performed -> False (this script never installs anything; the
    #                                           clean-host transcript attests that)
    assert msi_packet["wix_toolset_used"] is False, (
        "a stub MSI must not be reported as WiX-built; that is what made this gate vacuous"
    )
    assert msi_packet["msi_built"] is True
    assert msi_packet["msi_sha256_verified"] is True
    assert msi_packet["msi_installer_smoke_performed"] is False, (
        "package_download_bundle discovers and checksums artifacts; it cannot attest an install"
    )
    assert msi_packet["authority_granted"] is False
    assert msi_packet["msi_artifacts"][0]["file_name"] == "Determinex_0.1.0_x64_en-US.msi"


def test_discover_installers_fails_closed_when_no_setup_artifacts(tmp_path: Path):
    empty = tmp_path / "empty"
    empty.mkdir()

    try:
        discover_installers(empty)
    except FileNotFoundError as exc:
        assert "no installer/package artifacts" in str(exc)
    else:
        raise AssertionError("discover_installers should fail when no installers exist")


def test_download_bundle_records_msi_absence_for_nsis_only_package(tmp_path: Path):
    root = tmp_path / "repo"
    tauri = root / "frontend/src-tauri/tauri.conf.json"
    tauri.parent.mkdir(parents=True)
    tauri.write_text(
        json.dumps({"productName": "Determinex", "version": "0.1.0"}), encoding="utf-8"
    )
    installer_dir = tmp_path / "bundle"
    exe = installer_dir / "nsis/Determinex_0.1.0_x64-setup.exe"
    _write(exe, b"fake nsis installer")

    manifest = build_download_bundle(
        installer_dir,
        tmp_path / "out",
        root / "assurance/evidence/determinex_download_bundle_20260707",
        root=root,
    )

    assert {artifact["artifact_type"] for artifact in manifest["artifacts"]} == {
        "windows_nsis_setup",
    }
    assert "windows_msi_not_bundled" in manifest["remaining_blockers"]
    assert "linux_packages_not_bundled" in manifest["remaining_blockers"]
    assert manifest["packaging_notes"] == [
        "windows_msi_not_in_bundle; use the NSIS setup artifact until WiX/MSI bundling is repaired",
        "linux_packages_not_in_bundle; missing linux_appimage, linux_deb, linux_rpm; build Linux packages on a Linux host before public Linux distribution",
    ]
    assert not (root / "assurance/evidence/windows_msi").exists()


def test_download_bundle_records_each_missing_linux_package_type(tmp_path: Path):
    root = tmp_path / "repo"
    tauri = root / "frontend/src-tauri/tauri.conf.json"
    tauri.parent.mkdir(parents=True)
    tauri.write_text(
        json.dumps({"productName": "Determinex", "version": "0.1.0"}), encoding="utf-8"
    )
    installer_dir = tmp_path / "bundle"
    exe = installer_dir / "nsis/Determinex_0.1.0_x64-setup.exe"
    msi = installer_dir / "msi/Determinex_0.1.0_x64_en-US.msi"
    appimage = installer_dir / "appimage/determinex_0.1.0_amd64.AppImage"
    _write(exe, b"fake nsis installer")
    _write(msi, b"fake msi installer")
    _write(appimage, b"fake appimage package")

    manifest = build_download_bundle(
        installer_dir,
        tmp_path / "out",
        root / "assurance/evidence/determinex_download_bundle_20260707",
        root=root,
    )

    assert "linux_packages_not_bundled" in manifest["remaining_blockers"]
    assert "linux_deb_not_bundled" in manifest["remaining_blockers"]
    assert "linux_rpm_not_bundled" in manifest["remaining_blockers"]
    assert "linux_appimage_not_bundled" not in manifest["remaining_blockers"]
    assert manifest["packaging_notes"] == [
        "linux_packages_not_in_bundle; missing linux_deb, linux_rpm; build Linux packages on a Linux host before public Linux distribution",
    ]


def test_download_bundle_drops_legal_blocker_when_public_distribution_packet_passes(tmp_path: Path):
    root = tmp_path / "repo"
    tauri = root / "frontend/src-tauri/tauri.conf.json"
    tauri.parent.mkdir(parents=True)
    tauri.write_text(
        json.dumps({"productName": "Determinex", "version": "0.1.0"}), encoding="utf-8"
    )
    _write(
        root / "assurance/evidence/public_distribution/legal_public_distribution_20260712.json",
        json.dumps(
            {
                "schema_version": "determinex-legal-public-distribution-evidence-v1",
                "legal_review_completed": True,
                "license_inventory_reviewed": True,
                "model_notice_reviewed": True,
                "public_repo_secret_scan_passed": True,
                "public_repo_scrub_completed": True,
                "third_party_notices_present": True,
                "authority_granted": False,
            }
        ).encode("utf-8"),
    )
    installer_dir = tmp_path / "bundle"
    exe = installer_dir / "nsis/Determinex_0.1.0_x64-setup.exe"
    msi = installer_dir / "msi/Determinex_0.1.0_x64_en-US.msi"
    appimage = installer_dir / "appimage/determinex_0.1.0_amd64.AppImage"
    deb = installer_dir / "deb/determinex_0.1.0_amd64.deb"
    rpm = installer_dir / "rpm/determinex-0.1.0-1.x86_64.rpm"
    _write(exe, b"fake nsis installer")
    _write(msi, b"fake msi installer")
    _write(appimage, b"fake appimage package")
    _write(deb, b"fake deb package")
    _write(rpm, b"fake rpm package")

    manifest = build_download_bundle(
        installer_dir,
        tmp_path / "out",
        root / "assurance/evidence/determinex_download_bundle_20260707",
        root=root,
    )

    assert "public_distribution_legal_ip_packet_not_executed" not in manifest["remaining_blockers"]
