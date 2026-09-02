from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from scripts.release import determinex_release_gates as gates


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _artifact(
    root: Path, path: Path, content: bytes = b"determinex-test-artifact"
) -> dict[str, object]:
    import hashlib

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return {
        "source_path": str(path.relative_to(root)),
        "size_bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def test_release_gate_collector_keeps_blockers_distinct(tmp_path: Path):
    _write_json(
        tmp_path / "assurance/sbom/determinex-python.spdx.json",
        {"name": "determinex-python-1.0.0-dev"},
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
        {
            "status": "CLEAN_HOST_FRESH_INSTALL_RUNNER_EXECUTION_BLOCKED_RUNNER_NOT_EXECUTED",
            "clean_host_fresh_install": False,
            "artifact_payloads": {
                "clean_run_transcript_or_blocker": {
                    "blocker": "Docker/local clean runner unavailable or not healthy"
                }
            },
        },
    )
    _write_json(
        tmp_path / "assurance/evidence/first_end_to_end_user_workflow/result.json",
        {
            "status": "LANE_D_BLOCKED_LOCAL_BUILDER_OLLAMA_TIMEOUT",
            "next_required_action": "Restore local builder health or route Builder role to a stable admitted model.",
        },
    )
    _write_json(
        tmp_path
        / "assurance/evidence/first_end_to_end_user_workflow/builder_health_probe_latest.json",
        {
            "status": "passed",
            "exact_blocker": "",
            "release_ready": False,
        },
    )
    _write_json(
        tmp_path
        / "assurance/evidence/first_end_to_end_user_workflow/rerun_after_builder_health_latest.json",
        {
            "status": "BLOCKED_SESSION_BUDGET_EXHAUSTED_AFTER_BUILDER_HEALTH_PASSED",
            "session_id": "fresh-session-id",
            "exact_blocker": "Stored first E2E session rerun passed Builder health preflight, then skipped remaining waves because session budget was exhausted.",
            "next_required_action": "Create or reset a first E2E workflow session with sufficient budget.",
            "release_ready": False,
        },
    )
    _write_json(
        tmp_path
        / "assurance/evidence/installer_install_launch_uninstall_release_signoff_wave_001/public_distribution_go_no_go_20260602.json",
        {
            "installer_ready": True,
            "release_ready": False,
            "go_no_go": "NO_GO_PUBLIC_DISTRIBUTION",
            "exact_blockers": ["code_signing_not_verified"],
        },
    )
    _write_json(
        tmp_path
        / "assurance/evidence/installer_release_packet_hardening/run_20260629.INSTALLER_RELEASE_PACKET_HARDENED_UNSIGNED.json",
        {
            "status": "INSTALLER_RELEASE_PACKET_HARDENED_UNSIGNED",
            "protected_external_action_executed": False,
        },
    )
    _write_json(
        tmp_path / "assurance/evidence/determinex_download_bundle_20260707/download_manifest.json",
        {
            "schema_version": "determinex-download-bundle-v1",
            "setup_ready_for_local_operator_testing": True,
            "release_ready": False,
            "public_distribution_ready": False,
            "remaining_blockers": [
                "clean_host_install_proof_not_passed",
                "windows_msi_not_bundled",
                "linux_packages_not_bundled",
            ],
            "package_matrix": {
                "windows_nsis_setup": True,
                "windows_msi": False,
                "linux_appimage": False,
                "linux_deb": False,
                "linux_rpm": False,
            },
            "artifacts": [
                {
                    "file_name": "Determinex_0.1.0_x64-setup.exe",
                    "artifact_type": "windows_nsis_setup",
                }
            ],
        },
    )
    (tmp_path / "LICENSE").write_text(
        "GNU AFFERO GENERAL PUBLIC LICENSE\nVersion 3\n", encoding="utf-8"
    )
    (tmp_path / "pyproject.toml").write_text(
        'license = { text = "AGPL-3.0-or-later" }\n', encoding="utf-8"
    )
    (tmp_path / "frontend/package.json").parent.mkdir(parents=True)
    (tmp_path / "frontend/package.json").write_text(
        '{"license":"AGPL-3.0-or-later"}\n', encoding="utf-8"
    )
    (tmp_path / "frontend/src-tauri/Cargo.toml").parent.mkdir(parents=True)
    (tmp_path / "frontend/src-tauri/Cargo.toml").write_text(
        'license = "AGPL-3.0-or-later"\n', encoding="utf-8"
    )
    (tmp_path / "frontend/vscode-extension/package.json").parent.mkdir(parents=True)
    (tmp_path / "frontend/vscode-extension/package.json").write_text(
        '{"license":"AGPL-3.0-or-later"}\n', encoding="utf-8"
    )
    (tmp_path / "PROJECT.md").write_text(
        "Literal `determinex_*`/`DETERMINEX_*` script, env-var, and model-tag names remain until the coordinated internal rename.",
        encoding="utf-8",
    )
    _write_json(
        tmp_path / "corpus/programbench/eval_index.json",
        [
            {"slug": "tool_a", "status": "native_rebuild", "official_full_suite_resolved": False},
            {"slug": "tool_b", "status": "factory_accepted", "official_full_suite_resolved": False},
        ],
    )

    report = gates.collect(tmp_path)
    by_id = {gate.gate_id: gate for gate in report.gates}

    assert by_id["sbom"].status == "passed"
    assert by_id["installer"].status == "partial"
    assert "determinex_download_bundle_20260707/download_manifest.json" in " ".join(
        by_id["installer"].evidence
    )
    assert "windows_msi_not_bundled" in by_id["installer"].exact_blocker
    assert "linux_packages_not_bundled" in by_id["installer"].exact_blocker
    assert any(
        "-PackageDownloadBundle" in command for command in by_id["installer"].runbook_commands
    )
    assert by_id["clean_host"].status == "blocked"
    assert by_id["first_e2e"].status == "blocked"
    assert (
        "assurance/evidence/first_end_to_end_user_workflow/builder_health_probe_latest.json"
        in by_id["first_e2e"].evidence
    )
    assert "rerun_after_builder_health_latest.json" in " ".join(by_id["first_e2e"].evidence)
    assert by_id["first_e2e"].exact_blocker.startswith(
        "Stored first E2E session rerun passed Builder health preflight"
    )
    assert by_id["windows_trust"].status == "deferred"
    assert by_id["legal_public_distribution"].status == "partial"
    assert (
        "AGPLv3 source license evidence is present"
        in by_id["legal_public_distribution"].exact_blocker
    )
    assert by_id["windows_msi"].status == "blocked"
    assert by_id["linux_packages"].status == "blocked"
    assert by_id["extension_compat"].status == "deferred"
    assert by_id["internal_rename"].status == "deferred"
    assert by_id["programbench_200"].status == "deferred"
    assert by_id["programbench_200"].exact_blocker.startswith(
        "ProgramBench strict official locks are 0/200"
    )
    assert by_id["swebench_fresh"].status == "deferred"
    assert "fresh official SWE-bench privacy-mode rerun" in by_id["swebench_fresh"].exact_blocker
    assert report.release_ready is False
    assert "clean_host" in report.blocked_gate_ids
    assert "windows_trust" not in report.blocked_gate_ids
    assert "legal_public_distribution" not in report.blocked_gate_ids
    assert "windows_msi" in report.blocked_gate_ids
    assert "linux_packages" in report.blocked_gate_ids
    assert "clean_host" not in report.deferred_gate_ids
    assert "windows_trust" in report.deferred_gate_ids
    assert "legal_public_distribution" not in report.deferred_gate_ids
    assert "legal_public_distribution" in report.partial_gate_ids
    assert "windows_msi" not in report.deferred_gate_ids
    assert "programbench_200" not in report.blocked_gate_ids
    assert "swebench_fresh" not in report.blocked_gate_ids
    assert "programbench_200" in report.deferred_gate_ids
    assert "swebench_fresh" in report.deferred_gate_ids
    assert (
        by_id["clean_host"].exact_blocker == "Docker/local clean runner unavailable or not healthy"
    )
    assert any("docker info" in command for command in by_id["clean_host"].runbook_commands)
    assert any(
        "builder_health_probe.py" in command for command in by_id["first_e2e"].runbook_commands
    )
    assert any(
        "--session fresh-session-id" in command for command in by_id["first_e2e"].runbook_commands
    )


def test_release_gate_collector_serializes_without_granting_authority(tmp_path: Path):
    report = gates.collect(tmp_path)
    payload = report.to_dict()

    assert payload["release_ready"] is False
    assert payload["authority_granted"] is False
    assert payload["schema_version"] == "determinex-release-gate-status-v1"
    assert all(gate["release_ready"] is False for gate in payload["gates"])
    assert all("runbook_commands" in gate for gate in payload["gates"])


def test_first_e2e_gate_accepts_passing_rerun_as_superseding_evidence(tmp_path: Path):
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
            "release_ready": False,
            "observed_result": {
                "steps_complete": 2,
                "steps_total": 2,
                "steps_failed": 0,
                "steps_pending": 0,
            },
        },
    )

    gate = gates._first_e2e_gate(tmp_path)

    assert gate.status == "passed"
    assert gate.exact_blocker == ""
    assert any("--session passed-session" in command for command in gate.runbook_commands)


