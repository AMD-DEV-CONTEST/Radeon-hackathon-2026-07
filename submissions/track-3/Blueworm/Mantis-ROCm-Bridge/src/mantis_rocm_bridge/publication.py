"""Fail-closed assembly and audit of a public submission candidate.

The candidate gate deliberately separates content safety from publication
readiness. A candidate may be archived for review when its content is safe,
while missing owner decisions (for example, the project LICENSE) or
machine-specific paths continue to block release promotion.
"""

from __future__ import annotations

import fnmatch
import gzip
import hashlib
import io
import json
import os
import posixpath
import re
import shutil
import tarfile
import tempfile
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence


class PublicationGateError(RuntimeError):
    """Raised when the publication configuration or output contract is invalid."""


@dataclass(frozen=True)
class Finding:
    gate: str
    rule: str
    path: str
    line: int | None = None

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "gate": self.gate,
            "rule": self.rule,
            "path": self.path,
        }
        if self.line is not None:
            result["line"] = self.line
        return result


_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "private_key_header",
        re.compile(
            r"-----BEGIN (?:RSA |DSA |EC |OPENSSH )?PRIVATE KEY-----"
        ),
    ),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github_classic_token", re.compile(r"\bghp_[A-Za-z0-9]{30,}\b")),
    ("github_fine_grained_token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{30,}\b")),
    ("api_key_style_secret", re.compile(r"\bsk-[A-Za-z0-9_-]{24,}\b")),
    (
        "assigned_credential",
        re.compile(
            r"""(?ix)
            \b(?:password|passwd|api[_-]?key|secret[_-]?key|access[_-]?token)
            \b
            \s*
            (?::|(?<![=])=(?!=))
            \s*
            ["']?
            (?!
              <redacted>|redacted|changeme|example|placeholder|
              none|null|todo|\$\{|\{\{
            )
            [A-Za-z0-9/+_.:@-]{8,}
            """
        ),
    ),
)

