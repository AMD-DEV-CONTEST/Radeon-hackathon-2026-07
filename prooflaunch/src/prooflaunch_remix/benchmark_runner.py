from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Mapping, Protocol, Sequence

from .competition_benchmark import (
    CASE_GATE_EVIDENCE_SCHEMA,
    BenchmarkCase,
    CompetitionBenchmarkError,
    CompetitionCaseJournal,
    FrozenBenchmarkManifest,
    ProductSpec,
    load_frozen_manifest,
)


RUN_CHECKPOINT_SCHEMA = "ProofLaunchCompetition2XRunCheckpointV1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class BenchmarkRunnerError(RuntimeError):
    pass


class TransientActivityError(BenchmarkRunnerError):
    """A bounded retry may succeed without changing benchmark inputs."""


class PermanentActivityError(BenchmarkRunnerError):
    """The activity must fail closed until an operator changes external state."""


class BenchmarkPhase(str, Enum):
    PREPARE_PRODUCTS = "prepare_products"
    UNDERSTAND_PRODUCTS = "understand_products"
    GROUND_PRODUCTS = "ground_products"
    PLAN_PRODUCTS = "plan_products"
    GENERATE_STILLS = "generate_stills"
    AUDIT_STILLS = "audit_stills"
    GENERATE_VIDEOS = "generate_videos"
    TRACK_VIDEOS = "track_videos"
    AUDIT_VIDEOS = "audit_videos"


PHASE_ORDER = (
    BenchmarkPhase.PREPARE_PRODUCTS,
    BenchmarkPhase.UNDERSTAND_PRODUCTS,
    BenchmarkPhase.GROUND_PRODUCTS,
    BenchmarkPhase.PLAN_PRODUCTS,
    BenchmarkPhase.GENERATE_STILLS,
    BenchmarkPhase.AUDIT_STILLS,
    BenchmarkPhase.GENERATE_VIDEOS,
    BenchmarkPhase.TRACK_VIDEOS,
    BenchmarkPhase.AUDIT_VIDEOS,
)


@dataclass(frozen=True)
class ArtifactOutput:
    path: Path
    model_ref: str
    peak_vram_gb: float
    metadata: Mapping[str, object] = field(default_factory=dict)
    sidecars: tuple[Path, ...] = ()


@dataclass(frozen=True)
class StillAudit:
    repairs: int
    unsupported_claim_count: int
    observation_count: int
    located_observation_count: int
    image_identity_pass: bool
    cross_media_pass: bool
    peak_vram_gb: float = 0.0
    evidence: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class VideoAudit:
    preencode_video_identity_pass: bool
    encoded_video_identity_pass: bool
    audio_video_alignment_pass: bool
    cross_media_pass: bool
    peak_vram_gb: float = 0.0
    evidence: Mapping[str, object] = field(default_factory=dict)


class CompetitionBenchmarkAdapter(Protocol):
    """Caller-owned local Radeon adapter.

    Implementations must synchronize GPU work before returning so runner wall
    timings include the complete activity. The runner never sends data to a
    closed online inference API.
    """

    def identity(self) -> Mapping[str, object]: ...

    def load_phase(self, phase: BenchmarkPhase) -> Mapping[str, object]: ...

    def release_phase(self, phase: BenchmarkPhase) -> None: ...

    def prepare_product(
        self,
        product: ProductSpec,
        source_path: Path,
    ) -> Mapping[str, object]: ...

    def understand_product(
        self,
        product: ProductSpec,
        prepared: Mapping[str, object],
    ) -> Mapping[str, object]: ...

    def ground_product(
        self,
        product: ProductSpec,
        prepared: Mapping[str, object],
        understanding: Mapping[str, object],
    ) -> Mapping[str, object]: ...

    def plan_product(
        self,
        product: ProductSpec,
        prepared: Mapping[str, object],
        understanding: Mapping[str, object],
        grounding: Mapping[str, object],
    ) -> Mapping[str, object]: ...

    def generate_still(
        self,
        case: BenchmarkCase,
        product: ProductSpec,
        understanding: Mapping[str, object],
        grounding: Mapping[str, object],
        plan: Mapping[str, object],
        output_path: Path,
    ) -> ArtifactOutput: ...

    def audit_still(
        self,
        case: BenchmarkCase,
        product: ProductSpec,
        understanding: Mapping[str, object],
        grounding: Mapping[str, object],
        plan: Mapping[str, object],
        still: ArtifactOutput,
    ) -> StillAudit: ...

    def generate_video(
        self,
        case: BenchmarkCase,
        product: ProductSpec,
        understanding: Mapping[str, object],
        grounding: Mapping[str, object],
        plan: Mapping[str, object],
        still: ArtifactOutput,
        output_path: Path,
    ) -> ArtifactOutput: ...

    def track_video(
        self,
        case: BenchmarkCase,
        product: ProductSpec,
        grounding: Mapping[str, object],
        still: ArtifactOutput,
        video: ArtifactOutput,
    ) -> Mapping[str, object]: ...

    def audit_video(
        self,
        case: BenchmarkCase,
        product: ProductSpec,
        understanding: Mapping[str, object],
        grounding: Mapping[str, object],
        plan: Mapping[str, object],
        still: ArtifactOutput,
        video: ArtifactOutput,
        tracking: Mapping[str, object],
    ) -> VideoAudit: ...


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise PermanentActivityError(f"cannot hash artifact {path}: {error}") from error
    return digest.hexdigest()


