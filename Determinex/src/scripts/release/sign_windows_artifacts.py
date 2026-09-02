"""Sign the shipped Windows installers, then regenerate the windows_trust evidence.

`windows_trust` is the one remaining deferred gate that a purchase converts. Everything except the
certificate itself is now mechanical: this resolves the artifacts from the same manifest the gates
read, signs them with a real timestamp, verifies the result, and hands off to
`windows_trust_packet.py`.

WHY A SELF-SIGNED CERTIFICATE CANNOT SHORTCUT THIS, and why that is the gate working correctly:
`_windows_trust_errors` requires `artifact_authenticode_status == "Valid"`. Authenticode is only
"Valid" when the signing chain terminates in a root the *verifying machine* trusts. A self-signed
cert is trusted on the box that created it and nowhere else, so it would read Valid here and
UnknownError/NotTrusted for every user — a packet that says "signed" while every download still
warns. That is precisely the overclaim this repo keeps finding, so there is no flag here to force it.

WHAT TO BUY. An OV (Organization Validation) code-signing certificate is the cheap option (~$200-400
/yr) but SmartScreen reputation is earned per-certificate over time, so early downloads still warn.
An EV (Extended Validation) certificate costs more (~$400-700/yr) and carries SmartScreen reputation
immediately. Since 2023 both are issued on FIPS-140-2 hardware (a token, or a cloud HSM such as
Azure Trusted Signing / DigiCert KeyLocker / SSL.com eSigner), so there is no PFX file to point at
any more — pass the certificate by subject name or thumbprint and let the token/HSM hold the key.
That is why this script takes `--subject`/`--thumbprint` rather than a path and a password.

    # hardware token or cloud HSM already configured on this machine
    .venv\\Scripts\\python.exe scripts\\release\\sign_windows_artifacts.py --subject "Your Org Legal Name"
    .venv\\Scripts\\python.exe scripts\\release\\windows_trust_packet.py --smartscreen-verification-performed \\
        --smartscreen-result pass

SmartScreen cannot be established from this script: it is a property of Microsoft's reputation
service observed by downloading the signed artifact in a browser on a clean machine. It is recorded
by the trust packet as an operator observation, deliberately, rather than inferred here.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.release import determinex_release_gates  # noqa: E402

WINDOWS_ARTIFACT_TYPES = {"windows_msi", "windows_nsis_setup"}

#: RFC-3161 timestamp authority. Without a timestamp a signature dies with the certificate; with
#: one it stays valid for the life of the timestamp, which is why `timestamp_verified` is its own
#: field in the trust packet rather than folded into `code_signing_verified`.
DEFAULT_TIMESTAMP_URL = "http://timestamp.digicert.com"


def _find_signtool() -> Path | None:
    """The newest signtool.exe from the Windows SDK, or whatever is on PATH."""
    on_path = shutil.which("signtool")
    if on_path:
        return Path(on_path)
    roots = [
        Path(r"C:\Program Files (x86)\Windows Kits\10\bin"),
        Path(r"C:\Program Files\Windows Kits\10\bin"),
    ]
    found: list[Path] = []
    for root in roots:
        if root.is_dir():
            found.extend(root.glob("*/x64/signtool.exe"))
    return sorted(found)[-1] if found else None


def _windows_artifacts(root: Path) -> list[tuple[str, Path]]:
    """Resolve the shipped Windows installers from the manifest the gates read."""
    manifest_path = determinex_release_gates.newest_download_manifest_path(root)
    if manifest_path is None:
        raise SystemExit(
            "no download_manifest.json under assurance/evidence/ — package a bundle first "
            "(scripts/release/package_download_bundle.py)"
        )
    manifest: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    out: list[tuple[str, Path]] = []
    for artifact in manifest.get("artifacts", []):
        if artifact.get("artifact_type") not in WINDOWS_ARTIFACT_TYPES:
            continue
        source = str(artifact.get("source_path") or "").strip()
        for candidate in (Path(source), root / source):
            if source and candidate.is_file():
                out.append((str(artifact.get("file_name")), candidate.resolve()))
                break
        else:
            print(f"  WARN {artifact.get('file_name')}: source_path not found on disk")
    if not out:
        raise SystemExit(
            f"{manifest_path} lists no Windows installer with a resolvable source_path"
        )
    return out


def sign(
    artifact: Path,
    signtool: Path,
    *,
    subject: str | None,
    thumbprint: str | None,
    timestamp_url: str,
    dry_run: bool,
) -> tuple[bool, str]:
    cmd: list[str] = [str(signtool), "sign", "/fd", "SHA256", "/td", "SHA256", "/tr", timestamp_url]
    if thumbprint:
        cmd += ["/sha1", thumbprint]
    elif subject:
        cmd += ["/n", subject]
    else:  # /a picks the best available cert in the store
        cmd += ["/a"]
    cmd += ["/v", str(artifact)]

    if dry_run:
        return True, "DRY RUN: " + " ".join(cmd)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    return proc.returncode == 0, (proc.stdout + proc.stderr).strip()[-800:]


def verify(artifact: Path, signtool: Path) -> tuple[bool, str]:
    """`/pa` uses the Authenticode policy — the same chain evaluation the trust packet reads."""
    proc = subprocess.run(
        [str(signtool), "verify", "/pa", "/v", str(artifact)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    return proc.returncode == 0, (proc.stdout + proc.stderr).strip()[-800:]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--subject", help='certificate subject name, e.g. "Your Org Legal Name"')
    group.add_argument("--thumbprint", help="certificate SHA-1 thumbprint (no spaces)")
    parser.add_argument("--timestamp-url", default=DEFAULT_TIMESTAMP_URL)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the exact signtool invocations without running them",
    )
    args = parser.parse_args()

    root = Path.cwd()
    signtool = _find_signtool()
    if signtool is None:
        print(
            "signtool.exe not found. Install the Windows SDK "
            "(winget install Microsoft.WindowsSDK) or put signtool on PATH.",
            file=sys.stderr,
        )
        return 1
    print(f"signtool: {signtool}")

    artifacts = _windows_artifacts(root)
    print(f"artifacts to sign ({len(artifacts)}):")
    for name, path in artifacts:
        print(f"  {name}  <-  {path}")
    print()

    failures = 0
    for name, path in artifacts:
        ok, output = sign(
            path,
            signtool,
            subject=args.subject,
            thumbprint=args.thumbprint,
            timestamp_url=args.timestamp_url,
            dry_run=args.dry_run,
        )
        print(f"  {'OK  ' if ok else 'FAIL'} sign {name}")
        if not ok:
            failures += 1
            print(f"        {output}")
            continue
        if args.dry_run:
            print(f"        {output}")
            continue
        ok, output = verify(path, signtool)
        print(f"  {'OK  ' if ok else 'FAIL'} verify {name}")
        if not ok:
            failures += 1
            print(f"        {output}")

    if args.dry_run:
        print("\nDry run only — nothing was signed.")
        return 0
    if failures:
        print(f"\n{failures} step(s) failed; the trust packet would record the failure honestly.")
        return 1

    print("\nSigned and verified. Now record the evidence:")
    print(r"  .venv\Scripts\python.exe scripts\release\windows_trust_packet.py \\")
    print(r"      --smartscreen-verification-performed --smartscreen-result pass")
    print("\nSmartScreen must be OBSERVED, not assumed: download the signed installer in a browser")
    print("on a machine that has never seen it and record what actually happens.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
