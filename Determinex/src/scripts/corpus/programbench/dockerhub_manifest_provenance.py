#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from corpus.programbench.dockerhub_manifest_provenance_record import (
    make_dockerhub_manifest_provenance_record,
    write_dockerhub_manifest_provenance_record,
)
from corpus.programbench.infra_failure_triage import InfraFailureTriageStatus
from corpus.programbench.infra_failure_triage_record import verify_infra_failure_triage_record


class DockerHubManifestProvenanceStatus(str, Enum):
    DOCKERHUB_MANIFEST_PROVENANCE_READY = "DOCKERHUB_MANIFEST_PROVENANCE_READY"
    EXACT_REMOTE_MANIFEST_FOUND = "EXACT_REMOTE_MANIFEST_FOUND"
    OPERATOR_CLAIM_CREATED = "OPERATOR_CLAIM_CREATED"
    DOCKERHUB_MANIFEST_PROVENANCE_REJECTED = "DOCKERHUB_MANIFEST_PROVENANCE_REJECTED"
    DOCKERHUB_MANIFEST_BLOCKED_NO_TRIAGE = "DOCKERHUB_MANIFEST_BLOCKED_NO_TRIAGE"
    DOCKERHUB_MANIFEST_BLOCKED_IMAGE_MISMATCH = "DOCKERHUB_MANIFEST_BLOCKED_IMAGE_MISMATCH"
    DOCKERHUB_MANIFEST_BLOCKED_NO_DIGEST = "DOCKERHUB_MANIFEST_BLOCKED_NO_DIGEST"
    DOCKERHUB_MANIFEST_BLOCKED_FLOATING_LATEST = "DOCKERHUB_MANIFEST_BLOCKED_FLOATING_LATEST"
    DOCKERHUB_MANIFEST_BLOCKED_LAYER_PULL = "DOCKERHUB_MANIFEST_BLOCKED_LAYER_PULL"
    DOCKERHUB_MANIFEST_BLOCKED_EXECUTION = "DOCKERHUB_MANIFEST_BLOCKED_EXECUTION"
    DOCKERHUB_MANIFEST_NOT_HYDRATION_AUTHORIZED = "DOCKERHUB_MANIFEST_NOT_HYDRATION_AUTHORIZED"
    DOCKERHUB_MANIFEST_NOT_EXECUTION_AUTHORIZED = "DOCKERHUB_MANIFEST_NOT_EXECUTION_AUTHORIZED"


@dataclass(slots=True)
class DockerHubManifestProvenanceConfig:
    root: Path = Path(".")
    output_dir: Path = Path("assurance/evidence/programbench_dockerhub_manifest_provenance")
    operator_claim_dir: Path = Path("assurance/evidence/programbench_operator_artifact_admissions")


