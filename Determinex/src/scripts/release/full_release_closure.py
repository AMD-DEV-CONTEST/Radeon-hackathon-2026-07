"""Run the local Determinex full-release closure preflights.

The script updates evidence for what can be proven on this host. It does not
install the app, sign artifacts, publish binaries, or grant release authority.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.release import determinex_release_gates

SCHEMA_VERSION = "determinex-full-release-closure-v1"
PREFLIGHT_SCHEMA_VERSION = "determinex-clean-host-runner-preflight-v1"


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _date_stamp(now: str) -> str:
    return now[:10].replace("-", "")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git_head(root: Path) -> str:
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


def _latest_download_manifest(root: Path) -> Path | None:
    # Delegates to the one canonical resolver so closure and the gates can never disagree about
    # which bundle is current -- they had six hand-written copies of this glob between them.
    return determinex_release_gates.newest_download_manifest_path(root)


def verify_download_bundle(root: Path) -> dict[str, Any]:
    manifest_path = _latest_download_manifest(root)
    if manifest_path is None:
        return {
            "status": "blocked",
            "manifest_path": "",
            "exact_blocker": "No Determinex download bundle manifest found.",
            "checks": {},
        }

    manifest = _read_json(manifest_path)
    if not isinstance(manifest, dict):
        return {
            "status": "blocked",
            "manifest_path": str(manifest_path),
            "exact_blocker": "Download bundle manifest is not valid JSON.",
            "checks": {},
        }

    checks: dict[str, Any] = {
        "manifest_exists": True,
        "setup_ready_for_local_operator_testing": manifest.get(
            "setup_ready_for_local_operator_testing"
        )
        is True,
        "release_ready": manifest.get("release_ready") is True,
        "public_distribution_ready": manifest.get("public_distribution_ready") is True,
        "source_commit_current": manifest.get("source_commit") == _git_head(root),
    }
    blockers: list[str] = []
    zip_path = Path(str(manifest.get("bundle_zip_path") or ""))
    if not zip_path.is_file():
        blockers.append("download_bundle_zip_missing")
        checks["bundle_zip_exists"] = False
    else:
        checks["bundle_zip_exists"] = True
        expected_zip_hash = str(manifest.get("bundle_zip_sha256") or "")
        checks["bundle_zip_sha256_matches"] = (
            bool(expected_zip_hash) and _sha256(zip_path) == expected_zip_hash
        )
        if not checks["bundle_zip_sha256_matches"]:
            blockers.append("download_bundle_zip_sha256_mismatch")

    artifact_checks: list[dict[str, Any]] = []
    artifacts = manifest.get("artifacts") if isinstance(manifest.get("artifacts"), list) else []
    if not artifacts:
        blockers.append("download_bundle_has_no_installer_artifacts")
    if zip_path.is_file():
        try:
            with zipfile.ZipFile(zip_path) as zf:
                names = set(zf.namelist())
                for artifact in artifacts:
                    if not isinstance(artifact, dict):
                        continue
                    rel = str(artifact.get("bundle_relative_path") or "")
                    expected_sha = str(artifact.get("sha256") or "")
                    present = rel in names
                    sha_matches = False
                    if present and expected_sha:
                        sha_matches = _sha256_bytes(zf.read(rel)) == expected_sha
                    artifact_checks.append(
                        {
                            "bundle_relative_path": rel,
                            "present_in_zip": present,
                            "sha256_matches": sha_matches,
                            "authenticode_status": artifact.get("authenticode_status"),
                        }
                    )
                    if not present:
                        blockers.append(f"artifact_missing_from_zip:{rel}")
                    if present and not sha_matches:
                        blockers.append(f"artifact_sha256_mismatch:{rel}")
        except zipfile.BadZipFile:
            blockers.append("download_bundle_zip_invalid")
    checks["artifacts"] = artifact_checks

    if checks["release_ready"]:
        blockers.append("download_bundle_manifest_illegally_claims_release_ready")
    if checks["public_distribution_ready"]:
        blockers.append("download_bundle_manifest_illegally_claims_public_distribution_ready")
    if not checks["source_commit_current"]:
        blockers.append("download_bundle_source_commit_not_current")
    # Everything appended ABOVE this line is an integrity finding about this bundle: a corrupt
    # zip, a missing or wrong-hash artifact, a manifest claiming authority it does not have, a
    # stale source commit. Those mean the artifact is not trustworthy.
    #
    # What follows is different in kind: blockers the manifest itself already reported, i.e. the
    # release is not ready yet (unsigned, gates deferred). "passed_with_release_blockers" exists
    # precisely to describe a well-formed bundle for a not-yet-ready release, so those must not
    # block. Keeping the two in one flat list is what made the verdict below reach for a substring.
    integrity_blockers = list(dict.fromkeys(blockers))
    for blocker in manifest.get("remaining_blockers") or []:
        blockers.append(str(blocker))

    blockers = list(dict.fromkeys(blockers))
    return {
        # Fixed 2026-07-30. The condition was `not any("mismatch" in b for b in blockers)`, so ONLY
        # the two blockers whose text happens to contain the word "mismatch" could flip this. A
        # corrupt zip (download_bundle_zip_invalid), an artifact missing from the zip, a bundle
        # with no installer artifacts at all, and even
        # download_bundle_manifest_illegally_claims_release_ready ALL reported
        # "passed_with_release_blockers". A substring of a human-readable message is not a verdict.
        # Now it keys on the integrity set, so a broken bundle blocks while a well-formed bundle
        # for a not-yet-ready release still reports passed_with_release_blockers.
        "status": (
            "passed_with_release_blockers"
            if checks["bundle_zip_exists"] and not integrity_blockers
            else "blocked"
        ),
        "integrity_blockers": integrity_blockers,
        "manifest_path": str(manifest_path),
        "checks": checks,
        "remaining_blockers": blockers,
        "exact_blocker": "; ".join(blockers),
    }


def probe_clean_runner(root: Path, now: str | None = None) -> dict[str, Any]:
    generated_at = now or _utc_now()
    attempts: list[dict[str, Any]] = []
    selected: dict[str, Any] | None = None
    for command in (["docker", "info"], ["docker", "--context", "desktop-linux", "info"]):
        try:
            result = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=45)
            attempt = {
                "command": command,
                "exit_code": result.returncode,
                "stdout_tail": result.stdout[-4000:],
                "stderr_tail": result.stderr[-4000:],
            }
        except Exception as exc:
            attempt = {
                "command": command,
                "exit_code": -1,
                "stdout_tail": "",
                "stderr_tail": repr(exc),
            }
        attempts.append(attempt)
        if attempt["exit_code"] == 0:
            selected = attempt
            break
    if selected is None:
        selected = (
            attempts[-1]
            if attempts
            else {
                "command": ["docker", "info"],
                "exit_code": -1,
                "stdout_tail": "",
                "stderr_tail": "not run",
            }
        )

    available = selected["exit_code"] == 0
    combined_errors = "\n".join(str(attempt.get("stderr_tail") or "") for attempt in attempts)
    sandbox_denied = not available and (
        "Access is denied" in combined_errors
        or "permission denied while trying to connect to the docker API" in combined_errors
    )
    exact_blocker = (
        "Clean runner is available, but clean-host installer install/launch/uninstall proof has not been executed."
        if available
        else (
            "Current runner cannot access Docker Desktop state; rerun the clean-host probe outside the sandbox."
            if sandbox_denied
            else "Docker/local clean runner unavailable or not healthy."
        )
    )
    return {
        "schema_version": PREFLIGHT_SCHEMA_VERSION,
        "generated_at_utc": generated_at,
        "docker_info_available": available,
        "docker_info_exit_code": selected["exit_code"],
        "docker_probe_blocked_by_sandbox": sandbox_denied,
        "clean_host_fresh_install": False,
        "installer_execution_performed": False,
        "release_ready": False,
        "authority_granted": False,
        "exact_blocker": exact_blocker,
        "transcript": {
            "command": selected["command"],
            "timeout_seconds": 45,
            "stdout_tail": selected["stdout_tail"],
            "stderr_tail": selected["stderr_tail"],
            "attempts": attempts,
        },
    }


def write_clean_runner_preflight(root: Path, preflight: dict[str, Any]) -> Path:
    out_dir = root / "assurance/evidence/full_release_closure"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = _date_stamp(str(preflight.get("generated_at_utc") or _utc_now()))
    output = out_dir / f"clean_host_runner_preflight_{stamp}.json"
    output.write_text(json.dumps(preflight, indent=2), encoding="utf-8")
    return output


def build_report(root: Path, *, run_clean_runner_probe: bool = True) -> dict[str, Any]:
    now = _utc_now()
    preflight_path = None
    preflight = None
    if run_clean_runner_probe:
        preflight = probe_clean_runner(root, now)
        preflight_path = write_clean_runner_preflight(root, preflight)

    gate_report = determinex_release_gates.collect(root)
    bundle = verify_download_bundle(root)
    gate_payload = gate_report.to_dict()
    blocked = list(gate_payload["blocked_gate_ids"])
    partial = list(gate_payload["partial_gate_ids"])
    deferred = list(gate_payload.get("deferred_gate_ids") or [])
    legal_public_distribution_passed = "legal_public_distribution" not in blocked
    first_e2e_next_action = "Create or reset the first E2E user workflow session with sufficient budget and rerun it from a quiet model runtime."
    for gate in gate_payload.get("gates", []):
        if (
            isinstance(gate, dict)
            and gate.get("gate_id") == "first_e2e"
            and gate.get("next_action")
        ):
            first_e2e_next_action = str(gate["next_action"])
            break

    protected_external_blockers = [
        "code_signing_not_verified",
        "smartscreen_trust_not_verified",
        "vscode_openvsx_extension_import_runtime_not_implemented",
        "coordinated_internal_determinex_rename_not_complete",
    ]
    if not legal_public_distribution_passed:
        protected_external_blockers.append("public_distribution_legal_ip_packet_not_executed")
    if "windows_trust" in blocked:
        protected_external_blockers.append("windows_signing_smartscreen_trust_not_verified")
    if "legal_public_distribution" in blocked:
        protected_external_blockers.append("legal_public_distribution_packet_not_executed")
    if "windows_msi" in blocked:
        protected_external_blockers.append("windows_msi_distribution_not_built")
    if "linux_packages" in blocked:
        protected_external_blockers.append("linux_package_distribution_not_built")
    if "clean_host" in blocked:
        protected_external_blockers.append(
            "clean_host_install_launch_uninstall_transcript_not_executed"
        )
    if "first_e2e" in blocked:
        protected_external_blockers.append("first_end_to_end_user_workflow_not_passed")

    next_executable_actions = [
        "Run a clean Windows install/launch/uninstall transcript against the packaged setup artifact.",
        first_e2e_next_action,
        "Sign the Windows installer, verify Authenticode and SmartScreen trust, and record a Windows trust packet.",
        (
            "Finish signing, SmartScreen/trust, legal/IP, and public distribution packets."
            if not legal_public_distribution_passed
            else "Finish signing and SmartScreen/trust packets."
        ),
        "Implement and test the VS Code/Open VSX extension compatibility contract before claiming natural-successor parity.",
    ]
    if not legal_public_distribution_passed:
        next_executable_actions.insert(
            3,
            "Complete legal/IP, license, model notice, secret-scan, and public-repo scrub review before public distribution.",
        )
    if "windows_msi" in blocked:
        next_executable_actions.insert(
            4,
            "Build and smoke a WiX/MSI package, then record a Windows MSI evidence packet.",
        )
    if "linux_packages" in blocked:
        insert_at = 5 if "windows_msi" in blocked else 4
        next_executable_actions.insert(
            insert_at,
            "Build Linux AppImage/deb/rpm artifact(s) on a Linux host, then refresh the download bundle manifest.",
        )
    bundle_checks = bundle.get("checks") if isinstance(bundle.get("checks"), dict) else {}
    if bundle_checks.get("source_commit_current") is not True:
        next_executable_actions.insert(
            0, "Rebuild the download bundle after the final release commit."
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": now,
        "product_name": "Determinex",
        "release_ready": False,
        "authority_granted": False,
        "local_download_bundle_verification": bundle,
        "clean_host_runner_preflight_path": str(preflight_path) if preflight_path else "",
        "clean_host_runner_preflight": preflight,
        "release_gate_report": gate_payload,
        "blocked_gate_ids": blocked,
        "partial_gate_ids": partial,
        "deferred_gate_ids": deferred,
        "protected_external_blockers": protected_external_blockers,
        "deferred_proof_tracks": [
            "ProgramBench 200/200 strict locks remain deferred; do not make ProgramBench solve claims until official full-suite evidence exists.",
            "SWE-bench Lite fresh privacy-mode reruns remain deferred; do not make privacy-cost publication claims until rerun packets exist.",
            "SWE-bench Pro remains deferred; do not make SWE-bench Pro claims until a separate public evidence packet exists.",
        ],
        "next_executable_actions": next_executable_actions,
        "notes": [
            "This closure pass executes local preflights only.",
            "It does not install the app, sign artifacts, publish a release, or grant release authority.",
        ],
    }


def write_report(
    output_path: Path, root: Path | str | None = None, *, run_clean_runner_probe: bool = True
) -> dict[str, Any]:
    repo_root = Path(root) if root is not None else _repo_root()
    report = build_report(repo_root, run_clean_runner_probe=run_clean_runner_probe)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("assurance/evidence/full_release_closure/run_20260707.json"),
    )
    parser.add_argument("--skip-clean-runner-probe", action="store_true")
    args = parser.parse_args()

    report = write_report(
        args.output, args.root, run_clean_runner_probe=not args.skip_clean_runner_probe
    )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
