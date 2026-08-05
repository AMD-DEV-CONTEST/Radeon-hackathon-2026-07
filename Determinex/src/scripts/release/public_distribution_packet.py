"""Build the legal/public distribution evidence packet for source opening."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

SCHEMA_VERSION = "determinex-legal-public-distribution-evidence-v1"

AGPL_FILES = (
    "LICENSE",
    "pyproject.toml",
    "frontend/package.json",
    "frontend/src-tauri/Cargo.toml",
    "frontend/vscode-extension/package.json",
)

NOTICE_FILES = (
    "docs/release/MODEL_NOTICES.md",
    "docs/release/THIRD_PARTY_NOTICES.md",
)

# The corpus is published (2026-07-31), so the projects vendored inside it are redistributed and
# their notices are a distribution obligation, not an optional extra. `third_party_notices_present`
# was true on the strength of a 17-line file that named three SBOMs and did not mention the corpus
# at all, while the actual inventory of upstream projects lived in a 449-line file the packet never
# read. An operator attesting legal review off that packet would have been attesting over an
# inventory that omitted every one of them.
CORPUS_NOTICE_FILES = (
    "corpus/THIRD_PARTY_NOTICES.md",
    "corpus/REDISTRIBUTION_BOUNDARY.json",
)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _agpl_license_ok(root: Path) -> tuple[bool, list[str]]:
    evidence: list[str] = []
    for rel in AGPL_FILES:
        path = root / rel
        if not path.is_file():
            return False, evidence
        text = _read_text(path)
        evidence.append(rel)
        if rel == "LICENSE":
            if "GNU AFFERO GENERAL PUBLIC LICENSE" not in text or "Version 3" not in text:
                return False, evidence
        elif "AGPL-3.0" not in text:
            return False, evidence
    return True, evidence


def _notices_present(root: Path) -> tuple[bool, list[str]]:
    evidence: list[str] = []
    for rel in NOTICE_FILES:
        path = root / rel
        if not path.is_file() or not _read_text(path).strip():
            return False, evidence
        evidence.append(rel)
    corpus_ok, corpus_evidence = _corpus_notices_cover_what_ships(root)
    evidence.extend(corpus_evidence)
    return corpus_ok, evidence


def _corpus_notices_cover_what_ships(root: Path) -> tuple[bool, list[str]]:
    """Require the corpus notices to exist AND to be reachable from the release notices.

    Two separate failures are possible and both have to be caught. The notices can be absent, or
    they can exist while the document an operator actually reads never points at them -- which is
    the state this check was written for.
    """
    evidence: list[str] = []
    boundary_path = root / "corpus" / "REDISTRIBUTION_BOUNDARY.json"
    for rel in CORPUS_NOTICE_FILES:
        path = root / rel
        if not path.is_file() or not _read_text(path).strip():
            return False, evidence
        evidence.append(rel)

    # The boundary manifest must be readable and must actually account for something. An empty
    # boundary would satisfy a mere file-exists check while accounting for nothing.
    try:
        boundary = json.loads(_read_text(boundary_path))
    except (OSError, json.JSONDecodeError):
        return False, evidence
    if not isinstance(boundary, dict):
        return False, evidence
    counted = int(boundary.get("publishable_count") or 0) + int(boundary.get("withheld_count") or 0)
    if counted <= 0:
        return False, evidence

    release_notices = _read_text(root / "docs/release/THIRD_PARTY_NOTICES.md")
    if not all(rel in release_notices for rel in CORPUS_NOTICE_FILES):
        return False, evidence
    return True, evidence


def _secret_scan_clean(pushed: bool) -> tuple[bool, str]:
    args = ["python", "scripts/security/secret_scan.py"]
    if pushed:
        args.append("--pushed")
    try:
        completed = subprocess.run(
            args,
            cwd=Path.cwd(),
            text=True,
            capture_output=True,
            check=False,
            # 240s was shorter than the work. With --pushed the scanner walks the entire history of
            # a ~10 GB repository; it budgets 1800s for that git call itself, so a 4-minute cap here
            # recorded public_repo_secret_scan_passed=False for a scan that had not finished --
            # indistinguishable in the packet from a scan that found a secret.
            timeout=2100,
        )
    except subprocess.TimeoutExpired as exc:
        return False, f"{' '.join(args)} timed out after {exc.timeout} seconds"
    transcript = "\n".join(part for part in (completed.stdout, completed.stderr) if part).strip()
    return completed.returncode == 0, transcript[-8000:]


def build_packet(root: Path, *, operator_reviewed: bool, pushed_secret_scan: bool = True) -> dict:
    agpl_ok, license_evidence = _agpl_license_ok(root)
    notices_ok, notice_evidence = _notices_present(root)
    secret_clean, secret_scan_transcript = _secret_scan_clean(pushed_secret_scan)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "legal_review_completed": bool(
            operator_reviewed and agpl_ok and notices_ok and secret_clean
        ),
        "license_inventory_reviewed": agpl_ok,
        "model_notice_reviewed": notices_ok,
        "public_repo_secret_scan_passed": secret_clean,
        "public_repo_scrub_completed": bool(operator_reviewed and secret_clean),
        "third_party_notices_present": notices_ok,
        "authority_granted": False,
        "operator_reviewed": bool(operator_reviewed),
        "pushed_secret_scan": bool(pushed_secret_scan),
        "evidence": {
            "license_files": license_evidence,
            "notice_files": notice_evidence,
            "secret_scan_command": "python scripts/security/secret_scan.py --pushed"
            if pushed_secret_scan
            else "python scripts/security/secret_scan.py",
            "secret_scan_transcript_tail": secret_scan_transcript,
        },
        "claim_boundary": (
            "This packet records public-distribution hygiene checks and operator review. "
            "It does not grant release authority and is not a substitute for external legal counsel."
        ),
    }


def write_packet(
    root: Path, output: Path, *, operator_reviewed: bool, pushed_secret_scan: bool = True
) -> dict:
    packet = build_packet(
        root, operator_reviewed=operator_reviewed, pushed_secret_scan=pushed_secret_scan
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(packet, indent=2) + "\n", encoding="utf-8")
    return packet


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--operator-reviewed", action="store_true")
    parser.add_argument("--tracked-only-secret-scan", action="store_true")
    args = parser.parse_args()

    root = Path.cwd()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output = (
        args.output
        or root
        / "assurance/evidence/public_distribution"
        / f"legal_public_distribution_{stamp}.json"
    )
    output = output if output.is_absolute() else root / output
    packet = write_packet(
        root,
        output,
        operator_reviewed=args.operator_reviewed,
        pushed_secret_scan=not args.tracked_only_secret_scan,
    )
    print(
        json.dumps(
            {"output": str(output), "legal_review_completed": packet["legal_review_completed"]},
            indent=2,
        )
    )
    return (
        0
        if all(
            packet[field] is True
            for field in (
                "legal_review_completed",
                "license_inventory_reviewed",
                "model_notice_reviewed",
                "public_repo_secret_scan_passed",
                "public_repo_scrub_completed",
                "third_party_notices_present",
            )
        )
        else 2
    )


if __name__ == "__main__":
    raise SystemExit(main())
