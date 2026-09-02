from __future__ import annotations

import json
import zipfile
from pathlib import Path

from scripts.release import full_release_closure as closure


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_verify_download_bundle_checks_zip_artifact_hashes(tmp_path: Path, monkeypatch):
    evidence = tmp_path / "assurance/evidence/determinex_download_bundle_20260707"
    bundle = tmp_path / "bundle"
    installer_bytes = b"fake determinex setup"
    installer_sha = closure._sha256_bytes(installer_bytes)
    zip_path = tmp_path / "determinex.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("installers/Determinex_0.1.0_x64-setup.exe", installer_bytes)
    zip_sha = closure._sha256(zip_path)
    manifest = {
        "schema_version": "determinex-download-bundle-v1",
        "setup_ready_for_local_operator_testing": True,
        "release_ready": False,
        "public_distribution_ready": False,
        "source_commit": "abc123",
        "bundle_zip_path": str(zip_path),
        "bundle_zip_sha256": zip_sha,
        "bundle_dir": str(bundle),
        "remaining_blockers": ["code_signing_not_verified"],
        "artifacts": [
            {
                "bundle_relative_path": "installers/Determinex_0.1.0_x64-setup.exe",
                "sha256": installer_sha,
                "authenticode_status": "NotSigned",
            }
        ],
    }
    _write_json(evidence / "download_manifest.json", manifest)
    monkeypatch.setattr(closure, "_git_head", lambda root: "abc123")

    result = closure.verify_download_bundle(tmp_path)

    assert result["checks"]["bundle_zip_sha256_matches"] is True
    assert result["checks"]["artifacts"][0]["present_in_zip"] is True
    assert result["checks"]["artifacts"][0]["sha256_matches"] is True
    assert result["status"] == "passed_with_release_blockers"
    assert "code_signing_not_verified" in result["remaining_blockers"]


def test_full_release_closure_never_grants_release_authority(tmp_path: Path, monkeypatch):
    _write_json(
        tmp_path / "assurance/sbom/determinex-python.spdx.json", {"name": "determinex-python"}
    )
    _write_json(
        tmp_path / "assurance/sbom/determinex-python.cyclonedx.json",
        {"bomFormat": "CycloneDX", "metadata": {"component": {"name": "determinex-python"}}},
    )
    _write_json(
        tmp_path / "assurance/sbom/determinex-npm.cyclonedx.json", {"bomFormat": "CycloneDX"}
    )
    _write_json(
        tmp_path
        / "assurance/evidence/clean_host_fresh_install_runner_execution/run_20260531.CLEAN_HOST_FRESH_INSTALL_RUNNER_EXECUTION_BLOCKED_RUNNER_NOT_EXECUTED.json",
        {"clean_host_fresh_install": False, "status": "blocked"},
    )
    _write_json(
        tmp_path / "assurance/evidence/first_end_to_end_user_workflow/result.json",
        {"status": "blocked"},
    )
    _write_json(
        tmp_path
        / "assurance/evidence/first_end_to_end_user_workflow/rerun_after_builder_health_latest.json",
        {
            "session_id": "semantic-session",
            "status": "BLOCKED_CORRECTNESS_GATE_FAILED_AFTER_BUILDER_HEALTH_PASSED",
            "exact_blocker": "First E2E workflow now reaches the real Hive build loop, but the Builder/Architect output compiles while failing the generated correctness harness.",
            "next_required_action": "Improve the Builder/Architect semantic repair loop so the generated Rust implementation satisfies the correctness harness.",
        },
    )
    (tmp_path / "PROJECT.md").write_text(
        "Literal `determinex_*`/`DETERMINEX_*` script, env-var, and model-tag names remain until the coordinated internal rename.",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        closure,
        "verify_download_bundle",
        lambda root: {"status": "blocked", "remaining_blockers": ["download_bundle_zip_missing"]},
    )
    monkeypatch.setattr(
        closure,
        "probe_clean_runner",
        lambda root, now=None: {
            "schema_version": closure.PREFLIGHT_SCHEMA_VERSION,
            "generated_at_utc": "2026-07-07T00:00:00Z",
            "docker_info_available": True,
            "clean_host_fresh_install": False,
            "installer_execution_performed": False,
            "release_ready": False,
            "authority_granted": False,
        },
    )

    report = closure.write_report(tmp_path / "closure.json", tmp_path)

    assert report["schema_version"] == "determinex-full-release-closure-v1"
    assert report["release_ready"] is False
    assert report["authority_granted"] is False
    assert "clean_host" in report["blocked_gate_ids"]
    assert "windows_trust" not in report["blocked_gate_ids"]
    assert "legal_public_distribution" in report["blocked_gate_ids"]
    assert "windows_msi" in report["blocked_gate_ids"]
    assert "linux_packages" in report["blocked_gate_ids"]
    assert "programbench_200" not in report["blocked_gate_ids"]
    assert "swebench_fresh" not in report["blocked_gate_ids"]
    assert "programbench_200" in report["deferred_gate_ids"]
    assert "swebench_fresh" in report["deferred_gate_ids"]
    assert (
        "clean_host_install_launch_uninstall_transcript_not_executed"
        in report["protected_external_blockers"]
    )
    assert (
        "windows_signing_smartscreen_trust_not_verified"
        not in report["protected_external_blockers"]
    )
    assert "legal_public_distribution_packet_not_executed" in report["protected_external_blockers"]
    assert "windows_msi_distribution_not_built" in report["protected_external_blockers"]
    assert "linux_package_distribution_not_built" in report["protected_external_blockers"]
    assert (
        "programbench_200_of_200_strict_locks_not_complete"
        not in report["protected_external_blockers"]
    )
    assert (
        "fresh_swebench_privacy_mode_publication_reruns_not_complete"
        not in report["protected_external_blockers"]
    )
    assert "SWE-bench Pro" in " ".join(report["deferred_proof_tracks"])
    assert any("semantic repair loop" in action for action in report["next_executable_actions"])
    assert (
        tmp_path
        / "assurance/evidence/full_release_closure/clean_host_runner_preflight_20260707.json"
    ).is_file()


