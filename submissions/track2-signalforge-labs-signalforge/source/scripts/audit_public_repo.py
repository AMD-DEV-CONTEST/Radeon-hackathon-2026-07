#!/usr/bin/env python3
"""Audit the exact public SignalForge release candidate without network access."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "evidence" / "release-audit.json"
MAX_PUBLIC_FILE_BYTES = 10 * 1024 * 1024

REQUIRED_RELEASE_FILES = {
    ".env.example",
    "LICENSE",
    "NOTICE",
    "README.md",
    "THIRD_PARTY_NOTICES.md",
    "evidence/judge-package.json",
    "go.mod",
    "go.sum",
    "scripts/verify.sh",
    "web/package-lock.json",
    "web/package.json",
}

SECRET_PATTERNS = {
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"),
    "aws_access_key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "github_token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    "huggingface_token": re.compile(r"\bhf_[A-Za-z0-9]{30,}\b"),
    "openai_style_key": re.compile(r"\bsk-[A-Za-z0-9_-]{32,}\b"),
    "artificial_analysis_key": re.compile(r"\baa_[A-Za-z0-9]{20,}\b"),
    "google_oauth_code": re.compile(r"\b4/[A-Za-z0-9_-]{30,}\b"),
    "embedded_url_credentials": re.compile(r"https?://[^/\s:@]+:[^@\s/]+@"),
    "query_secret": re.compile(r"(?:[?&]|\b)(?:api[_-]?key|token|secret|password)=[^&\s\"'#]+", re.IGNORECASE),
}

# These exact strings are deliberately synthetic adversarial fixtures. The scanner still checks
# every other match in the same files, so placing a real credential beside a fixture fails.
SYNTHETIC_SECRET_SENTINELS = {
    ("internal/casestore/store_test.go", "api_key=super-secret-value"),
    ("internal/privacy/secrets_test.go", "api_key=super-secret-value"),
    ("internal/privacy/secrets_test.go", "hf_abcdefghijklmnopqrstuvwxyz"),
    ("internal/privacy/secrets_test.go", "sk-abcdefghijklmnopqrstuvwxyz"),
    ("internal/rawstore/store_test.go", "https://user:password@"),
    ("internal/rawstore/store_test.go", "&api_key=sensitive"),
    ("internal/rawstore/store_test.go", "&token=also-sensitive"),
    ("scripts/audit_public_repo.py", "https://user:password@"),
    ("scripts/audit_public_repo.py", "api_key=super-secret-value"),
    ("scripts/audit_public_repo.py", "&api_key=sensitive"),
    ("scripts/audit_public_repo.py", "&token=also-sensitive"),
}

BINARY_SUFFIXES = {
    ".aac", ".avif", ".gif", ".ico", ".jpeg", ".jpg", ".mp3", ".mp4", ".pdf",
    ".png", ".pptx", ".svgz", ".webm", ".woff", ".woff2", ".zip",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def public_files(root: Path, output: Path) -> list[Path]:
    command = [
        "git", "-C", str(root), "ls-files", "--cached", "--others",
        "--exclude-standard", "-z",
    ]
    raw = subprocess.check_output(command)
    output_relative = output.resolve().relative_to(root.resolve()) if output.resolve().is_relative_to(root.resolve()) else None
    names = sorted(item for item in raw.decode().split("\0") if item)
    return [Path(name) for name in names if output_relative is None or Path(name) != output_relative]


def forbidden_path_reason(path: Path) -> str | None:
    parts = set(path.parts)
    lower = path.as_posix().lower()
    if path.name.startswith(".env") and path.name != ".env.example":
        return "private environment file"
    if parts.intersection({"strategy", "Contabilidade", "corpus", "models", "var"}):
        return "internal strategy, corpus, model, or runtime data"
    if parts.intersection({"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".venv", "venv"}):
        return "generated Python cache or local environment"
    if path.suffix.lower() in {".gguf", ".safetensors", ".ckpt", ".pt", ".pth", ".pem", ".key", ".p12", ".pfx"}:
        return "model weight or credential container"
    if path.name in {".DS_Store", "id_rsa", "id_ed25519"}:
        return "local or credential file"
    if path.suffix.lower() in {".log", ".pid", ".duckdb", ".parquet", ".pyc", ".pyo", ".pyd"}:
        return "transient log, process, or local analytical data"
    if "private-report" in lower or "raw-response" in lower or "chain-of-thought" in lower:
        return "private inference material"
    return None


def text_payload(path: Path) -> str | None:
    if path.suffix.lower() in BINARY_SUFFIXES:
        return None
    payload = path.read_bytes()
    if b"\0" in payload:
        return None
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError:
        return None


def scan_secrets(relative: Path, text: str) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    normalized = relative.as_posix()
    for kind, pattern in SECRET_PATTERNS.items():
        for match in pattern.finditer(text):
            value = match.group(0)
            if (normalized, value) in SYNTHETIC_SECRET_SENTINELS:
                continue
            line = text.count("\n", 0, match.start()) + 1
            findings.append({"path": normalized, "line": line, "kind": kind})
    return findings


def validate_env_example(root: Path) -> list[str]:
    problems: list[str] = []
    path = root / ".env.example"
    if not path.is_file():
        return [".env.example is missing"]
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        if any(term in key.upper() for term in ("KEY", "SECRET", "TOKEN", "PASSWORD")) and value:
            problems.append(f".env.example:{line_number} assigns a non-empty credential value")
    return problems


def validate_release_files(root: Path) -> list[str]:
    problems = [f"required release file is missing: {name}" for name in sorted(REQUIRED_RELEASE_FILES) if not (root / name).is_file()]
    readme = root / "README.md"
    if readme.is_file() and "To be defined before the first implementation release." in readme.read_text(encoding="utf-8"):
        problems.append("README license section is unresolved")
    return problems


def verify_judge_artifacts(root: Path) -> tuple[list[dict[str, object]], list[str]]:
    package_path = root / "evidence" / "judge-package.json"
    if not package_path.is_file():
        return [], ["evidence/judge-package.json is missing"]
    package = json.loads(package_path.read_text(encoding="utf-8"))
    results: list[dict[str, object]] = []
    problems: list[str] = []
    for artifact_id, artifact in sorted(package.get("artifacts", {}).items()):
        relative = artifact.get("path")
        expected = artifact.get("sha256")
        if not relative or not expected:
            problems.append(f"judge artifact {artifact_id} lacks path or sha256")
            continue
        path = root / relative
        actual = sha256(path) if path.is_file() else "unavailable"
        matches = actual == expected
        results.append({"artifact_id": artifact_id, "path": relative, "sha256": actual, "matches": matches})
        if not matches:
            problems.append(f"judge artifact {artifact_id} hash mismatch")
    if package.get("status") != "public_artifacts_verified" or package.get("pending"):
        problems.append("judge package is not in public_artifacts_verified state")
    return results, problems


def build(root: Path, output: Path) -> dict[str, object]:
    files = public_files(root, output)
    forbidden: list[dict[str, str]] = []
    oversized: list[dict[str, object]] = []
    secret_findings: list[dict[str, object]] = []
    text_files = 0
    total_bytes = 0
    for relative in files:
        path = root / relative
        if not path.is_file():
            forbidden.append({"path": relative.as_posix(), "reason": "not a regular file"})
            continue
        size = path.stat().st_size
        total_bytes += size
        reason = forbidden_path_reason(relative)
        if reason:
            forbidden.append({"path": relative.as_posix(), "reason": reason})
        if size > MAX_PUBLIC_FILE_BYTES:
            oversized.append({"path": relative.as_posix(), "bytes": size})
        text = text_payload(path)
        if text is not None:
            text_files += 1
            secret_findings.extend(scan_secrets(relative, text))

    env_problems = validate_env_example(root)
    release_file_problems = validate_release_files(root)
    artifacts, artifact_problems = verify_judge_artifacts(root)
    checks = {
        "forbidden_paths": {"status": "passed" if not forbidden else "failed", "findings": forbidden},
        "oversized_files": {"status": "passed" if not oversized else "failed", "findings": oversized},
        "secret_scan": {"status": "passed" if not secret_findings else "failed", "findings": secret_findings},
        "environment_example": {"status": "passed" if not env_problems else "failed", "findings": env_problems},
        "required_release_files": {"status": "passed" if not release_file_problems else "failed", "findings": release_file_problems},
        "judge_artifact_hashes": {"status": "passed" if not artifact_problems else "failed", "findings": artifact_problems},
    }
    output_path = output.resolve()
    root_path = root.resolve()
    self_excluded = str(output_path.relative_to(root_path)) if output_path.is_relative_to(root_path) else str(output_path)
    return {
        "schema_version": "signalforge/public-release-audit/v1",
        "scope": "git cached plus untracked non-ignored files",
        "self_excluded_path": self_excluded,
        "summary": {
            "public_files": len(files),
            "text_files_scanned": text_files,
            "total_bytes": total_bytes,
            "all_checks_passed": all(item["status"] == "passed" for item in checks.values()),
        },
        "checks": checks,
        "synthetic_secret_sentinels": [
            {"path": path, "value_sha256": hashlib.sha256(value.encode()).hexdigest()}
            for path, value in sorted(SYNTHETIC_SECRET_SENTINELS)
        ],
        "judge_artifacts": artifacts,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output.resolve()
    report = build(root, output)
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if not report["summary"]["all_checks_passed"]:
        print(encoded, end="")
        raise SystemExit("public release audit failed")
    if args.check:
        if not output.is_file() or output.read_text(encoding="utf-8") != encoded:
            raise SystemExit(f"stale public release audit: {output}")
        print("public release audit passed")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(encoded, encoding="utf-8")
    print(f"wrote {output}")


if __name__ == "__main__":
    main()
