#!/usr/bin/env python3
"""Prove that blocked source bodies cannot enter SignalForge public surfaces."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from release_path_policy import resolve_candidate_file

RIGHTS_KEYS = {
    "permission_status",
    "rights_class",
    "rights_status",
    "source_rights",
}
RIGHTS_KEY_IDS = {"permissionstatus", "rightsclass", "rightsstatus", "sourcerights"}
BLOCKED_RIGHTS_MARKERS = {
    "pending-review",
    "pending-rights",
    "pending_review",
    "pending_rights",
    "quarantined",
    "restricted",
}
BODY_KEYS = {
    "body",
    "chunks",
    "content",
    "embedding",
    "excerpt",
    "raw_payload",
    "raw_response",
    "text",
    "vector",
}
BODY_KEY_IDS = {
    "authorialcontext",
    "body",
    "businessdescription",
    "chunks",
    "content",
    "embedding",
    "excerpt",
    "rawpayload",
    "rawresponse",
    "semanticprojection",
    "sourcebody",
    "summary",
    "text",
    "vector",
}
FINAL_RUNTIME_DATA_ROOTS = {
    Path("fixtures/golden"),
    Path("fixtures/productscope"),
    Path("fixtures/retrieval"),
    Path("fixtures/workspace"),
}
STRUCTURED_DATA_SUFFIXES = {".json", ".jsonl"}
FINAL_COPY_ALLOWLIST = {
    ("backend", "/out/signalforge-workspace"),
    ("backend", "/out/licenses"),
    ("web", "/source/web/dist"),
    ("web", "/out/font-licenses"),
    (None, "fixtures/golden"),
    (None, "fixtures/productscope"),
    (None, "fixtures/retrieval"),
    (None, "fixtures/workspace"),
}
BINARY_SUFFIXES = {
    ".aac",
    ".avif",
    ".gif",
    ".ico",
    ".jpeg",
    ".jpg",
    ".mp3",
    ".mp4",
    ".pdf",
    ".png",
    ".pptx",
    ".svgz",
    ".webm",
    ".woff",
    ".woff2",
    ".zip",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def public_files(root: Path, output: Path | None) -> list[Path]:
    raw = subprocess.check_output(
        [
            "git",
            "-C",
            str(root),
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
        ]
    )
    excluded: Path | None = None
    if output is not None:
        resolved_output = output.resolve()
        resolved_root = root.resolve()
        if resolved_output.is_relative_to(resolved_root):
            excluded = resolved_output.relative_to(resolved_root)
    return [
        Path(name)
        for name in sorted(item for item in raw.decode().split("\0") if item)
        if excluded is None or Path(name) != excluded
    ]


def prohibited_public_path(path: Path) -> str | None:
    lower = path.as_posix().lower()
    parts = set(path.parts)
    if lower.startswith("experiments/sprint32/holdout/"):
        return "sealed evaluation material"
    if parts.intersection({"Contabilidade", "corpus", "models", "strategy", "var"}):
        return "private corpus, model, strategy, or runtime material"
    if path.name.startswith(".env") and path.name != ".env.example":
        return "private environment file"
    if path.suffix.lower() in {
        ".ckpt",
        ".gguf",
        ".key",
        ".p12",
        ".pem",
        ".pfx",
        ".pt",
        ".pth",
        ".safetensors",
    }:
        return "model weight or credential container"
    if any(marker in lower for marker in ("private-report", "raw-response", "chain-of-thought")):
        return "private inference material"
    return None


def is_blocked_rights(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    normalized = value.strip().lower()
    return any(marker in normalized for marker in BLOCKED_RIGHTS_MARKERS)


def canonical_key(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def is_rights_key(value: str) -> bool:
    return value.casefold() in RIGHTS_KEYS or canonical_key(value) in RIGHTS_KEY_IDS


def is_body_key(value: str) -> bool:
    return value.casefold() in BODY_KEYS or canonical_key(value) in BODY_KEY_IDS


def populated_body_fields(value: Any, location: str = "$") -> list[str]:
    fields: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_location = f"{location}.{key}"
            if is_body_key(key) and child not in (None, "", [], {}):
                fields.append(child_location)
            fields.extend(populated_body_fields(child, child_location))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            fields.extend(populated_body_fields(child, f"{location}[{index}]"))
    return fields


def blocked_rights_fields(value: Any, location: str = "$") -> dict[str, Any]:
    fields: dict[str, Any] = {}
    if isinstance(value, dict):
        for key, child in value.items():
            child_location = f"{location}.{key}"
            if is_rights_key(key) and is_blocked_rights(child):
                fields[child_location] = child
            fields.update(blocked_rights_fields(child, child_location))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            fields.update(blocked_rights_fields(child, f"{location}[{index}]"))
    return fields


def blocked_rights_body_findings(value: Any, location: str = "$") -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    if isinstance(value, dict):
        blocked = blocked_rights_fields(value, location)
        if blocked:
            bodies = sorted(set(populated_body_fields(value, location)))
            if bodies:
                return [{
                    "location": location,
                    "blocked_rights": blocked,
                    "body_fields": bodies,
                }]
        for key, child in value.items():
            findings.extend(blocked_rights_body_findings(child, f"{location}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(blocked_rights_body_findings(child, f"{location}[{index}]"))
    return findings


def is_final_runtime_data(path: Path) -> bool:
    return any(path == root or path.is_relative_to(root) for root in FINAL_RUNTIME_DATA_ROOTS)


def load_structured_records(path: Path, suffix: str) -> list[tuple[str, Any]]:
    if suffix == ".json":
        return [("$", json.loads(path.read_text(encoding="utf-8")))]
    records: list[tuple[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if line.strip():
            records.append((f"$line[{line_number}]", json.loads(line)))
    return records


def audit_public_json(root: Path, files: list[Path]) -> tuple[list[dict[str, Any]], int]:
    findings: list[dict[str, Any]] = []
    inspected = 0
    for relative in files:
        suffix = relative.suffix.lower()
        if is_final_runtime_data(relative) and suffix not in STRUCTURED_DATA_SUFFIXES:
            findings.append(
                {
                    "path": relative.as_posix(),
                    "location": "$",
                    "error": "unsupported final-image runtime data format",
                }
            )
            continue
        if suffix not in STRUCTURED_DATA_SUFFIXES:
            continue
        if relative.parts and relative.parts[0] == "contracts" and relative.name.endswith(".schema.json"):
            continue
        path, containment_reason = resolve_candidate_file(root, relative)
        if containment_reason:
            findings.append(
                {
                    "path": relative.as_posix(),
                    "location": "$",
                    "error": f"candidate containment failed: {containment_reason}",
                }
            )
            continue
        assert path is not None
        try:
            records = load_structured_records(path, suffix)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
            findings.append(
                {
                    "path": relative.as_posix(),
                    "location": "$",
                    "error": f"structured-data inspection failed: {type(exc).__name__}",
                }
            )
            continue
        inspected += 1
        for record_location, payload in records:
            for finding in blocked_rights_body_findings(payload, record_location):
                findings.append({"path": relative.as_posix(), **finding})
    return findings, inspected


def audit_reference_manifest(root: Path) -> tuple[list[dict[str, Any]], int]:
    relative = Path("fixtures/investor-relations/document-manifest.json")
    path, containment_reason = resolve_candidate_file(root, relative)
    if containment_reason:
        return [
            {
                "path": relative.as_posix(),
                "error": f"candidate containment failed: {containment_reason}",
            }
        ], 0
    assert path is not None
    if not path.is_file():
        return [{"path": relative.as_posix(), "error": "required manifest is missing"}], 0
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [
            {
                "path": relative.as_posix(),
                "error": f"manifest inspection failed: {type(exc).__name__}",
            }
        ], 0
    documents = payload.get("documents")
    if not isinstance(documents, list):
        return [{"path": relative.as_posix(), "error": "documents must be a list"}], 0
    findings: list[dict[str, Any]] = []
    for index, document in enumerate(documents):
        location = f"$.documents[{index}]"
        if not isinstance(document, dict):
            findings.append({"path": relative.as_posix(), "location": location, "error": "document must be an object"})
            continue
        rights_class = document.get("rights_class")
        if rights_class != "reference_only":
            findings.append(
                {
                    "path": relative.as_posix(),
                    "location": location,
                    "error": "public investor-relations manifest must remain reference_only",
                    "rights_class": rights_class,
                }
            )
        bodies = sorted(set(populated_body_fields(document, location)))
        if bodies:
            findings.append(
                {
                    "path": relative.as_posix(),
                    "location": location,
                    "error": "reference-only manifest redistributes source body fields",
                    "body_fields": bodies,
                }
            )
    return findings, len(documents)


def docker_instructions(dockerfile: str) -> list[tuple[int, str]]:
    instructions: list[tuple[int, str]] = []
    continued: list[str] = []
    started_at = 0
    heredoc_delimiters: list[str] = []
    for line_number, raw in enumerate(dockerfile.splitlines(), start=1):
        stripped = raw.strip()
        if heredoc_delimiters:
            if stripped == heredoc_delimiters[0]:
                heredoc_delimiters.pop(0)
            continue
        if not continued and (not stripped or stripped.startswith("#")):
            continue
        if not continued:
            started_at = line_number
        continued.append(stripped.removesuffix("\\").strip())
        if raw.rstrip().endswith("\\"):
            continue
        instruction = " ".join(part for part in continued if part)
        continued = []
        if not instruction:
            continue
        instructions.append((started_at, instruction))
        heredoc_delimiters = [
            match.group(1)
            for match in re.finditer(r"<<-?['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?", instruction)
        ]
    if continued or heredoc_delimiters:
        raise ValueError("unterminated Dockerfile continuation or heredoc")
    return instructions


def audit_final_image_copy_boundary(dockerfile: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    findings: list[dict[str, Any]] = []
    observed: list[dict[str, Any]] = []
    try:
        instructions = docker_instructions(dockerfile)
    except ValueError as exc:
        return [{"error": str(exc)}], observed
    starts = [
        index
        for index, (_line_number, instruction) in enumerate(instructions)
        if instruction.split(maxsplit=1)[0].upper() == "FROM"
    ]
    if not starts:
        return [{"error": "Dockerfile has no final stage"}], observed
    for line_number, stripped in instructions[starts[-1] + 1 :]:
        instruction = stripped.split(maxsplit=1)[0].upper() if stripped else ""
        if instruction == "ADD":
            findings.append({"line": line_number, "error": "ADD is forbidden in final image stage"})
            continue
        if instruction == "RUN" and re.search(r"(?:^|\s)--mount(?:=|\s)", stripped, re.IGNORECASE):
            findings.append({"line": line_number, "error": "RUN --mount is forbidden in final image stage"})
            continue
        if instruction != "COPY":
            continue
        if stripped[len("COPY") :].lstrip().startswith("["):
            findings.append({"line": line_number, "error": "JSON-form COPY is unsupported and rejected"})
            continue
        try:
            tokens = shlex.split(stripped)
        except ValueError as exc:
            findings.append(
                {
                    "line": line_number,
                    "error": f"COPY parsing failed: {type(exc).__name__}",
                }
            )
            continue
        stage: str | None = None
        arguments: list[str] = []
        for token in tokens[1:]:
            if token.startswith("--from="):
                stage = token.split("=", 1)[1]
            elif token.startswith("--"):
                findings.append(
                    {
                        "line": line_number,
                        "error": f"unsupported COPY option: {token}",
                    }
                )
            else:
                arguments.append(token)
        if len(arguments) < 2:
            findings.append({"line": line_number, "error": "COPY lacks source or destination"})
            continue
        for source in arguments[:-1]:
            normalized = source.rstrip("/") or "/"
            entry = {"from": stage, "source": normalized, "destination": arguments[-1]}
            observed.append(entry)
            if normalized in {".", "./", "/"} or any(character in normalized for character in ("*", "?", "[")):
                findings.append({**entry, "error": "broad or wildcard COPY is forbidden in final image stage"})
            elif (stage, normalized) not in FINAL_COPY_ALLOWLIST:
                findings.append({**entry, "error": "COPY source is outside the final-image allowlist"})
    missing = FINAL_COPY_ALLOWLIST.difference((item["from"], item["source"]) for item in observed)
    for stage, source in sorted(missing, key=lambda item: (str(item[0]), item[1])):
        findings.append({"from": stage, "source": source, "error": "required allowlisted COPY is missing"})
    return findings, observed


def audit_judge_binaries(
    root: Path,
    public_inventory: set[Path] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    package_relative = Path("evidence/judge-package.json")
    package_path, containment_reason = resolve_candidate_file(root, package_relative)
    if containment_reason or package_path is None:
        return [
            {
                "path": package_relative.as_posix(),
                "error": "judge package path escapes repository candidate or uses a symlink",
            }
        ], []
    if not package_path.is_file():
        return [{"path": package_relative.as_posix(), "error": "judge package is missing"}], []
    package = json.loads(package_path.read_text(encoding="utf-8"))
    findings: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []
    for artifact_id, artifact in sorted(package.get("artifacts", {}).items()):
        relative = artifact.get("path")
        expected = artifact.get("sha256")
        if not isinstance(relative, str) or not relative or not expected:
            findings.append({"artifact_id": artifact_id, "error": "path or sha256 is missing"})
            continue
        relative_path = Path(relative)
        path, containment_reason = resolve_candidate_file(root, relative_path)
        if containment_reason:
            error = (
                "artifact path escapes repository candidate"
                if containment_reason == "path escapes repository candidate"
                else "artifact path escapes repository candidate or uses a symlink"
            )
            findings.append(
                {
                    "artifact_id": artifact_id,
                    "path": relative,
                    "error": error,
                }
            )
            continue
        assert path is not None
        if public_inventory is not None and relative_path not in public_inventory:
            findings.append({"artifact_id": artifact_id, "path": relative, "error": "artifact is outside the public candidate inventory"})
            continue
        if path.suffix.lower() not in BINARY_SUFFIXES:
            continue
        actual = sha256(path) if path.is_file() and not path.is_symlink() else "unavailable"
        item = {
            "artifact_id": artifact_id,
            "path": relative,
            "expected_sha256": expected,
            "actual_sha256": actual,
            "matches": actual == expected,
        }
        artifacts.append(item)
        if not item["matches"]:
            findings.append({"artifact_id": artifact_id, "path": relative, "error": "binary hash mismatch"})
    return findings, artifacts


def check(status_findings: list[dict[str, Any]], **details: Any) -> dict[str, Any]:
    return {
        "status": "passed" if not status_findings else "failed",
        "findings": status_findings,
        **details,
    }


def build(root: Path, output: Path | None = None) -> dict[str, Any]:
    files = public_files(root, output)
    forbidden = [
        {"path": path.as_posix(), "reason": reason}
        for path in files
        if (reason := prohibited_public_path(path)) is not None
    ]
    inspectable_files = [path for path in files if prohibited_public_path(path) is None]
    body_findings, json_files_inspected = audit_public_json(root, inspectable_files)
    manifest_findings, manifest_documents = audit_reference_manifest(root)
    dockerfile_path, dockerfile_reason = resolve_candidate_file(root, Path("Dockerfile"))
    if dockerfile_reason or dockerfile_path is None or not dockerfile_path.is_file():
        copy_findings = [
            {
                "path": "Dockerfile",
                "error": f"Dockerfile is unavailable or unsafe: {dockerfile_reason or 'not a regular file'}",
            }
        ]
        final_copies: list[dict[str, Any]] = []
    else:
        dockerfile = dockerfile_path.read_text(encoding="utf-8")
        copy_findings, final_copies = audit_final_image_copy_boundary(dockerfile)
    binary_findings, binary_artifacts = audit_judge_binaries(root, set(files))
    checks = {
        "prohibited_public_paths": check(forbidden),
        "blocked_rights_bodies": check(body_findings, json_files_inspected=json_files_inspected),
        "reference_only_manifest": check(
            manifest_findings,
            documents_inspected=manifest_documents,
        ),
        "final_image_copy_boundary": check(copy_findings, observed_copies=final_copies),
        "judge_binary_integrity": check(binary_findings, artifacts=binary_artifacts),
    }
    return {
        "schema_version": "signalforge/restricted-egress-audit/v1",
        "scope": "git cached plus untracked non-ignored public files and the Docker final stage",
        "summary": {
            "public_files_considered": len(files),
            "all_checks_passed": all(item["status"] == "passed" for item in checks.values()),
        },
        "checks": checks,
        "proof_boundary": {
            "claim": (
                "Blocked source bodies are absent from public data and final-image inputs, so the "
                "runtime has no blocked body available to project into UI, logs, exports, or captures."
            ),
            "reference_only_policy": (
                "Reference-only source metadata may be public; bounded authorial summaries already "
                "covered by the named rights decision remain permitted."
            ),
            "binary_limitation": (
                "Binary hashes prove artifact identity, not semantic legal clearance; named human "
                "rights authorization remains a separate release gate."
            ),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output.resolve() if args.output else None
    report = build(root, output)
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    if not report["summary"]["all_checks_passed"]:
        raise SystemExit("restricted egress audit failed")


if __name__ == "__main__":
    main()