def test_full_release_closure_drops_first_e2e_protected_blocker_after_passing_rerun(
    tmp_path: Path, monkeypatch
):
    _write_json(
        tmp_path / "assurance/sbom/determinex-python.spdx.json", {"name": "determinex-python"}
    )
    _write_json(
        tmp_path / "assurance/sbom/determinex-python.cyclonedx.json",
        {"bomFormat": "CycloneDX", "metadata": {"component": {"name": "determinex-python"}}},
    )
    _write_json(
        tmp_path / "assurance/sbom/determinex-npm.cyclonedx.json", {"bomFormat": "CycloneDX"}
    )
    _write_json(
        tmp_path
        / "assurance/evidence/clean_host_fresh_install_runner_execution/run_20260531.CLEAN_HOST_FRESH_INSTALL_RUNNER_EXECUTION_BLOCKED_RUNNER_NOT_EXECUTED.json",
        {"clean_host_fresh_install": False, "status": "blocked"},
    )
    _write_json(
        tmp_path / "assurance/evidence/first_end_to_end_user_workflow/result.json",
        {"status": "LANE_D_BLOCKED_LOCAL_BUILDER_OLLAMA_TIMEOUT"},
    )
    _write_json(
        tmp_path
        / "assurance/evidence/first_end_to_end_user_workflow/rerun_after_builder_health_latest.json",
        {
            "status": "FIRST_E2E_RERUN_PASSED",
            "session_id": "passed-session",
            "observed_result": {
                "steps_complete": 2,
                "steps_total": 2,
                "steps_failed": 0,
                "steps_pending": 0,
            },
        },
    )
    (tmp_path / "PROJECT.md").write_text(
        "Literal `determinex_*`/`DETERMINEX_*` script, env-var, and model-tag names remain until the coordinated internal rename.",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        closure,
        "verify_download_bundle",
        lambda root: {"status": "blocked", "remaining_blockers": ["download_bundle_zip_missing"]},
    )
    monkeypatch.setattr(
        closure,
        "probe_clean_runner",
        lambda root, now=None: {
            "schema_version": closure.PREFLIGHT_SCHEMA_VERSION,
            "generated_at_utc": "2026-07-07T00:00:00Z",
            "docker_info_available": True,
            "clean_host_fresh_install": False,
            "installer_execution_performed": False,
            "release_ready": False,
            "authority_granted": False,
        },
    )

    report = closure.write_report(tmp_path / "closure.json", tmp_path)

    assert "first_e2e" not in report["blocked_gate_ids"]
    assert "first_end_to_end_user_workflow_not_passed" not in report["protected_external_blockers"]


