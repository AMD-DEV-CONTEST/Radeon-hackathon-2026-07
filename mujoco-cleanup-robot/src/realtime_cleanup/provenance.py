"""Model lock verification and ROCm-only device selection."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from realtime_cleanup.telemetry import gpu_identity


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = PROJECT_ROOT / "configs" / "realtime_models.json"
DEFAULT_LOCK = PROJECT_ROOT / "configs" / "realtime_models.lock.json"
DEFAULT_TRAINED_LOCK = PROJECT_ROOT / "configs" / "realtime_trained.lock.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class ModelArtifact:
    name: str
    path: Path
    sha256: str | None
    revision: str | None
    architecture: str
    license: str

    def trace_metadata(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "architecture": self.architecture,
            "path": str(self.path),
            "sha256": self.sha256,
            "revision": self.revision,
            "license": self.license,
        }


class ModelRegistry:
    def __init__(
        self,
        manifest_path: Path = DEFAULT_MANIFEST,
        lock_path: Path = DEFAULT_LOCK,
    ) -> None:
        self.manifest_path = Path(manifest_path)
        self.lock_path = Path(lock_path)
        self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        if not self.lock_path.is_file():
            raise FileNotFoundError(
                f"model lock missing: {self.lock_path}; run scripts/download_realtime_models.py"
            )
        self.lock = json.loads(self.lock_path.read_text(encoding="utf-8"))

    def verify(self) -> list[str]:
        failures: list[str] = []
        for record in self.lock["artifacts"]:
            path = PROJECT_ROOT / record["path"]
            if not path.is_file():
                failures.append(f"missing: {record['path']}")
                continue
            digest = sha256_file(path)
            if digest != record["sha256"]:
                failures.append(f"sha256 mismatch: {record['path']}")
            if path.stat().st_size != record["bytes"]:
                failures.append(f"size mismatch: {record['path']}")
        if DEFAULT_TRAINED_LOCK.is_file():
            trained = json.loads(DEFAULT_TRAINED_LOCK.read_text(encoding="utf-8"))
            for record in trained["artifacts"].values():
                path = PROJECT_ROOT / record["path"]
                if not path.is_file():
                    failures.append(f"missing trained artifact: {record['path']}")
                    continue
                if sha256_file(path) != record["sha256"]:
                    failures.append(f"trained sha256 mismatch: {record['path']}")
        return failures

    def require_valid(self) -> None:
        failures = self.verify()
        if failures:
            raise RuntimeError("model provenance verification failed:\n" + "\n".join(failures))

    def artifact(self, name: str) -> ModelArtifact:
        specification = self.manifest["models"][name]
        locked = self.lock["models"][name]
        path = PROJECT_ROOT / locked["path"]
        return ModelArtifact(
            name=name,
            path=path,
            sha256=locked.get("sha256"),
            revision=locked.get("revision"),
            architecture=specification["architecture"],
            license=specification["license"],
        )

    def runtime_artifact(self, name: str) -> ModelArtifact:
        """Prefer a locally trained direct-control checkpoint when available."""

        base = self.artifact(name)
        if name == "perception":
            checkpoint = (
                PROJECT_ROOT
                / "outputs"
                / "realtime"
                / "yoloe_fixed_unknown"
                / "weights"
                / "best.pt"
            )
            if checkpoint.is_file():
                return ModelArtifact(
                    name=name,
                    path=checkpoint,
                    sha256=sha256_file(checkpoint),
                    revision="local-fixed-plus-unknown-finetune",
                    architecture="YOLOE-26S-Detect",
                    license=base.license,
                )
        if name == "navigation":
            checkpoint = (
                PROJECT_ROOT
                / "outputs"
                / "realtime"
                / "nomad_stretch"
                / "nomad_stretch.pth"
            )
            if checkpoint.is_file():
                return ModelArtifact(
                    name=name,
                    path=checkpoint,
                    sha256=sha256_file(checkpoint),
                    revision="local-wheel-dynamics-finetune",
                    architecture=base.architecture,
                    license=base.license,
                )
        if name == "manipulation":
            checkpoint = (
                PROJECT_ROOT
                / "outputs"
                / "realtime"
                / "smolvla_stretch"
                / "checkpoints"
                / "last"
                / "pretrained_model"
            )
            weights = checkpoint / "model.safetensors"
            if weights.is_file():
                return ModelArtifact(
                    name=name,
                    path=checkpoint,
                    sha256=sha256_file(weights),
                    revision="local-direct-actuator-finetune",
                    architecture=base.architecture,
                    license=base.license,
                )
        return base

    @staticmethod
    def require_rocm(device_index: int = 0) -> dict[str, Any]:
        return gpu_identity(device_index)
