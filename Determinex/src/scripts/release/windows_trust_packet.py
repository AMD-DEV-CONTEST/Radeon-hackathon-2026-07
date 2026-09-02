"""Create Windows signing and SmartScreen trust evidence from installer artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Run directly, so the repo root needs to be importable before asking the gates which download
# manifest is current. Same reason as clean_host_kit.
_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.release import determinex_release_gates  # noqa: E402  (needs the sys.path line above)

SCHEMA_VERSION = "determinex-windows-trust-evidence-v1"
WINDOWS_ARTIFACT_TYPES = {"windows_msi", "windows_nsis_setup"}


def _utc_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_artifact_path(root: Path, manifest: dict[str, Any], artifact: dict[str, Any]) -> Path:
    candidates: list[Path] = []
    source_path = str(artifact.get("source_path") or "").strip()
    if source_path:
        source = Path(source_path)
        candidates.append(source)
        candidates.append(root / source)
    bundle_relative_path = str(artifact.get("bundle_relative_path") or "").strip()
    bundle_dir = str(manifest.get("bundle_dir") or "").strip()
    if bundle_relative_path and bundle_dir:
        bundle_candidate = Path(bundle_dir) / bundle_relative_path
        candidates.append(bundle_candidate)
        candidates.append(root / bundle_candidate)
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError(f"Windows installer artifact not found: {artifact.get('file_name')}")


def _powershell_signature(path: Path) -> dict[str, str]:
    script = (
        "$Path = $env:DETERMINEX_TRUST_PROBE_PATH; "
        "$s = Get-AuthenticodeSignature -LiteralPath $Path; "
        "[pscustomobject]@{"
        "Status=$s.Status.ToString();"
        "StatusMessage=$s.StatusMessage;"
        "SignerCertificateSubject=if ($s.SignerCertificate) { $s.SignerCertificate.Subject } else { '' };"
        "TimeStamperCertificateSubject=if ($s.TimeStamperCertificate) { $s.TimeStamperCertificate.Subject } else { '' }"
        "} | ConvertTo-Json -Compress"
    )
    env = os.environ.copy()
    env["DETERMINEX_TRUST_PROBE_PATH"] = str(path)
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    if completed.returncode != 0:
        return {
            "Status": "ProbeFailed",
            "StatusMessage": completed.stderr.strip()[-2000:],
            "SignerCertificateSubject": "",
            "TimeStamperCertificateSubject": "",
        }
    try:
        data = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {
            "Status": "ProbeFailed",
            "StatusMessage": completed.stdout.strip()[-2000:],
            "SignerCertificateSubject": "",
            "TimeStamperCertificateSubject": "",
        }
    return {
        key: str(data.get(key) or "")
        for key in (
            "Status",
            "StatusMessage",
            "SignerCertificateSubject",
            "TimeStamperCertificateSubject",
        )
    }


def build_packet(
    root: Path,
    manifest_path: Path,
    *,
    smartscreen_result: str = "not_performed",
    smartscreen_verification_performed: bool = False,
) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifacts: list[dict[str, Any]] = []
    for artifact in manifest.get("artifacts", []):
        if (
            not isinstance(artifact, dict)
            or artifact.get("artifact_type") not in WINDOWS_ARTIFACT_TYPES
        ):
            continue
        path = _resolve_artifact_path(root, manifest, artifact)
        signature = _powershell_signature(path)
        expected_sha = str(artifact.get("sha256") or "").lower()
        actual_sha = _sha256(path)
        artifacts.append(
            {
                "artifact_type": artifact.get("artifact_type"),
                "path": str(path),
                "file_name": path.name,
                "sha256": actual_sha,
                "sha256_verified": bool(expected_sha) and expected_sha == actual_sha,
                "authenticode_status": signature["Status"],
                "authenticode_status_message": signature["StatusMessage"],
                "certificate_subject": signature["SignerCertificateSubject"],
                "timestamp_certificate_subject": signature["TimeStamperCertificateSubject"],
            }
        )
    if not artifacts:
        raise ValueError(f"No Windows installer artifacts found in {manifest_path}")

    statuses = {str(item["authenticode_status"]) for item in artifacts}
    all_signed = statuses == {"Valid"}
    timestamp_verified = all(bool(item["timestamp_certificate_subject"]) for item in artifacts)
    certificate_subjects = sorted(
        {str(item["certificate_subject"]) for item in artifacts if item["certificate_subject"]}
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "manifest_path": str(manifest_path),
        "artifact_authenticode_status": "Valid" if all_signed else ",".join(sorted(statuses)),
        "code_signing_verified": all_signed,
        "timestamp_verified": timestamp_verified,
        "smartscreen_verification_performed": smartscreen_verification_performed,
        "smartscreen_result": smartscreen_result,
        "certificate_subject": "; ".join(certificate_subjects),
        "artifacts": artifacts,
        "claim_boundary": "This records Windows Authenticode and optional SmartScreen observations only. It does not grant release authority.",
        "authority_granted": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    # No default here on purpose. This used to default to
    # assurance/evidence/determinex_download_bundle_20260707/download_manifest.json, a path that
    # goes stale the moment anyone packages a new bundle -- so the trust packet would silently
    # report Authenticode status for installers we no longer ship. Resolved below from the same
    # place the gates resolve it.
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--smartscreen-result", default="not_performed")
    parser.add_argument("--smartscreen-verification-performed", action="store_true")
    args = parser.parse_args()

    root = Path.cwd()
    if args.manifest is None:
        resolved = determinex_release_gates.newest_download_manifest_path(root)
        if resolved is None:
            print(
                "no download_manifest.json under assurance/evidence/ -- package a bundle first "
                "or pass --manifest explicitly",
                file=sys.stderr,
            )
            return 1
        manifest_path = resolved
    else:
        manifest_path = args.manifest if args.manifest.is_absolute() else root / args.manifest
    output = (
        args.output
        or root / "assurance/evidence/windows_trust" / f"windows_trust_{_utc_stamp()}.json"
    )
    output = output if output.is_absolute() else root / output

    packet = build_packet(
        root,
        manifest_path,
        smartscreen_result=args.smartscreen_result,
        smartscreen_verification_performed=args.smartscreen_verification_performed,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(packet, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(output),
                "artifact_authenticode_status": packet["artifact_authenticode_status"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