def test_full_release_closure_drops_clean_host_protected_blocker_after_valid_transcript(
    tmp_path: Path, monkeypatch
):
    _write_json(
        tmp_path / "assurance/sbom/determinex-python.spdx.json", {"name": "determinex-python"}
    )
    _write_json(
        tmp_path / "assurance/sbom/determinex-python.cyclonedx.json",
        {"bomFormat": "CycloneDX", "metadata": {"component": {"name": "determinex-python"}}},
    )
    _write_json(
        tmp_path / "assurance/sbom/determinex-npm.cyclonedx.json", {"bomFormat": "CycloneDX"}
    )
    # _clean_host_transcript_errors also requires runner.runner_id (non-mocked) and a
    # bundle.installer_sha256 that cross-validates against a REAL artifact hash recorded
    # in the current download bundle manifest (determinex_release_gates._latest_clean_host_
    # transcript) -- both were missing from this fixture, causing the transcript to always
    # be rejected regardless of the field this test actually means to exercise.
    installer_bytes = b"fake determinex setup for closure test"
    installer_sha256 = closure._sha256_bytes(installer_bytes)
    installer_path = tmp_path / "dist/Determinex_0.1.0_x64-setup.exe"
    installer_path.parent.mkdir(parents=True, exist_ok=True)
    installer_path.write_bytes(installer_bytes)
    _write_json(
        tmp_path / "assurance/evidence/determinex_download_bundle_20260707/download_manifest.json",
        {
            "schema_version": "determinex-download-bundle-v1",
            "artifacts": [
                {
                    "artifact_type": "windows_nsis_setup",
                    "source_path": "dist/Determinex_0.1.0_x64-setup.exe",
                    "sha256": installer_sha256,
                    "size_bytes": len(installer_bytes),
                }
            ],
        },
    )
    _write_json(
        tmp_path
        / "assurance/evidence/full_release_closure/clean_host_install_transcript_20260708.json",
        {
            "schema_version": "determinex-clean-host-install-transcript-v1",
            "product_name": "Determinex",
            "clean_host_fresh_install": True,
            "runner": {
                "is_clean_host": True,
                "host_reused_from_developer_machine": False,
                "os": "Windows 11",
                "runner_id": "azure-clean-host-vm-20260708",
            },
            "bundle": {
                "source_commit": "final-release-commit",
                "installer_sha256_verified": True,
                "installer_sha256": installer_sha256,
            },
            "dry_run": False,
            "installer_execution_performed": True,
            "launch_performed": True,
            "proof_center_smoke_performed": True,
            "workspace_command_smoke_performed": True,
            "uninstall_performed": True,
            "release_ready": False,
            "authority_granted": False,
        },
    )
    _write_json(
        tmp_path / "assurance/evidence/first_end_to_end_user_workflow/result.json",
        {"status": "LANE_D_BLOCKED_LOCAL_BUILDER_OLLAMA_TIMEOUT"},
    )
    _write_json(
        tmp_path
        / "assurance/evidence/first_end_to_end_user_workflow/rerun_after_builder_health_latest.json",
        {
            "status": "FIRST_E2E_RERUN_PASSED",
            "session_id": "passed-session",
            "observed_result": {
                "steps_complete": 2,
                "steps_total": 2,
                "steps_failed": 0,
                "steps_pending": 0,
            },
        },
    )
    (tmp_path / "PROJECT.md").write_text(
        "Literal `determinex_*`/`DETERMINEX_*` script, env-var, and model-tag names remain until the coordinated internal rename.",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        closure,
        "verify_download_bundle",
        lambda root: {"status": "blocked", "remaining_blockers": ["download_bundle_zip_missing"]},
    )
    monkeypatch.setattr(
        closure,
        "probe_clean_runner",
        lambda root, now=None: {
            "schema_version": closure.PREFLIGHT_SCHEMA_VERSION,
            "generated_at_utc": "2026-07-07T00:00:00Z",
            "docker_info_available": True,
            "clean_host_fresh_install": False,
            "installer_execution_performed": False,
            "release_ready": False,
            "authority_granted": False,
        },
    )

    report = closure.write_report(tmp_path / "closure.json", tmp_path)

    assert "clean_host" not in report["blocked_gate_ids"]
    assert (
        "clean_host_install_launch_uninstall_transcript_not_executed"
        not in report["protected_external_blockers"]
    )


def test_full_release_closure_omits_rebuild_action_when_download_bundle_is_current(
    tmp_path: Path, monkeypatch
):
    _write_json(
        tmp_path / "assurance/sbom/determinex-python.spdx.json", {"name": "determinex-python"}
    )
    _write_json(
        tmp_path / "assurance/sbom/determinex-python.cyclonedx.json",
        {"bomFormat": "CycloneDX", "metadata": {"component": {"name": "determinex-python"}}},
    )
    _write_json(
        tmp_path / "assurance/sbom/determinex-npm.cyclonedx.json", {"bomFormat": "CycloneDX"}
    )
    _write_json(
        tmp_path
        / "assurance/evidence/clean_host_fresh_install_runner_execution/run_20260531.CLEAN_HOST_FRESH_INSTALL_RUNNER_EXECUTION_BLOCKED_RUNNER_NOT_EXECUTED.json",
        {"clean_host_fresh_install": False, "status": "blocked"},
    )
    _write_json(
        tmp_path / "assurance/evidence/first_end_to_end_user_workflow/result.json",
        {"status": "FIRST_E2E_RERUN_PASSED"},
    )
    (tmp_path / "PROJECT.md").write_text(
        "Literal `determinex_*`/`DETERMINEX_*` script, env-var, and model-tag names remain until the coordinated internal rename.",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        closure,
        "verify_download_bundle",
        lambda root: {
            "status": "passed_with_release_blockers",
            "checks": {"source_commit_current": True},
            "remaining_blockers": ["code_signing_not_verified"],
        },
    )
    monkeypatch.setattr(
        closure,
        "probe_clean_runner",
        lambda root, now=None: {
            "schema_version": closure.PREFLIGHT_SCHEMA_VERSION,
            "generated_at_utc": "2026-07-07T00:00:00Z",
            "docker_info_available": True,
            "clean_host_fresh_install": False,
            "installer_execution_performed": False,
            "release_ready": False,
            "authority_granted": False,
        },
    )

    report = closure.write_report(tmp_path / "closure.json", tmp_path)

    assert not any(
        action.startswith("Rebuild the download bundle")
        for action in report["next_executable_actions"]
    )