def _json_mapping(value: Mapping[str, object], label: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise PermanentActivityError(f"{label} must return a mapping")
    normalized = dict(value)
    try:
        _canonical_json(normalized)
    except (TypeError, ValueError) as error:
        raise PermanentActivityError(
            f"{label} returned non-JSON checkpoint data: {error}"
        ) from error
    return normalized


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PermanentActivityError(f"{label} must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < 0:
        raise PermanentActivityError(f"{label} must be finite and non-negative")
    return normalized


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PermanentActivityError(f"{label} must be a non-negative integer")
    return value


def _boolean(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise PermanentActivityError(f"{label} must be a boolean")
    return value


def _write_json_atomic(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        )
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    try:
        directory_fd = os.open(path.parent, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


@dataclass
class RunCheckpoint:
    benchmark_id: str
    manifest_hash: str
    adapter_identity_hash: str
    shard_index: int
    shard_count: int
    activities: dict[str, dict[str, object]] = field(default_factory=dict)
    phase_states: dict[str, dict[str, object]] = field(default_factory=dict)
    trace: list[dict[str, object]] = field(default_factory=list)
    head_hash: str = "0" * 64
    schema: str = RUN_CHECKPOINT_SCHEMA

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "RunCheckpoint":
        if value.get("schema") != RUN_CHECKPOINT_SCHEMA:
            raise BenchmarkRunnerError("unsupported benchmark-run checkpoint schema")
        activities = value.get("activities", {})
        phase_states = value.get("phase_states", {})
        trace = value.get("trace", [])
        if not isinstance(activities, dict):
            raise BenchmarkRunnerError("checkpoint activities must be an object")
        if not isinstance(phase_states, dict):
            raise BenchmarkRunnerError("checkpoint phase_states must be an object")
        if not isinstance(trace, list):
            raise BenchmarkRunnerError("checkpoint trace must be a list")
        return cls(
            benchmark_id=str(value.get("benchmark_id", "")),
            manifest_hash=str(value.get("manifest_hash", "")),
            adapter_identity_hash=str(value.get("adapter_identity_hash", "")),
            shard_index=int(value.get("shard_index", -1)),
            shard_count=int(value.get("shard_count", 0)),
            activities={
                str(key): dict(item)
                for key, item in activities.items()
                if isinstance(item, dict)
            },
            phase_states={
                str(key): dict(item)
                for key, item in phase_states.items()
                if isinstance(item, dict)
            },
            trace=[dict(item) for item in trace if isinstance(item, dict)],
            head_hash=str(value.get("head_hash", "0" * 64)),
        )


class RunCheckpointStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def save(self, checkpoint: RunCheckpoint) -> None:
        _write_json_atomic(self.path, checkpoint.to_dict())

    def load(self) -> RunCheckpoint:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise BenchmarkRunnerError(
                f"cannot read run checkpoint {self.path}: {error}"
            ) from error
        if not isinstance(value, dict):
            raise BenchmarkRunnerError("run checkpoint must contain one JSON object")
        return RunCheckpoint.from_mapping(value)


class CompetitionMatrixRunner:
    """Durable, phase-batched executor for the frozen competition matrix."""

    def __init__(
        self,
        *,
        manifest_path: Path,
        run_dir: Path,
        adapter: CompetitionBenchmarkAdapter,
        resume: bool = False,
        shard_index: int = 0,
        shard_count: int = 1,
        max_retries: int = 2,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if shard_count < 1:
            raise BenchmarkRunnerError("shard_count must be positive")
        if not 0 <= shard_index < shard_count:
            raise BenchmarkRunnerError("shard_index must be within shard_count")
        if not 0 <= max_retries <= 2:
            raise BenchmarkRunnerError("max_retries must be between zero and two")
        self.manifest_path = manifest_path.resolve()
        self.manifest = load_frozen_manifest(self.manifest_path)
        self.run_dir = run_dir.resolve()
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.adapter = adapter
        self.shard_index = shard_index
        self.shard_count = shard_count
        self.max_retries = max_retries
        self.sleeper = sleeper
        self.identity = self._validate_adapter_identity(adapter.identity())
        self.identity_hash = _sha256_json(self.identity)
        suffix = (
            ""
            if shard_count == 1
            else f".shard-{shard_index:03d}-of-{shard_count:03d}"
        )
        self.results_path = self.run_dir / f"prooflaunch-results{suffix}.jsonl"
        self.checkpoint_path = self.run_dir / f"run-checkpoint{suffix}.json"
        self.store = RunCheckpointStore(self.checkpoint_path)
        if not resume and (self.checkpoint_path.exists() or self.results_path.exists()):
            raise BenchmarkRunnerError(
                "run state already exists; pass resume=True only after inspecting it"
            )
        if self.results_path.exists() and not self.checkpoint_path.exists():
            raise BenchmarkRunnerError(
                "result journal exists without its bound run checkpoint"
            )
        self.checkpoint = (
            self.store.load()
            if self.checkpoint_path.exists()
            else RunCheckpoint(
                benchmark_id=self.manifest.benchmark_id,
                manifest_hash=self.manifest.manifest_hash,
                adapter_identity_hash=self.identity_hash,
                shard_index=shard_index,
                shard_count=shard_count,
            )
        )
        self._validate_checkpoint_binding()
        self.cases = tuple(
            case
            for index, case in enumerate(self.manifest.cases)
            if index % shard_count == shard_index
        )
        selected_product_ids = {case.product_id for case in self.cases}
        self.products = tuple(
            product
            for product in self.manifest.products
            if product.product_id in selected_product_ids
        )
        self.product_by_id = {
            product.product_id: product for product in self.manifest.products
        }
        for product in self.products:
            self._source_path(product)
        self.journal = CompetitionCaseJournal(
            self.manifest_path,
            self.results_path,
        )
        self._validate_checkpoint_artifacts()

    @staticmethod
    def _validate_adapter_identity(
        value: Mapping[str, object],
    ) -> dict[str, object]:
        identity = _json_mapping(value, "adapter.identity")
        for field_name in ("adapter_id", "version"):
            field_value = identity.get(field_name)
            if not isinstance(field_value, str) or not field_value.strip():
                raise BenchmarkRunnerError(
                    f"adapter identity requires non-empty {field_name}"
                )
        if identity.get("system_kind") != "prooflaunch":
            raise BenchmarkRunnerError(
                "the competition runner accepts only system_kind=prooflaunch"
            )
        if identity.get("uses_closed_online_api") is not False:
            raise BenchmarkRunnerError(
                "closed online inference APIs are prohibited in this runner"
            )
        settings_hash = identity.get("settings_sha256")
        if not isinstance(settings_hash, str) or not SHA256_RE.fullmatch(
            settings_hash
        ):
            raise BenchmarkRunnerError(
                "adapter identity requires a lowercase settings_sha256"
            )
        return identity

    def _validate_checkpoint_binding(self) -> None:
        expected = (
            self.checkpoint.benchmark_id == self.manifest.benchmark_id
            and self.checkpoint.manifest_hash == self.manifest.manifest_hash
            and self.checkpoint.adapter_identity_hash == self.identity_hash
            and self.checkpoint.shard_index == self.shard_index
            and self.checkpoint.shard_count == self.shard_count
        )
        if not expected:
            raise BenchmarkRunnerError(
                "checkpoint does not match manifest, adapter, or shard identity"
            )

    def _validate_checkpoint_artifacts(self) -> None:
        for key, activity in self.checkpoint.activities.items():
            if activity.get("status") != "succeeded":
                continue
            output = activity.get("output")
            if not isinstance(output, dict):
                raise BenchmarkRunnerError(f"{key}: succeeded activity lacks output")
            artifact = output.get("artifact")
            if artifact is None:
                continue
            if not isinstance(artifact, dict):
                raise BenchmarkRunnerError(f"{key}: artifact checkpoint is invalid")
            path = self._bound_run_path(artifact.get("locator"), key)
            expected_hash = artifact.get("sha256")
            if not isinstance(expected_hash, str) or not SHA256_RE.fullmatch(
                expected_hash
            ):
                raise BenchmarkRunnerError(f"{key}: artifact SHA-256 is invalid")
            actual_hash = _file_sha256(path)
            if actual_hash != expected_hash:
                raise BenchmarkRunnerError(
                    f"{key}: checkpoint artifact hash mismatch"
                )
            sidecars = artifact.get("sidecars", [])
            if not isinstance(sidecars, list):
                raise BenchmarkRunnerError(f"{key}: artifact sidecars are invalid")
            for position, sidecar in enumerate(sidecars):
                if not isinstance(sidecar, dict):
                    raise BenchmarkRunnerError(
                        f"{key}: sidecar {position} checkpoint is invalid"
                    )
                sidecar_path = self._bound_run_path(
                    sidecar.get("locator"),
                    f"{key}.sidecar[{position}]",
                )
                sidecar_hash = sidecar.get("sha256")
                if (
                    not isinstance(sidecar_hash, str)
                    or not SHA256_RE.fullmatch(sidecar_hash)
                ):
                    raise BenchmarkRunnerError(
                        f"{key}: sidecar {position} SHA-256 is invalid"
                    )
                if _file_sha256(sidecar_path) != sidecar_hash:
                    raise BenchmarkRunnerError(
                        f"{key}: sidecar {position} hash mismatch"
                    )

    def _bound_run_path(self, locator: object, label: str) -> Path:
        if not isinstance(locator, str) or not locator:
            raise BenchmarkRunnerError(f"{label}: artifact locator is missing")
        relative = Path(locator)
        if relative.is_absolute() or ".." in relative.parts:
            raise BenchmarkRunnerError(
                f"{label}: artifact locator must be traversal-free and relative"
            )
        resolved = (self.run_dir / relative).resolve()
        if not resolved.is_relative_to(self.run_dir):
            raise BenchmarkRunnerError(f"{label}: artifact escapes run directory")
        if not resolved.is_file():
            raise BenchmarkRunnerError(f"{label}: artifact is missing")
        return resolved

    def _append_trace(
        self,
        *,
        event_type: str,
        phase: BenchmarkPhase | None = None,
        activity_key: str | None = None,
        status: str | None = None,
    ) -> None:
        event: dict[str, object] = {
            "index": len(self.checkpoint.trace) + 1,
            "event_type": event_type,
            "previous_hash": self.checkpoint.head_hash,
        }
        if phase is not None:
            event["phase"] = phase.value
        if activity_key is not None:
            event["activity_key"] = activity_key
        if status is not None:
            event["status"] = status
        event_hash = _sha256_json(event)
        event["event_hash"] = event_hash
        self.checkpoint.trace.append(event)
        self.checkpoint.head_hash = event_hash

    def _save(self) -> None:
        self.store.save(self.checkpoint)

    @staticmethod
    def _activity_status(
        checkpoint: RunCheckpoint,
        key: str,
    ) -> str:
        value = checkpoint.activities.get(key)
        return str(value.get("status")) if value else "pending"

    def _mark_skipped(self, key: str, reason: str) -> None:
        if self._activity_status(self.checkpoint, key) in {
            "succeeded",
            "failed",
            "skipped",
        }:
            return
        self.checkpoint.activities[key] = {
            "status": "skipped",
            "attempts": 0,
            "reason": reason,
        }
        self._append_trace(
            event_type="activity",
            activity_key=key,
            status="skipped",
        )
        self._save()

    def _run_activity(
        self,
        *,
        key: str,
        operation: Callable[[], object],
        normalize: Callable[[object, float], Mapping[str, object]],
    ) -> None:
        existing = self.checkpoint.activities.get(key, {})
        if existing.get("status") in {"succeeded", "failed", "skipped"}:
            return
        attempts = int(existing.get("attempts", 0))
        maximum_attempts = self.max_retries + 1
        while attempts < maximum_attempts:
            attempts += 1
            self.checkpoint.activities[key] = {
                "status": "running",
                "attempts": attempts,
            }
            self._append_trace(
                event_type="activity",
                activity_key=key,
                status="running",
            )
            self._save()
            started = time.perf_counter()
            try:
                raw_output = operation()
                duration = time.perf_counter() - started
                output = dict(normalize(raw_output, duration))
            except TransientActivityError as error:
                terminal = attempts >= maximum_attempts
                self.checkpoint.activities[key] = {
                    "status": "failed" if terminal else "pending",
                    "attempts": attempts,
                    "error_class": "transient",
                    "error_type": type(error).__name__,
                    "error": str(error),
                    "next_backoff_seconds": (
                        None if terminal else float(2 ** (attempts - 1))
                    ),
                }
                self._append_trace(
                    event_type="activity",
                    activity_key=key,
                    status="failed" if terminal else "retry_pending",
                )
                self._save()
                if terminal:
                    return
                self.sleeper(float(2 ** (attempts - 1)))
                continue
            except Exception as error:
                self.checkpoint.activities[key] = {
                    "status": "failed",
                    "attempts": attempts,
                    "error_class": "permanent",
                    "error_type": type(error).__name__,
                    "error": str(error),
                }
                self._append_trace(
                    event_type="activity",
                    activity_key=key,
                    status="failed",
                )
                self._save()
                return
            self.checkpoint.activities[key] = {
                "status": "succeeded",
                "attempts": attempts,
                "output": output,
            }
            self._append_trace(
                event_type="activity",
                activity_key=key,
                status="succeeded",
            )
            self._save()
            return

    def _source_path(self, product: ProductSpec) -> Path:
        relative = Path(product.source_locator)
        if relative.is_absolute() or ".." in relative.parts:
            raise PermanentActivityError(
                f"{product.product_id}: source_locator must be traversal-free and relative"
            )
        root = self.manifest_path.parent
        source = (root / relative).resolve()
        if not source.is_relative_to(root):
            raise PermanentActivityError(
                f"{product.product_id}: source_locator escapes manifest directory"
            )
        if not source.is_file():
            raise PermanentActivityError(
                f"{product.product_id}: product input is missing"
            )
        actual_hash = _file_sha256(source)
        if actual_hash != product.input_sha256:
            raise PermanentActivityError(
                f"{product.product_id}: product input hash mismatch"
            )
        return source

    def _context(self, key: str) -> Mapping[str, object]:
        activity = self.checkpoint.activities.get(key, {})
        output = activity.get("output")
        if activity.get("status") != "succeeded" or not isinstance(output, dict):
            raise BenchmarkRunnerError(f"{key}: required checkpoint output is missing")
        context = output.get("context")
        if not isinstance(context, dict):
            raise BenchmarkRunnerError(f"{key}: context checkpoint is invalid")
        return context

    def _artifact_from_checkpoint(self, key: str) -> ArtifactOutput:
        activity = self.checkpoint.activities.get(key, {})
        output = activity.get("output")
        if activity.get("status") != "succeeded" or not isinstance(output, dict):
            raise BenchmarkRunnerError(f"{key}: required artifact output is missing")
        artifact = output.get("artifact")
        if not isinstance(artifact, dict):
            raise BenchmarkRunnerError(f"{key}: artifact checkpoint is invalid")
        metadata = artifact.get("metadata", {})
        if not isinstance(metadata, dict):
            raise BenchmarkRunnerError(f"{key}: artifact metadata is invalid")
        sidecar_values = artifact.get("sidecars", [])
        if not isinstance(sidecar_values, list):
            raise BenchmarkRunnerError(f"{key}: artifact sidecars are invalid")
        return ArtifactOutput(
            path=self._bound_run_path(artifact.get("locator"), key),
            model_ref=str(artifact.get("model_ref", "")),
            peak_vram_gb=_number(
                artifact.get("peak_vram_gb"),
                f"{key}.peak_vram_gb",
            ),
            metadata=metadata,
            sidecars=tuple(
                self._bound_run_path(
                    item.get("locator") if isinstance(item, dict) else None,
                    f"{key}.sidecar[{position}]",
                )
                for position, item in enumerate(sidecar_values)
            ),
        )

    def _normalize_context(
        self,
        label: str,
    ) -> Callable[[object, float], Mapping[str, object]]:
        def normalize(value: object, duration: float) -> Mapping[str, object]:
            if not isinstance(value, Mapping):
                raise PermanentActivityError(f"{label} must return a mapping")
            return {
                "context": _json_mapping(value, label),
                "duration_seconds": duration,
            }

        return normalize

    def _normalize_artifact(
        self,
        *,
        label: str,
        expected_path: Path,
    ) -> Callable[[object, float], Mapping[str, object]]:
        def normalize(value: object, duration: float) -> Mapping[str, object]:
            if not isinstance(value, ArtifactOutput):
                raise PermanentActivityError(
                    f"{label} must return ArtifactOutput"
                )
            actual_path = value.path.resolve()
            if actual_path != expected_path.resolve():
                raise PermanentActivityError(
                    f"{label} must write the assigned output path"
                )
            if not actual_path.is_file() or actual_path.stat().st_size == 0:
                raise PermanentActivityError(
                    f"{label} did not create a non-empty artifact"
                )
            if not actual_path.is_relative_to(self.run_dir):
                raise PermanentActivityError(f"{label} output escapes run directory")
            if not isinstance(value.model_ref, str) or not value.model_ref.strip():
                raise PermanentActivityError(f"{label} requires a model_ref")
            metadata = _json_mapping(value.metadata, f"{label}.metadata")
            sidecar_records: list[dict[str, object]] = []
            seen_sidecars: set[Path] = set()
            for position, sidecar in enumerate(value.sidecars):
                sidecar_path = Path(sidecar).resolve()
                if sidecar_path == actual_path or sidecar_path in seen_sidecars:
                    raise PermanentActivityError(
                        f"{label}.sidecars must be unique and exclude the primary artifact"
                    )
                seen_sidecars.add(sidecar_path)
                if (
                    not sidecar_path.is_relative_to(self.run_dir)
                    or not sidecar_path.is_file()
                    or sidecar_path.stat().st_size == 0
                ):
                    raise PermanentActivityError(
                        f"{label}.sidecars[{position}] must be a non-empty file "
                        "beneath the run directory"
                    )
                sidecar_records.append(
                    {
                        "locator": sidecar_path.relative_to(
                            self.run_dir
                        ).as_posix(),
                        "sha256": _file_sha256(sidecar_path),
                    }
                )
            return {
                "artifact": {
                    "locator": actual_path.relative_to(self.run_dir).as_posix(),
                    "sha256": _file_sha256(actual_path),
                    "model_ref": value.model_ref.strip(),
                    "peak_vram_gb": _number(
                        value.peak_vram_gb,
                        f"{label}.peak_vram_gb",
                    ),
                    "metadata": metadata,
                    "sidecars": sidecar_records,
                },
                "duration_seconds": duration,
            }

        return normalize

    @staticmethod
    def _normalize_still_audit(
        value: object,
        duration: float,
    ) -> Mapping[str, object]:
        if not isinstance(value, StillAudit):
            raise PermanentActivityError("audit_still must return StillAudit")
        repairs = _integer(value.repairs, "still_audit.repairs")
        if repairs > 2:
            raise PermanentActivityError("still_audit.repairs cannot exceed two")
        observations = _integer(
            value.observation_count,
            "still_audit.observation_count",
        )
        located = _integer(
            value.located_observation_count,
            "still_audit.located_observation_count",
        )
        if located > observations:
            raise PermanentActivityError(
                "located observations cannot exceed total observations"
            )
        return {
            "audit": {
                "repairs": repairs,
                "unsupported_claim_count": _integer(
                    value.unsupported_claim_count,
                    "still_audit.unsupported_claim_count",
                ),
                "observation_count": observations,
                "located_observation_count": located,
                "image_identity_pass": _boolean(
                    value.image_identity_pass,
                    "still_audit.image_identity_pass",
                ),
                "cross_media_pass": _boolean(
                    value.cross_media_pass,
                    "still_audit.cross_media_pass",
                ),
                "peak_vram_gb": _number(
                    value.peak_vram_gb,
                    "still_audit.peak_vram_gb",
                ),
                "evidence": _json_mapping(
                    value.evidence,
                    "still_audit.evidence",
                ),
            },
            "duration_seconds": duration,
        }

    @staticmethod
    def _normalize_video_audit(
        value: object,
        duration: float,
    ) -> Mapping[str, object]:
        if not isinstance(value, VideoAudit):
            raise PermanentActivityError("audit_video must return VideoAudit")
        return {
            "audit": {
                "preencode_video_identity_pass": _boolean(
                    value.preencode_video_identity_pass,
                    "video_audit.preencode_video_identity_pass",
                ),
                "encoded_video_identity_pass": _boolean(
                    value.encoded_video_identity_pass,
                    "video_audit.encoded_video_identity_pass",
                ),
                "audio_video_alignment_pass": _boolean(
                    value.audio_video_alignment_pass,
                    "video_audit.audio_video_alignment_pass",
                ),
                "cross_media_pass": _boolean(
                    value.cross_media_pass,
                    "video_audit.cross_media_pass",
                ),
                "peak_vram_gb": _number(
                    value.peak_vram_gb,
                    "video_audit.peak_vram_gb",
                ),
                "evidence": _json_mapping(
                    value.evidence,
                    "video_audit.evidence",
                ),
            },
            "duration_seconds": duration,
        }

    def _phase_keys(self, phase: BenchmarkPhase) -> tuple[str, ...]:
        if phase == BenchmarkPhase.PREPARE_PRODUCTS:
            return tuple(f"prepare:{item.product_id}" for item in self.products)
        if phase == BenchmarkPhase.UNDERSTAND_PRODUCTS:
            return tuple(f"understand:{item.product_id}" for item in self.products)
        if phase == BenchmarkPhase.GROUND_PRODUCTS:
            return tuple(f"ground:{item.product_id}" for item in self.products)
        if phase == BenchmarkPhase.PLAN_PRODUCTS:
            return tuple(f"plan:{item.product_id}" for item in self.products)
        if phase == BenchmarkPhase.GENERATE_STILLS:
            return tuple(f"generate_still:{item.case_id}" for item in self.cases)
        if phase == BenchmarkPhase.AUDIT_STILLS:
            return tuple(f"audit_still:{item.case_id}" for item in self.cases)
        video_cases = tuple(item for item in self.cases if item.video_required)
        if phase == BenchmarkPhase.GENERATE_VIDEOS:
            return tuple(f"generate_video:{item.case_id}" for item in video_cases)
        if phase == BenchmarkPhase.TRACK_VIDEOS:
            return tuple(f"track_video:{item.case_id}" for item in video_cases)
        return tuple(f"audit_video:{item.case_id}" for item in video_cases)

    def _phase_needs_run(self, phase: BenchmarkPhase) -> bool:
        state = self.checkpoint.phase_states.get(phase.value, {})
        if state.get("status") == "release_failed":
            return True
        return any(
            self._activity_status(self.checkpoint, key) in {"pending", "running"}
            for key in self._phase_keys(phase)
        )

    def _load_phase(self, phase: BenchmarkPhase) -> None:
        attempts = 0
        while attempts <= self.max_retries:
            attempts += 1
            try:
                raw = self.adapter.load_phase(phase)
                details = _json_mapping(raw, f"load_phase({phase.value})")
                model_ref = details.get("model_ref")
                if not isinstance(model_ref, str) or not model_ref.strip():
                    raise PermanentActivityError(
                        f"load_phase({phase.value}) requires model_ref"
                    )
            except TransientActivityError:
                if attempts > self.max_retries:
                    raise
                self.sleeper(float(2 ** (attempts - 1)))
                continue
            self.checkpoint.phase_states[phase.value] = {
                "status": "loaded",
                "attempts": attempts,
                "details": details,
            }
            self._append_trace(event_type="phase_loaded", phase=phase)
            self._save()
            return

    def _release_phase(self, phase: BenchmarkPhase) -> None:
        try:
            self.adapter.release_phase(phase)
        except Exception as error:
            self.checkpoint.phase_states[phase.value] = {
                "status": "release_failed",
                "error_type": type(error).__name__,
                "error": str(error),
            }
            self._append_trace(
                event_type="phase_release",
                phase=phase,
                status="failed",
            )
            self._save()
            raise BenchmarkRunnerError(
                f"failed to release phase {phase.value}: {error}"
            ) from error
        self.checkpoint.phase_states[phase.value] = {"status": "released"}
        self._append_trace(
            event_type="phase_release",
            phase=phase,
            status="succeeded",
        )
        self._save()

    def _run_prepare(self) -> None:
        for product in self.products:
            key = f"prepare:{product.product_id}"
            self._run_activity(
                key=key,
                operation=lambda product=product: self.adapter.prepare_product(
                    product,
                    self._source_path(product),
                ),
                normalize=self._normalize_context("prepare_product"),
            )

    def _run_understand(self) -> None:
        for product in self.products:
            prepare_key = f"prepare:{product.product_id}"
            key = f"understand:{product.product_id}"
            if self._activity_status(self.checkpoint, prepare_key) != "succeeded":
                self._mark_skipped(key, f"prerequisite {prepare_key} did not succeed")
                continue
            self._run_activity(
                key=key,
                operation=lambda product=product, prepare_key=prepare_key: (
                    self.adapter.understand_product(
                        product,
                        self._context(prepare_key),
                    )
                ),
                normalize=self._normalize_context("understand_product"),
            )

    def _run_ground(self) -> None:
        for product in self.products:
            prepare_key = f"prepare:{product.product_id}"
            understand_key = f"understand:{product.product_id}"
            key = f"ground:{product.product_id}"
            prerequisites = (prepare_key, understand_key)
            missing = next(
                (
                    item
                    for item in prerequisites
                    if self._activity_status(self.checkpoint, item) != "succeeded"
                ),
                None,
            )
            if missing:
                self._mark_skipped(key, f"prerequisite {missing} did not succeed")
                continue
            self._run_activity(
                key=key,
                operation=lambda product=product: self.adapter.ground_product(
                    product,
                    self._context(prepare_key),
                    self._context(understand_key),
                ),
                normalize=self._normalize_context("ground_product"),
            )

    def _run_plan(self) -> None:
        for product in self.products:
            prepare_key = f"prepare:{product.product_id}"
            understand_key = f"understand:{product.product_id}"
            ground_key = f"ground:{product.product_id}"
            key = f"plan:{product.product_id}"
            prerequisites = (prepare_key, understand_key, ground_key)
            missing = next(
                (
                    item
                    for item in prerequisites
                    if self._activity_status(self.checkpoint, item) != "succeeded"
                ),
                None,
            )
            if missing:
                self._mark_skipped(key, f"prerequisite {missing} did not succeed")
                continue
            self._run_activity(
                key=key,
                operation=lambda product=product: self.adapter.plan_product(
                    product,
                    self._context(prepare_key),
                    self._context(understand_key),
                    self._context(ground_key),
                ),
                normalize=self._normalize_context("plan_product"),
            )

    def _run_generate_stills(self) -> None:
        for case in self.cases:
            product = self.product_by_id[case.product_id]
            understand_key = f"understand:{case.product_id}"
            ground_key = f"ground:{case.product_id}"
            plan_key = f"plan:{case.product_id}"
            key = f"generate_still:{case.case_id}"
            if self._activity_status(self.checkpoint, plan_key) != "succeeded":
                self._mark_skipped(
                    key,
                    f"prerequisite {plan_key} did not succeed",
                )
                continue
            output_path = self.run_dir / "artifacts" / "stills" / f"{case.case_id}.png"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            self._run_activity(
                key=key,
                operation=lambda case=case, product=product, output_path=output_path: (
                    self.adapter.generate_still(
                        case,
                        product,
                        self._context(understand_key),
                        self._context(ground_key),
                        self._context(plan_key),
                        output_path,
                    )
                ),
                normalize=self._normalize_artifact(
                    label="generate_still",
                    expected_path=output_path,
                ),
            )

    def _run_audit_stills(self) -> None:
        for case in self.cases:
            product = self.product_by_id[case.product_id]
            still_key = f"generate_still:{case.case_id}"
            understand_key = f"understand:{case.product_id}"
            ground_key = f"ground:{case.product_id}"
            plan_key = f"plan:{case.product_id}"
            key = f"audit_still:{case.case_id}"
            if self._activity_status(self.checkpoint, still_key) != "succeeded":
                self._mark_skipped(key, f"prerequisite {still_key} did not succeed")
                continue
            self._run_activity(
                key=key,
                operation=lambda case=case, product=product, still_key=still_key: (
                    self.adapter.audit_still(
                        case,
                        product,
                        self._context(understand_key),
                        self._context(ground_key),
                        self._context(plan_key),
                        self._artifact_from_checkpoint(still_key),
                    )
                ),
                normalize=self._normalize_still_audit,
            )

    def _run_generate_videos(self) -> None:
        for case in self.cases:
            if not case.video_required:
                continue
            product = self.product_by_id[case.product_id]
            still_key = f"generate_still:{case.case_id}"
            audit_key = f"audit_still:{case.case_id}"
            understand_key = f"understand:{case.product_id}"
            ground_key = f"ground:{case.product_id}"
            plan_key = f"plan:{case.product_id}"
            key = f"generate_video:{case.case_id}"
            if self._activity_status(self.checkpoint, audit_key) != "succeeded":
                self._mark_skipped(key, f"prerequisite {audit_key} did not succeed")
                continue
            output_path = self.run_dir / "artifacts" / "videos" / f"{case.case_id}.mp4"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            self._run_activity(
                key=key,
                operation=lambda case=case, product=product, output_path=output_path: (
                    self.adapter.generate_video(
                        case,
                        product,
                        self._context(understand_key),
                        self._context(ground_key),
                        self._context(plan_key),
                        self._artifact_from_checkpoint(still_key),
                        output_path,
                    )
                ),
                normalize=self._normalize_artifact(
                    label="generate_video",
                    expected_path=output_path,
                ),
            )

    def _run_track_videos(self) -> None:
        for case in self.cases:
            if not case.video_required:
                continue
            product = self.product_by_id[case.product_id]
            ground_key = f"ground:{case.product_id}"
            still_key = f"generate_still:{case.case_id}"
            video_key = f"generate_video:{case.case_id}"
            key = f"track_video:{case.case_id}"
            if self._activity_status(self.checkpoint, video_key) != "succeeded":
                self._mark_skipped(key, f"prerequisite {video_key} did not succeed")
                continue
            self._run_activity(
                key=key,
                operation=lambda case=case, product=product, video_key=video_key: (
                    self.adapter.track_video(
                        case,
                        product,
                        self._context(ground_key),
                        self._artifact_from_checkpoint(still_key),
                        self._artifact_from_checkpoint(video_key),
                    )
                ),
                normalize=self._normalize_context("track_video"),
            )

    def _run_audit_videos(self) -> None:
        for case in self.cases:
            if not case.video_required:
                continue
            product = self.product_by_id[case.product_id]
            still_key = f"generate_still:{case.case_id}"
            video_key = f"generate_video:{case.case_id}"
            understand_key = f"understand:{case.product_id}"
            ground_key = f"ground:{case.product_id}"
            plan_key = f"plan:{case.product_id}"
            track_key = f"track_video:{case.case_id}"
            key = f"audit_video:{case.case_id}"
            if self._activity_status(self.checkpoint, track_key) != "succeeded":
                self._mark_skipped(key, f"prerequisite {track_key} did not succeed")
                continue
            self._run_activity(
                key=key,
                operation=lambda case=case, product=product, video_key=video_key: (
                    self.adapter.audit_video(
                        case,
                        product,
                        self._context(understand_key),
                        self._context(ground_key),
                        self._context(plan_key),
                        self._artifact_from_checkpoint(still_key),
                        self._artifact_from_checkpoint(video_key),
                        self._context(track_key),
                    )
                ),
                normalize=self._normalize_video_audit,
            )

    def _execute_phase(self, phase: BenchmarkPhase) -> None:
        if not self._phase_needs_run(phase):
            return
        self._load_phase(phase)
        try:
            if phase == BenchmarkPhase.PREPARE_PRODUCTS:
                self._run_prepare()
            elif phase == BenchmarkPhase.UNDERSTAND_PRODUCTS:
                self._run_understand()
            elif phase == BenchmarkPhase.GROUND_PRODUCTS:
                self._run_ground()
            elif phase == BenchmarkPhase.PLAN_PRODUCTS:
                self._run_plan()
            elif phase == BenchmarkPhase.GENERATE_STILLS:
                self._run_generate_stills()
            elif phase == BenchmarkPhase.AUDIT_STILLS:
                self._run_audit_stills()
            elif phase == BenchmarkPhase.GENERATE_VIDEOS:
                self._run_generate_videos()
            elif phase == BenchmarkPhase.TRACK_VIDEOS:
                self._run_track_videos()
            else:
                self._run_audit_videos()
        finally:
            self._release_phase(phase)

    def _activity_output(self, key: str) -> Mapping[str, object]:
        activity = self.checkpoint.activities.get(key, {})
        output = activity.get("output")
        return output if isinstance(output, dict) else {}

    def _case_gate(self, case: BenchmarkCase) -> tuple[dict[str, object], Path | None, Path | None]:
        keys = (
            f"generate_still:{case.case_id}",
            f"audit_still:{case.case_id}",
        )
        if case.video_required:
            keys += (
                f"generate_video:{case.case_id}",
                f"track_video:{case.case_id}",
                f"audit_video:{case.case_id}",
            )
        completed = all(
            self._activity_status(self.checkpoint, key) == "succeeded"
            for key in keys
        )
        crashed = any(
            self._activity_status(self.checkpoint, key) == "failed"
            for key in keys
        )
        still_output = self._activity_output(f"generate_still:{case.case_id}")
        still_audit_output = self._activity_output(f"audit_still:{case.case_id}")
        video_output = self._activity_output(f"generate_video:{case.case_id}")
        track_output = self._activity_output(f"track_video:{case.case_id}")
        video_audit_output = self._activity_output(f"audit_video:{case.case_id}")
        still_artifact = still_output.get("artifact", {})
        still_audit = still_audit_output.get("audit", {})
        video_artifact = video_output.get("artifact", {})
        track_context = track_output.get("context", {})
        video_audit = video_audit_output.get("audit", {})
        if not isinstance(still_artifact, dict):
            still_artifact = {}
        if not isinstance(still_audit, dict):
            still_audit = {}
        if not isinstance(video_artifact, dict):
            video_artifact = {}
        if not isinstance(track_context, dict):
            track_context = {}
        if not isinstance(video_audit, dict):
            video_audit = {}
        timing_outputs = (
            still_output,
            still_audit_output,
            video_output,
            track_output,
            video_audit_output,
        )
        latency = sum(
            float(item.get("duration_seconds", 0.0))
            for item in timing_outputs
            if isinstance(item.get("duration_seconds", 0.0), (int, float))
        )
        peak_values = [
            float(item.get("peak_vram_gb", 0.0))
            for item in (
                still_artifact,
                still_audit,
                video_artifact,
                track_context,
                video_audit,
            )
            if isinstance(item.get("peak_vram_gb", 0.0), (int, float))
        ]
        still_path = (
            self._bound_run_path(
                still_artifact.get("locator"),
                f"generate_still:{case.case_id}",
            )
            if completed
            else None
        )
        video_path = (
            self._bound_run_path(
                video_artifact.get("locator"),
                f"generate_video:{case.case_id}",
            )
            if completed and case.video_required
            else None
        )
        gate: dict[str, object] = {
            "schema": CASE_GATE_EVIDENCE_SCHEMA,
            "manifest_hash": self.manifest.manifest_hash,
            "case_id": case.case_id,
            "completed": completed,
            "crashed": crashed,
            "repairs": int(still_audit.get("repairs", 0)),
            "unsupported_claim_count": int(
                still_audit.get("unsupported_claim_count", 0)
            ),
            "observation_count": int(still_audit.get("observation_count", 0)),
            "located_observation_count": int(
                still_audit.get("located_observation_count", 0)
            ),
            "image_identity_pass": bool(
                still_audit.get("image_identity_pass", False)
            ),
            "preencode_video_identity_pass": (
                bool(video_audit.get("preencode_video_identity_pass", False))
                if case.video_required
                else None
            ),
            "encoded_video_identity_pass": (
                bool(video_audit.get("encoded_video_identity_pass", False))
                if case.video_required
                else None
            ),
            "audio_video_alignment_pass": (
                bool(video_audit.get("audio_video_alignment_pass", False))
                if case.video_required
                else None
            ),
            "cross_media_pass": bool(
                still_audit.get("cross_media_pass", False)
                and (
                    video_audit.get("cross_media_pass", False)
                    if case.video_required
                    else True
                )
            ),
            "latency_seconds": latency,
            "peak_vram_gb": max(peak_values, default=0.0),
            "output_sha256": (
                str(still_artifact.get("sha256")) if completed else None
            ),
            "video_output_sha256": (
                str(video_artifact.get("sha256"))
                if completed and case.video_required
                else None
            ),
        }
        return gate, still_path, video_path

    def _finalize(self) -> None:
        pending_ids = {case.case_id for case in self.journal.pending_cases}
        for case in self.cases:
            key = f"finalize:{case.case_id}"
            if case.case_id not in pending_ids:
                if self._activity_status(self.checkpoint, key) != "succeeded":
                    self.checkpoint.activities[key] = {
                        "status": "succeeded",
                        "attempts": 1,
                        "output": {"journaled": True, "reconciled": True},
                    }
                    self._append_trace(
                        event_type="activity",
                        activity_key=key,
                        status="succeeded",
                    )
                    self._save()
                continue
            gate, still_path, video_path = self._case_gate(case)
            gate_path = self.run_dir / "gates" / f"{case.case_id}.json"

            def finalize_operation(
                gate: Mapping[str, object] = gate,
                gate_path: Path = gate_path,
                still_path: Path | None = still_path,
                video_path: Path | None = video_path,
                case: BenchmarkCase = case,
            ) -> Mapping[str, object]:
                _write_json_atomic(gate_path, gate)
                self.journal.append(
                    case_id=case.case_id,
                    gate_evidence_path=gate_path,
                    output_path=still_path,
                    video_output_path=video_path,
                )
                return {
                    "journaled": True,
                    "completed": gate["completed"],
                    "crashed": gate["crashed"],
                }

            self._run_activity(
                key=key,
                operation=finalize_operation,
                normalize=lambda value, duration: {
                    **_json_mapping(value, "finalize_case"),
                    "duration_seconds": duration,
                },
            )
            pending_ids.discard(case.case_id)

    def run(self) -> Mapping[str, object]:
        if not self.checkpoint_path.exists():
            self._save()
        for phase in PHASE_ORDER:
            self._execute_phase(phase)
        self._finalize()
        selected_finalized = sum(
            self._activity_status(
                self.checkpoint,
                f"finalize:{case.case_id}",
            )
            == "succeeded"
            for case in self.cases
        )
        failed_activities = sum(
            item.get("status") == "failed"
            for item in self.checkpoint.activities.values()
        )
        return {
            "schema": "ProofLaunchCompetition2XRunSummaryV1",
            "benchmark_id": self.manifest.benchmark_id,
            "manifest_hash": self.manifest.manifest_hash,
            "adapter_identity_hash": self.identity_hash,
            "shard_index": self.shard_index,
            "shard_count": self.shard_count,
            "selected_case_count": len(self.cases),
            "video_case_count": sum(case.video_required for case in self.cases),
            "finalized_case_count": selected_finalized,
            "failed_activity_count": failed_activities,
            "checkpoint_path": str(self.checkpoint_path),
            "results_path": str(self.results_path),
        }


def merge_sharded_results(
    *,
    manifest_path: Path,
    run_dir: Path,
    shard_count: int,
    output_path: Path | None = None,
) -> Mapping[str, object]:
    if shard_count < 2:
        raise BenchmarkRunnerError("merge requires at least two shards")
    manifest = load_frozen_manifest(manifest_path)
    root = run_dir.resolve()
    destination = (
        output_path.resolve()
        if output_path is not None
        else root / "prooflaunch-results.jsonl"
    )
    if destination.parent != root:
        raise BenchmarkRunnerError("merged result journal must be directly under run_dir")
    rows_by_case: dict[str, Mapping[str, object]] = {}
    case_index = {case.case_id: index for index, case in enumerate(manifest.cases)}
    for shard_index in range(shard_count):
        source = root / (
            f"prooflaunch-results.shard-{shard_index:03d}-of-{shard_count:03d}.jsonl"
        )
        journal = CompetitionCaseJournal(manifest_path, source)
        expected = {
            case.case_id
            for index, case in enumerate(manifest.cases)
            if index % shard_count == shard_index
        }
        actual: set[str] = set()
        try:
            lines = source.read_text(encoding="utf-8").splitlines()
        except OSError as error:
            raise BenchmarkRunnerError(f"cannot read shard {source}: {error}") from error
        for line in lines:
            if not line.strip():
                continue
            row = json.loads(line)
            case_id = row.get("case_id")
            if not isinstance(case_id, str):
                raise BenchmarkRunnerError(f"{source}: row lacks case_id")
            if case_id in rows_by_case:
                raise BenchmarkRunnerError(f"duplicate case across shards: {case_id}")
            if case_index.get(case_id, -1) % shard_count != shard_index:
                raise BenchmarkRunnerError(
                    f"{case_id}: result is stored in the wrong shard"
                )
            rows_by_case[case_id] = row
            actual.add(case_id)
        if actual != expected or journal.recorded_count != len(expected):
            missing = sorted(expected - actual)
            raise BenchmarkRunnerError(
                f"shard {shard_index} is incomplete"
                + (f"; first missing {missing[0]}" if missing else "")
            )
    merged = CompetitionCaseJournal(manifest_path, destination)
    pending_ids = {case.case_id for case in merged.pending_cases}
    for case in manifest.cases:
        if case.case_id not in pending_ids:
            continue
        row = rows_by_case[case.case_id]
        gate_locator = row.get("gate_evidence_locator")
        output_locator = row.get("output_locator")
        video_locator = row.get("video_output_locator")
        merged.append(
            case_id=case.case_id,
            gate_evidence_path=root / str(gate_locator),
            output_path=(root / str(output_locator) if output_locator else None),
            video_output_path=(root / str(video_locator) if video_locator else None),
        )
    return {
        "schema": "ProofLaunchCompetition2XShardMergeV1",
        "manifest_hash": manifest.manifest_hash,
        "shard_count": shard_count,
        "merged_case_count": merged.recorded_count,
        "output_path": str(destination),
    }