_TEXT_SAMPLE_LIMIT = 4 * 1024 * 1024
_MARKDOWN_LINK_PATTERN = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _matches(path: str, patterns: Sequence[str]) -> bool:
    pure = PurePosixPath(path)
    return any(pure.match(pattern) or fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def _relative_file(path: Path, root: Path) -> str:
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise PublicationGateError(f"path escapes repository root: {path}") from exc
    return relative.as_posix()


def _validate_exact_exception_file(candidate: Path, root: Path, relative: str) -> None:
    try:
        lexical = candidate.relative_to(root)
    except ValueError as exc:
        raise PublicationGateError(
            f"exact exclude exception escapes repository root: {relative}"
        ) from exc

    current = root
    for part in lexical.parts:
        current = current / part
        if current.is_symlink():
            raise PublicationGateError(
                "exact exclude exception contains a symlink component: "
                f"{relative}"
            )

    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        raise PublicationGateError(
            "exact exclude exception is missing or resolves outside repository "
            f"root: {relative}"
        ) from exc
    if resolved != candidate:
        raise PublicationGateError(
            f"exact exclude exception resolved path changed: {relative}"
        )
    if not candidate.is_file():
        raise PublicationGateError(
            f"exact exclude exception must be a regular file: {relative}"
        )


def load_publication_config(path: Path) -> dict[str, Any]:
    config = json.loads(path.read_text(encoding="utf-8"))
    if config.get("schema_version") != 1:
        raise PublicationGateError("publication config schema_version must be 1")
    required_lists = (
        "include_files",
        "include_directories",
        "exclude_globs",
        "exact_exclude_file_exceptions",
        "forbidden_asset_extensions",
        "permitted_fixture_asset_globs",
        "sensitive_filename_globs",
        "required_release_files",
        "permitted_provenance_path_globs",
        "machine_specific_path_prefixes",
    )
    for key in required_lists:
        value = config.get(key)
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise PublicationGateError(f"{key} must be a list of strings")
    maximum = config.get("maximum_file_bytes")
    if not isinstance(maximum, int) or maximum <= 0:
        raise PublicationGateError("maximum_file_bytes must be a positive integer")
    exceptions = config["exact_exclude_file_exceptions"]
    if len(set(exceptions)) != len(exceptions):
        raise PublicationGateError("exact_exclude_file_exceptions must be unique")
    included = set(config["include_files"])
    excludes = tuple(config["exclude_globs"])
    for exception in exceptions:
        pure = PurePosixPath(exception)
        if (
            not exception
            or pure.is_absolute()
            or pure.as_posix() != exception
            or "\\" in exception
            or any(character in exception for character in "*?[")
            or any(part in {"", ".", ".."} for part in pure.parts)
        ):
            raise PublicationGateError(
                "exact_exclude_file_exceptions must contain normalized relative "
                f"file paths without glob syntax: {exception!r}"
            )
        if exception not in included:
            raise PublicationGateError(
                "exact exclude exception must also be an include_file: "
                f"{exception}"
            )
        if not _matches(exception, excludes):
            raise PublicationGateError(
                "exact exclude exception must match an exclude_glob: "
                f"{exception}"
            )
    _validate_config_transforms(config.get("config_transforms", []))
    return config


def _validate_config_transforms(transforms: Any) -> None:
    """Validate an optional list of packaging-only JSON transforms.

    Each transform names one packaged JSON file and a set of top-level keys
    that must be removed from the public copy only. The source file is never
    modified. Declaration is fail-closed: a configured transform must target a
    real, packaged JSON object that actually contains every named key.
    """
    if not isinstance(transforms, list):
        raise PublicationGateError("config_transforms must be a list")
    seen: set[str] = set()
    for transform in transforms:
        if not isinstance(transform, Mapping):
            raise PublicationGateError("config_transforms entries must be objects")
        path = transform.get("path")
        keys = transform.get("remove_top_level_keys")
        if not isinstance(path, str) or not path:
            raise PublicationGateError(
                "config_transforms entry path must be a non-empty string"
            )
        pure = PurePosixPath(path)
        if (
            pure.is_absolute()
            or pure.as_posix() != path
            or "\\" in path
            or any(part in {"", ".", ".."} for part in pure.parts)
        ):
            raise PublicationGateError(
                "config_transforms path must be a normalized relative file "
                f"path: {path!r}"
            )
        if path in seen:
            raise PublicationGateError(f"config_transforms path duplicated: {path}")
        seen.add(path)
        if (
            not isinstance(keys, list)
            or not keys
            or not all(isinstance(item, str) and item for item in keys)
        ):
            raise PublicationGateError(
                "config_transforms remove_top_level_keys must be a non-empty "
                "list of non-empty strings"
            )
        remove_paths = transform.get("remove_paths", [])
        if not isinstance(remove_paths, list) or not all(
            isinstance(item, list)
            and item
            and all(isinstance(part, str) and part for part in item)
            for item in remove_paths
        ):
            raise PublicationGateError(
                "config_transforms remove_paths must be a list of non-empty "
                "string-path lists"
            )
        normalized_paths = [tuple(item) for item in remove_paths]
        if len(set(normalized_paths)) != len(normalized_paths):
            raise PublicationGateError("config_transforms remove_paths must be unique")
        unexpected = set(transform) - {
            "path",
            "remove_top_level_keys",
            "remove_paths",
        }
        if unexpected:
            raise PublicationGateError(
                "config_transforms entry has unexpected keys: "
                f"{sorted(unexpected)}"
            )


def collect_allowlisted_files(
    repository_root: Path,
    config: Mapping[str, Any],
) -> tuple[list[tuple[str, Path]], list[Finding]]:
    root = repository_root.resolve()
    excludes = tuple(config["exclude_globs"])
    exclude_exceptions = frozenset(config["exact_exclude_file_exceptions"])
    findings: list[Finding] = []
    selected: dict[str, Path] = {}

    candidates: list[Path] = []
    optional_release_files = set(config["required_release_files"])
    for item in config["include_files"]:
        candidate = root / item
        if item in exclude_exceptions:
            _validate_exact_exception_file(candidate, root, item)
            candidates.append(candidate)
            continue
        if not candidate.exists():
            if item not in optional_release_files:
                findings.append(Finding("allowlist", "missing_include_file", item))
            continue
        candidates.append(candidate)
    for item in config["include_directories"]:
        directory = root / item
        if not directory.is_dir():
            findings.append(Finding("allowlist", "missing_include_directory", item))
            continue
        candidates.extend(directory.rglob("*"))

    for candidate in candidates:
        relative = _relative_file(candidate, root)
        if _matches(relative, excludes) and relative not in exclude_exceptions:
            continue
        if candidate.is_symlink():
            findings.append(Finding("content", "symlink_forbidden", relative))
            continue
        if candidate.is_dir():
            continue
        if not candidate.is_file():
            findings.append(Finding("content", "non_regular_file", relative))
            continue
        selected[relative] = candidate

    return sorted(selected.items()), sorted(
        findings, key=lambda item: (item.gate, item.path, item.rule)
    )


def _decode_text(path: Path) -> str | None:
    if path.stat().st_size > _TEXT_SAMPLE_LIMIT:
        return None
    payload = path.read_bytes()
    if b"\x00" in payload:
        return None
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError:
        return None


def audit_allowlisted_files(
    files: Sequence[tuple[str, Path]],
    config: Mapping[str, Any],
    initial_findings: Iterable[Finding] = (),
) -> tuple[list[Finding], dict[str, Any]]:
    findings = list(initial_findings)
    maximum = int(config["maximum_file_bytes"])
    sensitive_names = tuple(config["sensitive_filename_globs"])
    forbidden_assets = {
        extension.lower() for extension in config["forbidden_asset_extensions"]
    }
    permitted_assets = tuple(config["permitted_fixture_asset_globs"])
    machine_prefixes = tuple(config["machine_specific_path_prefixes"])
    permitted_provenance_paths = tuple(config["permitted_provenance_path_globs"])
    fixture_assets: list[str] = []
    provenance_path_occurrences: list[dict[str, Any]] = []
    selected_paths = {relative for relative, _ in files}
    checked_local_markdown_links = 0
    total_bytes = 0

    for relative, source in files:
        size = source.stat().st_size
        total_bytes += size
        if size > maximum:
            findings.append(Finding("content", "file_exceeds_size_limit", relative))
        if _matches(relative, sensitive_names):
            findings.append(Finding("content", "sensitive_filename", relative))

        extension = source.suffix.lower()
        if extension in forbidden_assets:
            if _matches(relative, permitted_assets):
                fixture_assets.append(relative)
            else:
                findings.append(Finding("content", "robot_or_scene_asset_forbidden", relative))

        text = _decode_text(source)
        if text is None:
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            for rule, pattern in _SECRET_PATTERNS:
                if pattern.search(line):
                    findings.append(Finding("content", rule, relative, line_number))
            normalized_line = line.strip().rstrip(",").strip("\"'")
            defines_prefix = normalized_line in machine_prefixes
            if not defines_prefix and any(prefix in line for prefix in machine_prefixes):
                if _matches(relative, permitted_provenance_paths):
                    provenance_path_occurrences.append(
                        {"path": relative, "line": line_number}
                    )
                else:
                    findings.append(
                        Finding(
                            "promotion",
                            "machine_specific_absolute_path",
                            relative,
                            line_number,
                        )
                    )
            if extension == ".md":
                for match in _MARKDOWN_LINK_PATTERN.finditer(line):
                    raw_target = match.group(1).strip()
                    if raw_target.startswith("<") and raw_target.endswith(">"):
                        raw_target = raw_target[1:-1]
                    raw_target = raw_target.split(maxsplit=1)[0]
                    if (
                        not raw_target
                        or raw_target.startswith(("#", "http://", "https://", "mailto:"))
                    ):
                        continue
                    checked_local_markdown_links += 1
                    decoded = urllib.parse.unquote(raw_target).split("#", 1)[0]
                    normalized = posixpath.normpath(
                        posixpath.join(posixpath.dirname(relative), decoded)
                    )
                    target_exists = normalized in selected_paths or any(
                        item.startswith(normalized.rstrip("/") + "/")
                        for item in selected_paths
                    )
                    if normalized.startswith("../") or normalized == ".." or not target_exists:
                        findings.append(
                            Finding(
                                "promotion",
                                "broken_local_markdown_link",
                                relative,
                                line_number,
                            )
                        )

    findings.sort(key=lambda item: (item.gate, item.path, item.line or 0, item.rule))
    inventory = {
        "file_count": len(files),
        "total_bytes": total_bytes,
        "maximum_file_bytes": maximum,
        "permitted_fixture_assets": sorted(fixture_assets),
        "permitted_provenance_path_occurrences": sorted(
            provenance_path_occurrences,
            key=lambda item: (item["path"], item["line"]),
        ),
        "checked_local_markdown_links": checked_local_markdown_links,
        "exact_exclude_file_exceptions": sorted(
            config["exact_exclude_file_exceptions"]
        ),
        "config_transforms": [dict(transform) for transform in config.get("config_transforms", [])],
    }
    return findings, inventory


def _apply_config_transform(
    source: Path, destination: Path, transform: Mapping[str, Any]
) -> None:
    """Write a public copy of a JSON config with named top-level keys removed.

    The repository source is never modified. Removal is fail-closed: every
    configured key must already be present, so a stale transform or a regressed
    source file fails the build instead of shipping control-plane state.
    """
    keys = list(transform["remove_top_level_keys"])
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PublicationGateError(
            f"config_transforms target is not valid JSON: {source}"
        ) from exc
    if not isinstance(payload, dict):
        raise PublicationGateError(
            f"config_transforms target must be a JSON object: {source}"
        )
    for key in keys:
        if key not in payload:
            raise PublicationGateError(
                f"config_transforms expected top-level key {key!r} to remove "
                f"from {source}; the key is absent"
            )
        del payload[key]
    for path in transform.get("remove_paths", []):
        parent: Any = payload
        for part in path[:-1]:
            if not isinstance(parent, dict) or part not in parent:
                raise PublicationGateError(
                    "config_transforms expected nested path to remove from "
                    f"{source}: {'.'.join(path)}"
                )
            parent = parent[part]
        leaf = path[-1]
        if not isinstance(parent, dict) or leaf not in parent:
            raise PublicationGateError(
                "config_transforms expected nested path to remove from "
                f"{source}: {'.'.join(path)}"
            )
        del parent[leaf]
    destination.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_public_tree_manifest(public_tree: Path, destination: Path) -> None:
    """Hash the packaged public-tree bytes so the manifest matches the archive.

    Transformed files differ from their repository source, so the manifest is
    computed from the public tree (and therefore the archive) rather than from
    source bytes.
    """
    entries: list[str] = []
    for path in public_tree.rglob("*"):
        if path.is_file():
            relative = path.relative_to(public_tree).as_posix()
            entries.append(f"{_sha256(path)}  {relative}")
    entries.sort(key=lambda line: line.split("  ", 1)[1])
    destination.write_text("\n".join(entries) + "\n", encoding="utf-8")


def _copy_files(
    files: Sequence[tuple[str, Path]],
    public_tree: Path,
    transforms_by_path: Mapping[str, Mapping[str, Any]],
) -> None:
    for relative, source in files:
        destination = public_tree / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        transform = transforms_by_path.get(relative)
        if transform is not None:
            _apply_config_transform(source, destination, transform)
        else:
            shutil.copyfile(source, destination)
        os.chmod(destination, source.stat().st_mode & 0o777)


def _deterministic_tar_gz(public_tree: Path, destination: Path, arc_root: str) -> None:
    with destination.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as archive:
                for path in sorted(public_tree.rglob("*")):
                    relative = path.relative_to(public_tree).as_posix()
                    arcname = f"{arc_root}/{relative}"
                    info = archive.gettarinfo(str(path), arcname=arcname)
                    info.uid = 0
                    info.gid = 0
                    info.uname = ""
                    info.gname = ""
                    info.mtime = 0
                    if info.isfile():
                        with path.open("rb") as stream:
                            archive.addfile(info, stream)
                    else:
                        archive.addfile(info)


def _write_final_manifest(stage: Path, destination: Path) -> None:
    excluded = destination.resolve()
    members = sorted(
        path
        for path in stage.rglob("*")
        if path.is_file()
        and path.resolve() != excluded
        and "public_tree" not in path.relative_to(stage).parts
    )
    lines = [f"{_sha256(path)}  {path.relative_to(stage).as_posix()}" for path in members]
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_publication_candidate(
    repository_root: Path,
    config_path: Path,
    output_directory: Path,
) -> dict[str, Any]:
    repository_root = repository_root.resolve()
    config_path = config_path.resolve()
    output_directory = output_directory.resolve()
    if output_directory.exists():
        raise PublicationGateError(f"refusing to overwrite output: {output_directory}")
    output_directory.parent.mkdir(parents=True, exist_ok=True)

    config = load_publication_config(config_path)
    files, initial_findings = collect_allowlisted_files(repository_root, config)
    findings, inventory = audit_allowlisted_files(files, config, initial_findings)

    selected_paths = {relative for relative, _ in files}
    transforms_by_path: dict[str, Mapping[str, Any]] = {}
    for transform in config.get("config_transforms", []):
        path = transform["path"]
        if path not in selected_paths:
            raise PublicationGateError(
                "config_transforms target is not packaged, so the transform "
                f"cannot be applied: {path}"
            )
        transforms_by_path[path] = transform
    missing_release = sorted(
        path for path in config["required_release_files"] if path not in selected_paths
    )
    findings.extend(
        Finding("promotion", "missing_required_release_file", path)
        for path in missing_release
    )
    findings.sort(key=lambda item: (item.gate, item.path, item.line or 0, item.rule))

    content_findings = [item for item in findings if item.gate in {"allowlist", "content"}]
    promotion_findings = [item for item in findings if item.gate == "promotion"]
    content_pass = not content_findings
    promotion_pass = content_pass and not promotion_findings
    status = (
        "COMPLETE_RELEASE"
        if promotion_pass
        else "BLOCKED_PROMOTION"
        if content_pass
        else "FAILED_CONTENT_GATE"
    )

    temporary = Path(
        tempfile.mkdtemp(
            prefix=f".{output_directory.name}.staging-",
            dir=str(output_directory.parent),
        )
    )
    try:
        public_tree = temporary / "public_tree"
        public_tree.mkdir()
        _copy_files(files, public_tree, transforms_by_path)
        _write_public_tree_manifest(
            public_tree, temporary / "SOURCE_FILES.SHA256SUMS"
        )

        archive_name = f"{config['package_name']}-candidate.tar.gz"
        archive_path = temporary / archive_name
        if content_pass:
            _deterministic_tar_gz(public_tree, archive_path, str(config["package_name"]))
            (temporary / f"{archive_name}.sha256").write_text(
                f"{_sha256(archive_path)}  {archive_name}\n",
                encoding="utf-8",
            )

        audit = {
            "schema_version": 1,
            "generated_at_utc": _utc_now(),
            "repository_root": str(repository_root),
            "config": _relative_file(config_path, repository_root),
            "status": status,
            "content_gate_pass": content_pass,
            "promotion_gate_pass": promotion_pass,
            "archive_created": archive_path.exists(),
            "inventory": inventory,
            "finding_counts": {
                "content": len(content_findings),
                "promotion": len(promotion_findings),
            },
            "findings": [finding.as_dict() for finding in findings],
            "claim_boundary": (
                "A COMPLETE_RELEASE status is required before publication. "
                "BLOCKED_PROMOTION is an inspectable candidate only and is not "
                "a clean-room reproduction, public release, or competition submission."
            ),
        }
        (temporary / "publication_audit.json").write_text(
            json.dumps(audit, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (temporary / "run.status").write_text(status + "\n", encoding="utf-8")
        (temporary / "finished_at_utc.txt").write_text(_utc_now() + "\n", encoding="utf-8")
        _write_final_manifest(temporary, temporary / "FINAL_EVIDENCE.SHA256SUMS")
        temporary.rename(output_directory)
        return audit
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
