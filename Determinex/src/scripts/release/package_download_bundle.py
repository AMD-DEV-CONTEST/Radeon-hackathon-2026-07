"""Create a downloadable Determinex setup bundle from built installer artifacts.

The bundle is intentionally not a public-release approval. It packages the
current MSI/NSIS artifacts with checksums, setup instructions, and a small
evidence manifest while keeping signing and clean-host gates explicit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "determinex-download-bundle-v1"
WINDOWS_MSI_SCHEMA_VERSION = "determinex-windows-msi-evidence-v1"
LEGAL_PUBLIC_DISTRIBUTION_SCHEMA_VERSION = "determinex-legal-public-distribution-evidence-v1"
DEFAULT_EVIDENCE_DIR = Path("assurance/evidence/determinex_download_bundle_20260707")
DEFAULT_WINDOWS_MSI_EVIDENCE_DIR = Path("assurance/evidence/windows_msi")
INSTALLER_SUFFIXES = frozenset({".exe", ".msi", ".appimage", ".deb", ".rpm"})
LINUX_PACKAGE_TYPES = frozenset({"linux_appimage", "linux_deb", "linux_rpm"})
REQUIRED_LINUX_PACKAGE_TYPES = ("linux_appimage", "linux_deb", "linux_rpm")
LEGAL_PUBLIC_DISTRIBUTION_REQUIRED_TRUE = (
    "legal_review_completed",
    "license_inventory_reviewed",
    "model_notice_reviewed",
    "public_repo_secret_scan_passed",
    "public_repo_scrub_completed",
    "third_party_notices_present",
)


@dataclass(frozen=True)
class InstallerArtifact:
    source_path: Path
    file_name: str
    artifact_type: str
    size_bytes: int
    sha256: str
    authenticode_status: str


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read_tauri_metadata(root: Path) -> tuple[str, str]:
    config = root / "frontend/src-tauri/tauri.conf.json"
    try:
        data = json.loads(config.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "Determinex", "0.0.0"
    return str(data.get("productName") or "Determinex"), str(data.get("version") or "0.0.0")


def _git_commit(root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception:
        return "unknown"
    return result.stdout.strip() or "unknown"


def _authenticode_status(path: Path) -> str:
    """Authenticode status for one artifact, without letting its filename become code.

    THE BUG THIS FIXES (2026-07-30). The path used to be appended as a trailing argv element
    after `-Command`. List-form subprocess does not help there: powershell.exe joins every
    trailing argument into one command string and re-parses it. Demonstrated directly --

        C:\\nonexistent.msi; Write-Output DETERMINEX_INJECTION_EXECUTED

    printed DETERMINEX_INJECTION_EXECUTED and exited 0. The injected statement RAN. Reachable
    because `_artifact_type` accepts any `*.msi` by extension with no constraint on the name, and
    it matters far more than a filename probe should: `build_release_package.ps1` sets
    TAURI_SIGNING_PRIVATE_KEY to the updater key's content in the same PowerShell process that
    later invokes this script, so injected code would inherit the signing key in its environment.

    A second, quieter bug came from the same line: a path containing a space bound only its first
    token, so `C:\\Program Files\\...` reported "not_checked" while looking like a real answer.

    The env-var form below is the pattern `windows_trust_packet._powershell_signature` already
    used for this exact operation -- the value crosses as data and is never parsed as script.
    """
    if os.name != "nt":
        return "not_checked_non_windows"
    # Authenticode is a Windows PE concept. Probing a .deb / .rpm / .AppImage returns
    # "UnknownError", which reads in the manifest as though the check had failed on something it
    # should have handled -- three of the five artifacts said that. Say "not applicable" instead,
    # so a genuine UnknownError on a Windows binary still means something.
    if path.suffix.lower() not in {".msi", ".exe", ".dll", ".ps1", ".cat"}:
        return "not_applicable_non_windows_artifact"
    script = (
        "$Path = $env:DETERMINEX_AUTHENTICODE_PROBE_PATH; "
        "(Get-AuthenticodeSignature -LiteralPath $Path).Status.ToString()"
    )
    env = os.environ.copy()
    env["DETERMINEX_AUTHENTICODE_PROBE_PATH"] = str(path)
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
    except Exception:
        return "not_checked"
    # A non-zero exit means the probe did not answer. Reporting its empty stdout as a status
    # would be the same "failure looks like an answer" shape as the rest of today's findings.
    if result.returncode != 0:
        return "not_checked"
    return result.stdout.strip() or "not_checked"


def _has_passing_legal_public_distribution_packet(root: Path) -> bool:
    packet_dir = root / "assurance/evidence/public_distribution"
    packets = sorted(
        packet_dir.glob("legal_public_distribution_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for packet in packets:
        try:
            data = json.loads(packet.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        if data.get("schema_version") != LEGAL_PUBLIC_DISTRIBUTION_SCHEMA_VERSION:
            continue
        if all(data.get(field) is True for field in LEGAL_PUBLIC_DISTRIBUTION_REQUIRED_TRUE):
            return True
    return False


# Path segments that mean "this file is PAYLOAD INSIDE a package", not a package.
#
# The Linux bundle tree contains an unpacked AppDir, and Tauri copies declared resources
# into it -- including vc_redist.x64.exe, Microsoft's VC++ redistributable. The collector
# walks the bundle dir with rglob("*"), so those payload files are seen too.
_PAYLOAD_MARKERS = (".appdir", "/resources/", "\\resources\\", "/usr/lib/", "\\usr\\lib\\")


def _is_package_payload(path: Path) -> bool:
    """True when `path` sits inside an unpacked package rather than being one."""
    posix = path.as_posix().lower()
    return any(marker in posix for marker in (".appdir", "/resources/", "/usr/lib/"))


def _artifact_type(path: Path) -> str | None:
    """Classify a release artifact, or None when the file is not one.

    THE BUG THIS FIXES (2026-07-29). This mapped ANY `.exe` to "windows_nsis_setup". The
    first real Linux build therefore advertised

        file_name:     vc_redist.x64.exe
        artifact_type: windows_nsis_setup
        source_path:   .../appimage/Determinex.AppDir/usr/lib/Determinex/resources/vc_redist.x64.exe

    -- Microsoft's redistributable, listed in the download manifest as Determinex's own
    Windows installer, twice. Anyone fetching the advertised Windows installer would have
    downloaded vc_redist. Worse, the release gates count artifact TYPES from this manifest,
    so a bundle containing no Windows installer at all could satisfy a Windows artifact
    check.

    Extension alone cannot decide this, because the thing that broke it IS a .exe. So:
    payload inside an unpacked package is skipped, and a Windows installer must also look
    like one by name -- Tauri emits `<product>_<version>_x64-setup.exe`.
    """
    if _is_package_payload(path):
        return None

    suffix = path.suffix.lower()
    name = path.name.lower()

    # Updater artifacts, added 2026-07-29 when bundle.createUpdaterArtifacts was enabled. They
    # live in the same bundler output directory this function scans recursively, and the
    # fallthrough below classifies anything unrecognised as a generic "installer" -- so a
    # 96-byte detached signature and an update archive would both have been advertised in the
    # download manifest as things to install. That is the vc_redist bug in this same function,
    # reopened by a config change nowhere near it. They are update payloads, delivered by the
    # updater and attached to the GitHub release by tauri-action; they are not downloads.
    if suffix == ".sig":
        return None
    if suffix == ".zip" and Path(path.stem).suffix.lower() in (".msi", ".exe", ".app", ".dmg"):
        return None

    if suffix == ".msi":
        return "windows_msi"
    if suffix == ".exe":
        # Only Tauri's NSIS output, not any executable that happens to be lying around.
        return "windows_nsis_setup" if "setup" in name else None
    if suffix == ".appimage":
        return "linux_appimage"
    if suffix == ".deb":
        return "linux_deb"
    if suffix == ".rpm":
        return "linux_rpm"
    return "installer"


def _msi_built_by_wix(msi_artifacts: list[InstallerArtifact]) -> bool:
    """Whether the MSI on disk actually shows signs of having been produced by WiX.

    Derived instead of asserted. A WiX-linked MSI carries WiX's own authoring in its string pool
    (the WixUI Binary rows, among others), so a raw byte scan answers the question without needing
    the MSI COM API or a WiX install. Not a cryptographic proof -- but it is an observation of the
    artifact rather than a literal `True` written because a file with an .msi extension existed.
    """
    if not msi_artifacts:
        return False
    for artifact in msi_artifacts:
        path = Path(artifact.source_path)
        if not path.is_file():
            return False
        try:
            blob = path.read_bytes()
        except OSError:
            return False
        # An MSI is an OLE compound file. Checking the magic first is what makes this
        # discriminating: without it, a bare `b"WiX" in blob` returned True for the 105 MB NSIS
        # setup.exe too, because a 3-byte needle turns up incidentally in any large binary. Caught
        # by testing the fix against a non-MSI rather than only against the artifact it should pass.
        if blob[:8] != b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
            return False
        if not (b"WixUI" in blob or b"Windows Installer XML" in blob or b"wixpdb" in blob):
            return False
    return True


def _write_windows_msi_packet(
    evidence_dir: Path,
    generated_at: str,
    source_commit: str,
    msi_artifacts: list[InstallerArtifact],
) -> Path | None:
    if not msi_artifacts:
        return None
    evidence_dir.mkdir(parents=True, exist_ok=True)
    stamp = generated_at.replace(":", "").replace("-", "").replace("Z", "Z")
    packet_path = evidence_dir / f"windows_msi_{stamp}.json"
    packet = {
        "schema_version": WINDOWS_MSI_SCHEMA_VERSION,
        "generated_at_utc": generated_at,
        "source_commit": source_commit,
        # DERIVED, NOT ASSERTED (fixed 2026-07-30). These four were unconditional `True` literals
        # written whenever any *.msi was found, and `_windows_msi_errors` checks precisely these
        # four -- so dropping any file named *.msi into the installer directory turned the
        # windows_msi gate green. The packet even documented the contradiction one line below, in
        # msi_smoke_scope: "artifact_discovery_copy_checksum_and_bundle_manifest" -- discover, copy,
        # checksum. No MSI was ever installed, no WiX invocation was ever observed, and nothing
        # compared a hash to an expected value.
        #
        # What can honestly be derived here is derived. What cannot is reported false rather than
        # true: this script packages artifacts, so it is not the thing that can attest an installer
        # smoke. That attestation belongs to the clean-host transcript, which actually installs.
        "wix_toolset_used": _msi_built_by_wix(msi_artifacts),
        "msi_built": bool(msi_artifacts),
        "msi_sha256_verified": all(a.sha256 and len(a.sha256) == 64 for a in msi_artifacts),
        "msi_installer_smoke_performed": False,
        "msi_smoke_scope": "artifact_discovery_copy_checksum_and_bundle_manifest",
        "clean_host_install_performed": False,
        "authority_granted": False,
        "msi_artifacts": [
            {
                "file_name": artifact.file_name,
                "source_path": str(artifact.source_path),
                "size_bytes": artifact.size_bytes,
                "sha256": artifact.sha256,
                "authenticode_status": artifact.authenticode_status,
            }
            for artifact in msi_artifacts
        ],
        "claim_boundary": (
            "This packet proves the WiX/MSI artifact was built, discovered, copied, and "
            "checksum-recorded for the download bundle. It is not clean-host install proof."
        ),
    }
    packet_path.write_text(json.dumps(packet, indent=2), encoding="utf-8")
    return packet_path


def discover_installers(installer_dir: Path) -> list[InstallerArtifact]:
    if not installer_dir.is_dir():
        raise FileNotFoundError(f"installer directory not found: {installer_dir}")
    candidates = sorted(
        p
        for p in installer_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in INSTALLER_SUFFIXES
    )
    # _artifact_type returns None for a file that merely LOOKS like an installer because of
    # its extension -- payload inside an unpacked package, or a stray .exe that is not
    # Tauri's NSIS output. Those are dropped here rather than published under a type they
    # do not have. Classification happens once and is reused, so a file cannot be counted
    # under one type and described under another.
    classified = [(path, _artifact_type(path)) for path in candidates]
    skipped = [path for path, kind in classified if kind is None]
    artifacts = [
        InstallerArtifact(
            source_path=path,
            file_name=path.name,
            artifact_type=kind,
            size_bytes=path.stat().st_size,
            sha256=_sha256(path),
            authenticode_status=_authenticode_status(path),
        )
        for path, kind in classified
        if kind is not None
    ]
    for path in skipped:
        print(f"[package_download_bundle] skipped (not a release artifact): {path}")
    if not artifacts:
        raise FileNotFoundError(
            f"no installer/package artifacts ({', '.join(sorted(INSTALLER_SUFFIXES))}) found under "
            f"{installer_dir}"
            + (
                f" -- {len(skipped)} file(s) matched an installer extension but were package "
                f"payload or unrecognised"
                if skipped
                else ""
            )
        )
    return artifacts


def _clean_host_note(artifact: InstallerArtifact, verified: dict[str, str]) -> list[str]:
    """Whether THIS artifact -- this exact hash -- has clean-host evidence."""
    digest = (artifact.sha256 or "").strip().lower()
    if digest and digest in verified:
        return [
            "This exact build is clean-host verified on a Windows host with no Visual C++ runtime",
            f"present: install exit 0, launch survived the full window, uninstall exit 0 "
            f"(`{verified[digest]}`).",
            "",
        ]
    return [
        f"**This build has not itself been clean-host verified.** Its hash (`{digest[:16]}...`)",
        "appears in no passing clean-host transcript, which is what a rebuild does to that evidence"
        " --",
        "it anchors to a specific installer hash. Re-run",
        "`scripts/release/run_windows_clean_host_install_smoke.ps1` on a clean host before treating",
        "this artifact as verified.",
        "",
    ]


def _clean_host_verified_hashes(root: Path) -> dict[str, str]:
    """`installer_sha256` -> transcript filename, for every PASSING clean-host transcript.

    WHY THIS IS COMPUTED AND NOT ASSERTED. SETUP.md used to say, in prose, "This is the verified
    Windows path: it has been installed, launched and uninstalled on a clean Windows host with no
    Visual C++ runtime present." That was true of the artifact verified at the time and became false
    the next time anyone rebuilt -- clean-host evidence anchors to a specific installer HASH, and a
    rebuild produces a different one.

    Measured 2026-07-31: the transcripts covered 5fdfe015, 3f72e1d4 and d1f369ef while the bundle
    being written contained 677273cb and 2942b161. So the document whose job is to prevent
    overclaiming was asserting clean-host verification for two binaries that had never been near a
    clean host. Same failure as `test_the_staged_installers_are_the_current_build` guards for, in
    the user-facing text rather than the gate.

    Mocked transcripts are excluded: `installer_sha256: "mocked_sha256"` is a template, not evidence.
    """
    verified: dict[str, str] = {}
    for path in sorted(
        (root / "assurance" / "evidence").rglob("clean_host_install_transcript*.json")
    ):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        bundle = data.get("bundle") or {}
        digest = str(bundle.get("installer_sha256") or "").strip().lower()
        if not digest or not re.fullmatch(r"[0-9a-f]{64}", digest):
            continue
        # Only a transcript that actually recorded a successful cycle counts.
        required = (
            "clean_host_fresh_install",
            "installer_execution_performed",
            "launch_performed",
            "uninstall_performed",
        )
        if not all(data.get(field) is True for field in required):
            continue
        verified[digest] = path.name
    return verified


def _setup_markdown(
    product_name: str,
    version: str,
    artifacts: list[InstallerArtifact],
    clean_host_verified: dict[str, str] | None = None,
) -> str:
    nsis = next((a for a in artifacts if a.artifact_type == "windows_nsis_setup"), None)
    msi = next((a for a in artifacts if a.artifact_type == "windows_msi"), None)
    linux = [a for a in artifacts if a.artifact_type in LINUX_PACKAGE_TYPES]
    lines = [
        f"# {product_name} {version} Setup",
        "",
        "## What This Bundle Contains",
        "",
        "- Installer/package artifacts built from the current Determinex checkout.",
        "- `CHECKSUMS.sha256` for offline integrity verification.",
        "- `download_manifest.json` with artifact hashes, source commit, and release boundary.",
        "",
        "## Windows Setup",
        "",
    ]
    # THE MSI LEADS (2026-07-30). This used to number the NSIS setup as steps 1-2 and demote the
    # MSI to an "example" further down, so the documented Windows path was the installer we had
    # never verified. On a pristine Windows 11 VM with no VC++ runtime the MSI installs, launches
    # and uninstalls cleanly (recorded in the clean-host transcript, launch_performed=true with
    # vc_runtime_preinstalled=false), and the clean-host run of the NSIS setup reported that it exited
    # 0 having installed nothing.
    #
    # RESOLVED 2026-07-30: that was a MEASUREMENT defect, not an installer defect. The NSIS installer
    # works -- verified on a developer host with the remembered-location key cleared, with it present,
    # and with an explicit /D=. The clean-host script was looking for a per-user install in
    # `$LOCALAPPDATA\Programs\Determinex`, but installer.nsi uses `$LOCALAPPDATA\Determinex` with no
    # `Programs` segment, so a correct install could never be found. Fixed in
    # run_windows_clean_host_install_smoke.ps1; the clean-host run has not yet been repeated, which is
    # why the MSI still leads here. See docs/release/NSIS_SILENT_INSTALL.md.
    if msi is not None:
        lines.extend(
            [
                f"1. Verify `{msi.file_name}` against `CHECKSUMS.sha256`.",
                f"2. Run `{msi.file_name}` (double-click, or the command below).",
                "3. Launch Determinex from the Start Menu or installed executable.",
                "4. Open Mission Control in the IDE to review setup, proof, and release blockers.",
                "",
                "```powershell",
                f"msiexec /i .\\{msi.file_name}",
                "```",
                "",
                *_clean_host_note(msi, clean_host_verified or {}),
            ]
        )
    else:
        lines.extend(["No Windows MSI artifact is present in this bundle.", ""])
    if nsis is not None:
        lines.extend(
            [
                f"### Alternative: `{nsis.file_name}`",
                "",
                *_clean_host_note(nsis, clean_host_verified or {}),
                "Double-clicking is fine; for a silent install:",
                "",
                "```powershell",
                f".\\{nsis.file_name} /S",
                "```",
                "",
                "It installs to `%LOCALAPPDATA%\\Determinex`, or to wherever you last installed it. To",
                "choose the location, add `/D=` as the **last** argument, **unquoted** even if the path",
                "contains spaces (an NSIS rule, not a typo). It runs with user-level rights, so it",
                "cannot write to `C:\\Program Files`:",
                "",
                "```powershell",
                f".\\{nsis.file_name} /S /D=$env:LOCALAPPDATA\\Determinex",
                "```",
                "",
            ]
        )
    if linux:
        lines.extend(["## Linux Setup", ""])
        for artifact in linux:
            if artifact.artifact_type == "linux_appimage":
                lines.extend(
                    [
                        f"AppImage example for `{artifact.file_name}`:",
                        "",
                        "```bash",
                        f"chmod +x {artifact.file_name}",
                        f"./{artifact.file_name}",
                        "```",
                        "",
                    ]
                )
            elif artifact.artifact_type == "linux_deb":
                lines.extend(
                    [
                        f"Debian/Ubuntu example for `{artifact.file_name}`:",
                        "",
                        "```bash",
                        f"sudo apt install ./{artifact.file_name}",
                        "```",
                        "",
                    ]
                )
            elif artifact.artifact_type == "linux_rpm":
                lines.extend(
                    [
                        f"Fedora/RHEL example for `{artifact.file_name}`:",
                        "",
                        "```bash",
                        f"sudo dnf install ./{artifact.file_name}",
                        "```",
                        "",
                    ]
                )
    else:
        lines.extend(
            ["## Linux Setup", "", "No Linux package artifact is present in this bundle.", ""]
        )
    lines.extend(
        [
            "## Release Boundary",
            "",
            "This bundle is setup-ready for local/operator testing, not a public release approval.",
            "",
            # Was a hardcoded list: "code signing, SmartScreen/trust, public distribution review,
            # and clean-host install proof". Two of those four went stale the moment the gates
            # moved -- clean-host install proof passes, and NSIS is verified too -- so the document
            # that exists to prevent overclaiming was itself making a false claim, in the
            # understating direction. Prose cannot track gate state; state what was MEASURED here
            # and point at the live command for the rest.
            f"Signing status measured for the artifacts in this bundle: "
            f"{', '.join(sorted({a.authenticode_status for a in artifacts})) or 'unknown'}.",
            "",
            "For the current gate state, run:",
            "",
            "```powershell",
            r".venv\Scripts\python.exe scripts\release\determinex_release_gates.py",
            "```",
            "",
            "Until the signing and trust gates pass, do not describe this bundle as signed, trusted,",
            "or public-release ready.",
            "",
        ]
    )
    return "\n".join(lines)


def build_download_bundle(
    installer_dir: Path,
    output_dir: Path,
    evidence_dir: Path,
    *,
    root: Path | None = None,
    windows_msi_evidence_dir: Path | None = None,
) -> dict[str, Any]:
    repo_root = root or _repo_root()
    product_name, version = _read_tauri_metadata(repo_root)
    generated_at = _utc_now()
    stamp = generated_at.replace(":", "").replace("-", "")
    bundle_name = f"{product_name.lower()}-{version}-setup-{stamp}"
    bundle_dir = output_dir / bundle_name
    installers_dir = bundle_dir / "installers"
    installers_dir.mkdir(parents=True, exist_ok=True)
    evidence_dir.mkdir(parents=True, exist_ok=True)

    artifacts = discover_installers(installer_dir)
    artifact_types = {artifact.artifact_type for artifact in artifacts}
    source_commit = _git_commit(repo_root)
    msi_artifacts = [artifact for artifact in artifacts if artifact.artifact_type == "windows_msi"]
    msi_packet = _write_windows_msi_packet(
        windows_msi_evidence_dir or repo_root / DEFAULT_WINDOWS_MSI_EVIDENCE_DIR,
        generated_at,
        source_commit,
        msi_artifacts,
    )
    packaging_notes: list[str] = []
    if "windows_msi" not in artifact_types:
        packaging_notes.append(
            "windows_msi_not_in_bundle; use the NSIS setup artifact until WiX/MSI bundling is repaired"
        )
    missing_linux_package_types = [
        package_type
        for package_type in REQUIRED_LINUX_PACKAGE_TYPES
        if package_type not in artifact_types
    ]
    legal_public_distribution_passed = _has_passing_legal_public_distribution_packet(repo_root)
    if missing_linux_package_types:
        packaging_notes.append(
            "linux_packages_not_in_bundle; missing "
            + ", ".join(missing_linux_package_types)
            + "; build Linux packages on a Linux host before public Linux distribution"
        )
    copied_artifacts: list[dict[str, Any]] = []
    checksum_lines: list[str] = []
    for artifact in artifacts:
        target = installers_dir / artifact.file_name
        shutil.copy2(artifact.source_path, target)
        relative = target.relative_to(bundle_dir).as_posix()
        checksum_lines.append(f"{artifact.sha256}  {relative}")
        copied_artifacts.append(
            {
                "file_name": artifact.file_name,
                "artifact_type": artifact.artifact_type,
                "source_path": str(artifact.source_path),
                "bundle_relative_path": relative,
                "size_bytes": artifact.size_bytes,
                "sha256": artifact.sha256,
                "authenticode_status": artifact.authenticode_status,
            }
        )

    # Per-artifact, so the document cannot claim clean-host verification for a binary that
    # was rebuilt after the transcript was written.
    setup_text = _setup_markdown(
        product_name, version, artifacts, _clean_host_verified_hashes(repo_root)
    )
    (bundle_dir / "SETUP.md").write_text(setup_text, encoding="utf-8")
    (bundle_dir / "CHECKSUMS.sha256").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")

    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at,
        "product_name": product_name,
        "version": version,
        "platform": "cross-platform",
        "source_commit": source_commit,
        "installer_dir": str(installer_dir),
        "bundle_dir": str(bundle_dir),
        "package_matrix": {
            "windows_nsis_setup": "windows_nsis_setup" in artifact_types,
            "windows_msi": "windows_msi" in artifact_types,
            "linux_appimage": "linux_appimage" in artifact_types,
            "linux_deb": "linux_deb" in artifact_types,
            "linux_rpm": "linux_rpm" in artifact_types,
        },
        "release_ready": False,
        "public_distribution_ready": False,
        "setup_ready_for_local_operator_testing": True,
        "claim_boundary": (
            "Download bundle packaging proves that installer artifacts were wrapped with setup instructions "
            "and checksums. It does not prove signed/trusted public release, SmartScreen reputation, or "
            "clean-host install success."
        ),
        "remaining_blockers": [
            "code_signing_not_verified",
            "smartscreen_trust_not_verified",
            *(
                []
                if legal_public_distribution_passed
                else ["public_distribution_legal_ip_packet_not_executed"]
            ),
            "clean_host_install_proof_not_passed",
            *([] if "windows_msi" in artifact_types else ["windows_msi_not_bundled"]),
            *(
                []
                if not missing_linux_package_types
                else [
                    "linux_packages_not_bundled",
                    *(
                        f"{package_type}_not_bundled"
                        for package_type in missing_linux_package_types
                    ),
                ]
            ),
        ],
        "packaging_notes": packaging_notes,
        "windows_msi_evidence_packet": str(msi_packet) if msi_packet else None,
        "artifacts": copied_artifacts,
    }
    (bundle_dir / "download_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )

    zip_path = output_dir / f"{bundle_name}.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(bundle_dir.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(bundle_dir).as_posix())

    manifest["bundle_zip_path"] = str(zip_path)
    manifest["bundle_zip_size_bytes"] = zip_path.stat().st_size
    manifest["bundle_zip_sha256"] = _sha256(zip_path)
    manifest_text = json.dumps(manifest, indent=2)
    (bundle_dir / "download_manifest.json").write_text(manifest_text, encoding="utf-8")
    (evidence_dir / "download_manifest.json").write_text(manifest_text, encoding="utf-8")
    (evidence_dir / "SETUP.md").write_text(setup_text, encoding="utf-8")
    (evidence_dir / "CHECKSUMS.sha256").write_text(
        "\n".join(checksum_lines) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installer-dir", type=Path, required=True)
    parser.add_argument(
        "--output-dir", type=Path, default=Path(r"C:\tmp\determinex-download-bundles")
    )
    parser.add_argument("--evidence-dir", type=Path, default=DEFAULT_EVIDENCE_DIR)
    parser.add_argument(
        "--windows-msi-evidence-dir", type=Path, default=DEFAULT_WINDOWS_MSI_EVIDENCE_DIR
    )
    args = parser.parse_args()

    manifest = build_download_bundle(
        args.installer_dir,
        args.output_dir,
        args.evidence_dir,
        windows_msi_evidence_dir=args.windows_msi_evidence_dir,
    )
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
