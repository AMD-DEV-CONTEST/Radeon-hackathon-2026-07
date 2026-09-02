#!/usr/bin/env python3
"""Assemble a self-contained clean-host verification kit.

WHY THIS EXISTS
---------------
`clean_host` is the last gate standing between the release gates and
`release_ready: true`, and it cannot be satisfied from a developer machine by design --
the whole point is a host without the dev environment. Measured 2026-07-29, this box is
Windows 11 **Home**: no Windows Sandbox (Pro/Enterprise only, WindowsSandbox.exe absent),
no Hyper-V, no Windows containers. So the step genuinely requires a second machine.

What should NOT require the operator is assembling the pieces. The smoke script resolves
its manifest and installer relative to a repo root, and validates through the repo's venv
-- none of which exists on a bare VM. This packs everything into one folder with one
entry point, so the operator's whole job is: copy folder, run one command, copy one JSON
back.

Usage::

    python scripts/release/clean_host_kit.py --output .tmp/clean-host-kit
    python scripts/release/clean_host_kit.py --output .tmp/clean-host-kit --zip
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

# This module is run directly (`python scripts/release/clean_host_kit.py`), so the repo root is not
# on sys.path unless the caller set PYTHONPATH. Put it there before importing the gates, rather
# than making the manifest resolver conditional on how the script was invoked.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.release import determinex_release_gates  # noqa: E402  (needs the sys.path line above)

PREFLIGHT = r"""<#
Preflight: is this host clean enough to produce release-valid proof?

Run this FIRST. It answers in seconds and changes nothing, so a host that cannot qualify
is discovered before copying a 193 MB installer to it.

The two conditions mirror run_windows_clean_host_install_smoke.ps1 exactly: a clean-host
installer test has to establish that the app installs and runs WITHOUT the developer
environment, so a prior install or a dev toolchain on PATH both disqualify the host.
#>
$ErrorActionPreference = "Stop"

$priorInstalls = @()
foreach ($keyPattern in @(
    "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*",
    "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*",
    "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*")) {
    try {
        $priorInstalls += Get-ItemProperty -Path $keyPattern -ErrorAction SilentlyContinue |
            Where-Object { $_.DisplayName -and $_.DisplayName -like "*Determinex*" } |
            Select-Object -ExpandProperty DisplayName
    } catch { }
}

$devToolsFound = @()
foreach ($tool in @("cargo", "rustc", "node", "npm")) {
    if (Get-Command $tool -ErrorAction SilentlyContinue) { $devToolsFound += $tool }
}

# Get-CimInstance returns LastBootUpTime as a DateTime already. Passing it through
# ManagementDateTimeConverter::ToDateTime (which is for Get-WmiObject's DMTF strings) throws
# ArgumentOutOfRangeException -- and because this script exits 1 to mean "not clean", the
# crash was indistinguishable from a refusal. A clean host would have been rejected with a
# stack trace nobody would read as a bug in the probe.
$uptimeMin = [int]((Get-Date) - (Get-CimInstance Win32_OperatingSystem).LastBootUpTime).TotalMinutes

Write-Host ""
Write-Host "  host            : $env:COMPUTERNAME  ($((Get-CimInstance Win32_OperatingSystem).Caption))"
Write-Host "  uptime          : $uptimeMin minutes"
Write-Host "  prior installs  : $(if (@($priorInstalls).Count) { $priorInstalls -join ', ' } else { 'none' })"
Write-Host "  dev toolchain   : $(if (@($devToolsFound).Count) { $devToolsFound -join ', ' } else { 'none' })"
Write-Host ""

if (@($priorInstalls).Count -or @($devToolsFound).Count) {
    Write-Host "  VERDICT: NOT a clean host." -ForegroundColor Red
    Write-Host "  This host cannot produce release-valid clean-host proof. Use a freshly"
    Write-Host "  provisioned VM (or re-image this one) and run this preflight again."
    exit 1
}

Write-Host "  VERDICT: clean host. Run .\run-clean-host-smoke.ps1 next." -ForegroundColor Green
exit 0
"""

RUNNER = r"""<#
Runs the clean-host install/launch/uninstall smoke using the bundled installer, and writes
the transcript beside this script.

