#!/usr/bin/env python3
"""Validate a clean, public AMD Track 1 ProofLaunch export."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote


EXPECTED_ROOT_NAME = "prooflaunch"
MAX_TOTAL_BYTES = 300_000_000
MAX_REGULAR_FILE_BYTES = 100_000_000
MAX_DEMO_VIDEO_BYTES = 500_000_000

REQUIRED_FILES = (
    "README.md",
    "JUDGE_START_HERE.md",
    "LICENSE",
    "THIRD_PARTY.md",
    "CONTRIBUTING.md",
    "CODE_OF_CONDUCT.md",
    "SECURITY.md",
    "SUPPORT.md",
    "GOVERNANCE.md",
    "CHANGELOG.md",
    "pyproject.toml",
    "requirements-radeon.txt",
    "SUBMISSION_GATE.json",
    "docs/COMPETITION_PACKAGE.md",
    "docs/INSTALLATION.md",
    "docs/MODEL_CARD.md",
    "docs/RADEON_SETUP.md",
    "docs/EVALUATION.md",
    "docs/ProofLaunch_Project_Profile.pdf",
    "docs/ProofLaunch_Submission_Deck.pptx",
    "submission/track1-prooflaunch/PR_BODY.md",
    "submission/track1-prooflaunch/SUBMISSION_MANIFEST.json",
    "demos/run_track1_demo.py",
    ".github/workflows/quality.yml",
    ".github/PULL_REQUEST_TEMPLATE.md",
)

OFFICIAL_ENGLISH_FILES = (
    "README.md",
    "JUDGE_START_HERE.md",
    "SUBMISSION_GATE.json",
    "docs/COMPETITION_PACKAGE.md",
    "docs/INSTALLATION.md",
    "docs/MODEL_CARD.md",
    "docs/RADEON_SETUP.md",
    "docs/EVALUATION.md",
    "docs/DEMO_VIDEO_SHOTLIST.md",
    "submission/track1-prooflaunch/README.md",
    "submission/track1-prooflaunch/PR_BODY.md",
    "submission/track1-prooflaunch/RADEON_FINAL_CAPTURE.md",
    "submission/track1-prooflaunch/PUBLIC_RELEASE_POLICY.md",
    "submission/track1-prooflaunch/SUBMISSION_MANIFEST.json",
)

LINK_CHECK_FILES = (
    "docs/COMPETITION_PACKAGE.md",
    "docs/INSTALLATION.md",
    "docs/MODEL_CARD.md",
    "docs/RADEON_SETUP.md",
    "docs/EVALUATION.md",
    "JUDGE_START_HERE.md",
)

BANNED_COMPONENTS = {
    ".git",
    ".venv",
    ".pytest_cache",
    ".prooflaunch-runtime",
    ".prooflaunch-secrets",
    ".super-site-10x",
    "__pycache__",
    "node_modules",
    "tokenfactory_teacher_v10",
}

FORBIDDEN_TEXT = (
    "Track 1, ProofLaunch, ProofLaunch",
    "prooflaunch_submission/",
    "OwlSeer",
    "owlseer",
)

TEXT_SUFFIXES = {
    ".cjs",
    ".css",
    ".csv",
    ".html",
    ".ipynb",
    ".js",
    ".json",
    ".md",
    ".mjs",
    ".py",
    ".scd",
    ".sh",
    ".toml",
    ".txt",
    ".vtt",
    ".yaml",
    ".yml",
}

SECRET_PATTERNS = {
    "aws_access_key": re.compile(rb"AKIA[0-9A-Z]{16}"),
    "github_token": re.compile(rb"gh[pousr]_[A-Za-z0-9]{20,}"),
    "huggingface_token": re.compile(rb"hf_[A-Za-z0-9]{30,}"),
    "private_key": re.compile(
        rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
    ),
}

PRIVATE_ABSOLUTE_PATH = re.compile(
    r"/(?:Users|home)/[^/\s]+/(?:Documents|Desktop|Downloads|\.codex)/|/var/"
    r"folders/"
)
HAN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
MARKDOWN_LINK = re.compile(r"!?(?:\[[^\]]*\])\(([^)]+)\)")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def scan_high_confidence_secret(data: bytes) -> list[str]:
    return [name for name, pattern in SECRET_PATTERNS.items() if pattern.search(data)]


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _local_markdown_targets(path: Path, root: Path) -> list[Path]:
    targets: list[Path] = []
    text = path.read_text(encoding="utf-8")
    for raw in MARKDOWN_LINK.findall(text):
        target = raw.strip().split(maxsplit=1)[0].strip("<>")
        if not target or target.startswith(("#", "http://", "https://", "mailto:")):
            continue
        target = unquote(target.split("#", 1)[0])
        if not target:
            continue
        resolved = (path.parent / target).resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            targets.append(resolved)
            continue
        targets.append(resolved)
    return targets


def validate(export_root: str | Path) -> dict[str, Any]:
    root = Path(export_root).resolve()
    errors: list[str] = []
    warnings: list[str] = []

    if root.name != EXPECTED_ROOT_NAME:
        errors.append(f"wrong_export_root_name:{root.name}")
    if not root.is_dir():
        return {
            "schema": "ProofLaunchAMDPublicExportValidationV1",
            "status": "failed",
            "errors": [f"missing_export_root:{root}"],
            "warnings": [],
        }

    for relative in REQUIRED_FILES:
        if not (root / relative).is_file():
            errors.append(f"missing_required_file:{relative}")

    files = sorted(path for path in root.rglob("*") if path.is_file() or path.is_symlink())
    total_bytes = 0
    actual_entries: dict[str, dict[str, Any]] = {}
    for path in files:
        relative = path.relative_to(root).as_posix()
        parts = path.relative_to(root).parts
        if path.is_symlink():
            errors.append(f"symlink_forbidden:{relative}")
            continue
        if any(part in BANNED_COMPONENTS or part.endswith(".egg-info") for part in parts):
            errors.append(f"banned_path:{relative}")
        if path.suffix in {".pyc", ".pyo"} or path.name == ".DS_Store":
            errors.append(f"generated_file_forbidden:{relative}")

        size = path.stat().st_size
        total_bytes += size
        limit = (
            MAX_DEMO_VIDEO_BYTES
            if path.suffix.lower() in {".mp4", ".mov", ".webm"}
            else MAX_REGULAR_FILE_BYTES
        )
        if size > limit:
            errors.append(f"file_too_large:{relative}:{size}")

        if path.suffix.lower() in TEXT_SUFFIXES and size <= 10_000_000:
            data = path.read_bytes()
            for finding in scan_high_confidence_secret(data):
                errors.append(f"possible_secret:{relative}:{finding}")
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                errors.append(f"non_utf8_text_file:{relative}")
            else:
                if PRIVATE_ABSOLUTE_PATH.search(text):
                    errors.append(f"private_absolute_path:{relative}")

        if relative not in {"PUBLIC_EXPORT_MANIFEST.json", "PUBLIC_EXPORT_VALIDATION.json"}:
            actual_entries[relative] = {"bytes": size, "sha256": sha256_file(path)}

    if total_bytes > MAX_TOTAL_BYTES:
        errors.append(f"export_too_large:{total_bytes}")

    for relative in OFFICIAL_ENGLISH_FILES:
        path = root / relative
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        if HAN.search(text):
            errors.append(f"non_english_official_surface:{relative}")
        for marker in FORBIDDEN_TEXT:
            if marker in text:
                errors.append(f"forbidden_official_text:{relative}:{marker}")

    for relative in LINK_CHECK_FILES:
        path = root / relative
        if not path.is_file():
            continue
        for target in _local_markdown_targets(path, root):
            try:
                shown = target.relative_to(root).as_posix()
            except ValueError:
                errors.append(f"markdown_link_escapes_export:{relative}:{target}")
                continue
            if not target.exists():
                errors.append(f"broken_markdown_link:{relative}:{shown}")

    manifest_path = root / "PUBLIC_EXPORT_MANIFEST.json"
    if not manifest_path.is_file():
        errors.append("missing_public_export_manifest")
    else:
        try:
            manifest = _read_json(manifest_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"invalid_public_export_manifest:{exc}")
        else:
            expected_entries = {
                str(item.get("path")): {
                    "bytes": item.get("bytes"),
                    "sha256": item.get("sha256"),
                }
                for item in manifest.get("files", [])
                if isinstance(item, dict)
            }
            if expected_entries != actual_entries:
                errors.append("public_export_manifest_mismatch")
            if manifest.get("team") != "Banyan":
                errors.append("public_export_manifest_team_mismatch")
            if manifest.get("application") != "ProofLaunch":
                errors.append("public_export_manifest_application_mismatch")

    gate_path = root / "SUBMISSION_GATE.json"
    competition_status = "unknown"
    if gate_path.is_file():
        try:
            competition_status = str(_read_json(gate_path).get("overallStatus", "unknown"))
        except (OSError, ValueError, json.JSONDecodeError):
            pass
    if competition_status != "ready":
        warnings.append(f"competition_gate_not_ready:{competition_status}")

    return {
        "schema": "ProofLaunchAMDPublicExportValidationV1",
        "status": "passed" if not errors else "failed",
        "competition_status": competition_status,
        "file_count": len(actual_entries),
        "total_bytes": total_bytes,
        "errors": sorted(set(errors)),
        "warnings": sorted(set(warnings)),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("export_root", type=Path)
    args = parser.parse_args()
    report = validate(args.export_root)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
