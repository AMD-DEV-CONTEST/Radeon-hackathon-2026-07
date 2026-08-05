import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "release" / "build_release_package.ps1"


def test_release_build_script_anchors_paths_to_script_location():
    text = SCRIPT.read_text(encoding="utf-8")

    assert "$PSScriptRoot" in text
    assert "$RepoRoot" in text
    assert "Push-Location $FrontendDir" in text
    assert 'Push-Location "..\\..\\frontend"' not in text


def test_release_build_script_uses_deterministic_dependency_install():
    text = SCRIPT.read_text(encoding="utf-8")

    assert "$NpmExe" in text
    assert '"npm.cmd"' in text
    assert "& $NpmExe ci" in text
    assert "npm install" not in text


def test_release_build_script_generates_required_sbom_artifacts():
    text = SCRIPT.read_text(encoding="utf-8")

    assert "$VenvPython" in text
    assert "$PythonExe" in text
    assert "determinex-npm.cyclonedx.json" in text
    assert "determinex-python.spdx.json" in text
    assert "determinex-python.cyclonedx.json" in text
    assert "scripts\\security\\generate_sbom.py" in text
    assert "Expected SBOM artifact was not generated" in text
    assert "cargo-cyclonedx is not installed" not in text


def test_release_build_script_has_cargo_lock_workarounds():
    text = SCRIPT.read_text(encoding="utf-8")

    assert "[string]$CargoTargetDir" in text
    assert "$env:CARGO_TARGET_DIR = $CargoTargetDir" in text
    assert '$env:CARGO_BUILD_JOBS = "1"' in text
    assert '$env:CARGO_INCREMENTAL = "0"' in text
    assert "function Get-InstallerDir" in text
    assert 'Join-Path $env:CARGO_TARGET_DIR "release\\bundle"' in text


def test_release_build_script_has_optional_authenticode_signing_route():
    text = SCRIPT.read_text(encoding="utf-8")

    assert "[string]$SigningCertificateThumbprint" in text
    assert "DETERMINEX_SIGNING_CERT_THUMBPRINT" in text
    assert "DETERMINEX_TIMESTAMP_URL" in text
    assert "signtool" in text
    assert "Authenticode signing" in text
    assert "installers remain unsigned" in text


def test_release_build_script_can_package_download_bundle():
    text = SCRIPT.read_text(encoding="utf-8")

    assert "[switch]$PackageDownloadBundle" in text
    assert "[string]$TauriBundleTarget" in text
    assert "$EffectiveTauriBundleTarget = if ($TauriBundleTarget)" in text
    # 2026-07-19: "all" is not a valid --bundles value for tauri-cli on Windows
    # (only an explicit msi,nsis list is) -- this assertion used to lock in
    # that exact broken default, meaning the documented -PackageDownloadBundle
    # runbook command had never actually succeeded on Windows. Fixed live: ran
    # a full local release build end to end (MSI + NSIS + download bundle) to
    # confirm the corrected default genuinely works, not just that the text
    # changed.
    assert 'elseif ($PackageDownloadBundle) { "msi,nsis" }' in text
    assert 'elseif ($PackageDownloadBundle) { "all" }' not in text
    assert "& $NpmExe run tauri -- build --bundles $EffectiveTauriBundleTarget" in text
    assert "[string]$DownloadBundleOutputDir" in text
    assert "[string]$DownloadBundleEvidenceDir" in text
    assert "[string]$WindowsMsiEvidenceDir" in text
    assert "scripts\\release\\package_download_bundle.py" in text
    assert "--installer-dir $InstallerDir" in text
    assert "--output-dir $EffectiveDownloadBundleOutputDir" in text
    assert "--evidence-dir $EffectiveDownloadBundleEvidenceDir" in text
    assert "--windows-msi-evidence-dir $EffectiveWindowsMsiEvidenceDir" in text