Self-contained: the kit carries the installer, the manifest and the smoke script, so
nothing here resolves against a repo checkout. Copy transcript\clean_host_install_transcript.json
back to the repo when it finishes.
#>
param([int]$LaunchSeconds = 10)

$ErrorActionPreference = "Stop"
$KitDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $PSCommandPath }

Write-Host "== preflight =="
& (Join-Path $KitDir "preflight.ps1")
if ($LASTEXITCODE -ne 0) {
    throw "Preflight refused this host. Nothing was installed."
}

$installer = Get-ChildItem -Path (Join-Path $KitDir "installers") -Filter *.msi | Select-Object -First 1
if (-not $installer) {
    $installer = Get-ChildItem -Path (Join-Path $KitDir "installers") -Filter *-setup.exe | Select-Object -First 1
}
if (-not $installer) { throw "No installer found in the kit's installers\ directory." }

$transcriptDir = Join-Path $KitDir "transcript"
New-Item -ItemType Directory -Force -Path $transcriptDir | Out-Null
$out = Join-Path $transcriptDir "clean_host_install_transcript.json"

Write-Host ""
Write-Host "== smoke =="
Write-Host "  installer: $($installer.Name)"

& (Join-Path $KitDir "run_windows_clean_host_install_smoke.ps1") `
    -ManifestPath (Join-Path $KitDir "download_manifest.json") `
    -InstallerPath $installer.FullName `
    -OutputPath $out `
    -LaunchSeconds $LaunchSeconds