def test_full_release_closure_omits_msi_build_action_when_msi_gate_passes(
    tmp_path: Path, monkeypatch
):
    _write_json(
        tmp_path / "assurance/evidence/windows_msi/windows_msi_20260712.json",
        {
            "schema_version": "determinex-windows-msi-evidence-v1",
            "wix_toolset_used": True,
            "msi_built": True,
            "msi_sha256_verified": True,
            "msi_installer_smoke_performed": True,
            "authority_granted": False,
        },
    )
    _write_json(
        tmp_path / "assurance/evidence/determinex_download_bundle_20260707/download_manifest.json",
        {
            "schema_version": "determinex-download-bundle-v1",
            "package_matrix": {
                "windows_nsis_setup": True,
                "windows_msi": True,
                "linux_appimage": False,
                "linux_deb": False,
                "linux_rpm": False,
            },
            "artifacts": [
                {"artifact_type": "windows_nsis_setup"},
                {"artifact_type": "windows_msi"},
            ],
        },
    )
    monkeypatch.setattr(
        closure,
        "verify_download_bundle",
        lambda root: {
            "status": "passed_with_release_blockers",
            "checks": {"source_commit_current": True},
            "remaining_blockers": ["linux_packages_not_bundled"],
        },
    )
    monkeypatch.setattr(
        closure,
        "probe_clean_runner",
        lambda root, now=None: {
            "schema_version": closure.PREFLIGHT_SCHEMA_VERSION,
            "generated_at_utc": "2026-07-12T00:00:00Z",
            "docker_info_available": False,
            "clean_host_fresh_install": False,
            "installer_execution_performed": False,
            "release_ready": False,
            "authority_granted": False,
        },
    )

    report = closure.write_report(tmp_path / "closure.json", tmp_path)

    assert "windows_msi" not in report["blocked_gate_ids"]
    assert "windows_msi_distribution_not_built" not in report["protected_external_blockers"]
    assert not any("WiX/MSI" in action for action in report["next_executable_actions"])


def test_full_release_closure_omits_legal_action_when_public_distribution_gate_passes(
    tmp_path: Path, monkeypatch
):
    _write_json(
        tmp_path / "assurance/evidence/public_distribution/legal_public_distribution_20260712.json",
        {
            "schema_version": "determinex-legal-public-distribution-evidence-v1",
            "legal_review_completed": True,
            "license_inventory_reviewed": True,
            "model_notice_reviewed": True,
            "public_repo_secret_scan_passed": True,
            "public_repo_scrub_completed": True,
            "third_party_notices_present": True,
            "authority_granted": False,
        },
    )
    monkeypatch.setattr(
        closure,
        "verify_download_bundle",
        lambda root: {
            "status": "passed_with_release_blockers",
            "checks": {"source_commit_current": True},
            "remaining_blockers": ["public_distribution_legal_ip_packet_not_executed"],
        },
    )
    monkeypatch.setattr(
        closure,
        "probe_clean_runner",
        lambda root, now=None: {
            "schema_version": closure.PREFLIGHT_SCHEMA_VERSION,
            "generated_at_utc": "2026-07-12T00:00:00Z",
            "docker_info_available": True,
            "clean_host_fresh_install": False,
            "installer_execution_performed": False,
            "release_ready": False,
            "authority_granted": False,
        },
    )

    report = closure.write_report(tmp_path / "closure.json", tmp_path)

    assert "legal_public_distribution" not in report["blocked_gate_ids"]
    assert (
        "legal_public_distribution_packet_not_executed" not in report["protected_external_blockers"]
    )
    assert (
        "public_distribution_legal_ip_packet_not_executed"
        not in report["protected_external_blockers"]
    )
    assert not any("legal/IP" in action for action in report["next_executable_actions"])
