"""Determinex release gate status collector.

This collector turns scattered release evidence into one conservative status
model. It never grants release authority; it only reports what the current
checkout can prove from local files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "determinex-release-gate-status-v1"
CLEAN_HOST_TRANSCRIPT_SCHEMA_VERSION = "determinex-clean-host-install-transcript-v1"
SWEBENCH_FRESH_PUBLICATION_SCHEMA_VERSION = "determinex-swebench-fresh-publication-evidence-v1"
WINDOWS_TRUST_SCHEMA_VERSION = "determinex-windows-trust-evidence-v1"
LEGAL_PUBLIC_DISTRIBUTION_SCHEMA_VERSION = "determinex-legal-public-distribution-evidence-v1"
WINDOWS_MSI_SCHEMA_VERSION = "determinex-windows-msi-evidence-v1"
EXTENSION_COMPAT_SCHEMA_VERSION = "determinex-extension-compat-runtime-evidence-v1"
PROGRAMBENCH_DENOMINATOR = 200
SWEBENCH_REQUIRED_PRIVACY_MODES = frozenset({"B-Uncloaked", "RegionControl", "Cloaked"})
LINUX_PACKAGE_TYPES = frozenset({"linux_appimage", "linux_deb", "linux_rpm"})
REQUIRED_LINUX_PACKAGE_TYPES = ("linux_appimage", "linux_deb", "linux_rpm")


@dataclass(frozen=True)
class ReleaseGate:
    gate_id: str
    title: str
    status: str
    release_ready: bool
    evidence: tuple[str, ...]
    exact_blocker: str
    next_action: str
    runbook_commands: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["evidence"] = list(self.evidence)
        payload["runbook_commands"] = list(self.runbook_commands)
        return payload


@dataclass(frozen=True)
class ReleaseGateReport:
    schema_version: str
    generated_at_utc: str
    product_name: str
    release_ready: bool
    authority_granted: bool
    gates: tuple[ReleaseGate, ...]
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def blocked_gate_ids(self) -> tuple[str, ...]:
        return tuple(g.gate_id for g in self.gates if g.status == "blocked")

    @property
    def partial_gate_ids(self) -> tuple[str, ...]:
        return tuple(g.gate_id for g in self.gates if g.status == "partial")

    @property
    def deferred_gate_ids(self) -> tuple[str, ...]:
        return tuple(g.gate_id for g in self.gates if g.status == "deferred")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "generated_at_utc": self.generated_at_utc,
            "product_name": self.product_name,
            "release_ready": self.release_ready,
            "authority_granted": self.authority_granted,
            "blocked_gate_ids": list(self.blocked_gate_ids),
            "partial_gate_ids": list(self.partial_gate_ids),
            "deferred_gate_ids": list(self.deferred_gate_ids),
            "gates": [g.to_dict() for g in self.gates],
            "notes": list(self.notes),
        }


def _rel(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _read_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_sha256(value: str) -> bool:
    if len(value) != 64:
        return False
    return all(ch in "0123456789abcdefABCDEF" for ch in value)


def _download_artifacts(
    download: dict[str, Any] | None, artifact_type: str
) -> list[dict[str, Any]]:
    if not isinstance(download, dict):
        return []
    return [
        artifact
        for artifact in (download.get("artifacts") or [])
        if isinstance(artifact, dict) and artifact.get("artifact_type") == artifact_type
    ]


def _download_artifact_errors(root: Path, artifact: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    source_path = str(artifact.get("source_path") or "").strip()
    sha256 = str(artifact.get("sha256") or "").strip()
    size_bytes = artifact.get("size_bytes")

    if not source_path:
        errors.append("missing source_path")
        path = None
    elif "mocked" in source_path.lower():
        errors.append("mocked source_path")
        path = None
    else:
        path = root / source_path
        if not path.is_file():
            errors.append("missing source file")

    if not sha256:
        errors.append("missing sha256")
    elif "mocked" in sha256.lower():
        errors.append("mocked sha256")
    elif not _is_sha256(sha256):
        errors.append("invalid sha256")
    elif path is not None and path.is_file() and _hash_file(path).lower() != sha256.lower():
        errors.append("sha256 mismatch")

    if path is not None and path.is_file() and size_bytes is not None:
        try:
            expected_size = int(size_bytes)
        except (TypeError, ValueError):
            errors.append("invalid size_bytes")
        else:
            if expected_size != path.stat().st_size:
                errors.append("size_bytes mismatch")
    return errors


def _valid_download_artifact_types(root: Path, download: dict[str, Any] | None) -> set[str]:
    if not isinstance(download, dict):
        return set()
    valid: set[str] = set()
    for artifact in download.get("artifacts") or []:
        if not isinstance(artifact, dict):
            continue
        artifact_type = str(artifact.get("artifact_type") or "")
        if artifact_type and not _download_artifact_errors(root, artifact):
            valid.add(artifact_type)
    return valid


def _download_artifact_type_blockers(
    root: Path,
    download: dict[str, Any] | None,
    required_types: tuple[str, ...],
) -> list[str]:
    blockers: list[str] = []
    for artifact_type in required_types:
        artifacts = _download_artifacts(download, artifact_type)
        if not artifacts:
            blockers.append(f"{artifact_type}_not_bundled")
            continue
        artifact_errors = [_download_artifact_errors(root, artifact) for artifact in artifacts]
        if not any(not errors for errors in artifact_errors):
            merged = sorted({error for errors in artifact_errors for error in errors})
            blockers.append(f"{artifact_type} ({', '.join(merged)})")
    return blockers


def _download_artifact_hashes(root: Path, download: dict[str, Any] | None) -> set[str]:
    if not isinstance(download, dict):
        return set()
    hashes: set[str] = set()
    for artifact in download.get("artifacts") or []:
        if isinstance(artifact, dict) and not _download_artifact_errors(root, artifact):
            hashes.add(str(artifact["sha256"]).lower())
    return hashes


def _clean_host_transcript_candidates(root: Path) -> list[Path]:
    return sorted(
        [
            *(root / "assurance/evidence/full_release_closure").glob(
                "clean_host_install_transcript_*.json"
            ),
            *(root / "assurance/evidence/clean_host_fresh_install_runner_execution").glob(
                "clean_host_install_transcript_*.json"
            ),
        ],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )


def _clean_host_transcript_errors(data: Any) -> list[str]:
    if not isinstance(data, dict):
        return ["transcript JSON must be an object"]
    errors: list[str] = []
    expected_true = (
        "clean_host_fresh_install",
        "installer_execution_performed",
        "launch_performed",
        "proof_center_smoke_performed",
        "workspace_command_smoke_performed",
        "uninstall_performed",
    )
    # `key`, not `field`: this shadowed `dataclasses.field`, imported at line 14 and used by the
    # dataclasses above. Harmless as written -- the shadowing is function-local and the class
    # bodies ran at import -- but it is a trap for anyone who later needs field() in here.
    for key in expected_true:
        if data.get(key) is not True:
            errors.append(f"{key} must be true")
    expected_false = (
        "dry_run",
        "release_ready",
        "authority_granted",
    )
    for key in expected_false:
        if data.get(key) is not False:
            errors.append(f"{key} must be false")
    if data.get("schema_version") != CLEAN_HOST_TRANSCRIPT_SCHEMA_VERSION:
        errors.append(f"schema_version must be {CLEAN_HOST_TRANSCRIPT_SCHEMA_VERSION}")
    if data.get("product_name") != "Determinex":
        errors.append("product_name must be Determinex")

    runner = data.get("runner")
    if not isinstance(runner, dict):
        errors.append("runner must be an object")
    else:
        if runner.get("is_clean_host") is not True:
            errors.append("runner.is_clean_host must be true")
        if runner.get("host_reused_from_developer_machine") is not False:
            errors.append("runner.host_reused_from_developer_machine must be false")
        if not str(runner.get("os") or "").lower().startswith("windows"):
            errors.append("runner.os must identify a Windows clean host")
        runner_id = str(runner.get("runner_id") or "")
        if not runner_id or "mocked" in runner_id.lower():
            errors.append("runner.runner_id must not be a mocked runner")

    bundle = data.get("bundle")
    if not isinstance(bundle, dict):
        errors.append("bundle must be an object")
    else:
        if not str(bundle.get("source_commit") or "").strip():
            errors.append("bundle.source_commit must be recorded")
        if bundle.get("installer_sha256_verified") is not True:
            errors.append("bundle.installer_sha256_verified must be true")
        sha256 = str(bundle.get("installer_sha256") or "")
        if not sha256 or "mocked" in sha256.lower():
            errors.append("bundle.installer_sha256 must not be mocked")
    return errors


def _latest_clean_host_transcript(
    root: Path,
) -> tuple[Path | None, dict[str, Any] | None, list[str]]:
    download_manifest_path = newest_download_manifest_path(root)
    manifest = _read_json(download_manifest_path) if download_manifest_path is not None else None
    valid_hashes = _download_artifact_hashes(root, manifest)

    first_invalid: tuple[Path, list[str]] | None = None
    for candidate in _clean_host_transcript_candidates(root):
        data = _read_json(candidate)
        errors = _clean_host_transcript_errors(data)
        if not errors and isinstance(data, dict):
            bundle_hash = str((data.get("bundle") or {}).get("installer_sha256") or "").lower()
            if bundle_hash not in valid_hashes:
                errors.append(
                    "bundle.installer_sha256 does not match any known artifact in the current download bundle manifest"
                )
        if not errors and isinstance(data, dict):
            return candidate, data, []
        if first_invalid is None:
            first_invalid = (candidate, errors)
    if first_invalid is not None:
        path, errors = first_invalid
        return path, None, errors
    return None, None, []


def _gate(
    gate_id: str,
    title: str,
    status: str,
    evidence: list[str],
    exact_blocker: str,
    next_action: str,
    runbook_commands: list[str] | None = None,
) -> ReleaseGate:
    return ReleaseGate(
        gate_id=gate_id,
        title=title,
        status=status,
        release_ready=False,
        evidence=tuple(evidence),
        exact_blocker=exact_blocker,
        next_action=next_action,
        runbook_commands=tuple(runbook_commands or []),
    )


def _packet_field_errors(
    data: Any,
    *,
    schema_version: str,
    expected_true: tuple[str, ...] = (),
    expected_false: tuple[str, ...] = ("authority_granted",),
) -> list[str]:
    if not isinstance(data, dict):
        return ["packet JSON must be an object"]
    errors: list[str] = []
    if data.get("schema_version") != schema_version:
        errors.append(f"schema_version must be {schema_version}")
    for field_name in expected_true:
        if data.get(field_name) is not True:
            errors.append(f"{field_name} must be true")
    for field_name in expected_false:
        if data.get(field_name) is not False:
            errors.append(f"{field_name} must be false")
    return errors


def _latest_packet(
    root: Path,
    folder: str,
    pattern: str,
    errors_fn,
) -> tuple[Path | None, dict[str, Any] | None, list[str]]:
    candidates = sorted(
        (root / folder).glob(pattern),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    # THE NEWEST PACKET DECIDES. Fixed 2026-07-30: this used to return the first VALID candidate
    # and merely `continue` past an invalid newer one, so the semantics were "newest valid packet
    # wins" rather than "the newest packet must be valid". With nine MSI packets on disk an older
    # passing one always existed, so recording an honest new attestation that FAILED -- a rebuild
    # whose MSI was bad, or a re-sign that came back NotSigned -- left the gate green indefinitely.
    # Proven by injecting a rejection for the newest MSI packet: the gate fell back to an older
    # file, surfaced zero errors, and reported passed.
    #
    # Superseding evidence is legitimate, but it has to be NEWER than what it supersedes, not
    # merely valid. So only the newest packet is consulted; older ones are history, not fallback.
    if not candidates:
        return None, None, []
    newest = candidates[0]
    data = _read_json(newest)
    errors = errors_fn(data)
    if not errors and isinstance(data, dict):
        return newest, data, []
    return newest, None, errors


def _cyclonedx_component_ids(document: Any) -> set[str]:
    """Every name a CycloneDX component might be findable by.

    npm components are commonly split into `group` ("@tauri-apps") and `name`
    ("plugin-updater"), so a bare name lookup misses scoped packages entirely. purl is included
    because generators disagree about the group/name split.
    """
    ids: set[str] = set()
    if not isinstance(document, dict):
        return ids
    for component in document.get("components") or []:
        if not isinstance(component, dict):
            continue
        name = str(component.get("name") or "").strip().lower()
        group = str(component.get("group") or "").strip().lower()
        purl = str(component.get("purl") or "").strip().lower()
        if name:
            ids.add(name)
            ids.add(name.replace("_", "-"))
        if group and name:
            ids.add(f"{group}/{name}")
        if purl:
            ids.add(purl)
    return ids


def _normalize_python_requirement(spec: str) -> str:
    """ "fastembed>=0.4.0" -> "fastembed"; PEP 503 normalised."""
    name = spec.strip()
    for separator in ("[", ";", "<", ">", "=", "!", "~", " "):
        name = name.split(separator, 1)[0]
    return name.strip().lower().replace("_", ".").replace(".", "-")


def _sbom_missing_direct_dependencies(
    root: Path,
    npm_cdx: Any,
    python_cdx: Any,
) -> list[str]:
    """Direct dependencies we ship that the SBOMs do not list.

    Returns an empty list when the source of truth cannot be read: an unreadable package.json
    is a different problem from an incomplete SBOM, and failing this gate for it would report
    the wrong blocker.
    """
    missing: list[str] = []

    npm_ids = _cyclonedx_component_ids(npm_cdx)
    package_json = _read_json(root / "frontend" / "package.json")
    if isinstance(package_json, dict) and npm_ids:
        # Runtime dependencies only. devDependencies are not shipped in the bundle.
        for dep in package_json.get("dependencies") or {}:
            needle = str(dep).strip().lower()
            if not needle:
                continue
            if needle in npm_ids:
                continue
            # Scoped package: "@scope/name" may appear as group "@scope" + name "name".
            if needle.startswith("@") and "/" in needle:
                _, _, bare = needle.partition("/")
                if bare in npm_ids:
                    continue
            if any(needle in candidate for candidate in npm_ids):
                continue
            missing.append(f"npm:{dep}")

    python_ids = _cyclonedx_component_ids(python_cdx)
    pyproject = root / "pyproject.toml"
    if python_ids and pyproject.is_file():
        try:
            import tomllib

            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except (OSError, ValueError, ImportError):
            data = {}
        for spec in (data.get("project") or {}).get("dependencies") or []:
            needle = _normalize_python_requirement(str(spec))
            if not needle or needle in python_ids:
                continue
            if any(needle in candidate for candidate in python_ids):
                continue
            missing.append(f"python:{needle}")

    return missing


def _sbom_gate(root: Path) -> ReleaseGate:
    required = [
        root / "assurance/sbom/determinex-python.spdx.json",
        root / "assurance/sbom/determinex-python.cyclonedx.json",
        root / "assurance/sbom/determinex-npm.cyclonedx.json",
    ]
    missing = [p for p in required if not p.is_file()]
    evidence = [_rel(root, p) for p in required if p.is_file()]
    if missing:
        return _gate(
            "sbom",
            "SBOM coverage",
            "blocked",
            evidence,
            "Missing SBOM artifact(s): " + ", ".join(_rel(root, p) for p in missing),
            "Regenerate Python and npm SBOM artifacts and rerun this collector.",
            [
                r".venv\Scripts\python.exe scripts\security\generate_sbom.py",
                r".venv\Scripts\python.exe scripts\release\determinex_release_gates.py --output assurance\evidence\determinex_release_gate_status\release_gates_20260707.json",
            ],
        )

    parsed = [_read_json(p) for p in required]
    if any(p is None for p in parsed):
        return _gate(
            "sbom",
            "SBOM coverage",
            "blocked",
            evidence,
            "At least one SBOM artifact is not valid JSON.",
            "Regenerate malformed SBOM artifacts.",
            [
                r".venv\Scripts\python.exe scripts\security\generate_sbom.py",
                r".venv\Scripts\python.exe scripts\release\determinex_release_gates.py --output assurance\evidence\determinex_release_gate_status\release_gates_20260707.json",
            ],
        )

    spdx, python_cdx, npm_cdx = parsed
    python_spdx_name = str(spdx.get("name", "")) if isinstance(spdx, dict) else ""
    python_cdx_name = ""
    if isinstance(python_cdx, dict):
        metadata = python_cdx.get("metadata") or {}
        component = metadata.get("component") if isinstance(metadata, dict) else {}
        python_cdx_name = str((component or {}).get("name", ""))
    npm_bom_format = str(npm_cdx.get("bomFormat", "")) if isinstance(npm_cdx, dict) else ""
    if (
        not python_spdx_name.startswith("determinex-python")
        or python_cdx_name != "determinex-python"
    ):
        return _gate(
            "sbom",
            "SBOM coverage",
            "blocked",
            evidence,
            "Python SBOM artifacts are not Determinex branded.",
            "Regenerate SBOMs with scripts/security/generate_sbom.py.",
            [
                r".venv\Scripts\python.exe scripts\security\generate_sbom.py",
                r".venv\Scripts\python.exe scripts\release\determinex_release_gates.py --output assurance\evidence\determinex_release_gate_status\release_gates_20260707.json",
            ],
        )
    if npm_bom_format != "CycloneDX":
        return _gate(
            "sbom",
            "SBOM coverage",
            "blocked",
            evidence,
            "NPM SBOM is not a CycloneDX JSON artifact.",
            "Regenerate frontend SBOM with the npm SBOM script.",
            [
                r"cd frontend; npm.cmd run sbom",
                r".venv\Scripts\python.exe scripts\release\determinex_release_gates.py --output assurance\evidence\determinex_release_gate_status\release_gates_20260707.json",
            ],
        )
    # ── Content binding ──────────────────────────────────────────────────────────────────
    # Everything above checks that the files exist, parse, and are branded. None of it checks
    # that they DESCRIBE WHAT WE SHIP, and the gate's next_action ("Keep SBOMs regenerated")
    # was an instruction to a human standing in for that check. Measured 2026-07-29: the npm
    # SBOM was two weeks old and listed neither @tauri-apps/plugin-dialog (shipping for weeks)
    # nor the updater/process plugins added that day, and this gate reported SBOM coverage as
    # passed the whole time. An SBOM that omits shipped dependencies is worse than no SBOM,
    # because it is consumed as a supply-chain assertion.
    #
    # Direct dependencies only, deliberately: transitive resolution belongs to the generator,
    # and demanding it here would turn this into a second, competing implementation.
    missing_components = _sbom_missing_direct_dependencies(root, npm_cdx, python_cdx)
    if missing_components:
        shown = ", ".join(missing_components[:8])
        more = f" (+{len(missing_components) - 8} more)" if len(missing_components) > 8 else ""
        return _gate(
            "sbom",
            "SBOM coverage",
            "blocked",
            evidence,
            f"SBOM does not list shipped direct dependencies: {shown}{more}",
            "Regenerate the SBOMs so they describe the dependencies actually shipped.",
            [
                r"cd frontend; npm.cmd run generate:sbom",
                r".venv\Scripts\python.exe scripts\security\generate_sbom.py",
                r".venv\Scripts\python.exe scripts\release\determinex_release_gates.py --output assurance\evidence\determinex_release_gate_status\release_gates_20260729.json",
            ],
        )

    return _gate(
        "sbom",
        "SBOM coverage",
        "passed",
        evidence + [f"sha256:{_hash_file(p)}" for p in required],
        "",
        "Keep SBOMs regenerated for release artifacts and clean-host packets.",
        [
            r".venv\Scripts\python.exe scripts\security\generate_sbom.py",
            r".venv\Scripts\python.exe scripts\release\determinex_release_gates.py --output assurance\evidence\determinex_release_gate_status\release_gates_20260707.json",
        ],
    )


def _clean_host_gate(root: Path) -> ReleaseGate:
    path = root / (
        "assurance/evidence/clean_host_fresh_install_runner_execution/"
        "run_20260531.CLEAN_HOST_FRESH_INSTALL_RUNNER_EXECUTION_BLOCKED_RUNNER_NOT_EXECUTED.json"
    )
    transcript_path, transcript_data, transcript_errors = _latest_clean_host_transcript(root)
    preflights = sorted(
        [
            *(root / "assurance/evidence/clean_host_fresh_install_runner_execution").glob(
                "runner_preflight_*.json"
            ),
            *(root / "assurance/evidence/full_release_closure").glob(
                "clean_host_runner_preflight_*.json"
            ),
        ],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    preflight = preflights[0] if preflights else None
    evidence = [
        _rel(root, p) for p in (transcript_path, path, preflight) if p is not None and p.is_file()
    ]
    data = _read_json(path) if path.is_file() else None
    preflight_data = _read_json(preflight) if preflight and preflight.is_file() else None
    if transcript_data is not None:
        return _gate(
            "clean_host",
            "Clean-host install proof",
            "passed",
            evidence,
            "",
            "Keep the clean-host transcript tied to the final release commit.",
            [
                r".venv\Scripts\python.exe scripts\release\clean_host_install_transcript.py --validate "
                + _rel(root, transcript_path),
                r".venv\Scripts\python.exe scripts\release\determinex_release_gates.py --output assurance\evidence\determinex_release_gate_status\release_gates_20260707.json",
            ],
        )
    if transcript_path is not None:
        return _gate(
            "clean_host",
            "Clean-host install proof",
            "blocked",
            evidence,
            "Invalid clean-host install transcript: " + "; ".join(transcript_errors),
            "Rerun the clean-host installer transcript on a clean Windows runner and validate it before collecting release gates.",
            [
                r".venv\Scripts\python.exe scripts\release\clean_host_install_transcript.py --template-output assurance\evidence\full_release_closure\clean_host_install_transcript_YYYYMMDD.json",
                r".venv\Scripts\python.exe scripts\release\clean_host_install_transcript.py --validate "
                + _rel(root, transcript_path),
                r".venv\Scripts\python.exe scripts\release\determinex_release_gates.py --output assurance\evidence\determinex_release_gate_status\release_gates_20260707.json",
            ],
        )
    if not isinstance(data, dict):
        return _gate(
            "clean_host",
            "Clean-host install proof",
            "blocked",
            evidence,
            "No clean-host install execution record found.",
            "Run a clean-host install/launch/smoke/uninstall transcript and record the output.",
            [
                "docker info",
                r".venv\Scripts\python.exe scripts\release\clean_host_install_transcript.py --template-output assurance\evidence\full_release_closure\clean_host_install_transcript_YYYYMMDD.json",
                r".venv\Scripts\python.exe scripts\release\determinex_release_gates.py --output assurance\evidence\determinex_release_gate_status\release_gates_20260707.json",
            ],
        )
    if isinstance(preflight_data, dict) and preflight_data.get("docker_info_available") is True:
        return _gate(
            "clean_host",
            "Clean-host install proof",
            "blocked",
            evidence,
            "Clean runner is available, but clean-host installer install/launch/uninstall proof has not been executed.",
            "Run the installer in a clean Windows runner, capture install/launch/uninstall transcript, and replace the blocked clean-host record with passing proof.",
            [
                "docker info",
                r".venv\Scripts\python.exe scripts\release\clean_host_install_transcript.py --template-output assurance\evidence\full_release_closure\clean_host_install_transcript_YYYYMMDD.json",
                r".venv\Scripts\python.exe scripts\release\full_release_closure.py --output assurance\evidence\full_release_closure\run_20260707.json",
                r".venv\Scripts\python.exe scripts\release\determinex_release_gates.py --output assurance\evidence\determinex_release_gate_status\release_gates_20260707.json",
            ],
        )
    preflight_blocker = (
        str(preflight_data.get("exact_blocker"))
        if isinstance(preflight_data, dict) and preflight_data.get("exact_blocker")
        else ""
    )
    blocker = (
        preflight_blocker
        or ((data.get("artifact_payloads") or {}).get("clean_run_transcript_or_blocker") or {}).get(
            "blocker"
        )
        or data.get("status")
        or "Clean-host proof did not pass."
    )
    next_action = (
        "Rerun the clean-host probe outside the sandbox, then execute the install/launch/uninstall transcript."
        if isinstance(preflight_data, dict)
        and preflight_data.get("docker_probe_blocked_by_sandbox") is True
        else "Provision or repair a clean runner, then rerun install/build/smoke proof."
    )
    return _gate(
        "clean_host",
        "Clean-host install proof",
        "blocked",
        evidence,
        str(blocker),
        next_action,
        [
            "docker info",
            r".venv\Scripts\python.exe scripts\release\clean_host_install_transcript.py --template-output assurance\evidence\full_release_closure\clean_host_install_transcript_YYYYMMDD.json",
            r".venv\Scripts\python.exe scripts\release\full_release_closure.py --output assurance\evidence\full_release_closure\run_20260707.json",
            r".venv\Scripts\python.exe scripts\release\determinex_release_gates.py --output assurance\evidence\determinex_release_gate_status\release_gates_20260707.json",
        ],
    )


def newest_download_manifest_path(root: Path) -> Path | None:
    """THE answer to "which download manifest describes what we ship" — one implementation.

    Promoted to the canonical home 2026-07-31. This glob-and-sort-by-mtime was written out by
    hand in six places (four in this file, plus full_release_closure and clean_host_kit), and two
    further scripts skipped it entirely and hardcoded `determinex_download_bundle_20260707` as a
    default. Every rebuild moves the answer, so the hardcoded ones went stale the first time
    anyone packaged a bundle, and they stayed stale silently.

    That is not hypothetical twice over. `clean_host_kit._newest_manifest` sorted by `p.name` --
    identical for every candidate, so the sort was a no-op -- and shipped a kit built from the
    20260707 bundle while the gates read 20260729. And on 2026-07-31 the clean-host smoke, whose
    default still named 20260707, produced a transcript claiming installer_sha256_verified=true
    for an installer that appears in no manifest that script could see.

    Returns None when no manifest exists, so callers keep deciding what absence means.
    """
    manifests = sorted(
        (root / "assurance/evidence").glob("determinex_download_bundle_*/download_manifest.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for candidate in manifests:
        if candidate.is_file():
            return candidate
    return None


def _newest_download_manifest(root: Path) -> dict[str, Any] | None:
    """The manifest describing the artifacts currently on offer, parsed."""
    path = newest_download_manifest_path(root)
    if path is None:
        return None
    data = _read_json(path)
    return data if isinstance(data, dict) else None


def _release_artifacts_built_at(root: Path, manifest: dict[str, Any] | None) -> str:
    """When the shipped artifacts were actually BUILT, as an ISO-8601 UTC stamp.

    Anchoring freshness on `manifest.generated_at_utc` was wrong and I proved it by tripping it:
    re-running package_download_bundle.py to correct a line of SETUP.md moved that stamp forward 14
    minutes and instantly invalidated end-to-end evidence gathered against byte-identical
    installers. Repackaging is not rebuilding, and a gate that blocks on it is a gate that gets
    switched off rather than satisfied.

    The installers' own mtimes are the honest anchor: they move when a build produces new binaries
    and stay put when the manifest is merely rewritten. Returns "" when nothing can be determined,
    which callers treat as "no freshness claim" rather than as a failure.
    """
    if not isinstance(manifest, dict):
        return ""
    newest = 0.0
    for artifact in manifest.get("artifacts") or []:
        if not isinstance(artifact, dict):
            continue
        source = str(artifact.get("source_path") or "").strip()
        if not source:
            continue
        path = root / source
        try:
            newest = max(newest, path.stat().st_mtime)
        except OSError:
            continue
    if newest <= 0:
        return ""
    return (
        datetime.fromtimestamp(newest, tz=UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _is_passing_status(status: str) -> bool:
    """Whether a free-text status field reports success.

    `status.endswith("PASSED")` alone is not safe: "NOT_PASSED" ends with "PASSED", and the
    statuses in this evidence tree are hand-built strings like
    "LANE_D_BLOCKED_LOCAL_BUILDER_OLLAMA_TIMEOUT". A suffix test on an unconstrained string is
    one unlucky label away from reading a failure as a pass, so negative markers are excluded
    explicitly.
    """
    upper = status.upper()
    # A denylist alone was not enough, and the first attempt at this proved it: excluding
    # negative markers and then accepting any string ENDING in PASSED/SUCCESS still accepted
    # BYPASSED (the word simply contains "PASSED"), UNVERIFIED_PASSED, PARTIALLY_PASSED,
    # MOCK_SUCCESS, SIMULATED_SUCCESS and STUBBED_SUCCESS. That replaced one suffix bug with a
    # narrower version of the same bug.
    #
    # So two independent conditions now hold. First, the verdict token must be a WHOLE token --
    # preceded by a separator or the start of the string -- which is what excludes BYPASSED.
    # Second, no qualifier may appear anywhere: UNVERIFIED_ matters specifically, because the
    # lenient-oracle path tags its results with a literal "UNVERIFIED:" prefix, and a qualified
    # pass is exactly the kind of claim this collector exists not to make.
    disqualifying = (
        "NOT",
        "UNPASSED",
        "FAIL",
        "BLOCK",
        "TIMEOUT",
        "ERROR",
        "BYPASS",
        "UNVERIFIED",
        "PARTIAL",
        "MOCK",
        "SIMULAT",
        "STUB",
        "SKIP",
        "LENIENT",
        "PENDING",
        "DEFERRED",
        "ASSUMED",
        "EXPECTED",
    )
    if any(marker in upper for marker in disqualifying):
        return False
    return re.search(r"(?:^|[_\- ])(?:PASSED|SUCCESS)$", upper) is not None


def _first_e2e_gate(root: Path) -> ReleaseGate:
    path = root / "assurance/evidence/first_end_to_end_user_workflow/result.json"
    probe = (
        root / "assurance/evidence/first_end_to_end_user_workflow/builder_health_probe_latest.json"
    )
    rerun = (
        root
        / "assurance/evidence/first_end_to_end_user_workflow/rerun_after_builder_health_latest.json"
    )
    evidence = [_rel(root, p) for p in (path, probe, rerun) if p.is_file()]
    data = _read_json(path) if path.is_file() else None
    probe_data = _read_json(probe) if probe.is_file() else None
    rerun_data = _read_json(rerun) if rerun.is_file() else None
    rerun_session_id = (
        str(rerun_data.get("session_id"))
        if isinstance(rerun_data, dict) and rerun_data.get("session_id")
        else "99d31f71-a25a-4849-8b12-44131c586699"
    )
    if not isinstance(data, dict):
        return _gate(
            "first_e2e",
            "First end-to-end user workflow",
            "blocked",
            evidence,
            "No first E2E workflow result found.",
            "Run and capture a full user workflow transcript.",
            [
                r".venv\Scripts\python.exe scripts\hive\builder_health_probe.py --model determinex/engineer --output assurance\evidence\first_end_to_end_user_workflow\builder_health_probe_latest.json",
            ],
        )
    status = str(data.get("status", ""))
    rerun_status = str(rerun_data.get("status", "")) if isinstance(rerun_data, dict) else ""

    # ── Freshness binding ────────────────────────────────────────────────────────────────
    # This gate had NO tie to the code being shipped. It read a status string out of an
    # evidence file and passed, so a single old transcript authorised every later release: the
    # passing rerun was dated 2026-07-07 and stayed green across the rename, the addition of
    # the updater, and a period when the installed app could not launch at all on a clean host
    # (0xC0000135, fixed 2026-07-29). Its own next_action said "Keep the transcript current
    # with the release commit" -- an instruction to a human standing in for a check.
    #
    # An end-to-end proof taken before the artifacts were built does not exercise them, so the
    # rule is simply that the proof may not predate what it claims to validate. Compared
    # against the download manifest rather than against HEAD on purpose: gating on every commit
    # would demand a rerun for a docs typo and the gate would live permanently blocked, which
    # is how checks end up quietly relaxed. Cutting new installers is the event that
    # invalidates the claim.
    manifest = _newest_download_manifest(root)
    manifest_built = _release_artifacts_built_at(root, manifest)
    e2e_stamp = ""
    for candidate_data in (rerun_data, data):
        if isinstance(candidate_data, dict) and candidate_data.get("generated_at_utc"):
            e2e_stamp = str(candidate_data["generated_at_utc"])
            break
    if manifest_built and e2e_stamp and e2e_stamp < manifest_built:
        return _gate(
            "first_e2e",
            "First end-to-end user workflow",
            "blocked",
            evidence,
            (
                f"First E2E evidence ({e2e_stamp}) predates the release artifacts "
                f"({manifest_built}), so it did not exercise the build being shipped."
            ),
            "Rerun the first end-to-end workflow against the current build and recapture it.",
            [
                r".venv\Scripts\python.exe scripts\hive\builder_health_probe.py --model determinex/engineer --output assurance\evidence\first_end_to_end_user_workflow\builder_health_probe_latest.json",
                rf".venv\Scripts\python.exe scripts\determinex_hive.py run-session --session {rerun_session_id}",
            ],
        )

    rerun_observed = rerun_data.get("observed_result") if isinstance(rerun_data, dict) else {}
    rerun_steps_complete = (
        int(rerun_observed.get("steps_complete", -1)) if isinstance(rerun_observed, dict) else -1
    )
    rerun_steps_total = (
        int(rerun_observed.get("steps_total", -2)) if isinstance(rerun_observed, dict) else -2
    )
    rerun_steps_failed = (
        int(rerun_observed.get("steps_failed", 1)) if isinstance(rerun_observed, dict) else 1
    )
    if (
        isinstance(rerun_data, dict)
        and _is_passing_status(rerun_status)
        and rerun_steps_total > 0
        and rerun_steps_complete == rerun_steps_total
        and rerun_steps_failed == 0
    ):
        return _gate(
            "first_e2e",
            "First end-to-end user workflow",
            "passed",
            evidence,
            "",
            "Keep the passing first-E2E transcript current with the release commit.",
            [
                r".venv\Scripts\python.exe scripts\hive\builder_health_probe.py --model determinex/engineer --output assurance\evidence\first_end_to_end_user_workflow\builder_health_probe_latest.json",
                rf".venv\Scripts\python.exe scripts\determinex_hive.py run-session --session {rerun_session_id}",
            ],
        )
    if _is_passing_status(status):
        return _gate(
            "first_e2e",
            "First end-to-end user workflow",
            "passed",
            evidence,
            "",
            "Keep the transcript current with the release commit.",
            [
                r".venv\Scripts\python.exe scripts\hive\builder_health_probe.py --model determinex/engineer --output assurance\evidence\first_end_to_end_user_workflow\builder_health_probe_latest.json",
            ],
        )
    return _gate(
        "first_e2e",
        "First end-to-end user workflow",
        "blocked",
        evidence,
        (
            str(rerun_data.get("exact_blocker"))
            if isinstance(rerun_data, dict) and rerun_data.get("exact_blocker")
            else "First E2E transcript has not been rerun after Builder health passed."
            if isinstance(probe_data, dict) and probe_data.get("status") == "passed"
            else status or "First E2E did not pass."
        ),
        (
            str(rerun_data.get("next_required_action"))
            if isinstance(rerun_data, dict) and rerun_data.get("next_required_action")
            else "Rerun session 99d31f71-a25a-4849-8b12-44131c586699 with the existing correctness harness."
            if isinstance(probe_data, dict) and probe_data.get("status") == "passed"
            else str(
                data.get("next_required_action")
                or "Restore workflow health and rerun the transcript."
            )
        ),
        [
            r".venv\Scripts\python.exe scripts\hive\builder_health_probe.py --model determinex/engineer --output assurance\evidence\first_end_to_end_user_workflow\builder_health_probe_latest.json",
            r'$env:DETERMINEX_BUILDER_FALLBACK_MODEL="<stable admitted model>"; .venv\Scripts\python.exe scripts\hive\builder_health_probe.py --model determinex/engineer --fallback-model "<stable admitted model>"',
            rf".venv\Scripts\python.exe scripts\determinex_hive.py run-session --session {rerun_session_id}",
        ],
    )


def _download_artifact_types(download: dict[str, Any] | None) -> set[str]:
    if not isinstance(download, dict):
        return set()
    artifact_types = {
        str(artifact.get("artifact_type"))
        for artifact in (download.get("artifacts") or [])
        if isinstance(artifact, dict) and artifact.get("artifact_type")
    }
    matrix = download.get("package_matrix")
    if isinstance(matrix, dict):
        artifact_types.update(str(name) for name, present in matrix.items() if present is True)
    return artifact_types


def _installer_gate(root: Path) -> ReleaseGate:
    go_no_go = root / (
        "assurance/evidence/installer_install_launch_uninstall_release_signoff_wave_001/"
        "public_distribution_go_no_go_20260602.json"
    )
    hardening = root / (
        "assurance/evidence/installer_release_packet_hardening/"
        "run_20260629.INSTALLER_RELEASE_PACKET_HARDENED_UNSIGNED.json"
    )
    download_manifest = newest_download_manifest_path(root)
    evidence_paths = [
        p for p in (go_no_go, hardening, download_manifest) if p is not None and p.is_file()
    ]
    evidence = [_rel(root, p) for p in evidence_paths]
    go = _read_json(go_no_go) if go_no_go.is_file() else None
    hard = _read_json(hardening) if hardening.is_file() else None
    download = (
        _read_json(download_manifest) if download_manifest and download_manifest.is_file() else None
    )
    if not isinstance(go, dict) and not isinstance(hard, dict) and not isinstance(download, dict):
        return _gate(
            "installer",
            "Installer/signing/public distribution",
            "blocked",
            evidence,
            "No installer release gate evidence found.",
            "Build an installer packet and capture install/launch/uninstall proof.",
            [
                r".venv\Scripts\python.exe scripts\release\determinex_release_gates.py --output assurance\evidence\determinex_release_gate_status\release_gates_20260707.json",
            ],
        )
    if (
        isinstance(go, dict)
        and go.get("release_ready") is True
        and go.get("go_no_go") == "GO_PUBLIC_DISTRIBUTION"
    ):
        return _gate(
            "installer",
            "Installer/signing/public distribution",
            "passed",
            evidence,
            "",
            "Keep installer proof tied to the final release artifact.",
            [
                r".venv\Scripts\python.exe scripts\release\determinex_release_gates.py --output assurance\evidence\determinex_release_gate_status\release_gates_20260707.json",
            ],
        )
    blockers: list[str] = []
    if isinstance(go, dict):
        blockers.extend(str(b) for b in go.get("exact_blockers") or [])
    if isinstance(hard, dict) and hard.get("status"):
        blockers.append(str(hard["status"]))
    artifact_types = _download_artifact_types(download)
    setup_ready = (
        isinstance(download, dict)
        and download.get("setup_ready_for_local_operator_testing") is True
    )
    package_blockers: list[str] = []
    if setup_ready:
        if "windows_nsis_setup" not in artifact_types:
            package_blockers.append("windows_nsis_setup_not_bundled")
        if "windows_msi" not in artifact_types:
            package_blockers.append("windows_msi_not_bundled")
        missing_linux = [
            package_type
            for package_type in REQUIRED_LINUX_PACKAGE_TYPES
            if package_type not in artifact_types
        ]
        if missing_linux:
            package_blockers.append("linux_packages_not_bundled")
            package_blockers.extend(f"{package_type}_not_bundled" for package_type in missing_linux)
    elif isinstance(download, dict):
        package_blockers.append("download_bundle_not_setup_ready")
    blockers = list(dict.fromkeys(blockers))
    if setup_ready:
        artifact_blockers = _download_artifact_type_blockers(
            root,
            download,
            ("windows_nsis_setup", "windows_msi", *REQUIRED_LINUX_PACKAGE_TYPES),
        )
        package_blockers.extend(artifact_blockers)
    package_blockers = list(dict.fromkeys(package_blockers))
    if setup_ready and not package_blockers:
        return _gate(
            "installer",
            "Installer/package artifact matrix",
            "passed",
            evidence,
            "",
            "Keep the cross-platform download bundle current with the final release commit.",
            [
                r"powershell -ExecutionPolicy Bypass -File scripts\release\build_release_package.ps1 -SkipDependencyRestore -SkipSbom -SkipSidecar -CargoTargetDir .tmp\determinex-cargo-target -PackageDownloadBundle -TauriBundleTarget all -DownloadBundleOutputDir .tmp\determinex-download-bundles",
                r".venv\Scripts\python.exe scripts\release\determinex_release_gates.py --output assurance\evidence\determinex_release_gate_status\release_gates_20260707.json",
            ],
        )
    return _gate(
        "installer",
        "Installer/package artifact matrix",
        "partial",
        evidence,
        "; ".join(package_blockers or blockers)
        or "Installer packet exists but final package artifact matrix is incomplete.",
        "Build the full package matrix: Windows NSIS, Windows MSI, and Linux package artifact(s), then refresh the download bundle.",
        [
            r"powershell -ExecutionPolicy Bypass -File scripts\release\build_release_package.ps1 -SkipDependencyRestore -SkipSbom -SkipSidecar -CargoTargetDir .tmp\determinex-cargo-target -PackageDownloadBundle -TauriBundleTarget all -DownloadBundleOutputDir .tmp\determinex-download-bundles",
            r"cd frontend; npm run tauri -- build --bundles appimage,deb,rpm",
            r".venv\Scripts\python.exe scripts\release\determinex_release_gates.py --output assurance\evidence\determinex_release_gate_status\release_gates_20260707.json",
        ],
    )


def _windows_trust_errors(data: Any) -> list[str]:
    errors = _packet_field_errors(
        data,
        schema_version=WINDOWS_TRUST_SCHEMA_VERSION,
        expected_true=(
            "code_signing_verified",
            "timestamp_verified",
            "smartscreen_verification_performed",
        ),
    )
    if not isinstance(data, dict):
        return errors
    if data.get("artifact_authenticode_status") != "Valid":
        errors.append("artifact_authenticode_status must be Valid")
    if str(data.get("smartscreen_result") or "").lower() not in {"pass", "no_warning", "trusted"}:
        errors.append("smartscreen_result must be pass, no_warning, or trusted")
    if not str(data.get("certificate_subject") or "").strip():
        errors.append("certificate_subject must be recorded")
    return errors


def _windows_trust_gate(root: Path) -> ReleaseGate:
    path, data, errors = _latest_packet(
        root,
        "assurance/evidence/windows_trust",
        "windows_trust_*.json",
        _windows_trust_errors,
    )
    evidence = [_rel(root, path)] if path else []
    if data is not None:
        return _gate(
            "windows_trust",
            "Windows signing and SmartScreen trust",
            "passed",
            evidence,
            "",
            "Keep Authenticode and SmartScreen evidence current for the final installer artifacts.",
            [
                r"powershell Get-AuthenticodeSignature <installer.exe>",
                r".venv\Scripts\python.exe scripts\release\determinex_release_gates.py --output assurance\evidence\determinex_release_gate_status\release_gates_20260707.json",
            ],
        )
    return _gate(
        "windows_trust",
        "Windows signing and SmartScreen trust",
        "deferred",
        evidence,
        (
            "Invalid Windows signing and SmartScreen trust packet: " + "; ".join(errors)
            if path
            else "No Windows signing and SmartScreen trust packet was found."
        ),
        "Sign the Windows installer, verify Authenticode and timestamp status, then run SmartScreen trust verification on the final artifact.",
        [
            r"powershell Get-AuthenticodeSignature <installer.exe>",
            r"powershell -ExecutionPolicy Bypass -File scripts\release\build_release_package.ps1 -PackageDownloadBundle",
            r".venv\Scripts\python.exe scripts\release\determinex_release_gates.py --output assurance\evidence\determinex_release_gate_status\release_gates_20260707.json",
        ],
    )


def _legal_public_distribution_errors(data: Any) -> list[str]:
    return _packet_field_errors(
        data,
        schema_version=LEGAL_PUBLIC_DISTRIBUTION_SCHEMA_VERSION,
        expected_true=(
            "legal_review_completed",
            "license_inventory_reviewed",
            "model_notice_reviewed",
            "public_repo_secret_scan_passed",
            "public_repo_scrub_completed",
            "third_party_notices_present",
        ),
    )


def _agpl_source_license_evidence(root: Path) -> tuple[list[str], list[str]]:
    required = [
        root / "LICENSE",
        root / "pyproject.toml",
        root / "frontend/package.json",
        root / "frontend/src-tauri/Cargo.toml",
        root / "frontend/vscode-extension/package.json",
    ]
    evidence: list[str] = []
    errors: list[str] = []
    for path in required:
        if not path.is_file():
            errors.append(f"{_rel(root, path)} missing")
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        evidence.append(_rel(root, path))
        if path.name == "LICENSE":
            if "GNU AFFERO GENERAL PUBLIC LICENSE" not in text or "Version 3" not in text:
                errors.append("LICENSE is not AGPLv3 text")
        elif "AGPL-3.0" not in text:
            errors.append(f"{_rel(root, path)} does not declare AGPL-3.0")
    return evidence, errors


def _legal_public_distribution_gate(root: Path) -> ReleaseGate:
    path, data, errors = _latest_packet(
        root,
        "assurance/evidence/public_distribution",
        "legal_public_distribution_*.json",
        _legal_public_distribution_errors,
    )
    evidence = [_rel(root, path)] if path else []

    # Freshness binding, added 2026-07-30 -- the same one _first_e2e_gate got, for the same reason.
    # This gate passed on a hand-written packet dated 2026-07-12: 17 days stale, predating the
    # internal rename, the in-app updater, and all of the MSI work. Nothing tied it to the artifacts
    # being shipped.
    #
    # It matters more here than staleness usually would, because of what the packet asserts. Its
    # proof for `public_repo_secret_scan_passed: true` is a pasted transcript tail ending
    # "OK: no secret in tracked files or pushed history." That line was printed UNCONDITIONALLY by
    # a scanner which -- as of 2026-07-30 -- is now known never to have scanned anything at all:
    # its PCRE patterns were passed to `git grep -lE`, which rejected them, and the error was
    # swallowed into a clean verdict. The packet's own `pushed_secret_scan` field is false.
    #
    # So the old packet does not merely predate the artifacts; it attests a scan that did not
    # happen. Forcing regeneration is what gets the now-working scanner's real result on the record.
    if data is not None:
        manifest = _newest_download_manifest(root)
        manifest_built = _release_artifacts_built_at(root, manifest)
        packet_stamp = str(data.get("generated_at_utc") or "")
        if manifest_built and packet_stamp and packet_stamp < manifest_built:
            return _gate(
                "legal_public_distribution",
                "Legal/IP public distribution packet",
                "blocked",
                evidence,
                (
                    f"Legal/IP packet ({packet_stamp}) predates the release artifacts "
                    f"({manifest_built}); its secret-scan attestation was produced by a scanner "
                    f"that has since been found never to have scanned."
                ),
                "Re-run the secret scan with --pushed and regenerate the public distribution packet.",
                [
                    r".venv\Scripts\python.exe scripts\security\secret_scan.py --pushed",
                    r".venv\Scripts\python.exe scripts\release\public_distribution_packet.py",
                ],
            )
    if data is not None:
        return _gate(
            "legal_public_distribution",
            "Legal/IP public distribution packet",
            "passed",
            evidence,
            "",
            "Keep legal, license, model notice, and public-repo scrub packets current with release artifacts.",
            [
                r".venv\Scripts\python.exe scripts\release\determinex_release_gates.py --output assurance\evidence\determinex_release_gate_status\release_gates_20260707.json",
            ],
        )
    agpl_evidence, agpl_errors = _agpl_source_license_evidence(root)
    if not agpl_errors:
        return _gate(
            "legal_public_distribution",
            "Legal/IP public distribution packet",
            "partial",
            evidence + agpl_evidence,
            # Report the packet's actual failing fields. This branch used to print a fixed sentence
            # naming four missing items -- secret scan, repo scrub, model notices, third-party
            # notices -- while the packet on disk had three of those recorded true and was failing
            # on two entirely different fields (`legal_review_completed`,
            # `public_repo_scrub_completed`). The errors were computed and thrown away, so the
            # operator was told to redo finished work and never told what was actually blocking.
            (
                "AGPLv3 source license evidence is present, but the legal public distribution "
                "packet is incomplete: " + "; ".join(errors)
                if errors
                else "AGPLv3 source license evidence is present, but no legal public distribution "
                "packet has been recorded."
            ),
            "Complete the public distribution packet after source license, notices, model inventory, secret scan, and repo scrub review.",
            [
                r".venv\Scripts\python.exe scripts\release\determinex_release_gates.py --output assurance\evidence\determinex_release_gate_status\release_gates_20260707.json",
                r"powershell # write assurance\evidence\public_distribution\legal_public_distribution_YYYYMMDD.json after review",
            ],
        )
    return _gate(
        "legal_public_distribution",
        "Legal/IP public distribution packet",
        "blocked",
        evidence + agpl_evidence,
        (
            "Invalid legal/IP public distribution packet: " + "; ".join(errors)
            if path
            else "No legal/IP public distribution packet was found; AGPL source license evidence incomplete: "
            + "; ".join(agpl_errors)
        ),
        "Complete legal/IP review, license inventory, model notices, secret scan, and public repo scrub before public distribution.",
        [
            r".venv\Scripts\python.exe scripts\release\determinex_release_gates.py --output assurance\evidence\determinex_release_gate_status\release_gates_20260707.json",
            r"powershell # write assurance\evidence\public_distribution\legal_public_distribution_YYYYMMDD.json after review",
        ],
    )


def _windows_msi_errors(data: Any) -> list[str]:
    # `msi_installer_smoke_performed` is deliberately NOT required here (2026-07-30). The packet
    # writer is package_download_bundle.py, which discovers, copies and checksums artifacts -- it
    # never installs anything, and its own msi_smoke_scope field said exactly that. It used to
    # write all four of these as unconditional `True` literals whenever a file named *.msi existed,
    # so this gate was satisfied by a file's presence.
    #
    # The three below are now derived from the artifact (WiX authoring present in the MSI, an MSI
    # exists, every recorded sha256 is a real 64-hex digest). The install smoke is attested by the
    # thing that actually installs: the clean-host transcript, which the clean_host gate validates
    # independently and which cannot pass without a real install/launch/uninstall cycle. Requiring
    # it from this packet only ever produced a literal.
    return _packet_field_errors(
        data,
        schema_version=WINDOWS_MSI_SCHEMA_VERSION,
        expected_true=(
            "wix_toolset_used",
            "msi_built",
            "msi_sha256_verified",
        ),
    )


def _windows_msi_gate(root: Path) -> ReleaseGate:
    path, data, errors = _latest_packet(
        root,
        "assurance/evidence/windows_msi",
        "windows_msi_*.json",
        _windows_msi_errors,
    )
    evidence = [_rel(root, path)] if path else []
    if data is not None:
        return _gate(
            "windows_msi",
            "Windows MSI/WiX distribution",
            "passed",
            evidence,
            "",
            "Keep MSI/WiX evidence current with the final release bundle.",
            [
                r"powershell -ExecutionPolicy Bypass -File scripts\release\build_release_package.ps1 -TauriBundleTarget msi",
                r".venv\Scripts\python.exe scripts\release\determinex_release_gates.py --output assurance\evidence\determinex_release_gate_status\release_gates_20260707.json",
            ],
        )
    return _gate(
        "windows_msi",
        "Windows MSI/WiX distribution",
        "blocked",
        evidence,
        (
            "Invalid Windows MSI/WiX evidence packet: " + "; ".join(errors)
            if path
            else "No Windows MSI/WiX evidence packet was found."
        ),
        "Build an MSI with WiX, verify the MSI hash, run an installer smoke, and record the MSI evidence packet.",
        [
            r"powershell -ExecutionPolicy Bypass -File scripts\release\build_release_package.ps1 -TauriBundleTarget msi",
            r".venv\Scripts\python.exe scripts\release\determinex_release_gates.py --output assurance\evidence\determinex_release_gate_status\release_gates_20260707.json",
        ],
    )


def _linux_packages_gate(root: Path) -> ReleaseGate:
    download_manifest = newest_download_manifest_path(root)
    download = _read_json(download_manifest) if download_manifest is not None else None
    evidence = [_rel(root, download_manifest)] if download_manifest else []
    artifact_types = _valid_download_artifact_types(root, download)
    missing_linux = [
        package_type
        for package_type in REQUIRED_LINUX_PACKAGE_TYPES
        if package_type not in artifact_types
    ]
    linux_blockers = _download_artifact_type_blockers(root, download, REQUIRED_LINUX_PACKAGE_TYPES)

    if not missing_linux and not linux_blockers:
        return _gate(
            "linux_packages",
            "Linux package distribution",
            "passed",
            evidence,
            "",
            "Keep Linux package artifacts current with the final release commit.",
            [
                r"cd frontend; npm run tauri -- build --bundles appimage,deb,rpm",
                r".venv\Scripts\python.exe scripts\release\determinex_release_gates.py --output assurance\evidence\determinex_release_gate_status\release_gates_20260707.json",
            ],
        )
    return _gate(
        "linux_packages",
        "Linux package distribution",
        "blocked",
        evidence,
        (
            "Missing or invalid Linux package artifacts: " + ", ".join(linux_blockers)
            if linux_blockers
            else "No Linux package artifact was found in the latest download bundle manifest."
            if len(missing_linux) == len(REQUIRED_LINUX_PACKAGE_TYPES)
            else "Missing or invalid Linux package artifacts: " + ", ".join(missing_linux)
        ),
        "Build Linux AppImage, deb, and rpm package artifacts on a Linux host and refresh the download bundle manifest.",
        [
            r"cd frontend; npm run tauri -- build --bundles appimage,deb,rpm",
            r".venv\Scripts\python.exe scripts\release\package_download_bundle.py --installer-dir frontend/src-tauri/target/release/bundle --output-dir .tmp/determinex-download-bundles --evidence-dir assurance/evidence/determinex_download_bundle_20260707",
            r".venv\Scripts\python.exe scripts\release\determinex_release_gates.py --output assurance\evidence\determinex_release_gate_status\release_gates_20260707.json",
        ],
    )


def _extension_compat_errors(data: Any) -> list[str]:
    return _packet_field_errors(
        data,
        schema_version=EXTENSION_COMPAT_SCHEMA_VERSION,
        expected_true=(
            "extension_api_contract_defined",
            "vsix_import_smoke_passed",
            "open_vsx_metadata_parsed",
            "sandbox_permissions_enforced",
            "activation_event_smoke_passed",
        ),
    )


def _extension_gate(root: Path) -> ReleaseGate:
    bridge = root / "frontend/vscode-extension"
    contract = root / "docs/release/DETERMINEX_EXTENSION_COMPATIBILITY_CONTRACT.md"
    packet, data, errors = _latest_packet(
        root,
        "assurance/evidence/extension_compat",
        "extension_compat_*.json",
        _extension_compat_errors,
    )
    evidence = [_rel(root, p) for p in (bridge, contract, packet) if p is not None and p.exists()]
    if data is not None:
        return _gate(
            "extension_compat",
            "VS Code/Open VSX compatibility",
            "passed",
            evidence,
            "",
            "Keep extension import, metadata, activation, and sandbox smokes current.",
            [
                r".venv\Scripts\python.exe scripts\release\determinex_release_gates.py --output assurance\evidence\determinex_release_gate_status\release_gates_20260707.json",
            ],
        )
    if contract.is_file():
        return _gate(
            "extension_compat",
            "VS Code/Open VSX compatibility",
            "deferred",
            evidence,
            (
                "Invalid extension runtime compatibility packet: " + "; ".join(errors)
                if packet
                else "Extension compatibility contract exists, but runtime compatibility packet has not passed."
            ),
            "Run VSIX import, Open VSX metadata, activation-event, and sandbox permission smokes against the contract.",
            [
                r".venv\Scripts\python.exe scripts\release\determinex_release_gates.py --output assurance\evidence\determinex_release_gate_status\release_gates_20260707.json",
            ],
        )
    return _gate(
        "extension_compat",
        "VS Code/Open VSX compatibility",
        "deferred",
        evidence,
        "Standalone IDE does not yet import or run VS Code/Open VSX extensions.",
        "Define and implement extension compatibility/import contract.",
        [
            r".venv\Scripts\python.exe scripts\release\determinex_release_gates.py --output assurance\evidence\determinex_release_gate_status\release_gates_20260707.json",
        ],
    )


def _internal_rename_gate(root: Path) -> ReleaseGate:
    project = root / "PROJECT.md"
    migration = root / "docs/release/DETERMINEX_INTERNAL_RENAME_MIGRATION.md"
    evidence = [_rel(root, p) for p in (project, migration) if p.is_file()]
    text = project.read_text(encoding="utf-8", errors="replace") if project.is_file() else ""
    if "Literal `determinex_*`/`DETERMINEX_*`" in text:
        return _gate(
            "internal_rename",
            "Internal Determinex rename",
            "deferred",
            evidence,
            "Legacy determinex_* and DETERMINEX_* implementation identifiers remain by project contract.",
            "Execute the internal rename migration with compatibility aliases and migration tests.",
            [
                'rg "determinex_|DETERMINEX_"',
                r".venv\Scripts\python.exe scripts\release\determinex_release_gates.py --output assurance\evidence\determinex_release_gate_status\release_gates_20260707.json",
            ],
        )
    return _gate(
        "internal_rename",
        "Internal Determinex rename",
        "passed",
        evidence,
        "",
        "Keep compatibility aliases for older scripts and evidence.",
        [
            r".venv\Scripts\python.exe scripts\release\determinex_release_gates.py --output assurance\evidence\determinex_release_gate_status\release_gates_20260707.json",
        ],
    )


def _programbench_rows(root: Path) -> list[dict[str, Any]]:
    path = root / "corpus/programbench/eval_index.json"
    data = _read_json(path)
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        rows = list(data.values())
    else:
        return []
    return [row for row in rows if isinstance(row, dict)]


def _programbench_200_gate(root: Path) -> ReleaseGate:
    path = root / "corpus/programbench/eval_index.json"
    evidence = [_rel(root, path)] if path.is_file() else []
    rows = _programbench_rows(root)
    if not rows:
        return _gate(
            "programbench_200",
            "ProgramBench 200/200 strict locks",
            "deferred",
            evidence,
            "No readable ProgramBench eval_index.json was found.",
            "Deferred for this open-source launch profile; restore ProgramBench evidence before making benchmark claims.",
            [
                r".venv\Scripts\python.exe scripts\pb_doc_count_check.py --verbose",
                r".venv\Scripts\python.exe scripts\pb_board_guard.py --guard",
                r".venv\Scripts\python.exe scripts\pb_override_scan.py --guard",
            ],
        )
    canonical = [row for row in rows if not row.get("alias_of") and not row.get("canonical_slug")]
    strict_count = sum(1 for row in canonical if row.get("official_full_suite_resolved") is True)
    status_counts = Counter(str(row.get("status")) for row in canonical)
    status_summary = ", ".join(
        f"{status}={count}" for status, count in status_counts.most_common(6)
    )
    if len(canonical) == PROGRAMBENCH_DENOMINATOR and strict_count == PROGRAMBENCH_DENOMINATOR:
        return _gate(
            "programbench_200",
            "ProgramBench 200/200 strict locks",
            "passed",
            evidence,
            "",
            "Keep ProgramBench guards green and archive only official full-suite locks.",
            [
                r".venv\Scripts\python.exe scripts\pb_doc_count_check.py --verbose",
                r".venv\Scripts\python.exe scripts\pb_board_guard.py --guard",
                r".venv\Scripts\python.exe scripts\pb_override_scan.py --guard",
            ],
        )
    denominator_note = (
        ""
        if len(canonical) == PROGRAMBENCH_DENOMINATOR
        else f"; canonical non-alias rows={len(canonical)}, expected={PROGRAMBENCH_DENOMINATOR}"
    )
    return _gate(
        "programbench_200",
        "ProgramBench 200/200 strict locks",
        "deferred",
        evidence,
        (
            f"ProgramBench strict official locks are {strict_count}/{PROGRAMBENCH_DENOMINATOR}"
            f"{denominator_note}; current non-authorizing status mix: {status_summary or 'none'}."
        ),
        "Deferred for this open-source launch profile; continue the official lock campaign before making ProgramBench claims.",
        [
            r".venv\Scripts\python.exe scripts\pb_doc_count_check.py --verbose",
            r".venv\Scripts\python.exe scripts\pb_board_guard.py --guard",
            r".venv\Scripts\python.exe scripts\pb_override_scan.py --guard",
        ],
    )


def _swebench_packet_errors(data: Any) -> list[str]:
    if not isinstance(data, dict):
        return ["packet JSON must be an object"]
    errors: list[str] = []
    if data.get("schema_version") != SWEBENCH_FRESH_PUBLICATION_SCHEMA_VERSION:
        errors.append(f"schema_version must be {SWEBENCH_FRESH_PUBLICATION_SCHEMA_VERSION}")
    if data.get("benchmark") != "SWE-bench_Lite":
        errors.append("benchmark must be SWE-bench_Lite")
    expected_true = ("fresh_rerun_completed", "official_harness_used", "publication_claim_ready")
    for field_name in expected_true:
        if data.get(field_name) is not True:
            errors.append(f"{field_name} must be true")
    if data.get("authority_granted") is not False:
        errors.append("authority_granted must be false")
    modes = data.get("privacy_modes_completed")
    if not isinstance(modes, list) or not SWEBENCH_REQUIRED_PRIVACY_MODES.issubset(
        {str(m) for m in modes}
    ):
        errors.append(
            "privacy_modes_completed must include B-Uncloaked, RegionControl, and Cloaked"
        )
    reports = data.get("reports")
    if not isinstance(reports, list) or not reports:
        errors.append("reports must list the official rerun report paths")
    return errors


def _swebench_fresh_gate(root: Path) -> ReleaseGate:
    candidates = sorted(
        (root / "assurance/evidence/swebench_fresh_publication").glob(
            "swebench_fresh_publication_*.json"
        ),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    first_invalid: tuple[Path, list[str]] | None = None
    for candidate in candidates:
        data = _read_json(candidate)
        errors = _swebench_packet_errors(data)
        if not errors:
            return _gate(
                "swebench_fresh",
                "Fresh SWE-bench publication reruns",
                "passed",
                [_rel(root, candidate)],
                "",
                "Keep the official SWE-bench rerun packet current with the release claim snapshot.",
                [
                    "python -m swebench.harness.run_evaluation --dataset_name princeton-nlp/SWE-bench_Lite --split test",
                    r".venv\Scripts\python.exe scripts\release\determinex_release_gates.py --output assurance\evidence\determinex_release_gate_status\release_gates_20260707.json",
                ],
            )
        if first_invalid is None:
            first_invalid = (candidate, errors)
    evidence = [_rel(root, first_invalid[0])] if first_invalid else []
    blocker = (
        "Invalid fresh SWE-bench publication packet: " + "; ".join(first_invalid[1])
        if first_invalid
        else "No fresh official SWE-bench privacy-mode rerun packet was found."
    )
    return _gate(
        "swebench_fresh",
        "Fresh SWE-bench publication reruns",
        "deferred",
        evidence,
        blocker,
        "Deferred for this open-source launch profile; run fresh official SWE-bench Lite reruns before making SWE-bench claims.",
        [
            "python -m swebench.harness.run_evaluation --dataset_name princeton-nlp/SWE-bench_Lite --split test",
            r".venv\Scripts\python.exe scripts\verified_task\swebench_result_ingest.py --report <report.json> --predictions <predictions.jsonl>",
            r".venv\Scripts\python.exe scripts\release\determinex_release_gates.py --output assurance\evidence\determinex_release_gate_status\release_gates_20260707.json",
        ],
    )


def collect(root: Path | str | None = None) -> ReleaseGateReport:
    repo_root = Path(root) if root is not None else Path(__file__).resolve().parents[2]
    gates = (
        _sbom_gate(repo_root),
        _installer_gate(repo_root),
        _windows_trust_gate(repo_root),
        _legal_public_distribution_gate(repo_root),
        _windows_msi_gate(repo_root),
        _linux_packages_gate(repo_root),
        _clean_host_gate(repo_root),
        _first_e2e_gate(repo_root),
        _programbench_200_gate(repo_root),
        _swebench_fresh_gate(repo_root),
        _extension_gate(repo_root),
        _internal_rename_gate(repo_root),
    )
    release_ready = all(g.status in {"passed", "deferred"} for g in gates)
    return ReleaseGateReport(
        schema_version=SCHEMA_VERSION,
        generated_at_utc=datetime.now(UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        product_name="Determinex",
        release_ready=release_ready,
        authority_granted=False,
        gates=gates,
        notes=(
            "This report is a local evidence classifier, not a release approval.",
            "A passed individual gate does not override claim boundaries or protected action packets.",
            "ProgramBench, SWE-bench Lite, and SWE-bench Pro are deferred proof tracks for this open-source launch profile.",
        ),
    )


def write_report(output_path: Path, root: Path | str | None = None) -> ReleaseGateReport:
    report = collect(root)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    report = collect(args.root)
    payload = json.dumps(report.to_dict(), indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
