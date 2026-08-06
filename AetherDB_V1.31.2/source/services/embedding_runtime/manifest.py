import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Tuple
from app.config import get_resource_path
from services.model_integrity import ArtifactChangedDuringHashError, sha256_file


DEFAULT_MANIFEST_PATH = get_resource_path("resources", "model_manifests", "bge-m3.json")
EXPECTED_PROVIDER_ORDER = (
    "MIGraphXExecutionProvider",
    "CUDAExecutionProvider",
    "CPUExecutionProvider",
)
VERIFICATION_RECORD_NAME = ".aetherdb-model-verified.json"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class ModelArtifact:
    path: str
    size: int
    sha256: str


@dataclass(frozen=True)
class BgeM3Manifest:
    model_id: str
    revision: str
    license: str
    dimensions: int
    max_tokens: int
    output_modes: Tuple[str, ...]
    normalization: str
    provider_preference: Tuple[str, ...]
    artifacts: Tuple[ModelArtifact, ...]

    def missing_artifacts(self, model_root: Path) -> Tuple[str, ...]:
        return tuple(
            artifact.path
            for artifact in self.artifacts
            if not (model_root / Path(artifact.path)).is_file()
        )

    def verify_artifacts(self, model_root: Path) -> Tuple[str, ...]:
        issues = []
        for artifact in self.artifacts:
            path = model_root / artifact.path
            if not path.is_file():
                issues.append(f"missing:{artifact.path}")
                continue
            if path.stat().st_size != artifact.size:
                issues.append(f"size:{artifact.path}")
                continue
            try:
                digest = sha256_file(path)
            except (OSError, ArtifactChangedDuringHashError):
                issues.append(f"changed:{artifact.path}")
                continue
            if digest != artifact.sha256:
                issues.append(f"sha256:{artifact.path}")
        return tuple(issues)

    def write_verification_record(self, model_root: Path) -> Path:
        artifacts = []
        for artifact in self.artifacts:
            stat = (model_root / artifact.path).stat()
            artifacts.append({
                "path": artifact.path,
                "size": artifact.size,
                "sha256": artifact.sha256,
                "mtime_ns": stat.st_mtime_ns,
            })
        record = {
            "schema_version": 1,
            "model_id": self.model_id,
            "revision": self.revision,
            "artifacts": artifacts,
        }
        destination = model_root / VERIFICATION_RECORD_NAME
        temporary = destination.with_suffix(".tmp")
        temporary.write_text(json.dumps(record, indent=2), encoding="utf-8")
        os.replace(temporary, destination)
        return destination

    def verification_record_is_current(self, model_root: Path) -> bool:
        record_path = model_root / VERIFICATION_RECORD_NAME
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return False
        if (
            record.get("schema_version") != 1
            or record.get("model_id") != self.model_id
            or record.get("revision") != self.revision
        ):
            return False

        expected = {item.path: item for item in self.artifacts}
        recorded = record.get("artifacts")
        if not isinstance(recorded, list) or len(recorded) != len(expected):
            return False
        for item in recorded:
            artifact = expected.get(item.get("path")) if isinstance(item, dict) else None
            if artifact is None:
                return False
            path = model_root / artifact.path
            try:
                stat = path.stat()
            except OSError:
                return False
            if (
                item.get("size") != artifact.size
                or item.get("sha256") != artifact.sha256
                or item.get("mtime_ns") != stat.st_mtime_ns
                or stat.st_size != artifact.size
            ):
                return False
            try:
                if sha256_file(path) != artifact.sha256:
                    return False
            except (OSError, ArtifactChangedDuringHashError):
                return False
        return True


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(f"Invalid BGE-M3 manifest: {message}")


def _safe_artifact_path(value: Any) -> str:
    _require(isinstance(value, str) and bool(value), "artifact path is required")
    path = Path(value)
    _require(not path.is_absolute(), "artifact path must be relative")
    _require(".." not in path.parts, "artifact path must stay inside model root")
    _require(path.parts[0] == "onnx", "artifact path must be under onnx/")
    return path.as_posix()


def load_bge_m3_manifest(path: Path = DEFAULT_MANIFEST_PATH) -> BgeM3Manifest:
    raw: Dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    _require(raw.get("schema_version") == 1, "schema_version must be 1")

    model = raw.get("model") or {}
    runtime = raw.get("runtime") or {}
    _require(model.get("id") == "BAAI/bge-m3", "model id must be BAAI/bge-m3")
    _require(_REVISION_RE.fullmatch(str(model.get("revision", ""))) is not None, "revision must be a full commit SHA")
    _require(model.get("license") == "MIT", "model license must be MIT")
    _require(model.get("embedding_dimension") == 1024, "embedding dimension must be 1024")
    _require(model.get("max_tokens") == 8192, "max_tokens must be 8192")
    _require(model.get("normalization") == "l2", "dense vectors must use L2 normalization")
    _require("multilingual" in model.get("languages", []), "multilingual capability is required")
    _require("dense" in model.get("output_modes", []), "dense output mode is required")
    _require(runtime.get("owner") == "aetherdb", "runtime must be owned by AetherDB")
    _require(runtime.get("engine") == "onnxruntime", "runtime engine must be onnxruntime")

    provider_preference = tuple(runtime.get("provider_preference") or ())
    _require(provider_preference == EXPECTED_PROVIDER_ORDER, "provider order must be MIGraphX, CUDA, CPU")
    _require(runtime.get("cpu_fallback_required") is True, "CPU fallback must be required")

    artifacts = []
    for item in raw.get("artifacts") or []:
        artifact_path = _safe_artifact_path(item.get("path"))
        size = item.get("size")
        sha256 = str(item.get("sha256", ""))
        _require(isinstance(size, int) and size > 0, f"invalid size for {artifact_path}")
        _require(_SHA256_RE.fullmatch(sha256) is not None, f"invalid SHA-256 for {artifact_path}")
        artifacts.append(ModelArtifact(artifact_path, size, sha256))
    _require(len(artifacts) == 8, "all eight pinned ONNX artifacts are required")
    _require(len({item.path for item in artifacts}) == len(artifacts), "artifact paths must be unique")

    return BgeM3Manifest(
        model_id=model["id"],
        revision=model["revision"],
        license=model["license"],
        dimensions=model["embedding_dimension"],
        max_tokens=model["max_tokens"],
        output_modes=tuple(model["output_modes"]),
        normalization=model["normalization"],
        provider_preference=provider_preference,
        artifacts=tuple(artifacts),
    )
