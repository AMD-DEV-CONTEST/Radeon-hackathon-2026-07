import json
from pathlib import Path

from scripts.release import windows_trust_packet


def test_windows_trust_packet_records_unsigned_artifact_without_granting_authority(
    tmp_path: Path, monkeypatch
):
    artifact_dir = tmp_path / "dist"
    artifact_dir.mkdir()
    installer = artifact_dir / "Determinex_0.1.0_x64_en-US.msi"
    installer.write_bytes(b"fake-msi")
    sha256 = windows_trust_packet._sha256(installer)
    manifest = {
        "schema_version": "determinex-download-bundle-v1",
        "bundle_dir": str(artifact_dir),
        "artifacts": [
            {
                "artifact_type": "windows_msi",
                "file_name": installer.name,
                "bundle_relative_path": installer.name,
                "source_path": str(installer),
                "sha256": sha256,
            }
        ],
    }
    manifest_path = tmp_path / "download_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    monkeypatch.setattr(
        windows_trust_packet,
        "_powershell_signature",
        lambda path: {
            "Status": "NotSigned",
            "StatusMessage": "The file is not signed.",
            "SignerCertificateSubject": "",
            "TimeStamperCertificateSubject": "",
        },
    )

    packet = windows_trust_packet.build_packet(tmp_path, manifest_path)

    assert packet["schema_version"] == "determinex-windows-trust-evidence-v1"
    assert packet["artifact_authenticode_status"] == "NotSigned"
    assert packet["code_signing_verified"] is False
    assert packet["timestamp_verified"] is False
    assert packet["smartscreen_verification_performed"] is False
    assert packet["smartscreen_result"] == "not_performed"
    assert packet["authority_granted"] is False
    assert packet["artifacts"][0]["sha256_verified"] is True


def test_windows_trust_packet_can_record_valid_signed_smartscreen_packet(
    tmp_path: Path, monkeypatch
):
    artifact_dir = tmp_path / "dist"
    artifact_dir.mkdir()
    installer = artifact_dir / "Determinex_0.1.0_x64-setup.exe"
    installer.write_bytes(b"fake-exe")
    manifest_path = tmp_path / "download_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "determinex-download-bundle-v1",
                "bundle_dir": str(artifact_dir),
                "artifacts": [
                    {
                        "artifact_type": "windows_nsis_setup",
                        "file_name": installer.name,
                        "bundle_relative_path": installer.name,
                        "sha256": windows_trust_packet._sha256(installer),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        windows_trust_packet,
        "_powershell_signature",
        lambda path: {
            "Status": "Valid",
            "StatusMessage": "",
            "SignerCertificateSubject": "CN=Determinex Test Publisher",
            "TimeStamperCertificateSubject": "CN=Timestamp Authority",
        },
    )

    packet = windows_trust_packet.build_packet(
        tmp_path,
        manifest_path,
        smartscreen_result="pass",
        smartscreen_verification_performed=True,
    )

    assert packet["artifact_authenticode_status"] == "Valid"
    assert packet["code_signing_verified"] is True
    assert packet["timestamp_verified"] is True
    assert packet["smartscreen_verification_performed"] is True
    assert packet["smartscreen_result"] == "pass"
    assert packet["certificate_subject"] == "CN=Determinex Test Publisher"
