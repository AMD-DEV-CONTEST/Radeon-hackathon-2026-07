<#
.SYNOPSIS
Runs a Windows clean-host install/launch/uninstall smoke and writes a release transcript.

.DESCRIPTION
This script is intended for an ephemeral Windows CI runner or Windows Sandbox/VM.
It installs the packaged Determinex MSI/NSIS artifact, launches the installed app,
checks that the packaged Proof Center route was built, performs a minimal installed
workspace-resource smoke, uninstalls, and writes a transcript consumable by
clean_host_install_transcript.py.
#>

param(
    # Empty by default and resolved below to the newest bundle. It used to name
    # determinex_download_bundle_20260707 outright, which every rebuild made stale -- and on
    # 2026-07-31 that produced a clean-host transcript attesting installer_sha256_verified=true
    # for an installer that appears in no manifest this script could see.
    [string]$ManifestPath = "",
    [string]$InstallerPath,
    [string]$OutputPath = "assurance\evidence\full_release_closure\clean_host_install_transcript_ci.json",
    [int]$LaunchSeconds = 10,
    [switch]$AllowDeveloperHostSmoke
)

$ErrorActionPreference = "Stop"

$ScriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $PSCommandPath }
$RepoRoot = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path
function Resolve-NewestManifest {
    <#
    The PowerShell twin of determinex_release_gates.newest_download_manifest_path: newest
    determinex_download_bundle_*/download_manifest.json by LastWriteTime. Two implementations of
    one rule is one more than ideal, but this script also runs on a clean host with no repo venv,
    so it cannot call the Python. Keep the ordering rule identical -- a test asserts the two agree.
    #>
    param([Parameter(Mandatory=$true)][string]$Root)

    $evidence = Join-Path $Root "assurance\evidence"
    if (!(Test-Path -LiteralPath $evidence)) { return "" }
    $found = Get-ChildItem -LiteralPath $evidence -Directory -Filter "determinex_download_bundle_*" -ErrorAction SilentlyContinue |
        ForEach-Object { Join-Path $_.FullName "download_manifest.json" } |
        Where-Object { Test-Path -LiteralPath $_ } |
        Sort-Object { (Get-Item -LiteralPath $_).LastWriteTime } -Descending |
        Select-Object -First 1
    if ($found) { return $found }
    return ""
}

$ManifestFullPath = if ($ManifestPath) {
    if ([System.IO.Path]::IsPathRooted($ManifestPath)) { $ManifestPath } else { Join-Path $RepoRoot $ManifestPath }
} else {
    $auto = Resolve-NewestManifest -Root $RepoRoot
    if (!$auto) {
        throw ("No determinex_download_bundle_*/download_manifest.json under " +
            (Join-Path $RepoRoot "assurance\evidence") +
            ". Package a bundle first, or pass -ManifestPath explicitly.")
    }
    $auto
}
$OutputFullPath = if ([System.IO.Path]::IsPathRooted($OutputPath)) { $OutputPath } else { Join-Path $RepoRoot $OutputPath }

function Get-Sha256Hex {
    param([Parameter(Mandatory=$true)][string]$Path)
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

function Resolve-InstallerFromManifest {
    param([Parameter(Mandatory=$true)]$Manifest)

    $artifacts = @($Manifest.artifacts)
    $preferred = $artifacts | Where-Object { $_.artifact_type -eq "windows_msi" } | Select-Object -First 1
    if (!$preferred) {
        $preferred = $artifacts | Where-Object { $_.artifact_type -eq "windows_nsis_setup" } | Select-Object -First 1
    }
    if (!$preferred) {
        throw "No Windows installer artifact was found in $ManifestFullPath"
    }

    $candidatePaths = @()
    if ($preferred.source_path) {
        $candidatePaths += $preferred.source_path
        $candidatePaths += (Join-Path $RepoRoot $preferred.source_path)
    }
    if ($preferred.bundle_relative_path -and $Manifest.bundle_dir) {
        $candidatePaths += (Join-Path $Manifest.bundle_dir $preferred.bundle_relative_path)
        $candidatePaths += (Join-Path $RepoRoot (Join-Path $Manifest.bundle_dir $preferred.bundle_relative_path))
    }

    foreach ($candidate in $candidatePaths) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return @{
                Path = (Resolve-Path -LiteralPath $candidate).Path
                Artifact = $preferred
            }
        }
    }
    throw "Installer artifact listed in manifest could not be found: $($preferred.file_name)"
}