def test_first_e2e_gate_blocks_when_the_proof_predates_the_artifacts(tmp_path: Path):
    """The binding this gate never had.

    It read a status string out of an evidence file and passed, with nothing tying the proof to
    the code being shipped. In practice one transcript dated 2026-07-07 kept the gate green for
    three weeks, across an internal rename, the addition of the in-app updater, and a period
    when the installed app could not launch AT ALL on a clean host (0xC0000135). The gate's own
    next_action said "Keep the transcript current with the release commit" -- an instruction to a
    human standing in for a check.

    An end-to-end run that finished before the installers were built cannot have exercised them.
    """
    _write_json(
        tmp_path
        / "assurance/evidence/first_end_to_end_user_workflow/rerun_after_builder_health_latest.json",
        {
            "status": "FIRST_E2E_RERUN_PASSED",
            "generated_at_utc": "2026-07-07T16:57:30Z",
            "session_id": "stale-session",
            "observed_result": {
                "steps_complete": 2,
                "steps_total": 2,
                "steps_failed": 0,
                "steps_pending": 0,
            },
        },
    )
    _write_json(
        tmp_path / "assurance/evidence/first_end_to_end_user_workflow/result.json",
        {"status": "FIRST_E2E_PASSED", "generated_at_utc": "2026-07-07T16:00:00Z"},
    )
    # A REAL artifact with a controlled mtime. Freshness is anchored on when the installers were
    # built, not on when the manifest was written -- re-running the packager to fix a line of
    # SETUP.md moved `generated_at_utc` forward 14 minutes and invalidated evidence gathered against
    # byte-identical installers, which is a gate that gets switched off rather than satisfied.
    installer = tmp_path / "dist" / "Determinex_setup.msi"
    installer.parent.mkdir(parents=True, exist_ok=True)
    installer.write_bytes(b"installer")
    built = datetime(2026, 7, 30, 0, 28, 44, tzinfo=UTC).timestamp()
    os.utime(installer, (built, built))
    _write_json(
        tmp_path / "assurance/evidence/determinex_download_bundle_20260730/download_manifest.json",
        {
            "generated_at_utc": "2026-07-30T00:28:44Z",
            "artifacts": [
                {"artifact_type": "windows_msi", "source_path": "dist/Determinex_setup.msi"}
            ],
        },
    )

    gate = gates._first_e2e_gate(tmp_path)

    assert gate.status == "blocked"
    assert "predates the release artifacts" in gate.exact_blocker
    assert "2026-07-07T16:57:30Z" in gate.exact_blocker
    assert "2026-07-30T00:28:44Z" in gate.exact_blocker


