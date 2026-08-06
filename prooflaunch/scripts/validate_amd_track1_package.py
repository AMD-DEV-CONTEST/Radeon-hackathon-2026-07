from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
KIT = Path("submission/track1-prooflaunch")
EXPECTED_TEAM = "Banyan"
EXPECTED_APPLICATION = "ProofLaunch"
EXPECTED_TITLE = "Track 1, Banyan, ProofLaunch: Multimodal GTM Studio"
EXPECTED_DESTINATION = "prooflaunch/"

REQUIRED_FILES = (
    Path("LICENSE"),
    Path("THIRD_PARTY.md"),
    Path("CONTRIBUTING.md"),
    Path("CODE_OF_CONDUCT.md"),
    Path("SECURITY.md"),
    Path("SUPPORT.md"),
    Path("GOVERNANCE.md"),
    Path("CHANGELOG.md"),
    Path("README.md"),
    Path("JUDGE_START_HERE.md"),
    Path("SUBMISSION_GATE.json"),
    Path("docs/ProofLaunch_Project_Profile.pdf"),
    Path("docs/ProofLaunch_Submission_Deck.pptx"),
    Path("docs/ProofLaunch_Poster.pptx"),
    Path("docs/COMPETITION_PACKAGE.md"),
    Path("docs/INSTALLATION.md"),
    Path("docs/MODEL_CARD.md"),
    Path("docs/RADEON_SETUP.md"),
    Path("docs/EVALUATION.md"),
    Path("docs/DEMO_VIDEO_SHOTLIST.md"),
    KIT / "README.md",
    KIT / "PR_BODY.md",
    KIT / "RADEON_FINAL_CAPTURE.md",
    KIT / "PUBLIC_RELEASE_POLICY.md",
    KIT / "SUBMISSION_MANIFEST.json",
    Path("demos/run_track1_demo.py"),
    Path("scripts/build_amd_public_export.py"),
    Path("scripts/validate_amd_public_export.py"),
)

OFFICIAL_TEXT_FILES = (
    Path("README.md"),
    Path("JUDGE_START_HERE.md"),
    Path("docs/SUBMISSION_CHECKLIST.md"),
    Path("docs/DEMO_VIDEO_SHOTLIST.md"),
    Path("docs/COMPETITION_PACKAGE.md"),
    Path("docs/INSTALLATION.md"),
    Path("docs/MODEL_CARD.md"),
    Path("docs/RADEON_SETUP.md"),
    Path("docs/EVALUATION.md"),
    Path("SUBMISSION_GATE.json"),
    KIT / "README.md",
    KIT / "PR_BODY.md",
    KIT / "RADEON_FINAL_CAPTURE.md",
    KIT / "PUBLIC_RELEASE_POLICY.md",
    KIT / "SUBMISSION_MANIFEST.json",
)

TITLE_FILES = (
    Path("README.md"),
    Path("JUDGE_START_HERE.md"),
    Path("docs/SUBMISSION_CHECKLIST.md"),
    Path("SUBMISSION_GATE.json"),
    KIT / "README.md",
    KIT / "PUBLIC_RELEASE_POLICY.md",
    KIT / "SUBMISSION_MANIFEST.json",
)

FORBIDDEN_TEXT = (
    "Track 1, ProofLaunch, ProofLaunch",
    "Evidence-Grounded Multimodal Campaign Studio",
    "prooflaunch_submission/",
    "OwlSeer",
    "owlseer",
)

SECRET_PATTERNS = {
    "aws_access_key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "github_token": re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    "generic_secret_key": re.compile(r"(?i)(api[_-]?key|secret[_-]?key)\s*[:=]\s*['\"][^'\"]{8,}"),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}

HAN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return payload


def validate(root: str | Path = ROOT) -> dict[str, Any]:
    project = Path(root).resolve()
    errors: list[str] = []
    warnings: list[str] = []

    for relative in REQUIRED_FILES:
        if not (project / relative).is_file():
            errors.append(f"missing_required_file:{relative.as_posix()}")

    for relative in OFFICIAL_TEXT_FILES:
        path = project / relative
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        if HAN.search(text):
            errors.append(f"non_english_submission_text:{relative.as_posix()}")
        for marker in FORBIDDEN_TEXT:
            if marker in text:
                errors.append(f"forbidden_text:{relative.as_posix()}:{marker}")
        for name, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                errors.append(f"possible_secret:{relative.as_posix()}:{name}")

    for relative in TITLE_FILES:
        path = project / relative
        if path.is_file() and EXPECTED_TITLE not in path.read_text(encoding="utf-8"):
            errors.append(f"title_mismatch:{relative.as_posix()}")

    if (project / KIT / "TRACK1_SHARE_ZH.md").exists():
        errors.append("chinese_community_copy_inside_official_kit")

    gitignore_path = project / ".gitignore"
    if gitignore_path.is_file():
        ignore_lines = {
            line.strip()
            for line in gitignore_path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        for expected in (".prooflaunch-secrets/", ".prooflaunch-runtime/", ".venv/", "dist/"):
            if expected not in ignore_lines:
                errors.append(f"missing_private_ignore:{expected}")
    else:
        errors.append("missing_gitignore")

    manifest_path = project / KIT / "SUBMISSION_MANIFEST.json"
    gate_path = project / "SUBMISSION_GATE.json"
    runtime_blockers: list[str] = []
    if manifest_path.is_file():
        try:
            manifest = _read_json(manifest_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"invalid_submission_manifest:{exc}")
        else:
            expected_fields = {
                "team": EXPECTED_TEAM,
                "application": EXPECTED_APPLICATION,
                "github_submitter": "sylvanccc",
                "official_repository_destination": EXPECTED_DESTINATION,
                "proposed_pr_title": EXPECTED_TITLE,
                "submission_language": "English",
                "public_export_builder": "scripts/build_amd_public_export.py",
            }
            for field, expected in expected_fields.items():
                if manifest.get(field) != expected:
                    errors.append(f"manifest_field_mismatch:{field}")
            for record in manifest.get("core_evidence", []):
                relative = Path(str(record.get("path", "")))
                path = project / relative
                if not path.is_file():
                    errors.append(f"missing_core_evidence:{relative.as_posix()}")
                    continue
                if record.get("sha256") != _sha256(path):
                    errors.append(f"core_evidence_hash_mismatch:{relative.as_posix()}")
            runtime_blockers.extend(str(item) for item in manifest.get("hard_blockers", []))

    competition_status = "unknown"
    if gate_path.is_file():
        try:
            gate = _read_json(gate_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"invalid_submission_gate:{exc}")
        else:
            competition_status = str(gate.get("overallStatus", "unknown"))
            if gate.get("proposedPullRequestTitle") != EXPECTED_TITLE:
                errors.append("gate_title_mismatch")
            if competition_status != "ready":
                warnings.append(f"competition_gate_not_ready:{competition_status}")

    return {
        "schema": "ProofLaunchAMDTrack1PackageValidationV1",
        "structural_status": "passed" if not errors else "failed",
        "competition_status": competition_status,
        "errors": sorted(set(errors)),
        "warnings": sorted(set(warnings)),
        "runtime_blockers": runtime_blockers,
    }


def main() -> int:
    report = validate(ROOT)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["structural_status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
