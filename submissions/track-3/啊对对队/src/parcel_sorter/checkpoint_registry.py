"""Fail-closed resolution of the promoted mobile SmolVLA checkpoint."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
import hashlib
import json
from pathlib import Path
from typing import Any


ACTIVE_CHECKPOINT_PROTOCOLS = {
    "pash-active-mobile-checkpoint-v1",
    "pi05-active-mobile-checkpoint-v1",
}


@dataclass(frozen=True)
class ActiveCheckpoint:
    checkpoint: Path
    artifact: Path
    artifact_sha256: str
    promotion_evidence: Path
    promotion_evidence_sha256: str
    config: Path

    def to_dict(self) -> dict[str, Any]:
        return {key: str(value) if isinstance(value, Path) else value for key, value in asdict(self).items()}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_active_checkpoint(
    config_path: str | Path,
    *,
    project_root: str | Path | None = None,
) -> ActiveCheckpoint:
    """Resolve and verify a promoted checkpoint without mutating any artifact."""

    config = Path(config_path).resolve()
    payload = json.loads(config.read_text(encoding="utf-8"))
    if payload.get("protocol") not in ACTIVE_CHECKPOINT_PROTOCOLS:
        raise ValueError("unsupported active-checkpoint protocol")
    if payload.get("status") != "promoted":
        raise ValueError("active checkpoint must have promoted status")
    root = Path(project_root).resolve() if project_root is not None else config.parent.parent
    checkpoint = _project_path(root, payload.get("checkpoint_relative_path"), "checkpoint")
    artifact = _project_path(
        root,
        Path(payload.get("checkpoint_relative_path", "")) / str(payload.get("artifact", "")),
        "checkpoint artifact",
    )
    evidence = _project_path(
        root, payload.get("promotion_evidence_relative_path"), "promotion evidence"
    )
    expected_artifact_sha = _sha(payload.get("artifact_sha256"), "artifact_sha256")
    expected_evidence_sha = _sha(
        payload.get("promotion_evidence_sha256"), "promotion_evidence_sha256"
    )
    if not checkpoint.is_dir() or not artifact.is_file():
        raise FileNotFoundError(f"active checkpoint artifact is missing: {artifact}")
    if not evidence.is_file():
        raise FileNotFoundError(f"promotion evidence is missing: {evidence}")
    if sha256_file(artifact) != expected_artifact_sha:
        raise ValueError("active checkpoint artifact hash mismatch")
    if sha256_file(evidence) != expected_evidence_sha:
        raise ValueError("promotion evidence hash mismatch")
    gate = json.loads(evidence.read_text(encoding="utf-8"))
    if not _gate_promoted(gate):
        raise ValueError("promotion evidence does not authorize the checkpoint")
    paired_sha = ((gate.get("pairing") or {}).get("candidate_checkpoint_sha256"))
    if paired_sha != expected_artifact_sha:
        raise ValueError("promotion evidence references a different checkpoint hash")
    return ActiveCheckpoint(
        checkpoint=checkpoint,
        artifact=artifact,
        artifact_sha256=expected_artifact_sha,
        promotion_evidence=evidence,
        promotion_evidence_sha256=expected_evidence_sha,
        config=config,
    )


def activate_promoted_checkpoint(
    config_path: str | Path,
    *,
    project_root: str | Path,
    checkpoint: str | Path,
    promotion_evidence: str | Path,
    artifact_name: str | None = None,
    promoted_on: str | None = None,
    protocol: str = "pash-active-mobile-checkpoint-v1",
) -> ActiveCheckpoint:
    """Atomically activate a checkpoint already authorized by a frozen gate."""

    root = Path(project_root).resolve()
    config = Path(config_path).resolve()
    checkpoint_path = Path(checkpoint).resolve()
    evidence_path = Path(promotion_evidence).resolve()
    if protocol not in ACTIVE_CHECKPOINT_PROTOCOLS:
        raise ValueError("unsupported active-checkpoint protocol")
    resolved_artifact_name = artifact_name or _detect_artifact_name(checkpoint_path)
    artifact = (checkpoint_path / resolved_artifact_name).resolve()
    for path, name in (
        (config, "active-checkpoint config"),
        (checkpoint_path, "checkpoint"),
        (artifact, "checkpoint artifact"),
        (evidence_path, "promotion evidence"),
    ):
        _relative_to_root(root, path, name)
    if not checkpoint_path.is_dir() or not artifact.is_file():
        raise FileNotFoundError(f"candidate checkpoint artifact is missing: {artifact}")
    if not evidence_path.is_file():
        raise FileNotFoundError(f"promotion evidence is missing: {evidence_path}")

    artifact_sha = sha256_file(artifact)
    evidence_sha = sha256_file(evidence_path)
    gate = json.loads(evidence_path.read_text(encoding="utf-8"))
    if not _gate_promoted(gate):
        raise ValueError("promotion evidence rejected the candidate checkpoint")
    paired_sha = (gate.get("pairing") or {}).get("candidate_checkpoint_sha256")
    if paired_sha != artifact_sha:
        raise ValueError("promotion evidence references a different checkpoint hash")

    payload = {
        "schema_version": 1,
        "protocol": protocol,
        "status": "promoted",
        "checkpoint_relative_path": _relative_to_root(
            root, checkpoint_path, "checkpoint"
        ).as_posix(),
        "artifact": resolved_artifact_name,
        "artifact_sha256": artifact_sha,
        "promotion_evidence_relative_path": _relative_to_root(
            root, evidence_path, "promotion evidence"
        ).as_posix(),
        "promotion_evidence_sha256": evidence_sha,
        "promoted_on": promoted_on or date.today().isoformat(),
        "claim_boundary": (
            "the registry changes only between episodes after a paired frozen gate; "
            "an active rollout never mutates model weights"
        ),
    }
    config.parent.mkdir(parents=True, exist_ok=True)
    temporary = config.parent / f".{config.name}.tmp"
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temporary.replace(config)
    return load_active_checkpoint(config, project_root=root)


def _project_path(root: Path, value: Any, name: str) -> Path:
    if not isinstance(value, (str, Path)) or not str(value):
        raise ValueError(f"{name} path must be non-empty")
    candidate = (root / Path(value)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{name} path escapes the project root") from exc
    return candidate


def _relative_to_root(root: Path, path: Path, name: str) -> Path:
    try:
        return path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{name} path escapes the project root") from exc


def _sha(value: Any, name: str) -> str:
    text = str(value or "")
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return text


def _detect_artifact_name(checkpoint: Path) -> str:
    for name in ("adapter_model.safetensors", "model.safetensors"):
        if (checkpoint / name).is_file():
            return name
    raise FileNotFoundError(
        "checkpoint has neither adapter_model.safetensors nor model.safetensors"
    )


def _gate_promoted(gate: dict[str, Any]) -> bool:
    return gate.get("promoted") is True or gate.get("promotion_gate_passed") is True