function Invoke-Installer {
    param(
        [Parameter(Mandatory=$true)][string]$Path,
        [Parameter(Mandatory=$true)][ValidateSet("install", "uninstall")][string]$Mode
    )

    $extension = [System.IO.Path]::GetExtension($Path).ToLowerInvariant()
    if ($extension -eq ".msi") {
        $verb = if ($Mode -eq "install") { "/i" } else { "/x" }
        return Start-Process -FilePath "msiexec.exe" -ArgumentList @($verb, "`"$Path`"", "ALLUSERS=2", "MSIINSTALLPERUSER=1", "/qn", "/norestart") -Wait -PassThru
    }
    if ($extension -eq ".exe") {
        if ($Mode -eq "install") {
            return Start-Process -FilePath $Path -ArgumentList @("/S") -Wait -PassThru
        }
        # Same directory mismatch as Find-InstalledExe: installer.nsi puts a currentUser install in
        # "$LOCALAPPDATA\Determinex", which was missing from this list entirely.
        # Same WOW64 redirection as Find-InstalledExe: a 32-bit NSIS stub running as SYSTEM writes
        # under SysWOW64, so the uninstaller is not where LOCALAPPDATA says either.
        # `-replace` takes a REGEX, so the separators must be escaped: '\s' is the whitespace class,
        # and a lone trailing '\' is an invalid escape. Got this wrong once here already.
        $sysNativeUn = if ($env:LOCALAPPDATA -like "*\system32\*") {
            $env:LOCALAPPDATA -replace '\\system32\\', '\SysWOW64\'
        } else { $null }
        $uninstallCandidates = @(
            (Join-Path $env:LOCALAPPDATA "Determinex\uninstall.exe"),
            (Join-Path $env:LOCALAPPDATA "Programs\Determinex\uninstall.exe"),
            (Join-Path $env:ProgramFiles "Determinex\uninstall.exe"),
            (Join-Path ${env:ProgramFiles(x86)} "Determinex\uninstall.exe")
        )
        if ($sysNativeUn) {
            $uninstallCandidates += (Join-Path $sysNativeUn "Determinex\uninstall.exe")
            $uninstallCandidates += (Join-Path $sysNativeUn "Programs\Determinex\uninstall.exe")
        }
        $uninstaller = $uninstallCandidates | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
        if (!$uninstaller) {
            throw ("NSIS uninstaller not found in any of: " + ($uninstallCandidates -join "; "))
        }
        return Start-Process -FilePath $uninstaller -ArgumentList @("/S") -Wait -PassThru
    }
    throw "Unsupported installer extension: $extension"
}

function Find-InstalledExe {
    # Two defects fixed here 2026-07-30, both of which made this report success wrongly.
    #
    # 1. "C:\tmp\determinex-smoke-install\determinex.exe" was listed FIRST. That is one developer's
    #    scratch directory, and on this machine it still held a determinex.exe from 2026-07-21. So a
    #    local run of this smoke test resolved to a stale binary from a previous session and every
    #    downstream check -- launch, ASCII probe -- passed against an artifact the installer under
    #    test had not produced. On a genuinely clean host the path is absent, which is exactly why
    #    it survived: the gate could not see it, only a developer re-running locally could.
    #
    # 2. The per-user candidate was "$LOCALAPPDATA\Programs\Determinex". The generated
    #    installer.nsi sets `StrCpy $INSTDIR "$LOCALAPPDATA\${PRODUCTNAME}"` for INSTALLMODE
    #    currentUser -- no "Programs" segment. So a correct per-user NSIS install would never have
    #    been found here, and the failure would read as "the installer installed nothing".
    # 3. WOW64 REDIRECTION, found 2026-07-30 on the clean-host VM. Tauri's NSIS stub is a 32-bit
    #    process (makensis reports "x86-unicode"). When this smoke runs as SYSTEM -- which it does
    #    under `az vm run-command` -- $env:LOCALAPPDATA is
    #    C:\Windows\system32\config\systemprofile\AppData\Local, and Windows redirects `system32` to
    #    `SysWOW64` for a 32-bit process. So the installer's files land under SysWOW64 while the HKCU
    #    registry records the UN-redirected system32 path. Files and registry then disagree, and the
    #    result reads exactly like the original S7 report: "exits 0, writes an uninstall entry, and
    #    that directory does not exist".
    #
    #    It is an artefact of installing as SYSTEM, not a product defect -- an interactive install runs
    #    as the user, where %LOCALAPPDATA% is C:\Users\<name>\AppData\Local with no `system32` segment
    #    to redirect. But this script DOES run as SYSTEM, so it has to look in both.
    $sysNative = if ($env:LOCALAPPDATA -like "*\system32\*") {
        $env:LOCALAPPDATA -replace '\\system32\\', '\SysWOW64\'
    } else { $null }

    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Determinex\determinex.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Determinex\determinex.exe"),
        (Join-Path $env:ProgramFiles "Determinex\determinex.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "Determinex\determinex.exe")
    )
    if ($sysNative) {
        $candidates += (Join-Path $sysNative "Determinex\determinex.exe")
        $candidates += (Join-Path $sysNative "Programs\Determinex\determinex.exe")
    }
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    return ""
}

function Test-BinaryContainsAscii {
    param(
        [Parameter(Mandatory=$true)][string]$Path,
        [Parameter(Mandatory=$true)][string]$Needle
    )

    if (!(Test-Path -LiteralPath $Path)) {
        return $false
    }
    $bytes = [System.IO.File]::ReadAllBytes($Path)
    $text = [System.Text.Encoding]::ASCII.GetString($bytes)
    return $text.Contains($Needle)
}

if (!(Test-Path -LiteralPath $ManifestFullPath)) {
    throw "Missing download manifest: $ManifestFullPath"
}

$manifest = Get-Content -LiteralPath $ManifestFullPath -Raw | ConvertFrom-Json
$resolved = if ($InstallerPath) {
    @{
        Path = (Resolve-Path -LiteralPath $InstallerPath).Path
        Artifact = $null
    }
} else {
    Resolve-InstallerFromManifest -Manifest $manifest
}

$InstallerFullPath = $resolved.Path
$artifact = $resolved.Artifact
$installerSha256 = Get-Sha256Hex -Path $InstallerFullPath

# `installer_sha256_verified` used to be set to $true whenever there was nothing to compare
# against -- which is every -InstallerPath run, because that branch sets Artifact to $null.
# So the field read "verified" precisely when no verification had happened, and it caught me
# with it on 2026-07-31: a clean-host NSIS transcript attested
# installer_sha256_verified=true for d1f369ef..., an installer that is NOT the ff21a812...
# artifact the manifest ships. The transcript was internally consistent and wrong.
#
# Fail closed instead, and match an explicitly-supplied installer against the manifest by
# hash so -InstallerPath still earns a real true when it points at a shipped artifact.
$installerSha256Verified = $false
$installerSha256Basis = "no_manifest_artifact_to_compare"
if ($artifact -and $artifact.sha256) {
    $installerSha256Verified = ($installerSha256 -eq [string]$artifact.sha256)
    $installerSha256Basis = if ($installerSha256Verified) {
        "matched manifest artifact $($artifact.file_name)"
    } else {
        "MISMATCH against manifest artifact $($artifact.file_name) ($($artifact.sha256))"
    }
} else {
    $manifestMatch = @($manifest.artifacts) |
        Where-Object { $_.sha256 -and ([string]$_.sha256 -eq $installerSha256) } |
        Select-Object -First 1
    if ($manifestMatch) {
        $installerSha256Verified = $true
        $installerSha256Basis = "explicit -InstallerPath matched manifest artifact $($manifestMatch.file_name) by hash"
        $artifact = $manifestMatch
    } else {
        $manifestHashes = @($manifest.artifacts | Where-Object { $_.sha256 } |
            ForEach-Object { "$($_.file_name)=$($_.sha256)" })
        $installerSha256Basis = ("explicit -InstallerPath $installerSha256 matches NO manifest artifact; " +
            "manifest lists " + ($manifestHashes -join ", "))
    }
}

$signature = Get-AuthenticodeSignature -LiteralPath $InstallerFullPath
$IsGitHubWindowsRunner = ($env:GITHUB_ACTIONS -eq "true") -and [bool]$env:GITHUB_RUN_ID

# ── Is this actually a clean host? ───────────────────────────────────────────
#
# WHY THIS EXISTS (2026-07-29). clean_host_fresh_install used to be assigned
# $IsGitHubWindowsRunner directly -- the transcript attested "am I inside GitHub Actions",
# not any property of the machine. That was wrong in both directions:
#
#   TOO STRICT  a freshly provisioned cloud VM reported false and self-labelled as a
#               reused developer host, so no amount of reprovisioning could satisfy the
#               gate. Re-imaging does not help when cleanliness is never examined.
#   TOO WEAK    an environment variable is not proof. Anything able to set
#               GITHUB_ACTIONS=true produced an authorizing transcript.
#
# What a clean-host installer test must actually establish is that the app installs and
# runs WITHOUT the developer environment: nothing of it installed already, and no dev
# toolchain present that could quietly satisfy a dependency the installer should ship.
# Both are directly checkable, so they are checked, and the basis is recorded in the
# transcript so a reader can see which evidence carried it.
#
# This is ADDITIVE: the GitHub-runner path still qualifies on its own. It only stops the
# gate being unsatisfiable by any other genuinely clean machine.

$priorInstallKeys = @(
    "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*",
    "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*",
    "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*"
)
$priorInstalls = @()
foreach ($keyPattern in $priorInstallKeys) {
    try {
        $priorInstalls += Get-ItemProperty -Path $keyPattern -ErrorAction SilentlyContinue |
            Where-Object { $_.DisplayName -and $_.DisplayName -like "*Determinex*" } |
            Select-Object -ExpandProperty DisplayName
    } catch { }
}
$HasPriorInstall = @($priorInstalls).Count -gt 0

# A developer box has these; a clean host does not. If they are present, the installer's
# dependency handling is not being tested -- the machine already satisfies it.
$devTools = @("cargo", "rustc", "node", "npm")
$devToolsFound = @()
foreach ($tool in $devTools) {
    if (Get-Command $tool -ErrorAction SilentlyContinue) { $devToolsFound += $tool }
}
$HasDevToolchain = @($devToolsFound).Count -gt 0

# The MSVC runtime determinex.exe links against dynamically. This is THE dependency the
# installer has to deliver, so whether the host already had it decides whether a passing
# launch check means anything: on a host that already has it, the app starts whether or not
# the installer did its job. That is not hypothetical -- it is how a real bug hid until
# 2026-07-29, when a clean host showed determinex.exe dying with 0xC0000135 because the WiX
# fragment meant to install the redistributable was being silently pruned from the MSI.
#
# Recorded rather than enforced: a GitHub Windows runner ships with the redistributable, so
# requiring its absence would make that blessed path unsatisfiable. But a reader can now
# tell a real proof from a vacuous one instead of having to guess.
$vcRuntimeNames = @("vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll")
$vcRuntimeFound = @($vcRuntimeNames | Where-Object {
    Test-Path -LiteralPath (Join-Path $env:SystemRoot "System32\$_")
})
$HasVcRuntimePreinstalled = @($vcRuntimeFound).Count -gt 0

$IsEvidenceCleanHost = (-not $HasPriorInstall) -and (-not $HasDevToolchain)
$IsCleanHost = $IsGitHubWindowsRunner -or $IsEvidenceCleanHost
$CleanHostBasis = if ($IsGitHubWindowsRunner) {
    "ephemeral_github_windows_runner"
} elseif ($IsEvidenceCleanHost) {
    "host_evidence_no_prior_install_no_dev_toolchain"
} else {
    "none"
}

if (!$IsCleanHost -and !$AllowDeveloperHostSmoke) {
    $why = @()
    if ($HasPriorInstall) { $why += "Determinex is already installed ($($priorInstalls -join ', '))" }
    if ($HasDevToolchain) { $why += "developer toolchain present on PATH ($($devToolsFound -join ', '))" }
    throw ("This release clean-host smoke needs a clean host: " + ($why -join "; ") +
        ". Use an ephemeral GitHub Windows runner, a freshly provisioned VM, or " +
        "-AllowDeveloperHostSmoke for non-release local smoke output.")
}
$runnerId = if ($env:GITHUB_RUN_ID) { "$($env:GITHUB_RUN_ID)-$($env:GITHUB_RUN_ATTEMPT)" } else { $env:COMPUTERNAME }

$InstallPassed = $false
$LaunchPassed = $false
$ProofCenterSmokePassed = $false
$WorkspaceSmokePassed = $false
$UninstallPassed = $false
$installedExe = ""
$installExitCode = $null
$uninstallExitCode = $null
$launchExitObserved = $null
$launchExitCode = $null
$launchExitCodeHex = ""

try {
    $install = Invoke-Installer -Path $InstallerFullPath -Mode install
    $installExitCode = $install.ExitCode
    $InstallPassed = ($install.ExitCode -in @(0, 3010))

    $installedExe = Find-InstalledExe
    if ($InstallPassed -and $installedExe) {
        $process = Start-Process -FilePath $installedExe -PassThru
        # WaitForExit with a timeout rather than a blind sleep: it returns the moment the
        # process dies, and it leaves the exit code readable. Recording that code matters --
        # the first failing transcript from a clean host reported only the boolean "it
        # exited", which was true and useless. The code was 0xC0000135
        # (STATUS_DLL_NOT_FOUND), the single detail that identified a missing VC++ runtime
        # rather than anything wrong with the app itself.
        $launchExitObserved = $process.WaitForExit($LaunchSeconds * 1000)
        $LaunchPassed = -not $launchExitObserved
        if ($launchExitObserved) {
            $launchExitCode = $process.ExitCode
            $launchExitCodeHex = "0x{0:X8}" -f $process.ExitCode
        } else {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        }

        $ProofCenterSmokePassed = Test-BinaryContainsAscii -Path $installedExe -Needle "proof-center"

        $installDir = Split-Path -Parent $installedExe
        # The second half of this used to be `-or (... "determinex_model_registry.json")`, which
        # could never be true: the registry is declared as ../../determinex_model_registry.json,
        # so Tauri preserves that relative path and installs it to _up_\_up_\, not beside the
        # exe. The check therefore looked like it accepted either of two proofs while only ever
        # evaluating one. Both are now required and the registry is looked for where it lands.
        $registryPath = Join-Path $installDir "_up_\_up_\determinex_model_registry.json"
        $WorkspaceSmokePassed = (Test-Path -LiteralPath (Join-Path $installDir "determinex.exe")) -and
            (Test-Path -LiteralPath (Join-Path $installDir "determinex-hive.exe")) -and
            (Test-Path -LiteralPath $registryPath)
    }
} finally {
    try {
        $uninstall = Invoke-Installer -Path $InstallerFullPath -Mode uninstall
        $uninstallExitCode = $uninstall.ExitCode
        $UninstallPassed = ($uninstall.ExitCode -in @(0, 3010))
    } catch {
        $UninstallPassed = $false
    }
}

$payload = [ordered]@{
    schema_version = "determinex-clean-host-install-transcript-v1"
    generated_at_utc = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    product_name = "Determinex"
    clean_host_fresh_install = $IsCleanHost
    runner = [ordered]@{
        is_clean_host = $IsCleanHost
        host_reused_from_developer_machine = -not $IsCleanHost
        os = "Windows $([System.Environment]::OSVersion.VersionString)"
        runner_id = $runnerId
        # Which evidence carried the claim, so a reader never has to guess whether this
        # transcript rests on an ephemeral runner or on the host's own state.
        clean_host_basis = $CleanHostBasis
        is_github_windows_runner = $IsGitHubWindowsRunner
        prior_determinex_install_found = $HasPriorInstall
        prior_determinex_install_names = @($priorInstalls)
        developer_toolchain_on_path = @($devToolsFound)
        # False is the stronger evidence: it means the launch below had to rely on the
        # installer having delivered the runtime itself.
        vc_runtime_preinstalled = $HasVcRuntimePreinstalled
        vc_runtime_preinstalled_files = @($vcRuntimeFound)
        # Get-CimInstance already yields a DateTime; ManagementDateTimeConverter is for
        # Get-WmiObject's DMTF strings and throws here.
        uptime_minutes = [int]((Get-Date) - (Get-CimInstance Win32_OperatingSystem).LastBootUpTime).TotalMinutes
    }
    bundle = [ordered]@{
        manifest_path = $ManifestFullPath
        bundle_zip_path = [string]$manifest.bundle_zip_path
        source_commit = [string]$manifest.source_commit
        installer_path = $InstallerFullPath
        installer_sha256 = $installerSha256
        installer_sha256_verified = $installerSha256Verified
        # What the boolean above actually rests on. Without this a reader cannot tell a real
        # hash match from "there was nothing to compare against", which is how a transcript
        # for the wrong installer read as verified.
        installer_sha256_basis = $installerSha256Basis
        authenticode_status = $signature.Status.ToString()
    }
    dry_run = $false
    installer_execution_performed = $InstallPassed
    launch_performed = $LaunchPassed
    proof_center_smoke_performed = $ProofCenterSmokePassed
    workspace_command_smoke_performed = $WorkspaceSmokePassed
    uninstall_performed = $UninstallPassed
    release_ready = $false
    authority_granted = $false
    observed = [ordered]@{
        install_exit_code = $installExitCode
        uninstall_exit_code = $uninstallExitCode
        installed_exe = $installedExe
        launch_process_exited_during_smoke = $launchExitObserved
        launch_exit_code = $launchExitCode
        launch_exit_code_hex = $launchExitCodeHex
        proof_center_smoke_method = "installed executable contains the packaged proof-center route marker after app launch"
        workspace_smoke_method = "installed app directory contains executable plus sidecar or model registry resource"
    }
}

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutputFullPath) | Out-Null
$jsonString = ConvertTo-Json -InputObject $payload -Depth 10
[System.IO.File]::WriteAllText($OutputFullPath, $jsonString, (New-Object System.Text.UTF8Encoding($false)))

Push-Location $RepoRoot
try {
    $env:PYTHONPATH="."
    if ($IsCleanHost) {
        # Was `if ($IsGitHubWindowsRunner)`. Missed when the attestation moved to host
        # evidence, so a genuinely clean VM would have been told its own transcript "is
        # intentionally not valid clean-host release proof" -- the opposite of true, and
        # it would have skipped validation of the one transcript that mattered.
        #
        # Validation needs the repo's venv, which a bare clean host does not have. That is
        # not a failure of the smoke: the transcript is already written and can be
        # validated wherever the repo lives. Skipping loudly beats throwing after a
        # successful install/launch/uninstall cycle.
        $validator = Join-Path $RepoRoot ".venv\Scripts\python.exe"
        if (Test-Path $validator) {
            & $validator scripts\release\clean_host_install_transcript.py --validate $OutputFullPath
            if ($LASTEXITCODE -ne 0) {
                throw "clean host transcript validation failed"
            }
        } else {
            Write-Host "Clean-host transcript written on a host without the repo venv; validate it where the repo lives:"
            Write-Host "  .venv\Scripts\python.exe scripts\release\clean_host_install_transcript.py --validate <transcript.json>"
        }
    } else {
        Write-Warning "Developer-host smoke transcript written; it is intentionally not valid clean-host release proof."
    }
} finally {
    Pop-Location
}

Write-Host "Clean-host transcript written to $OutputFullPath"