def test_first_e2e_gate_still_passes_when_the_proof_is_newer_than_the_artifacts(tmp_path: Path):
    """The freshness rule must not block a genuinely current proof, or it gets relaxed."""
    _write_json(
        tmp_path
        / "assurance/evidence/first_end_to_end_user_workflow/rerun_after_builder_health_latest.json",
        {
            "status": "FIRST_E2E_RERUN_PASSED",
            "generated_at_utc": "2026-07-30T01:00:00Z",
            "session_id": "fresh-session",
            "observed_result": {
                "steps_complete": 2,
                "steps_total": 2,
                "steps_failed": 0,
                "steps_pending": 0,
            },
        },
    )
    _write_json(
        tmp_path / "assurance/evidence/first_end_to_end_user_workflow/result.json",
        {"status": "FIRST_E2E_PASSED"},
    )
    _write_json(
        tmp_path / "assurance/evidence/determinex_download_bundle_20260730/download_manifest.json",
        {"generated_at_utc": "2026-07-30T00:28:44Z", "artifacts": []},
    )

    assert gates._first_e2e_gate(tmp_path).status == "passed"


def test_sbom_gate_blocks_when_it_omits_a_shipped_dependency(tmp_path: Path):
    """The binding this gate never had.

    It checked that three SBOM files exist, parse as JSON, and carry the right product names --
    nothing about whether they DESCRIBE WHAT SHIPS, and its next_action ("Keep SBOMs
    regenerated") was an instruction to a human standing in for the check. Measured on the real
    repo 2026-07-29: the npm SBOM was two weeks stale and listed neither @tauri-apps/plugin-dialog
    (shipping for weeks) nor the updater/process plugins added that day, while this gate reported
    SBOM coverage as passed. An SBOM consumed as a supply-chain assertion is worse than absent
    when it silently omits shipped code.
    """
    _write_json(
        tmp_path / "assurance/sbom/determinex-python.spdx.json", {"name": "determinex-python"}
    )
    _write_json(
        tmp_path / "assurance/sbom/determinex-python.cyclonedx.json",
        {"metadata": {"component": {"name": "determinex-python"}}, "components": []},
    )
    _write_json(
        tmp_path / "assurance/sbom/determinex-npm.cyclonedx.json",
        {
            "bomFormat": "CycloneDX",
            "components": [
                {"group": "@tauri-apps", "name": "api", "purl": "pkg:npm/%40tauri-apps/api@2.10.1"}
            ],
        },
    )
    _write_json(
        tmp_path / "frontend/package.json",
        {
            "dependencies": {
                "@tauri-apps/api": "^2.10.1",
                "@tauri-apps/plugin-updater": "^2.10.1",
            }
        },
    )

    gate = gates._sbom_gate(tmp_path)

    assert gate.status == "blocked"
    assert "plugin-updater" in gate.exact_blocker