Write-Host ""
Write-Host "== done =="
Write-Host "  transcript: $out"
Write-Host "  Copy that file back to the repo and run:"
Write-Host "    .venv\Scripts\python.exe scripts\release\clean_host_install_transcript.py --validate <path>"
"""


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _newest_manifest() -> Path:
    """The manifest the release gates themselves would read.

    Fixed 2026-07-30. This sorted by `p.name`, and EVERY candidate's name is the identical string
    "download_manifest.json" -- so the sort was a no-op and `reverse=True` merely reversed glob
    order. Measured: the kit shipped the MSI from determinex_download_bundle_20260707 (sha
    5377496523f38b5a) while every release gate and full_release_closure read
    determinex_download_bundle_20260729 by mtime (sha 720cedc10d619ec3).

    The consequence was not cosmetic: an operator would copy ~193 MB to a clean VM, run the full
    install/launch/uninstall cycle, and produce a transcript whose installer hash appears in no
    current manifest -- so the clean_host gate, the last one standing, could not be satisfied
    through its own documented path.

    2026-07-31: the mtime sort is now *shared* rather than re-derived. "The manifest the gates
    read" is a fact about the gates, so asking the gates is the only way this docstring stays
    true -- a local copy is one edit away from disagreeing again.
    """
    candidate = determinex_release_gates.newest_download_manifest_path(ROOT)
    if candidate is None:
        raise SystemExit("no download_manifest.json under assurance/evidence/")
    return candidate


def build(out_dir: Path, make_zip: bool, installer_choice: str = "msi") -> None:
    manifest_path = _newest_manifest()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    # Windows installers only: this kit tests a Windows clean host.
    #
    # Default is MSI alone. The smoke installs ONE installer (it prefers the MSI), so
    # shipping both doubles a copy that has to cross an RDP session for no extra coverage:
    # 381 MB vs 193 MB. `--installer both` is there for when the NSIS path is what you want
    # to exercise.
    types = {
        "msi": ("windows_msi",),
        "nsis": ("windows_nsis_setup",),
        "both": ("windows_msi", "windows_nsis_setup"),
    }[installer_choice]
    wanted = [a for a in manifest.get("artifacts", []) if a.get("artifact_type") in types]
    if not wanted:
        raise SystemExit(
            f"{manifest_path} lists no Windows installer. Build one first "
            "(npm run tauri -- build) and refresh the bundle."
        )

    if out_dir.exists():
        shutil.rmtree(out_dir)
    (out_dir / "installers").mkdir(parents=True)

    copied = []
    for artifact in wanted:
        src = ROOT / str(artifact.get("source_path", ""))
        if not src.is_file():
            print(f"  SKIP {artifact.get('file_name')}: source file absent ({src})")
            continue
        dst = out_dir / "installers" / src.name
        print(f"  copying {src.name} ({src.stat().st_size / 1024 / 1024:.1f} MB)...")
        shutil.copy2(src, dst)
        # Verify the copy, because a truncated installer would fail on the VM in a way
        # that looks like an installer defect rather than a bad copy.
        digest = _sha256(dst)
        if artifact.get("sha256") and digest != artifact["sha256"]:
            raise SystemExit(f"copy of {src.name} does not match the manifest sha256")
        copied.append((src.name, digest))

    if not copied:
        raise SystemExit("no Windows installer could be copied; nothing to verify on a clean host")

    shutil.copy2(manifest_path, out_dir / "download_manifest.json")
    shutil.copy2(ROOT / "scripts/release/run_windows_clean_host_install_smoke.ps1", out_dir)
    (out_dir / "preflight.ps1").write_text(PREFLIGHT, encoding="utf-8")
    (out_dir / "run-clean-host-smoke.ps1").write_text(RUNNER, encoding="utf-8")

    readme = [
        "# Clean-host verification kit",
        "",
        "Produces the one piece of evidence that cannot be generated on a developer",
        "machine: proof that the installer installs, launches and uninstalls on a host",
        "without the development environment.",
        "",
        "## On the clean host",
        "",
        "1. Copy this whole folder over.",
        "2. Open PowerShell in it and run:",
        "",
        "       .\\preflight.ps1              # seconds, changes nothing",
        "       .\\run-clean-host-smoke.ps1   # installs, launches, verifies, uninstalls",
        "",
        "3. Copy `transcript\\clean_host_install_transcript.json` back to the repo.",
        "",
        "`preflight.ps1` refuses a host that already has Determinex installed or that has",
        "cargo/rustc/node/npm on PATH -- on such a host the installer's dependency handling",
        "is not actually being tested, so the transcript would not be release-valid.",
        "",
        "## Back in the repo",
        "",
        "       .venv\\Scripts\\python.exe scripts\\release\\clean_host_install_transcript.py --validate <transcript.json>",
        "       .venv\\Scripts\\python.exe scripts\\release\\determinex_release_gates.py --output assurance\\evidence\\determinex_release_gate_status\\release_gates_<date>.json",
        "",
        "## Contents",
        "",
    ]
    for name, digest in copied:
        readme.append(f"* `installers/{name}` — sha256 `{digest}`")
    readme += [
        "* `download_manifest.json` — the manifest the release gates read",
        "* `run_windows_clean_host_install_smoke.ps1` — the real smoke, unmodified",
        "* `preflight.ps1`, `run-clean-host-smoke.ps1` — entry points",
        "",
    ]
    (out_dir / "README.md").write_text("\n".join(readme), encoding="utf-8")

    total = sum(p.stat().st_size for p in out_dir.rglob("*") if p.is_file())
    print(f"\n  kit: {out_dir}  ({total / 1024 / 1024:.1f} MB)")

    if make_zip:
        zip_path = out_dir.with_suffix(".zip")
        print(f"  zipping -> {zip_path}")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as zf:
            for path in sorted(out_dir.rglob("*")):
                if path.is_file():
                    zf.write(path, path.relative_to(out_dir))
        print(f"  zip: {zip_path} ({zip_path.stat().st_size / 1024 / 1024:.1f} MB)")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--output", type=Path, default=ROOT / ".tmp" / "clean-host-kit")
    ap.add_argument("--zip", action="store_true", help="also produce a single .zip")
    ap.add_argument(
        "--installer",
        choices=("msi", "nsis", "both"),
        default="msi",
        help="which installer to ship (default: msi -- the smoke installs one)",
    )
    args = ap.parse_args()
    build(args.output, args.zip, args.installer)
    return 0


if __name__ == "__main__":
    sys.exit(main())
