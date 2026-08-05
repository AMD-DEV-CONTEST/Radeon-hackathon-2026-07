from __future__ import annotations

import json
from pathlib import Path

from scripts.release import clean_host_install_transcript as transcript


def test_template_is_not_release_ready_and_names_required_steps():
    payload = transcript.build_template("2026-07-08T00:00:00Z")

    assert payload["schema_version"] == "determinex-clean-host-install-transcript-v1"
    assert payload["product_name"] == "Determinex"
    assert payload["clean_host_fresh_install"] is False
    assert payload["release_ready"] is False
    assert payload["authority_granted"] is False
    assert "install Determinex setup artifact" in " ".join(payload["required_steps"])
    assert "uninstall Determinex" in " ".join(payload["required_steps"])


def test_validate_file_accepts_complete_transcript(tmp_path: Path):
    path = tmp_path / "clean_host_install_transcript_20260708.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "determinex-clean-host-install-transcript-v1",
                "product_name": "Determinex",
                "clean_host_fresh_install": True,
                "runner": {
                    "is_clean_host": True,
                    "host_reused_from_developer_machine": False,
                    "os": "Windows 11",
                    "runner_id": "clean-host-runner-20260708",
                },
                "bundle": {
                    "source_commit": "final-release-commit",
                    "installer_sha256_verified": True,
                    "installer_sha256": "a" * 64,
                },
                "dry_run": False,
                "installer_execution_performed": True,
                "launch_performed": True,
                "proof_center_smoke_performed": True,
                "workspace_command_smoke_performed": True,
                "uninstall_performed": True,
                "release_ready": False,
                "authority_granted": False,
            }
        ),
        encoding="utf-8",
    )

    result = transcript.validate_file(path)

    assert result["status"] == "passed"
    assert result["errors"] == []


def test_validate_file_rejects_partial_or_dry_run_transcript(tmp_path: Path):
    path = tmp_path / "clean_host_install_transcript_20260708.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "determinex-clean-host-install-transcript-v1",
                "product_name": "Determinex",
                "clean_host_fresh_install": True,
                "runner": {
                    "is_clean_host": True,
                    "host_reused_from_developer_machine": False,
                    "os": "Windows 11",
                },
                "bundle": {
                    "source_commit": "final-release-commit",
                    "installer_sha256_verified": True,
                },
                "dry_run": True,
                "installer_execution_performed": True,
                "launch_performed": False,
                "proof_center_smoke_performed": True,
                "workspace_command_smoke_performed": True,
                "uninstall_performed": True,
                "release_ready": False,
                "authority_granted": False,
            }
        ),
        encoding="utf-8",
    )

    result = transcript.validate_file(path)

    assert result["status"] == "blocked"
    assert "dry_run must be false" in result["errors"]
    assert "launch_performed must be true" in result["errors"]