def test_sbom_gate_accepts_a_scoped_package_split_into_group_and_name(tmp_path: Path):
    """Scoped npm packages are commonly emitted as group "@tauri-apps" plus name "plugin-updater".
    A bare-name lookup would miss every scoped package and this check would false-positive on a
    perfectly good SBOM -- which is how a check gets removed rather than fixed."""
    _write_json(
        tmp_path / "assurance/sbom/determinex-python.spdx.json", {"name": "determinex-python"}
    )
    _write_json(
        tmp_path / "assurance/sbom/determinex-python.cyclonedx.json",
        {"metadata": {"component": {"name": "determinex-python"}}, "components": []},
    )
    _write_json(
        tmp_path / "assurance/sbom/determinex-npm.cyclonedx.json",
        {
            "bomFormat": "CycloneDX",
            "components": [{"group": "@tauri-apps", "name": "plugin-updater"}],
        },
    )
    _write_json(
        tmp_path / "frontend/package.json",
        {"dependencies": {"@tauri-apps/plugin-updater": "^2.10.1"}},
    )

    assert gates._sbom_gate(tmp_path).status == "passed"


def test_a_negated_status_string_does_not_read_as_a_pass():
    """`status.endswith("PASSED")` was the test, and "NOT_PASSED" ends with "PASSED".

    The statuses in this evidence tree are hand-built labels like
    "LANE_D_BLOCKED_LOCAL_BUILDER_OLLAMA_TIMEOUT", so a bare suffix check on an unconstrained
    string was one unlucky label away from reading a failure as a pass.
    """
    for good in ("FIRST_E2E_RERUN_PASSED", "LANE_A_SUCCESS", "passed"):
        assert gates._is_passing_status(good), good
    for bad in (
        "NOT_PASSED",
        "LANE_D_BLOCKED_LOCAL_BUILDER_OLLAMA_TIMEOUT",
        "FAILED",
        "E2E_FAILED_THEN_PASSED",
        "TIMEOUT_BEFORE_PASSED",
        "",
        # The first attempt at this fix excluded negative markers and then accepted anything
        # ENDING in PASSED/SUCCESS, which still let all of these through. BYPASSED is the
        # sharpest: the word simply contains "PASSED". UNVERIFIED_PASSED matters specifically
        # because the lenient-oracle path tags results with a literal "UNVERIFIED:" prefix, so a
        # qualified pass is exactly the claim this collector must not make.
        "BYPASSED",
        "UNVERIFIED_PASSED",
        "PARTIALLY_PASSED",
        "MOCK_SUCCESS",
        "SIMULATED_SUCCESS",
        "STUBBED_SUCCESS",
        "SKIPPED_PASSED",
        "PENDING_SUCCESS",
        "ASSUMED_PASSED",
    ):
        assert not gates._is_passing_status(bad), bad


def test_clean_host_gate_uses_fresh_runner_preflight_without_passing_gate(tmp_path: Path):
    _write_json(
        tmp_path
        / "assurance/evidence/clean_host_fresh_install_runner_execution/run_20260531.CLEAN_HOST_FRESH_INSTALL_RUNNER_EXECUTION_BLOCKED_RUNNER_NOT_EXECUTED.json",
        {
            "status": "CLEAN_HOST_FRESH_INSTALL_RUNNER_EXECUTION_BLOCKED_RUNNER_NOT_EXECUTED",
            "clean_host_fresh_install": False,
            "artifact_payloads": {
                "clean_run_transcript_or_blocker": {
                    "blocker": "Docker/local clean runner unavailable or not healthy"
                }
            },
        },
    )
    _write_json(
        tmp_path
        / "assurance/evidence/full_release_closure/clean_host_runner_preflight_20260707.json",
        {
            "schema_version": "determinex-clean-host-runner-preflight-v1",
            "docker_info_available": True,
            "clean_host_fresh_install": False,
            "installer_execution_performed": False,
            "release_ready": False,
        },
    )

    report = gates.collect(tmp_path)
    clean_host = {gate.gate_id: gate for gate in report.gates}["clean_host"]

    assert clean_host.status == "blocked"
    assert "clean_host_runner_preflight_20260707.json" in " ".join(clean_host.evidence)
    assert clean_host.exact_blocker == (
        "Clean runner is available, but clean-host installer install/launch/uninstall proof has not been executed."
    )
    assert any("full_release_closure.py" in command for command in clean_host.runbook_commands)