class ProgramBenchDockerHubManifestProvenance:
    def __init__(self, config: DockerHubManifestProvenanceConfig | None = None) -> None:
        self.config = config or DockerHubManifestProvenanceConfig()

    def convert(
        self, triage_record_path: Path, manifest_metadata: dict[str, Any]
    ) -> dict[str, Any]:
        triage_path = self._resolve(triage_record_path)
        if not triage_path.is_file():
            return self._blocked(
                DockerHubManifestProvenanceStatus.DOCKERHUB_MANIFEST_BLOCKED_NO_TRIAGE.value,
                triage_path,
                {},
                manifest_metadata,
                ["triage_record_missing"],
            )
        triage = _read_json(triage_path)
        if not verify_infra_failure_triage_record(triage):
            return self._blocked(
                DockerHubManifestProvenanceStatus.DOCKERHUB_MANIFEST_BLOCKED_NO_TRIAGE.value,
                triage_path,
                triage,
                manifest_metadata,
                ["triage_record_signature_invalid"],
            )
        if (
            str(triage.get("failure_type") or "")
            != InfraFailureTriageStatus.MISSING_CLEANROOM_IMAGE.value
        ):
            return self._blocked(
                DockerHubManifestProvenanceStatus.DOCKERHUB_MANIFEST_BLOCKED_NO_TRIAGE.value,
                triage_path,
                triage,
                manifest_metadata,
                ["triage_failure_type_not_missing_cleanroom_image"],
            )

        image = str(triage.get("missing_image") or "")
        parsed = _parse_image(image)
        digest = _extract_digest(manifest_metadata)
        tag = str(manifest_metadata.get("tag") or parsed["tag"])
        repository = str(manifest_metadata.get("repository") or parsed["repository"])
        registry = str(manifest_metadata.get("registry") or "docker.io")

        metadata_image = str(manifest_metadata.get("image_reference") or image)
        if metadata_image != image or repository != parsed["repository"] or tag != parsed["tag"]:
            return self._blocked(
                DockerHubManifestProvenanceStatus.DOCKERHUB_MANIFEST_BLOCKED_IMAGE_MISMATCH.value,
                triage_path,
                triage,
                manifest_metadata,
                ["manifest_metadata_does_not_match_missing_image"],
            )
        if tag.lower() == "latest":
            return self._blocked(
                DockerHubManifestProvenanceStatus.DOCKERHUB_MANIFEST_BLOCKED_FLOATING_LATEST.value,
                triage_path,
                triage,
                manifest_metadata,
                ["latest_tag_blocked"],
            )
        if not digest.startswith("sha256:") or len(digest) <= len("sha256:"):
            return self._blocked(
                DockerHubManifestProvenanceStatus.DOCKERHUB_MANIFEST_BLOCKED_NO_DIGEST.value,
                triage_path,
                triage,
                manifest_metadata,
                ["manifest_digest_required"],
            )
        if bool(manifest_metadata.get("pulled_layers")):
            return self._blocked(
                DockerHubManifestProvenanceStatus.DOCKERHUB_MANIFEST_BLOCKED_LAYER_PULL.value,
                triage_path,
                triage,
                manifest_metadata,
                ["layer_pull_not_allowed_for_provenance_lookup"],
            )
        if bool(manifest_metadata.get("executed")):
            return self._blocked(
                DockerHubManifestProvenanceStatus.DOCKERHUB_MANIFEST_BLOCKED_EXECUTION.value,
                triage_path,
                triage,
                manifest_metadata,
                ["execution_not_allowed_for_provenance_lookup"],
            )

        claim = _operator_claim(
            image=image,
            digest=digest,
            tag=tag,
            registry=registry,
            repository=repository,
            triage_path=_rel(self.config.root, triage_path),
            triage=triage,
            metadata=manifest_metadata,
        )
        claim_path = self._write_operator_claim(claim)
        record = make_dockerhub_manifest_provenance_record(
            status=DockerHubManifestProvenanceStatus.EXACT_REMOTE_MANIFEST_FOUND.value,
            triage_record=_rel(self.config.root, triage_path),
            image_reference=image,
            registry=registry,
            repository=repository,
            tag=tag,
            manifest_digest=digest,
            target=dict(triage.get("target") or {}),
            provenance_statuses=[
                DockerHubManifestProvenanceStatus.DOCKERHUB_MANIFEST_PROVENANCE_READY.value,
                DockerHubManifestProvenanceStatus.EXACT_REMOTE_MANIFEST_FOUND.value,
                DockerHubManifestProvenanceStatus.OPERATOR_CLAIM_CREATED.value,
                DockerHubManifestProvenanceStatus.DOCKERHUB_MANIFEST_NOT_HYDRATION_AUTHORIZED.value,
                DockerHubManifestProvenanceStatus.DOCKERHUB_MANIFEST_NOT_EXECUTION_AUTHORIZED.value,
            ],
            metadata=_compact_metadata(manifest_metadata),
            operator_claim_path=_rel(self.config.root, claim_path),
            reasons=[],
        )
        record_path = write_dockerhub_manifest_provenance_record(
            record, self._resolve(self.config.output_dir)
        )
        return {
            "record_path": str(record_path),
            "record": record,
            "operator_claim_path": str(claim_path),
            "operator_claim": claim,
        }

    def _blocked(
        self,
        status: str,
        triage_path: Path,
        triage: dict[str, Any],
        manifest_metadata: dict[str, Any],
        reasons: list[str],
    ) -> dict[str, Any]:
        image = str(triage.get("missing_image") or manifest_metadata.get("image_reference") or "")
        parsed = _parse_image(image) if image else {"repository": "", "tag": ""}
        record = make_dockerhub_manifest_provenance_record(
            status=status,
            triage_record=_rel(self.config.root, triage_path),
            image_reference=image,
            registry=str(manifest_metadata.get("registry") or "docker.io"),
            repository=str(manifest_metadata.get("repository") or parsed["repository"]),
            tag=str(manifest_metadata.get("tag") or parsed["tag"]),
            manifest_digest=_extract_digest(manifest_metadata),
            target=dict(triage.get("target") or {}),
            provenance_statuses=[
                DockerHubManifestProvenanceStatus.DOCKERHUB_MANIFEST_PROVENANCE_REJECTED.value,
                status,
                DockerHubManifestProvenanceStatus.DOCKERHUB_MANIFEST_NOT_HYDRATION_AUTHORIZED.value,
                DockerHubManifestProvenanceStatus.DOCKERHUB_MANIFEST_NOT_EXECUTION_AUTHORIZED.value,
            ],
            metadata=_compact_metadata(manifest_metadata),
            reasons=reasons,
        )
        record_path = write_dockerhub_manifest_provenance_record(
            record, self._resolve(self.config.output_dir)
        )
        return {"record_path": str(record_path), "record": record}

    def _write_operator_claim(self, claim: dict[str, Any]) -> Path:
        out = self._resolve(self.config.operator_claim_dir)
        out.mkdir(parents=True, exist_ok=True)
        path = out / "doxygen_dockerhub_operator_claim_20260527.json"
        path.write_text(json.dumps(claim, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return path

    def _resolve(self, path: Path) -> Path:
        return path if path.is_absolute() else self.config.root / path


def _operator_claim(
    *,
    image: str,
    digest: str,
    tag: str,
    registry: str,
    repository: str,
    triage_path: str,
    triage: dict[str, Any],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    target = triage.get("target") if isinstance(triage.get("target"), dict) else {}
    rerun_scope = (
        triage.get("evidence", {}).get("rerun_scope")
        if isinstance(triage.get("evidence"), dict)
        else {}
    )
    intended_scope = {
        "tool": target.get("tool"),
        "candidate_id": target.get("candidate_id"),
    }
    if isinstance(rerun_scope, dict) and rerun_scope.get("max_attempts") is not None:
        intended_scope["max_attempts"] = rerun_scope.get("max_attempts")
    last_pushed = str(metadata.get("last_pushed") or metadata.get("last_updated") or "")
    updater = str(metadata.get("last_updater_username") or "")
    return {
        "admission_reason": "Exact Docker Hub manifest metadata was found for the ProgramBench cleanroom image; admit as hydration candidate only, pending separate quarantine fetch, digest verification, scan, and policy gate.",
        "created_at_or_published_at": str(metadata.get("last_updated") or last_pushed or ""),
        "digest": digest,
        "image_reference": image,
        "intended_scope": intended_scope,
        "license_provenance_notes": (
            f"Docker Hub exact tag metadata and OCI manifest digest found for {registry}/{repository}:{tag}. "
            f"Digest {digest}; last_pushed {last_pushed or 'unknown'}; "
            f"last_updater_username {updater or 'unknown'}. This admits a pinned source candidate only; "
            "trust, scan, cache, and execution remain separate gates."
        ),
        "operator_id": "codex_registry_metadata_lookup",
        "related_triage_record": triage_path,
        "requested_use": "hydration_candidate",
        "source_type": "docker_hub_exact_reference",
        "source_url_or_registry": f"{registry}/{repository}@{digest}",
        "tag": tag,
        "trust_level": "public_untrusted",
    }


def _compact_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    allowed = (
        "image_reference",
        "registry",
        "repository",
        "tag",
        "manifest_digest",
        "descriptor_digest",
        "media_type",
        "platform",
        "config_digest",
        "last_updated",
        "last_pushed",
        "last_updater_username",
        "full_size",
        "pulled_layers",
        "executed",
    )
    return {key: metadata.get(key) for key in allowed if key in metadata}


def _extract_digest(metadata: dict[str, Any]) -> str:
    return str(
        metadata.get("manifest_digest")
        or metadata.get("descriptor_digest")
        or metadata.get("digest")
        or ""
    )


def _parse_image(image: str) -> dict[str, str]:
    if ":" not in image:
        return {"repository": image, "tag": ""}
    repository, tag = image.rsplit(":", 1)
    return {"repository": repository, "tag": tag}


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    return data if isinstance(data, dict) else {}


def _rel(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert exact Docker Hub manifest metadata into signed ProgramBench provenance."
    )
    parser.add_argument("triage_record", type=Path)
    parser.add_argument("manifest_metadata", type=Path)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("assurance/evidence/programbench_dockerhub_manifest_provenance"),
    )
    parser.add_argument(
        "--operator-claim-dir",
        type=Path,
        default=Path("assurance/evidence/programbench_operator_artifact_admissions"),
    )
    args = parser.parse_args()
    metadata = _read_json(args.manifest_metadata)
    result = ProgramBenchDockerHubManifestProvenance(
        DockerHubManifestProvenanceConfig(
            root=args.root,
            output_dir=args.output_dir,
            operator_claim_dir=args.operator_claim_dir,
        )
    ).convert(args.triage_record, metadata)
    print(json.dumps(result["record"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