def test_authenticode_signing_does_not_splat_the_automatic_args_variable():
    """Authenticode signing had never worked.

    The signing loop built its argument array in `$Args` and then ran
    `Invoke-Checked ... { signtool @Args }`. `$Args` is a PowerShell AUTOMATIC variable, and
    Invoke-Checked runs the block as `& $Command` with no arguments, so inside the block `$Args`
    is that invocation's own empty argument list -- not the array built outside. `signtool @Args`
    therefore splatted nothing: signtool ran bare, printed usage, and the step failed with a
    generic nonzero exit that looks like a certificate problem. Verified directly:

        $Args = @("a","b"); & { $Args.Count }   -> 0
        $S    = @("a","b"); & { $S.Count }      -> 2

    Nothing caught it because the path is only reached once a signing thumbprint is configured,
    and `windows_trust` is still deferred pending a purchased certificate. It would have
    surfaced as a confusing failure on the first real signing attempt.
    """
    text = SCRIPT.read_text(encoding="utf-8")
    assert "$Args = @(" not in text, (
        "the signing loop assigns the automatic variable $Args; inside the Invoke-Checked "
        "scriptblock that resolves to an empty list and signtool receives no arguments"
    )
    assert "signtool @Args" not in text, "signtool is splatting the automatic $Args variable"
    assert "signtool @SignArgs" in text, "signing must splat a non-automatic variable name"


def test_updater_signing_key_uses_the_variable_the_bundler_actually_reads():
    """`tauri signer generate` advertises both TAURI_SIGNING_PRIVATE_KEY and
    ..._PATH, but the bundler reads only the former (trying the value as a file path first,
    then as literal key content). Setting _PATH built both installers and then failed at the
    final step with "A public key has been found, but no private key", which reads as a missing
    key rather than a misnamed variable."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert "$env:TAURI_SIGNING_PRIVATE_KEY = (Get-Content" in text, (
        "TAURI_SIGNING_PRIVATE_KEY must carry the key CONTENT; a Windows path is not base64 and "
        "fails on the ':' at offset 1, which the bundler reports as no artifacts and no error"
    )
    assert "$env:TAURI_SIGNING_PRIVATE_KEY_PATH = $LocalUpdaterKey" in text, (
        "..._PATH must also be set, since that is the variable documented to take a file"
    )
    assert "TAURI_SIGNING_PRIVATE_KEY_PASSWORD" in text, (
        "the script must still address the password variable — the signer blocks on an interactive "
        "prompt when it is absent, which hangs a non-interactive build"
    )


def test_the_script_does_not_try_to_pass_an_empty_password_via_the_environment():
    """It is not possible, and pretending otherwise hid a real hang.

    The script used to do this, with a rationale that was false on its own platform:

        # Set explicitly even when empty: the signer prompts for a password interactively
        # when the variable is absent, and a prompt in a non-interactive build hangs.
        if (-not $env:TAURI_SIGNING_PRIVATE_KEY_PASSWORD) {
            $env:TAURI_SIGNING_PRIVATE_KEY_PASSWORD = ""
        }

    Measured on Windows 2026-07-30: after `$env:X = ""`, `Test-Path Env:\\X` is False,
    `[Environment]::GetEnvironmentVariable('X')` is `$null`, and `cmd /c "if defined X"` reports
    UNDEFINED. Assigning an empty string DELETES the variable, and .NET's `SetEnvironmentVariable`
    documents the same. So "defined but empty" cannot be handed to a child process, and the guard was
    a no-op that read like a fix.

    The consequence was real rather than cosmetic: `tauri signer sign` genuinely blocks on a password
    prompt when the variable is absent, reproduced live until killed. A passwordless updater key
    therefore cannot satisfy the bundler's signing step at all, because the bundler takes no password
    flag. See docs/release/UPDATER_ARTIFACTS.md.
    """
    text = SCRIPT.read_text(encoding="utf-8")
    # Only flag a real assignment, not the commented-out record of the old code or the warning text.
    live = [
        line
        for line in text.splitlines()
        if "TAURI_SIGNING_PRIVATE_KEY_PASSWORD" in line
        and not line.lstrip().startswith("#")
        and re.search(r'PRIVATE_KEY_PASSWORD\s*=\s*""\s*$', line)
    ]
    assert not live, (
        f"assigning an empty string to TAURI_SIGNING_PRIVATE_KEY_PASSWORD deletes it on Windows, so "
        f"this cannot work and masks the interactive prompt it claims to prevent: {live}"
    )