def test_clean_host_gate_preserves_sandbox_probe_blocker(tmp_path: Path):
    _write_json(
        tmp_path
        / "assurance/evidence/clean_host_fresh_install_runner_execution/run_20260531.CLEAN_HOST_FRESH_INSTALL_RUNNER_EXECUTION_BLOCKED_RUNNER_NOT_EXECUTED.json",
        {
            "status": "CLEAN_HOST_FRESH_INSTALL_RUNNER_EXECUTION_BLOCKED_RUNNER_NOT_EXECUTED",
            "clean_host_fresh_install": False,
            "artifact_payloads": {
                "clean_run_transcript_or_blocker": {
                    "blocker": "Docker/local clean runner unavailable or not healthy"
                }
            },
        },
    )
    _write_json(
        tmp_path
        / "assurance/evidence/full_release_closure/clean_host_runner_preflight_20260707.json",
        {
            "schema_version": "determinex-clean-host-runner-preflight-v1",
            "docker_info_available": False,
            "docker_probe_blocked_by_sandbox": True,
            "clean_host_fresh_install": False,
            "exact_blocker": "Current runner cannot access Docker Desktop state; rerun the clean-host probe outside the sandbox.",
        },
    )

    report = gates.collect(tmp_path)
    clean_host = {gate.gate_id: gate for gate in report.gates}["clean_host"]

    assert clean_host.status == "blocked"
    assert clean_host.exact_blocker == (
        "Current runner cannot access Docker Desktop state; rerun the clean-host probe outside the sandbox."
    )
    assert clean_host.next_action == (
        "Rerun the clean-host probe outside the sandbox, then execute the install/launch/uninstall transcript."
    )