def test_windows_clean_host_smoke_script_installs_launches_and_validates_transcript():
    root = Path(__file__).resolve().parents[1]
    script = root / "scripts" / "release" / "run_windows_clean_host_install_smoke.ps1"
    text = script.read_text(encoding="utf-8")

    assert "msiexec.exe" in text
    assert "Start-Process" in text
    assert "Get-AuthenticodeSignature" in text
    assert "Test-BinaryContainsAscii" in text
    assert "frontend\\out" not in text
    assert "clean_host_install_transcript.py" in text
    assert "installer_execution_performed = $InstallPassed" in text
    assert "launch_performed = $LaunchPassed" in text
    assert "proof_center_smoke_performed = $ProofCenterSmokePassed" in text
    assert "workspace_command_smoke_performed = $WorkspaceSmokePassed" in text
    assert "uninstall_performed = $UninstallPassed" in text
    assert "[switch]$AllowDeveloperHostSmoke" in text
    assert "$IsGitHubWindowsRunner = $true" not in text
    assert '$env:GITHUB_ACTIONS -eq "true"' in text
    assert "-AllowDeveloperHostSmoke" in text
    assert "Developer-host smoke transcript written" in text

    # ── the attestation must rest on host EVIDENCE, not on an env var ─────────
    #
    # Updated 2026-07-29. This block previously pinned
    # `host_reused_from_developer_machine = -not $IsGitHubWindowsRunner`, i.e. it locked in
    # the very thing that was wrong: clean_host_fresh_install was assigned "am I inside
    # GitHub Actions" rather than any property of the machine. That was simultaneously too
    # strict (a freshly provisioned VM could never satisfy the gate, and re-imaging did not
    # help because cleanliness was never examined) and too weak (an environment variable is
    # not proof -- anything able to set GITHUB_ACTIONS=true produced an authorizing
    # transcript).
    #
    # The claim now derives from two checkable facts, with the GitHub-runner path kept as
    # one way to qualify so nothing got weaker:
    assert "$IsCleanHost = $IsGitHubWindowsRunner -or $IsEvidenceCleanHost" in text, (
        "the clean-host claim must accept an ephemeral runner OR host evidence"
    )
    assert "clean_host_fresh_install = $IsCleanHost" in text, (
        "clean_host_fresh_install must come from the cleanliness decision, not from GITHUB_ACTIONS"
    )
    assert "host_reused_from_developer_machine = -not $IsCleanHost" in text
    # No prior install of the product, and no developer toolchain that would satisfy a
    # dependency the installer is supposed to ship. Both are what a clean-host installer
    # test actually needs to establish.
    assert "$HasPriorInstall" in text
    assert "$HasDevToolchain" in text
    assert "CurrentVersion\\Uninstall" in text, (
        "prior-install check must read the uninstall registry"
    )
    for tool in ("cargo", "rustc", "node", "npm"):
        assert f'"{tool}"' in text, f"dev-toolchain probe must look for {tool}"
    # The transcript has to say which evidence carried it, or a reader cannot tell an
    # ephemeral runner from a machine that merely looked clean.
    assert "clean_host_basis = $CleanHostBasis" in text
    assert "ephemeral_github_windows_runner" in text
    assert "host_evidence_no_prior_install_no_dev_toolchain" in text


def test_the_smoke_records_whether_the_host_already_had_the_vc_runtime():
    """Added 2026-07-29, after a launch failure the transcript could not explain.

    determinex.exe links the MSVC runtime dynamically, so the runtime is THE dependency the
    installer must deliver. On a host that already has it the app starts whether or not the
    installer did its job -- a passing launch check there proves nothing. That is not
    theoretical: the first clean-host run failed launch because the MSI's VC++ custom action
    was being pruned away, and the second host had the runtime installed by then, which would
    have produced a green transcript for the wrong reason.

    Recorded rather than enforced: a GitHub Windows runner ships with the redistributable, so
    requiring absence would make that blessed path unsatisfiable. But the fact has to be IN
    the transcript, or a reader cannot distinguish a real proof from a vacuous one.
    """
    root = Path(__file__).resolve().parents[1]
    text = (root / "scripts" / "release" / "run_windows_clean_host_install_smoke.ps1").read_text(
        encoding="utf-8"
    )
    assert "vc_runtime_preinstalled = $HasVcRuntimePreinstalled" in text
    assert "vc_runtime_preinstalled_files" in text
    for dll in ("vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll"):
        assert dll in text, f"runtime probe must look for {dll}"


def test_the_smoke_records_the_launch_exit_code_not_just_that_it_exited():
    """A boolean was true and useless.

    The first failing clean-host transcript said only
    `launch_process_exited_during_smoke: true`. The exit code was 0xC0000135
    (STATUS_DLL_NOT_FOUND) -- the single fact that identified a missing VC++ runtime rather
    than a crash in the app, a WebView2 problem, or the absence of an interactive desktop.
    Recovering it took a separate round-trip to the host, which the transcript exists to
    avoid.
    """
    root = Path(__file__).resolve().parents[1]
    text = (root / "scripts" / "release" / "run_windows_clean_host_install_smoke.ps1").read_text(
        encoding="utf-8"
    )
    assert "launch_exit_code = $launchExitCode" in text
    assert "launch_exit_code_hex = $launchExitCodeHex" in text
    # WaitForExit returns as soon as the process dies AND leaves ExitCode readable; the old
    # sleep-then-Refresh shape discarded it.
    assert "$process.WaitForExit(" in text, "launch must use WaitForExit so the exit code survives"