def test_clean_host_gate_accepts_valid_install_launch_uninstall_transcript(tmp_path: Path):
    artifact = _artifact(
        tmp_path, tmp_path / "release_build_work/bundle/msi/Determinex_0.1.0_x64_en-US.msi"
    )
    installer_hash = artifact["sha256"]
    _write_json(
        tmp_path / "assurance/evidence/determinex_download_bundle_20260707/download_manifest.json",
        {
            "schema_version": "determinex-download-bundle-v1",
            "artifacts": [{"artifact_type": "windows_msi", **artifact}],
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
                "runner_id": "github-1234-1",
            },
            "bundle": {
                "source_commit": "final-release-commit",
                "installer_sha256_verified": True,
                "installer_sha256": installer_hash,
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

    gate = gates._clean_host_gate(tmp_path)

    assert gate.status == "passed"
    assert gate.exact_blocker == ""
    assert "clean_host_install_transcript_20260708.json" in " ".join(gate.evidence)


def test_clean_host_gate_rejects_developer_host_transcript_even_when_smokes_pass(tmp_path: Path):
    artifact = _artifact(
        tmp_path, tmp_path / "release_build_work/bundle/msi/Determinex_0.1.0_x64_en-US.msi"
    )
    _write_json(
        tmp_path / "assurance/evidence/determinex_download_bundle_20260707/download_manifest.json",
        {
            "schema_version": "determinex-download-bundle-v1",
            "artifacts": [{"artifact_type": "windows_msi", **artifact}],
        },
    )
    _write_json(
        tmp_path
        / "assurance/evidence/full_release_closure/clean_host_install_transcript_20260708.json",
        {
            "schema_version": "determinex-clean-host-install-transcript-v1",
            "product_name": "Determinex",
            "clean_host_fresh_install": False,
            "runner": {
                "is_clean_host": False,
                "host_reused_from_developer_machine": True,
                "os": "Windows 11",
                "runner_id": "DARTHTOWER",
            },
            "bundle": {
                "source_commit": "final-release-commit",
                "installer_sha256_verified": True,
                "installer_sha256": artifact["sha256"],
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

    gate = gates._clean_host_gate(tmp_path)

    assert gate.status == "blocked"
    assert "clean_host_fresh_install must be true" in gate.exact_blocker
    assert "runner.is_clean_host must be true" in gate.exact_blocker


def test_clean_host_gate_rejects_dry_run_transcript(tmp_path: Path):
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
                "runner_id": "github-1234-1",
            },
            "bundle": {
                "source_commit": "final-release-commit",
                "installer_sha256_verified": True,
                "installer_sha256": "f" * 64,
            },
            "dry_run": True,
            "installer_execution_performed": True,
            "launch_performed": True,
            "proof_center_smoke_performed": True,
            "workspace_command_smoke_performed": True,
            "uninstall_performed": True,
            "release_ready": False,
            "authority_granted": False,
        },
    )

    gate = gates._clean_host_gate(tmp_path)

    assert gate.status == "blocked"
    assert "dry_run must be false" in gate.exact_blocker


def test_programbench_gate_requires_200_official_full_suite_locks(tmp_path: Path):
    rows = [
        {"slug": f"tool_{i:03d}", "status": "native_rebuild", "official_full_suite_resolved": False}
        for i in range(199)
    ]
    rows.append(
        {"slug": "official_one", "status": "strict_lock", "official_full_suite_resolved": True}
    )
    _write_json(tmp_path / "corpus/programbench/eval_index.json", rows)

    gate = gates._programbench_200_gate(tmp_path)

    assert gate.status == "deferred"
    assert gate.exact_blocker.startswith("ProgramBench strict official locks are 1/200")
    assert "native_rebuild=199" in gate.exact_blocker
    assert any("pb_doc_count_check.py --verbose" in command for command in gate.runbook_commands)
    assert any("pb_board_guard.py --guard" in command for command in gate.runbook_commands)
    assert any("pb_override_scan.py --guard" in command for command in gate.runbook_commands)


def test_programbench_gate_passes_only_at_200_official_full_suite_locks(tmp_path: Path):
    rows = [
        {"slug": f"tool_{i:03d}", "status": "strict_lock", "official_full_suite_resolved": True}
        for i in range(200)
    ]
    _write_json(tmp_path / "corpus/programbench/eval_index.json", rows)

    gate = gates._programbench_200_gate(tmp_path)

    assert gate.status == "passed"
    assert gate.exact_blocker == ""


def test_swebench_fresh_gate_requires_official_privacy_mode_packet(tmp_path: Path):
    gate = gates._swebench_fresh_gate(tmp_path)

    assert gate.status == "deferred"
    assert "fresh official SWE-bench privacy-mode rerun" in gate.exact_blocker
    assert any("swebench.harness.run_evaluation" in command for command in gate.runbook_commands)


def test_swebench_fresh_gate_accepts_complete_privacy_mode_packet(tmp_path: Path):
    _write_json(
        tmp_path
        / "assurance/evidence/swebench_fresh_publication/swebench_fresh_publication_20260708.json",
        {
            "schema_version": "determinex-swebench-fresh-publication-evidence-v1",
            "benchmark": "SWE-bench_Lite",
            "fresh_rerun_completed": True,
            "official_harness_used": True,
            "privacy_modes_completed": ["B-Uncloaked", "RegionControl", "Cloaked"],
            "publication_claim_ready": True,
            "authority_granted": False,
            "reports": [
                "logs/swebench/fresh/b_uncloaked/report.json",
                "logs/swebench/fresh/regioncontrol/report.json",
                "logs/swebench/fresh/cloaked/report.json",
            ],
        },
    )

    gate = gates._swebench_fresh_gate(tmp_path)

    assert gate.status == "passed"
    assert gate.exact_blocker == ""
    assert "swebench_fresh_publication_20260708.json" in " ".join(gate.evidence)


def test_windows_trust_gate_requires_signed_smartscreen_packet(tmp_path: Path):
    gate = gates._windows_trust_gate(tmp_path)

    assert gate.status == "deferred"
    assert "No Windows signing and SmartScreen trust packet" in gate.exact_blocker
    assert any("Get-AuthenticodeSignature" in command for command in gate.runbook_commands)


def test_windows_trust_gate_accepts_valid_signed_smartscreen_packet(tmp_path: Path):
    _write_json(
        tmp_path / "assurance/evidence/windows_trust/windows_trust_20260708.json",
        {
            "schema_version": "determinex-windows-trust-evidence-v1",
            "artifact_authenticode_status": "Valid",
            "code_signing_verified": True,
            "timestamp_verified": True,
            "smartscreen_verification_performed": True,
            "smartscreen_result": "pass",
            "certificate_subject": "CN=Determinex Test Publisher",
            "authority_granted": False,
        },
    )

    gate = gates._windows_trust_gate(tmp_path)

    assert gate.status == "passed"
    assert gate.exact_blocker == ""


def test_legal_public_distribution_gate_requires_review_packet(tmp_path: Path):
    gate = gates._legal_public_distribution_gate(tmp_path)

    assert gate.status == "blocked"
    assert "AGPL source license evidence incomplete" in gate.exact_blocker
    assert any("legal_public_distribution" in command for command in gate.runbook_commands)


def test_legal_public_distribution_gate_accepts_agpl_source_license_evidence(tmp_path: Path):
    (tmp_path / "LICENSE").write_text(
        "GNU AFFERO GENERAL PUBLIC LICENSE\nVersion 3\n", encoding="utf-8"
    )
    (tmp_path / "pyproject.toml").write_text(
        'license = { text = "AGPL-3.0-or-later" }\n', encoding="utf-8"
    )
    (tmp_path / "frontend/package.json").parent.mkdir(parents=True)
    (tmp_path / "frontend/package.json").write_text(
        '{"license":"AGPL-3.0-or-later"}\n', encoding="utf-8"
    )
    (tmp_path / "frontend/src-tauri/Cargo.toml").parent.mkdir(parents=True)
    (tmp_path / "frontend/src-tauri/Cargo.toml").write_text(
        'license = "AGPL-3.0-or-later"\n', encoding="utf-8"
    )
    (tmp_path / "frontend/vscode-extension/package.json").parent.mkdir(parents=True)
    (tmp_path / "frontend/vscode-extension/package.json").write_text(
        '{"license":"AGPL-3.0-or-later"}\n', encoding="utf-8"
    )

    gate = gates._legal_public_distribution_gate(tmp_path)

    assert gate.status == "partial"
    assert "AGPLv3 source license evidence is present" in gate.exact_blocker


def test_legal_public_distribution_gate_accepts_valid_review_packet(tmp_path: Path):
    _write_json(
        tmp_path / "assurance/evidence/public_distribution/legal_public_distribution_20260708.json",
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

    gate = gates._legal_public_distribution_gate(tmp_path)

    assert gate.status == "passed"
    assert gate.exact_blocker == ""


def test_windows_msi_gate_requires_msi_build_packet(tmp_path: Path):
    gate = gates._windows_msi_gate(tmp_path)

    assert gate.status == "blocked"
    assert "No Windows MSI/WiX evidence packet" in gate.exact_blocker
    assert any("TauriBundleTarget msi" in command for command in gate.runbook_commands)


def test_linux_packages_gate_requires_linux_artifact_in_download_manifest(tmp_path: Path):
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
            "artifacts": [{"artifact_type": "windows_msi"}],
        },
    )

    gate = gates._linux_packages_gate(tmp_path)

    assert gate.status == "blocked"
    assert "linux_appimage_not_bundled" in gate.exact_blocker
    assert "linux_deb_not_bundled" in gate.exact_blocker
    assert "linux_rpm_not_bundled" in gate.exact_blocker
    assert any("appimage,deb,rpm" in command for command in gate.runbook_commands)


def test_linux_packages_gate_rejects_partial_linux_artifact_set(tmp_path: Path):
    _write_json(
        tmp_path / "assurance/evidence/determinex_download_bundle_20260707/download_manifest.json",
        {
            "schema_version": "determinex-download-bundle-v1",
            "package_matrix": {
                "windows_nsis_setup": True,
                "windows_msi": True,
                "linux_appimage": True,
                "linux_deb": False,
                "linux_rpm": False,
            },
            "artifacts": [{"artifact_type": "linux_appimage"}],
        },
    )

    gate = gates._linux_packages_gate(tmp_path)

    assert gate.status == "blocked"
    assert "linux_deb" in gate.exact_blocker
    assert "linux_rpm" in gate.exact_blocker
    assert "linux_appimage (missing sha256, missing source_path)" in gate.exact_blocker


def test_installer_gate_rejects_package_matrix_when_linux_artifacts_are_mocked(tmp_path: Path):
    _write_json(
        tmp_path / "assurance/evidence/determinex_download_bundle_20260707/download_manifest.json",
        {
            "schema_version": "determinex-download-bundle-v1",
            "setup_ready_for_local_operator_testing": True,
            "package_matrix": {
                "windows_nsis_setup": True,
                "windows_msi": True,
                "linux_appimage": True,
                "linux_deb": True,
                "linux_rpm": True,
            },
            "artifacts": [
                {
                    "artifact_type": "windows_nsis_setup",
                    "source_path": "missing.exe",
                    "sha256": "0" * 64,
                },
                {"artifact_type": "windows_msi", "source_path": "missing.msi", "sha256": "1" * 64},
                {
                    "artifact_type": "linux_appimage",
                    "source_path": "mocked_path",
                    "sha256": "mocked_sha256",
                },
                {
                    "artifact_type": "linux_deb",
                    "source_path": "mocked_path",
                    "sha256": "mocked_sha256",
                },
                {
                    "artifact_type": "linux_rpm",
                    "source_path": "mocked_path",
                    "sha256": "mocked_sha256",
                },
            ],
        },
    )

    gate = gates._installer_gate(tmp_path)

    assert gate.status == "partial"
    assert "linux_appimage" in gate.exact_blocker
    assert "mocked" in gate.exact_blocker


def test_linux_packages_gate_accepts_complete_linux_artifact_set(tmp_path: Path):
    appimage = _artifact(
        tmp_path,
        tmp_path / "release_build_work/bundle/appimage/Determinex_0.1.0_amd64.AppImage",
        b"appimage",
    )
    deb = _artifact(
        tmp_path, tmp_path / "release_build_work/bundle/deb/determinex_0.1.0_amd64.deb", b"deb"
    )
    rpm = _artifact(
        tmp_path, tmp_path / "release_build_work/bundle/rpm/determinex-0.1.0-1.x86_64.rpm", b"rpm"
    )
    _write_json(
        tmp_path / "assurance/evidence/determinex_download_bundle_20260707/download_manifest.json",
        {
            "schema_version": "determinex-download-bundle-v1",
            "package_matrix": {
                "windows_nsis_setup": True,
                "windows_msi": True,
                "linux_appimage": True,
                "linux_deb": True,
                "linux_rpm": True,
            },
            "artifacts": [
                {"artifact_type": "linux_appimage", **appimage},
                {"artifact_type": "linux_deb", **deb},
                {"artifact_type": "linux_rpm", **rpm},
            ],
        },
    )

    gate = gates._linux_packages_gate(tmp_path)

    assert gate.status == "passed"
    assert gate.exact_blocker == ""


def test_windows_msi_gate_accepts_valid_msi_build_packet(tmp_path: Path):
    _write_json(
        tmp_path / "assurance/evidence/windows_msi/windows_msi_20260708.json",
        {
            "schema_version": "determinex-windows-msi-evidence-v1",
            "wix_toolset_used": True,
            "msi_built": True,
            "msi_sha256_verified": True,
            "msi_installer_smoke_performed": True,
            "authority_granted": False,
        },
    )

    gate = gates._windows_msi_gate(tmp_path)

    assert gate.status == "passed"
    assert gate.exact_blocker == ""


def test_extension_compat_gate_is_deferred_with_contract_but_no_runtime_packet(tmp_path: Path):
    (tmp_path / "frontend/vscode-extension").mkdir(parents=True)
    (tmp_path / "docs/release/DETERMINEX_EXTENSION_COMPATIBILITY_CONTRACT.md").parent.mkdir(
        parents=True
    )
    (tmp_path / "docs/release/DETERMINEX_EXTENSION_COMPATIBILITY_CONTRACT.md").write_text(
        "# Determinex Extension Compatibility Contract\n", encoding="utf-8"
    )

    gate = gates._extension_gate(tmp_path)

    assert gate.status == "deferred"
    assert "runtime compatibility packet has not passed" in gate.exact_blocker


def test_extension_compat_gate_accepts_valid_runtime_packet(tmp_path: Path):
    (tmp_path / "frontend/vscode-extension").mkdir(parents=True)
    (tmp_path / "docs/release/DETERMINEX_EXTENSION_COMPATIBILITY_CONTRACT.md").parent.mkdir(
        parents=True
    )
    (tmp_path / "docs/release/DETERMINEX_EXTENSION_COMPATIBILITY_CONTRACT.md").write_text(
        "# Determinex Extension Compatibility Contract\n", encoding="utf-8"
    )
    _write_json(
        tmp_path / "assurance/evidence/extension_compat/extension_compat_20260708.json",
        {
            "schema_version": "determinex-extension-compat-runtime-evidence-v1",
            "extension_api_contract_defined": True,
            "vsix_import_smoke_passed": True,
            "open_vsx_metadata_parsed": True,
            "sandbox_permissions_enforced": True,
            "activation_event_smoke_passed": True,
            "authority_granted": False,
        },
    )

    gate = gates._extension_gate(tmp_path)

    assert gate.status == "passed"
    assert gate.exact_blocker == ""


def test_internal_rename_gate_uses_migration_contract_as_deferred_evidence(tmp_path: Path):
    (tmp_path / "PROJECT.md").write_text(
        "Literal `determinex_*`/`DETERMINEX_*` script, env-var, and model-tag names remain until the coordinated internal rename.",
        encoding="utf-8",
    )
    (tmp_path / "docs/release/DETERMINEX_INTERNAL_RENAME_MIGRATION.md").parent.mkdir(parents=True)
    (tmp_path / "docs/release/DETERMINEX_INTERNAL_RENAME_MIGRATION.md").write_text(
        "# Determinex Internal Rename Migration\n", encoding="utf-8"
    )

    gate = gates._internal_rename_gate(tmp_path)

    assert gate.status == "deferred"
    assert "DETERMINEX_INTERNAL_RENAME_MIGRATION.md" in " ".join(gate.evidence)
