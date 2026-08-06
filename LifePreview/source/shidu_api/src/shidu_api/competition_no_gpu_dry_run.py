"""Cross-component pre-click dry-run with an explicit no-GPU boundary.

This module is deliberately not a fake 73-frame renderer.  It drives the real
HTTP API, deferred-job row, production claimant/coordinator, persistent
checkpoint, operation/attempt repositories, CAS publisher, signer, and
artifact route.  FLUX and H3 execution are the only deterministic execution
stubs.  The delivered artifact is JSON evidence marked ``DRY-RUN-NO-GPU``;
it is never projected as a video and never claims that frames or audio were
rendered.

The CPU stage bundle is injected and may be supplied as a late-bound
``module:function`` factory.  A live deployment still needs that factory to
bind the real source preparation, reference publication, authority
finalization, and deferred-workflow materialization functions.  Importing this
module, building a factory, or polling before the isolated test click performs
no GPU-capable import or process start.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from hashlib import sha256
import importlib
import json
import os
from pathlib import Path
import re
import struct
from typing import Any, Literal, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5
import zlib

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from creative_hub.artifact_proxy import RemoteArtifact
from creative_hub.artifact_publication import (
    ArtifactPublicationService,
    ArtifactStatus,
    ContentAddressedArtifactStore,
    PostgresArtifactRepository,
)
from creative_hub.db.canonical import canonical_json_digest
from creative_hub.db.models import (
    ArtifactPublicationClaimRecord,
    ArtifactRecordRow,
    OperationAttemptRecord,
    OperationAttemptStateRecord,
    OperationRunRecord,
    ProductCommandLedgerRecord,
    ProjectRecord,
    VideoJobProjectionRecord,
)
from creative_hub.db.repositories import OperationRepository
from shared_contracts import RetentionClass

from .competition_vertical_slice_daemon import (
    AtomicPersistentCheckpointPort,
    CompetitionDaemonContext,
    PostgresDeferredJobPort,
    ProductionStageFunctions,
    StageFactory,
    StageFunction,
    StageInvocation,
    build_competition_vertical_slice_daemon,
)
from .competition_vertical_slice_worker import (
    CheckpointPort,
    ClickedDeferredVideoJob,
    CoordinatorContractError,
    WorkerCheckpoint,
    WorkerStage,
)
from .security import ArtifactTokenSigner


SessionFactory = Callable[[], Session]
DRY_RUN_MARKER = "DRY-RUN-NO-GPU"
DRY_RUN_OWNER = "shidu_dry_run"
DRY_RUN_SCHEMA = "amd.competition-no-gpu-dry-run.v1"
DRY_RUN_AUTHORITY_FIELD = "competitionNoGpuDryRunAuthority"
DRY_RUN_EVIDENCE_FIELD = "competitionNoGpuDryRunEvidence"
DRY_RUN_EVIDENCE_ROLE = "dry_run_no_gpu_evidence"
LIVE_STAGE_FACTORY_DEPENDENCY = (
    "A production StageFactory must bind source_prepared, "
    "references_published, authority_finalized, and workflow_materialized "
    "to their live CPU/durable implementations and accept the explicit "
    "DRY-RUN-NO-GPU FLUX/H3 receipts."
)

_STAGE_ORDER: tuple[WorkerStage, ...] = (
    "source_prepared",
    "flux_generated",
    "references_published",
    "authority_finalized",
    "workflow_materialized",
    "h3_generated",
    "delivered",
)
_GPU_STAGES = frozenset({"flux_generated", "h3_generated"})
_DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")
_RANGE_RE = re.compile(r"bytes=([0-9]+)-([0-9]*)\Z")
_IMPLEMENTATION_DIGEST = sha256(
    b"amd.competition-no-gpu-dry-run.v1|evidence-only|no-rendered-media"
).hexdigest()
_PRECLICK_MEMORY_LIMIT_BYTES = 44 * 1024**3
_GPU_PROCESS_MARKERS = (
    "comfyui/main.py",
    "run-three-second-vertical-slice.py",
    "run-h3-production-smoke.py",
    "start-gpu-after-user-click.sh",
    "h3-production-smoke",
)


class CompetitionNoGpuDryRunError(RuntimeError):
    """The isolated no-GPU proof could not be completed truthfully."""


class SimulatedNoGpuRestart(RuntimeError):
    """Test-only process boundary raised after a durable checkpoint save."""


class HttpClient(Protocol):
    def post(
        self,
        url: str,
        *,
        json: Mapping[str, Any],
        headers: Mapping[str, str],
    ) -> Any: ...

    def head(self, url: str, *, headers: Mapping[str, str] | None = None) -> Any: ...

    def get(self, url: str, *, headers: Mapping[str, str] | None = None) -> Any: ...


def frozen_no_gpu_contract() -> dict[str, object]:
    """Return a fresh, unambiguous requested-vs-observed dry-run contract."""

    return {
        "schemaVersion": DRY_RUN_SCHEMA,
        "marker": DRY_RUN_MARKER,
        "artifactKind": "cross-component-evidence-only",
        "requestedDurationSeconds": 3.0,
        "requestedFrameCount": 73,
        "requestedFps": 24,
        "requestedNativeAudio": True,
        "requestedSubtitles": False,
        "mediaRendered": False,
        "renderedFrameCount": 0,
        "renderedAudioStreams": 0,
    }


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _strict_digest(value: object, field: str) -> str:
    if type(value) is not str or _DIGEST_RE.fullmatch(value) is None:
        raise CompetitionNoGpuDryRunError(f"{field} must be a lowercase SHA-256")
    return value


def _standard_json_object(value: object, field: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise CompetitionNoGpuDryRunError(f"{field} must be a JSON object")
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        decoded = json.loads(encoded)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise CompetitionNoGpuDryRunError(f"{field} must be standard JSON") from exc
    if type(decoded) is not dict:
        raise CompetitionNoGpuDryRunError(f"{field} must be a JSON object")
    return decoded


def _validate_gpu_disabled_proof(value: object) -> dict[str, Any]:
    proof = _standard_json_object(value, "GPU-disabled proof")
    if (
        proof.get("marker") != "GPU-DISABLED-BEFORE-FINAL-USER-CLICK"
        or proof.get("gpuEnabled") is not False
        or proof.get("comfyUiProcessCount") != 0
        or proof.get("finalUserClickPerformed") is not False
    ):
        raise CompetitionNoGpuDryRunError(
            "GPU-disabled proof does not show a closed final-user click gate"
        )
    return proof


def probe_live_gpu_disabled_state(
    *,
    cgroup_root: Path = Path("/sys/fs/cgroup"),
    proc_root: Path = Path("/proc"),
    memory_limit_bytes: int = _PRECLICK_MEMORY_LIMIT_BYTES,
    process_markers: tuple[str, ...] = _GPU_PROCESS_MARKERS,
) -> dict[str, Any]:
    """Read the live cgroup/procfs gate without starting GPU or network work."""

    if type(memory_limit_bytes) is not int or memory_limit_bytes < 1:
        raise ValueError("GPU-disabled memory limit is invalid")
    if (
        type(process_markers) is not tuple
        or not process_markers
        or any(type(marker) is not str or not marker for marker in process_markers)
    ):
        raise ValueError("GPU process markers are invalid")
    cgroup = Path(cgroup_root)
    proc = Path(proc_root)

    def read_int(name: str) -> int:
        try:
            value = int((cgroup / name).read_text(encoding="utf-8").strip())
        except (OSError, UnicodeError, ValueError) as exc:
            raise CompetitionNoGpuDryRunError(
                f"live cgroup authority is unavailable: {name}"
            ) from exc
        if value < 0:
            raise CompetitionNoGpuDryRunError(
                f"live cgroup authority is invalid: {name}"
            )
        return value

    def read_pairs(name: str) -> dict[str, int]:
        try:
            lines = (cgroup / name).read_text(encoding="utf-8").splitlines()
            values = {
                key: int(raw)
                for key, raw in (line.split(maxsplit=1) for line in lines)
            }
        except (OSError, UnicodeError, ValueError) as exc:
            raise CompetitionNoGpuDryRunError(
                f"live cgroup authority is unavailable: {name}"
            ) from exc
        if any(value < 0 for value in values.values()):
            raise CompetitionNoGpuDryRunError(
                f"live cgroup authority is invalid: {name}"
            )
        return values

    current = read_int("memory.current")
    try:
        maximum_raw = (cgroup / "memory.max").read_text(encoding="utf-8").strip()
        maximum = None if maximum_raw == "max" else int(maximum_raw)
    except (OSError, UnicodeError, ValueError) as exc:
        raise CompetitionNoGpuDryRunError(
            "live cgroup authority is unavailable: memory.max"
        ) from exc
    if maximum is not None and maximum < 1:
        raise CompetitionNoGpuDryRunError(
            "live cgroup authority is invalid: memory.max"
        )
    memory_stat = read_pairs("memory.stat")
    events = read_pairs("memory.events.local")
    active: list[dict[str, object]] = []
    try:
        entries = tuple(proc.iterdir())
    except OSError as exc:
        raise CompetitionNoGpuDryRunError("live procfs authority is unavailable") from exc
    normalized_markers = tuple(marker.casefold() for marker in process_markers)
    for entry in entries:
        if not entry.name.isdecimal() or int(entry.name) == os.getpid():
            continue
        try:
            raw = (entry / "cmdline").read_bytes()
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        except OSError as exc:
            raise CompetitionNoGpuDryRunError(
                "live process authority is unavailable"
            ) from exc
        command = raw.replace(b"\0", b" ").decode("utf-8", errors="replace").strip()
        folded = command.casefold()
        matches = [
            process_markers[index]
            for index, marker in enumerate(normalized_markers)
            if marker in folded
        ]
        if matches:
            active.append({"pid": int(entry.name), "markers": matches})
    if current >= memory_limit_bytes:
        raise CompetitionNoGpuDryRunError(
            "GPU-disabled pre-click gate exceeds the 44 GiB cgroup limit"
        )
    if active:
        raise CompetitionNoGpuDryRunError(
            "GPU-disabled pre-click gate found a FLUX/H3/ComfyUI process"
        )
    return {
        "marker": "GPU-DISABLED-BEFORE-FINAL-USER-CLICK",
        "gpuEnabled": False,
        "comfyUiProcessCount": 0,
        "acceleratorProcessCount": 0,
        "finalUserClickPerformed": False,
        "proofSource": "cgroup-v2-plus-procfs",
        "memoryCurrentBytes": current,
        "memoryMaxBytes": maximum,
        "memoryLimitBytes": memory_limit_bytes,
        "fileCacheBytes": memory_stat.get("file", 0),
        "anonymousBytes": memory_stat.get("anon", 0),
        "memoryEventsLocal": events,
        "activeProcessMatches": [],
    }


def _safe_persistent_root(root: Path, persistent_root: Path) -> tuple[Path, Path]:
    anchor = Path(persistent_root).absolute()
    location = Path(root).absolute()
    anchor.mkdir(parents=True, exist_ok=True)
    if anchor.is_symlink():
        raise ValueError("dry-run persistent root symlinks are forbidden")
    resolved_anchor = anchor.resolve(strict=True)
    try:
        relative = location.relative_to(anchor)
    except ValueError as exc:
        raise ValueError("dry-run evidence must stay in persistent storage") from exc
    current = anchor
    for part in relative.parts:
        current = current / part
        if current.exists() and current.is_symlink():
            raise ValueError("dry-run evidence directory symlinks are forbidden")
    location.mkdir(parents=True, exist_ok=True)
    resolved = location.resolve(strict=True)
    try:
        resolved.relative_to(resolved_anchor)
    except ValueError as exc:
        raise ValueError("dry-run evidence must stay in persistent storage") from exc
    return resolved, resolved_anchor


@contextmanager
def _locked_file(path: Path):
    if path.is_symlink():
        raise CompetitionNoGpuDryRunError("dry-run audit lock symlinks are forbidden")
    handle = path.open("a+b")
    try:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    body = json.dumps(
        dict(payload),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.partial")
    try:
        with temporary.open("xb") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_bytes(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.is_symlink() or path.read_bytes() != body:
            raise CompetitionNoGpuDryRunError("dry-run artifact changed on replay")
        return
    temporary = path.with_name(f".{path.name}.{os.getpid()}.partial")
    try:
        with temporary.open("xb") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.is_symlink() or path.read_bytes() != body:
                raise CompetitionNoGpuDryRunError(
                    "dry-run artifact changed on concurrent publication"
                )
    finally:
        temporary.unlink(missing_ok=True)


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


def _deterministic_reference_png(*, width: int = 512, height: int = 768) -> bytes:
    """Return the one fully-decodable RGB PNG used as dry-run FLUX output."""

    if type(width) is not int or type(height) is not int or width <= 0 or height <= 0:
        raise ValueError("deterministic PNG dimensions are invalid")
    pixel = bytes((80, 72, 56))
    scanline = b"\x00" + pixel * width
    pixels = scanline * height
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + _png_chunk(b"IDAT", zlib.compress(pixels, level=9))
        + _png_chunk(b"IEND", b"")
    )


class PersistentStageInvocationLedger:
    """Durable execute-once wrapper for all seven coordinator boundaries."""

    def __init__(
        self,
        *,
        root: Path,
        persistent_root: Path,
        authority_id: UUID,
    ) -> None:
        if not isinstance(authority_id, UUID):
            raise ValueError("dry-run authority_id must be a UUID")
        base, _anchor = _safe_persistent_root(root, persistent_root)
        self.root = base / str(authority_id)
        self.root.mkdir(parents=True, exist_ok=True)
        if self.root.is_symlink():
            raise ValueError("dry-run invocation ledger symlinks are forbidden")
        self.authority_id = authority_id

    def _path(self, stage: WorkerStage) -> Path:
        if stage not in _STAGE_ORDER:
            raise ValueError("dry-run stage is invalid")
        return self.root / f"{stage}.json"

    @staticmethod
    def _record_digest(record: Mapping[str, Any]) -> str:
        return canonical_json_digest(
            {
                key: value
                for key, value in record.items()
                if key not in {"recordDigest", "replayCount"}
            }
        )

    @staticmethod
    def _invocation_identity(invocation: StageInvocation) -> dict[str, Any]:
        return {
            "jobAuthorityDigest": invocation.job.authority_digest,
            "externalJobId": invocation.job.external_job_id,
            "idempotencyKey": invocation.idempotency_key,
            "priorReceiptDigests": [
                receipt.receipt_digest for receipt in invocation.prior_receipts
            ],
        }

    def invoke(
        self,
        invocation: StageInvocation,
        function: StageFunction,
        *,
        executor_kind: Literal["production-boundary", "deterministic-no-gpu-stub"],
    ) -> dict[str, Any]:
        if not isinstance(invocation, StageInvocation) or invocation.stage not in _STAGE_ORDER:
            raise CoordinatorContractError("dry-run stage invocation is invalid")
        if not callable(function):
            raise ValueError("dry-run stage function is invalid")
        path = self._path(invocation.stage)
        lock = path.with_suffix(".lock")
        identity = self._invocation_identity(invocation)
        with _locked_file(lock):
            if path.exists():
                try:
                    record = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                    raise CompetitionNoGpuDryRunError(
                        "dry-run invocation ledger is unavailable"
                    ) from exc
                if (
                    type(record) is not dict
                    or record.get("marker") != DRY_RUN_MARKER
                    or record.get("authorityId") != str(self.authority_id)
                    or record.get("stage") != invocation.stage
                    or record.get("invocation") != identity
                    or record.get("executorKind") != executor_kind
                    or record.get("executionCount") != 1
                    or type(record.get("result")) is not dict
                    or record.get("recordDigest") != self._record_digest(record)
                ):
                    raise CompetitionNoGpuDryRunError(
                        "dry-run invocation replay authority changed"
                    )
                replayed = {**record, "replayCount": int(record.get("replayCount", 0)) + 1}
                _atomic_json(path, replayed)
                return dict(record["result"])

            result_value = function(invocation)
            if not isinstance(result_value, Mapping):
                raise CoordinatorContractError(
                    f"{invocation.stage} returned an invalid dry-run receipt"
                )
            result = _standard_json_object(dict(result_value), "dry-run stage result")
            _strict_digest(result.get("outputDigest"), "dry-run stage outputDigest")
            record = {
                "schemaVersion": "amd.no-gpu-stage-invocation.v1",
                "marker": DRY_RUN_MARKER,
                "authorityId": str(self.authority_id),
                "stage": invocation.stage,
                "executorKind": executor_kind,
                "executionCount": 1,
                "replayCount": 0,
                "invocation": identity,
                "result": result,
            }
            record["recordDigest"] = self._record_digest(record)
            _atomic_json(path, record)
            return result

    def summary(self) -> dict[str, dict[str, int | str]]:
        summary: dict[str, dict[str, int | str]] = {}
        for stage in _STAGE_ORDER:
            path = self._path(stage)
            if not path.is_file() or path.is_symlink():
                raise CompetitionNoGpuDryRunError(
                    f"dry-run stage audit is missing: {stage}"
                )
            value = json.loads(path.read_text(encoding="utf-8"))
            if (
                type(value) is not dict
                or value.get("marker") != DRY_RUN_MARKER
                or value.get("authorityId") != str(self.authority_id)
                or value.get("stage") != stage
                or value.get("recordDigest") != self._record_digest(value)
            ):
                raise CompetitionNoGpuDryRunError(
                    f"dry-run stage audit is invalid: {stage}"
                )
            summary[stage] = {
                "executorKind": str(value["executorKind"]),
                "executionCount": int(value["executionCount"]),
                "replayCount": int(value["replayCount"]),
            }
        return summary


def _deterministic_gpu_stub(invocation: StageInvocation) -> dict[str, Any]:
    if invocation.stage not in _GPU_STAGES:
        raise CoordinatorContractError("no-GPU stub is restricted to FLUX/H3")
    identity = {
        "schemaVersion": "amd.deterministic-no-gpu-executor.v1",
        "marker": DRY_RUN_MARKER,
        "stage": invocation.stage,
        "jobAuthorityDigest": invocation.job.authority_digest,
        "idempotencyKey": invocation.idempotency_key,
        "priorReceiptDigests": [
            receipt.receipt_digest for receipt in invocation.prior_receipts
        ],
        "requestedContract": frozen_no_gpu_contract(),
        "mediaRendered": False,
        "renderedFrameCount": 0,
        "gpuProcessStarted": False,
        "comfyUiStarted": False,
    }
    return {**identity, "outputDigest": canonical_json_digest(identity)}


def _deterministic_flux_stub(
    invocation: StageInvocation,
    *,
    production_flux_stage: StageFunction,
    ledger: PersistentStageInvocationLedger,
) -> dict[str, Any]:
    """Prepare the real click authority, then replace only GPU execution."""

    if invocation.stage != "flux_generated":
        raise CoordinatorContractError("FLUX dry-run stub owns only flux_generated")
    owner = getattr(production_flux_stage, "__self__", None)
    prepare_authority = getattr(owner, "_ensure_click_authority", None)
    runner_arguments = getattr(owner, "_runner_arguments", None)
    prompt_authority_reader = getattr(owner, "_prompt_authority", None)
    if (
        not callable(prepare_authority)
        or not callable(runner_arguments)
        or not callable(prompt_authority_reader)
    ):
        raise CompetitionNoGpuDryRunError(
            "production FLUX stage lacks the authority-preparation boundary"
        )
    prepare_authority(invocation)
    arguments = runner_arguments(invocation)
    prompt_authority = prompt_authority_reader(invocation)
    try:
        click_path = Path(arguments.click_authority).resolve(strict=True)
        click = json.loads(click_path.read_text(encoding="utf-8"))
        workflow_path = Path(click["workflowPath"]).resolve(strict=True)
        workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
        generation = workflow["fluxReferenceGeneration"]
        prompt = generation["prompt"]
        seed = generation["seed"]
        if (
            type(prompt) is not str
            or not prompt
            or type(seed) is not int
            or isinstance(seed, bool)
            or seed < 0
        ):
            raise ValueError
        prompt_sha = sha256(prompt.encode("utf-8")).hexdigest()
        if generation.get("promptSha256", prompt_sha) != prompt_sha:
            raise ValueError
        authority_workflow_sha = _sha256_file(workflow_path)
        workflow_sha = _strict_digest(
            generation.get("workflowSha256"),
            "production FLUX workflowSha256",
        )
        logical_prompt_id = click["promptId"]
        if type(logical_prompt_id) is not str or not logical_prompt_id:
            raise ValueError
        checkpoint_path = Path(arguments.checkpoint).absolute()
    except (AttributeError, KeyError, OSError, UnicodeError, ValueError) as exc:
        raise CompetitionNoGpuDryRunError(
            "production FLUX authority was not persisted"
        ) from exc
    view = "front_three_quarter"
    try:
        from drama.flux2_reference import (
            compile_flux2_workflow,
            load_flux2_dev_capability,
            load_flux2_workflow_templates,
        )

        loaded_flux = load_flux2_dev_capability(
            Path(owner.flux_manifest), verify_files=False
        )
        templates = load_flux2_workflow_templates(
            Path(owner.flux_workflow_root), loaded_flux.capability
        )
        compiled = compile_flux2_workflow(
            role="text_to_image",
            templates=templates,
            capability=loaded_flux.capability,
            prompt=prompt,
            width=512,
            height=768,
            seed=seed,
            reference_images=(),
            filename_prefix=f"vertical-slice/{logical_prompt_id}/{view}",
        )
        compiled_workflow_sha = _strict_digest(
            compiled.workflow_digest,
            "compiled FLUX workflow SHA256",
        )
    except (AttributeError, OSError, TypeError, ValueError) as exc:
        raise CompetitionNoGpuDryRunError(
            "production FLUX workflow could not be compiled without GPU"
        ) from exc

    prepared_binding = getattr(invocation.job, "prepared_reference", None)
    if prepared_binding is not None:
        prepared_loader = getattr(owner, "prepared_reference_loader", None)
        if not callable(prepared_loader):
            raise CompetitionNoGpuDryRunError(
                "production imported-reference loader is unavailable"
            )
        try:
            prepared = prepared_loader(prompt_authority)
            row = prepared["reference"]
            path = Path(row["path"]).resolve(strict=True)
            digest = _strict_digest(row["sha256"], "imported reference SHA256")
            import_authority = _strict_digest(
                prepared["importAuthoritySha256"],
                "imported reference authority SHA256",
            )
            if (
                prepared["schemaVersion"]
                != "amd.competition-imported-reference.v1"
                or prepared["status"] != "prepared"
                or prepared["referenceProfile"]
                != "competition-imported-single-view-v1"
                or prepared["sourceMode"] != "preuploaded_imported"
                or prepared["requiredImages"] != 1
                or prepared["fluxRuntimeProofPromptAuthority"] != prompt_authority
                or row["viewName"] != view
                or row["generatedByCurrentFlux"] is not False
                or row["importedBeforeUserClick"] is not True
                or _sha256_file(path) != digest
                or not isinstance(prepared_binding, Mapping)
                or prepared_binding.get("artifactSha256") != digest
                or prepared_binding.get("importAuthoritySha256")
                != import_authority
            ):
                raise ValueError
        except (KeyError, OSError, TypeError, ValueError) as exc:
            raise CompetitionNoGpuDryRunError(
                "production imported-reference authority is invalid"
            ) from exc
        proof_prompt_id = str(
            uuid5(
                NAMESPACE_URL,
                f"dry-run-flux-proof:{invocation.job.authority_digest}",
            )
        )
        reference = {
            "viewName": view,
            "path": str(path),
            "sha256": digest,
            "sourceMode": "preuploaded_imported",
            "generatedByCurrentFlux": False,
            "fluxOutputUsed": False,
            "importAuthoritySha256": import_authority,
            "fluxProofPromptId": proof_prompt_id,
            "fluxProofQueueId": 0,
            "promptSha256": prompt_sha,
            "seed": seed,
            "workflowSha256": workflow_sha,
            "compiledWorkflowSha256": compiled_workflow_sha,
            "generationAttemptOrdinal": 0,
            "technicalFailureReceiptSha256": None,
        }
        proof = {
            "schemaVersion": "amd.flux-runtime-proof.dry-run.v1",
            "marker": DRY_RUN_MARKER,
            "status": "dry_run_no_gpu",
            "promptId": proof_prompt_id,
            "queueId": 0,
            "gpuActivity": {"gpuActivityObserved": False},
            "outputUsedByH3": False,
            "processExited": True,
            "vramIdleAfterStop": True,
        }
        identity = {
            "schemaVersion": "amd.flux-runtime-proof-stage.v1",
            "marker": DRY_RUN_MARKER,
            "reference": reference,
            "referenceProfile": "competition-imported-single-view-v1",
            "sourceMode": "preuploaded_imported",
            "requiredImages": 1,
            "generationInvocationCount": 1,
            "fluxRuntimeProof": proof,
            "runnerCheckpointPath": str(checkpoint_path),
            "authorityPreparationPath": str(click_path),
            "authorityPreparationSha256": _sha256_file(click_path),
            "authorityWorkflowSha256": authority_workflow_sha,
            "requestedContract": frozen_no_gpu_contract(),
            "mediaRendered": False,
            "renderedFrameCount": 0,
            "gpuProcessStarted": False,
            "comfyUiStarted": False,
        }
        return {**identity, "outputDigest": canonical_json_digest(identity)}

    reference_root = ledger.root / "deterministic-reference-assets"
    body = _deterministic_reference_png()
    digest = sha256(body).hexdigest()
    path = reference_root / f"01-{view}-{digest[:16]}.png"
    _atomic_bytes(path, body)
    reference = {
        "viewName": view,
        "path": str(path),
        "sha256": digest,
        "promptId": str(
            uuid5(
                NAMESPACE_URL,
                f"dry-run-flux:{invocation.job.authority_digest}:{view}",
            )
        ),
        "promptSha256": prompt_sha,
        "seed": seed,
        "workflowSha256": workflow_sha,
        "compiledWorkflowSha256": compiled_workflow_sha,
        "generationAttemptOrdinal": 0,
        "technicalFailureReceiptSha256": None,
    }
    identity = {
        "schemaVersion": "amd.flux-generated-stage.v2",
        "marker": DRY_RUN_MARKER,
        "reference": reference,
        "referenceProfile": "competition-prompt-single-view-v1",
        "sourceMode": "prompt_synthesized",
        "requiredImages": 1,
        "generationInvocationCount": 1,
        "runnerCheckpointPath": str(checkpoint_path),
        "authorityPreparationPath": str(click_path),
        "authorityPreparationSha256": _sha256_file(click_path),
        "authorityWorkflowSha256": authority_workflow_sha,
        "requestedContract": frozen_no_gpu_contract(),
        "mediaRendered": False,
        "renderedFrameCount": 0,
        "gpuProcessStarted": False,
        "comfyUiStarted": False,
    }
    return {**identity, "outputDigest": canonical_json_digest(identity)}


class DryRunEvidencePublisher:
    """Publish JSON proof through the real attempt-aware CAS service."""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        cas_root: Path,
        authority_id: UUID,
    ) -> None:
        if not callable(session_factory) or not isinstance(authority_id, UUID):
            raise ValueError("dry-run evidence publisher configuration is invalid")
        self._sessions = session_factory
        self._cas_root = Path(cas_root)
        self._authority_id = authority_id

    def __call__(self, invocation: StageInvocation) -> dict[str, Any]:
        if invocation.stage != "delivered":
            raise CoordinatorContractError("dry-run publisher owns only delivery")
        stages = tuple(receipt.stage for receipt in invocation.prior_receipts)
        if stages != _STAGE_ORDER[:-1]:
            raise CoordinatorContractError("dry-run delivery receipts are incomplete")
        by_stage = {receipt.stage: receipt for receipt in invocation.prior_receipts}
        for stage in _GPU_STAGES:
            payload = by_stage[stage].payload
            if (
                payload.get("marker") != DRY_RUN_MARKER
                or payload.get("mediaRendered") is not False
                or payload.get("renderedFrameCount") != 0
                or payload.get("gpuProcessStarted") is not False
            ):
                raise CoordinatorContractError(
                    "dry-run GPU receipt attempted to claim rendered media"
                )

        job = invocation.job
        with self._sessions() as session, session.begin():
            row = session.scalar(
                select(VideoJobProjectionRecord)
                .where(
                    VideoJobProjectionRecord.project_id == job.project_id,
                    VideoJobProjectionRecord.external_job_id == job.external_job_id,
                )
                .with_for_update()
            )
            if row is None:
                raise CoordinatorContractError("dry-run job disappeared")
            authority = _standard_json_object(
                row.payload.get(DRY_RUN_AUTHORITY_FIELD), "dry-run authority"
            )
            if (
                authority.get("marker") != DRY_RUN_MARKER
                or authority.get("authorityId") != str(self._authority_id)
                or authority.get("authorityDigest")
                != canonical_json_digest(
                    {
                        key: value
                        for key, value in authority.items()
                        if key != "authorityDigest"
                    }
                )
            ):
                raise CoordinatorContractError("dry-run authority is invalid")
            try:
                workflow_run_id = UUID(str(row.payload["workflowRunId"]))
            except (KeyError, TypeError, ValueError) as exc:
                raise CoordinatorContractError(
                    "dry-run workflow was not materialized"
                ) from exc
            evidence = {
                "schemaVersion": DRY_RUN_SCHEMA,
                "marker": DRY_RUN_MARKER,
                "authorityId": str(self._authority_id),
                "authorityDigest": authority["authorityDigest"],
                "projectId": str(job.project_id),
                "externalJobId": job.external_job_id,
                "jobAuthorityDigest": job.authority_digest,
                "requestedContract": frozen_no_gpu_contract(),
                "mediaRendered": False,
                "renderedFrameCount": 0,
                "nativeAudioRendered": False,
                "subtitleTrackRendered": False,
                "stageReceiptDigests": [
                    receipt.receipt_digest for receipt in invocation.prior_receipts
                ],
            }
            evidence["evidenceDigest"] = canonical_json_digest(evidence)
            operations = OperationRepository(session)
            operation = operations.create_operation_run(
                project_id=job.project_id,
                workflow_run_id=workflow_run_id,
                node_key="competition.no-gpu.dry-run.evidence",
                op_type="competition.no-gpu.dry-run.evidence.publish",
                op_version="1",
                command_idempotency_key=(
                    f"dry-run-no-gpu:evidence:{job.authority_digest}"
                ),
                request_payload=evidence,
                operation_run_id=uuid5(
                    NAMESPACE_URL,
                    f"dry-run-operation:{job.project_id}:{job.authority_digest}",
                ),
            ).value
            attempt_id = uuid5(
                NAMESPACE_URL,
                f"dry-run-attempt:{job.project_id}:{job.authority_digest}",
            )
            attempt = operations.create_attempt(
                project_id=job.project_id,
                operation_run_id=operation.id,
                attempt_number=1,
                fencing_token=1,
                worker_id=DRY_RUN_MARKER,
                implementation_digest=_IMPLEMENTATION_DIGEST,
                request_payload=evidence,
                submission_nonce=uuid5(
                    NAMESPACE_URL,
                    f"dry-run-nonce:{job.project_id}:{job.authority_digest}",
                ),
                attempt_id=attempt_id,
            ).value
            operation_run_id = operation.id

        body = json.dumps(
            evidence,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        content_digest = sha256(body).hexdigest()
        publication = ArtifactPublicationService(
            repository=PostgresArtifactRepository(self._sessions),
            store=ContentAddressedArtifactStore(self._cas_root),
        )
        artifact = publication.publish(
            project_id=job.project_id,
            operation_run_id=operation_run_id,
            attempt_id=attempt.id,
            attempt_number=1,
            fencing_token=1,
            publication_key=f"dry-run-no-gpu:{job.external_job_id}",
            stream=(body,),
            mime_type="application/json",
            logical_role=DRY_RUN_EVIDENCE_ROLE,
            retention_class=RetentionClass.AUDIT,
            expected_digest=content_digest,
            expected_size=len(body),
        )
        if artifact.status is not ArtifactStatus.COMMITTED:
            raise CompetitionNoGpuDryRunError("dry-run evidence did not commit to CAS")

        persisted_evidence = {
            "schemaVersion": DRY_RUN_SCHEMA,
            "marker": DRY_RUN_MARKER,
            "authorityId": str(self._authority_id),
            "artifactId": str(artifact.artifact_id),
            "artifactDigest": artifact.content_digest,
            "byteSize": artifact.byte_size,
            "mimeType": "application/json",
            "logicalRole": DRY_RUN_EVIDENCE_ROLE,
            "mediaRendered": False,
            "renderedFrameCount": 0,
        }
        persisted_evidence["recordDigest"] = canonical_json_digest(
            persisted_evidence
        )
        with self._sessions() as session, session.begin():
            operations = OperationRepository(session)
            state = session.get(OperationAttemptStateRecord, attempt.id)
            if state is None:
                raise CoordinatorContractError("dry-run attempt state disappeared")
            if state.status != "SUCCEEDED":
                operations.compare_and_set_attempt_state(
                    attempt_id=attempt.id,
                    project_id=job.project_id,
                    expected_state_version=state.state_version,
                    status="SUCCEEDED",
                    stage="DRY_RUN_EVIDENCE_COMMITTED",
                    event_type="DRY_RUN_NO_GPU_SUCCEEDED",
                    event_data={"marker": DRY_RUN_MARKER},
                    metrics={
                        "media_rendered": False,
                        "rendered_frame_count": 0,
                        "gpu_process_started": False,
                    },
                )
            operation = session.get(OperationRunRecord, operation_run_id)
            if operation is None:
                raise CoordinatorContractError("dry-run operation disappeared")
            operations.accept_attempt(
                operation_run_id=operation.id,
                attempt_id=attempt.id,
                project_id=job.project_id,
                expected_state_version=operation.state_version,
            )
            row = session.scalar(
                select(VideoJobProjectionRecord)
                .where(
                    VideoJobProjectionRecord.project_id == job.project_id,
                    VideoJobProjectionRecord.external_job_id == job.external_job_id,
                )
                .with_for_update()
            )
            if row is None:
                raise CoordinatorContractError("dry-run job disappeared")
            payload = dict(row.payload)
            replay = payload.get(DRY_RUN_EVIDENCE_FIELD)
            if replay is not None and replay != persisted_evidence:
                raise CoordinatorContractError("dry-run evidence changed on replay")
            payload[DRY_RUN_EVIDENCE_FIELD] = persisted_evidence
            row.payload = payload
            session.flush()
        return {
            "schemaVersion": DRY_RUN_SCHEMA,
            "marker": DRY_RUN_MARKER,
            "outputDigest": artifact.content_digest,
            "artifactId": str(artifact.artifact_id),
            "artifactKind": "cross-component-evidence-only",
            "mediaRendered": False,
            "renderedFrameCount": 0,
        }


def build_no_gpu_stage_factory(
    *,
    base_stage_factory: StageFactory,
    ledger: PersistentStageInvocationLedger,
    evidence_publisher: DryRunEvidencePublisher,
) -> StageFactory:
    """Wrap a late-created CPU bundle; only FLUX/H3 use execution stubs."""

    if not callable(base_stage_factory):
        raise ValueError("base competition stage factory is invalid")
    if not isinstance(ledger, PersistentStageInvocationLedger):
        raise ValueError("dry-run invocation ledger is invalid")
    if not isinstance(evidence_publisher, DryRunEvidencePublisher):
        raise ValueError("dry-run evidence publisher is invalid")

    def factory(context: CompetitionDaemonContext) -> ProductionStageFunctions:
        base = base_stage_factory(context)
        if not isinstance(base, ProductionStageFunctions):
            raise CompetitionNoGpuDryRunError(
                "base stage factory did not return ProductionStageFunctions"
            )

        def production(stage: WorkerStage) -> StageFunction:
            function = base.for_stage(stage)

            def execute(invocation: StageInvocation) -> Mapping[str, Any]:
                def invoke_production(_current: StageInvocation) -> Mapping[str, Any]:
                    return function(invocation)

                return ledger.invoke(
                    invocation,
                    invoke_production,
                    executor_kind="production-boundary",
                )

            return execute

        production_flux_stage = base.for_stage("flux_generated")

        def gpu_stub(invocation: StageInvocation) -> Mapping[str, Any]:
            function: StageFunction
            if invocation.stage == "flux_generated":
                function = lambda current: _deterministic_flux_stub(
                    current,
                    production_flux_stage=production_flux_stage,
                    ledger=ledger,
                )
            elif invocation.stage == "h3_generated":
                if not any(
                    receipt.stage == "workflow_materialized"
                    for receipt in invocation.prior_receipts
                ):
                    raise CoordinatorContractError(
                        "H3 dry-run requires a real materialized workflow"
                    )
                function = _deterministic_gpu_stub
            else:
                raise CoordinatorContractError(
                    "no-GPU stub is restricted to FLUX/H3"
                )
            return ledger.invoke(
                invocation,
                function,
                executor_kind="deterministic-no-gpu-stub",
            )

        def publish_evidence(invocation: StageInvocation) -> Mapping[str, Any]:
            return ledger.invoke(
                invocation,
                evidence_publisher,
                executor_kind="production-boundary",
            )

        return ProductionStageFunctions(
            source_prepared=production("source_prepared"),
            flux_generated=gpu_stub,
            references_published=production("references_published"),
            authority_finalized=production("authority_finalized"),
            workflow_materialized=production("workflow_materialized"),
            h3_generated=gpu_stub,
            delivered=publish_evidence,
        )

    return factory


def late_bound_stage_factory(specification: str) -> StageFactory:
    """Import the deployment's CPU stage factory only after a job is claimed."""

    if type(specification) is not str or specification.count(":") != 1:
        raise ValueError("stage factory must use module:function")
    module_name, attribute = specification.split(":", 1)
    if not module_name or not attribute:
        raise ValueError("stage factory must use module:function")

    def factory(context: CompetitionDaemonContext) -> ProductionStageFunctions:
        try:
            function = getattr(importlib.import_module(module_name), attribute)
        except (ImportError, AttributeError) as exc:
            raise CompetitionNoGpuDryRunError(
                f"live stage factory is unavailable. {LIVE_STAGE_FACTORY_DEPENDENCY}"
            ) from exc
        value = function(context)
        if not isinstance(value, ProductionStageFunctions):
            raise CompetitionNoGpuDryRunError(
                "live stage factory returned the wrong type"
            )
        return value

    return factory


class RestartAfterStageCheckpointPort(CheckpointPort):
    """Raise once *after* the selected real checkpoint is durably saved."""

    def __init__(
        self,
        *,
        delegate: AtomicPersistentCheckpointPort,
        stage: WorkerStage,
        marker_path: Path,
    ) -> None:
        if not isinstance(delegate, AtomicPersistentCheckpointPort):
            raise ValueError("restart checkpoint delegate is invalid")
        if stage not in _STAGE_ORDER:
            raise ValueError("restart stage is invalid")
        self._delegate = delegate
        self._stage = stage
        self._marker = Path(marker_path)

    def load(self, job: ClickedDeferredVideoJob) -> WorkerCheckpoint | None:
        return self._delegate.load(job)

    def save(
        self,
        job: ClickedDeferredVideoJob,
        checkpoint: WorkerCheckpoint,
        *,
        expected_revision: int | None,
    ) -> WorkerCheckpoint:
        persisted = self._delegate.save(
            job,
            checkpoint,
            expected_revision=expected_revision,
        )
        if persisted.completed_stage == self._stage and not self._marker.exists():
            self._marker.parent.mkdir(parents=True, exist_ok=True)
            _atomic_json(
                self._marker,
                {
                    "marker": DRY_RUN_MARKER,
                    "restartAfterStage": self._stage,
                    "checkpointDigest": persisted.checkpoint_digest,
                    "checkpointRevision": persisted.revision,
                },
            )
            raise SimulatedNoGpuRestart(
                f"simulated restart after {self._stage} checkpoint"
            )
        return persisted


class DryRunCasArtifactGateway:
    """Project-scoped CAS reader used by the real signed artifact route."""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        cas_root: Path,
        project_id: UUID,
    ) -> None:
        if not callable(session_factory) or not isinstance(project_id, UUID):
            raise ValueError("dry-run CAS gateway configuration is invalid")
        self._sessions = session_factory
        self._store = ContentAddressedArtifactStore(cas_root)
        self._project_id = project_id

    @staticmethod
    def _chunks(path: Path, start: int, length: int) -> Iterator[bytes]:
        remaining = length
        with path.open("rb") as handle:
            handle.seek(start)
            while remaining:
                chunk = handle.read(min(64 * 1024, remaining))
                if not chunk:
                    raise CompetitionNoGpuDryRunError(
                        "CAS object ended before its catalog byte size"
                    )
                remaining -= len(chunk)
                yield chunk

    def open(
        self,
        owner: str,
        artifact_id: UUID,
        *,
        method: str,
        headers: dict[str, str],
    ) -> RemoteArtifact:
        if owner != DRY_RUN_OWNER or method not in {"GET", "HEAD"}:
            return RemoteArtifact(404, {}, None)
        with self._sessions() as session:
            artifact = session.scalar(
                select(ArtifactRecordRow).where(
                    ArtifactRecordRow.id == artifact_id,
                    ArtifactRecordRow.project_id == self._project_id,
                    ArtifactRecordRow.status == "COMMITTED",
                )
            )
            if (
                artifact is None
                or artifact.mime_type != "application/json"
                or artifact.logical_role != DRY_RUN_EVIDENCE_ROLE
            ):
                return RemoteArtifact(404, {}, None)
            digest = artifact.content_digest
            byte_size = artifact.byte_size
        path = self._store.object_path(digest)
        if (
            not path.is_file()
            or path.is_symlink()
            or path.stat().st_size != byte_size
            or _sha256_file(path) != digest
        ):
            raise CompetitionNoGpuDryRunError("dry-run CAS object failed SHA verification")
        start = 0
        end = byte_size - 1
        status = 200
        range_header = headers.get("Range")
        if range_header is not None:
            match = _RANGE_RE.fullmatch(range_header)
            if match is None:
                return RemoteArtifact(
                    416,
                    {"Content-Range": f"bytes */{byte_size}"},
                    None,
                )
            start = int(match.group(1))
            end = byte_size - 1 if not match.group(2) else int(match.group(2))
            if start >= byte_size or end < start or end >= byte_size:
                return RemoteArtifact(
                    416,
                    {"Content-Range": f"bytes */{byte_size}"},
                    None,
                )
            status = 206
        length = end - start + 1
        response_headers = {
            "Accept-Ranges": "bytes",
            "Cache-Control": "no-store",
            "Content-Length": str(length),
            "Content-Type": "application/json",
            "ETag": f'"sha256:{digest}"',
            "X-Content-Type-Options": "nosniff",
        }
        if status == 206:
            response_headers["Content-Range"] = f"bytes {start}-{end}/{byte_size}"
        body = None if method == "HEAD" else self._chunks(path, start, length)
        return RemoteArtifact(status, response_headers, body)


@dataclass(frozen=True, slots=True)
class NoGpuDryRunReport:
    schema_version: Literal["amd.competition-no-gpu-dry-run-report.v1"]
    marker: Literal["DRY-RUN-NO-GPU"]
    project_id: str
    external_job_id: str
    authority_id: str
    authority_digest: str
    before_click_post_count: int
    trigger_post_count: int
    claim_owner_count: int
    claim_attempt_ordinal: int
    checkpoint_completed_stage: str
    checkpoint_revision: int
    stage_audit: Mapping[str, Mapping[str, int | str]]
    cas_publication_claim_count: int
    artifact_id: str
    artifact_digest: str
    signed_url: str
    head_status: int
    range_status: int
    full_status: int
    full_download_sha256: str
    media_rendered: bool
    rendered_frame_count: int
    final_user_click_performed: bool
    live_stage_factory_dependency: str

    def to_json_object(self) -> dict[str, Any]:
        return asdict(self)


def run_competition_no_gpu_dry_run(
    *,
    client: HttpClient,
    session_factory: SessionFactory,
    project_id: UUID,
    request: Mapping[str, Any],
    idempotency_key: str,
    authority_id: UUID,
    persistent_root: Path,
    checkpoint_root: Path,
    cas_root: Path,
    signer: ArtifactTokenSigner,
    base_stage_factory: StageFactory,
    gpu_disabled_probe: Callable[[], Mapping[str, Any]],
    worker_identity: str = "dry-run-no-gpu-worker",
    restart_after_stage: WorkerStage = "flux_generated",
) -> NoGpuDryRunReport:
    """Run one isolated real API-to-signed-CAS proof and simulate restart.

    The caller must provide a dedicated project with no video-job rows.  This
    makes it impossible for the production claimant to touch the user's final
    task.  The single HTTP POST is a test-authority click, never the final user
    click.
    """

    if not isinstance(project_id, UUID) or not isinstance(authority_id, UUID):
        raise ValueError("dry-run project and authority IDs must be UUIDs")
    if (
        type(idempotency_key) is not str
        or not idempotency_key.startswith("dry-run-no-gpu:")
    ):
        raise ValueError("dry-run idempotency key must be isolated")
    if not isinstance(signer, ArtifactTokenSigner):
        raise ValueError("dry-run artifact signer is invalid")
    if not callable(gpu_disabled_probe):
        raise ValueError("GPU-disabled proof callback is required")
    canonical_request = _standard_json_object(dict(request), "video-job request")
    if set(canonical_request) != {
        "bookId",
        "directionRevisionId",
        "trialScriptRevisionId",
    }:
        raise ValueError("dry-run video-job request fields are invalid")
    proof = _validate_gpu_disabled_proof(gpu_disabled_probe())
    with session_factory() as session:
        project = session.scalar(
            select(ProjectRecord).where(ProjectRecord.id == project_id)
        )
        job_count = session.scalar(
            select(func.count())
            .select_from(VideoJobProjectionRecord)
            .where(VideoJobProjectionRecord.project_id == project_id)
        )
        before_click_post_count = int(
            session.scalar(
                select(func.count())
                .select_from(ProductCommandLedgerRecord)
                .where(
                    ProductCommandLedgerRecord.project_id == project_id,
                    ProductCommandLedgerRecord.command_kind
                    == "shidu.create_video_job",
                )
            )
            or 0
        )
    if project is None or job_count != 0 or before_click_post_count != 0:
        raise CompetitionNoGpuDryRunError(
            "dry-run requires a dedicated project with zero video-job commands"
        )

    response = client.post(
        "/api/video-jobs",
        json=canonical_request,
        headers={"Idempotency-Key": idempotency_key},
    )
    if response.status_code != 202:
        raise CompetitionNoGpuDryRunError(
            f"isolated dry-run POST failed with {response.status_code}"
        )
    response_payload = response.json()
    external_job_id = response_payload.get("jobId")
    if type(external_job_id) is not str or not external_job_id.startswith("shidu_"):
        raise CompetitionNoGpuDryRunError("dry-run API did not return a Shidu job")
    with session_factory() as session:
        after_click_post_count = int(
            session.scalar(
                select(func.count())
                .select_from(ProductCommandLedgerRecord)
                .where(
                    ProductCommandLedgerRecord.project_id == project_id,
                    ProductCommandLedgerRecord.command_kind
                    == "shidu.create_video_job",
                )
            )
            or 0
        )
    trigger_post_count = after_click_post_count - before_click_post_count
    if trigger_post_count != 1:
        raise CompetitionNoGpuDryRunError(
            "dry-run API click was not observed exactly once in the command ledger"
        )

    authority_identity = {
        "schemaVersion": DRY_RUN_SCHEMA,
        "marker": DRY_RUN_MARKER,
        "authorityId": str(authority_id),
        "projectId": str(project_id),
        "externalJobId": external_job_id,
        "idempotencyKey": idempotency_key,
        "request": canonical_request,
        "requestedContract": frozen_no_gpu_contract(),
        "gpuDisabledProof": proof,
        "finalUserClickPerformed": False,
    }
    authority = {
        **authority_identity,
        "authorityDigest": canonical_json_digest(authority_identity),
    }
    with session_factory() as session, session.begin():
        row = session.scalar(
            select(VideoJobProjectionRecord)
            .where(
                VideoJobProjectionRecord.project_id == project_id,
                VideoJobProjectionRecord.external_job_id == external_job_id,
            )
            .with_for_update()
        )
        if row is None or row.payload.get("pipelineMode") != "h3_deferred_vertical_slice":
            raise CompetitionNoGpuDryRunError(
                "real API did not persist the deferred competition row"
            )
        payload = dict(row.payload)
        payload.update(
            {
                "frameCount": 73,
                "fps": 24,
                "nativeAudio": True,
                "subtitles": False,
                DRY_RUN_AUTHORITY_FIELD: authority,
            }
        )
        row.payload = payload
        session.flush()
        ClickedDeferredVideoJob.from_projection_record(row)

    persistent = Path(persistent_root)
    checkpoints = AtomicPersistentCheckpointPort(
        root=Path(checkpoint_root),
        persistent_root=persistent,
    )
    ledger = PersistentStageInvocationLedger(
        root=persistent / "competition-no-gpu" / "stage-audit",
        persistent_root=persistent,
        authority_id=authority_id,
    )
    evidence_publisher = DryRunEvidencePublisher(
        session_factory=session_factory,
        cas_root=cas_root,
        authority_id=authority_id,
    )
    stages = build_no_gpu_stage_factory(
        base_stage_factory=base_stage_factory,
        ledger=ledger,
        evidence_publisher=evidence_publisher,
    )
    context = CompetitionDaemonContext(
        project_id=project_id,
        persistent_root=persistent,
        session_factory=session_factory,
    )
    restart_marker = persistent / "competition-no-gpu" / str(authority_id) / "restart.json"
    first_jobs = PostgresDeferredJobPort(
        session_factory=session_factory,
        project_id=project_id,
        worker_identity=worker_identity,
    )
    first = build_competition_vertical_slice_daemon(
        jobs=first_jobs,
        checkpoints=RestartAfterStageCheckpointPort(
            delegate=checkpoints,
            stage=restart_after_stage,
            marker_path=restart_marker,
        ),
        context=context,
        stage_factory=stages,
    )
    try:
        first.run_once()
    except SimulatedNoGpuRestart:
        pass
    else:
        raise CompetitionNoGpuDryRunError("restart simulation did not occur")

    restarted_jobs = PostgresDeferredJobPort(
        session_factory=session_factory,
        project_id=project_id,
        worker_identity=worker_identity,
    )
    restarted = build_competition_vertical_slice_daemon(
        jobs=restarted_jobs,
        checkpoints=checkpoints,
        context=context,
        stage_factory=stages,
    )
    checkpoint = restarted.run_once()
    if checkpoint is None or checkpoint.status != "delivered":
        raise CompetitionNoGpuDryRunError("dry-run did not resume to delivery")
    if restarted.run_once() is not None:
        raise CompetitionNoGpuDryRunError("delivered dry-run job was claimed twice")

    stage_audit = ledger.summary()
    if any(item["executionCount"] != 1 for item in stage_audit.values()):
        raise CompetitionNoGpuDryRunError("a dry-run stage executed more than once")
    if any(
        stage_audit[stage]["executorKind"] != "deterministic-no-gpu-stub"
        for stage in _GPU_STAGES
    ):
        raise CompetitionNoGpuDryRunError("FLUX/H3 did not use the no-GPU stub")
    if any(
        stage_audit[stage]["executorKind"] != "production-boundary"
        for stage in set(_STAGE_ORDER) - _GPU_STAGES
    ):
        raise CompetitionNoGpuDryRunError("a non-GPU stage used an execution stub")

    with session_factory() as session:
        row = session.scalar(
            select(VideoJobProjectionRecord).where(
                VideoJobProjectionRecord.project_id == project_id,
                VideoJobProjectionRecord.external_job_id == external_job_id,
            )
        )
        if row is None:
            raise CompetitionNoGpuDryRunError("dry-run job disappeared")
        durable_authority = row.payload.get(DRY_RUN_AUTHORITY_FIELD)
        evidence = row.payload.get(DRY_RUN_EVIDENCE_FIELD)
        worker = row.payload.get("competitionWorker")
        if durable_authority != authority or type(evidence) is not dict:
            raise CompetitionNoGpuDryRunError("dry-run marker was not persisted")
        if (
            type(worker) is not dict
            or worker.get("ownerDigest") != restarted_jobs.owner_digest
            or worker.get("status") != "delivered"
            or worker.get("attemptOrdinal") != 2
        ):
            raise CompetitionNoGpuDryRunError("dry-run durable claim is invalid")
        artifact_id = UUID(str(evidence["artifactId"]))
        artifact_digest = _strict_digest(
            evidence.get("artifactDigest"), "dry-run artifact digest"
        )
        claims = session.scalar(
            select(func.count())
            .select_from(ArtifactPublicationClaimRecord)
            .where(ArtifactPublicationClaimRecord.project_id == project_id)
        )
        artifacts = list(
            session.scalars(
                select(ArtifactRecordRow).where(
                    ArtifactRecordRow.project_id == project_id
                )
            )
        )
        attempts = list(
            session.scalars(
                select(OperationAttemptRecord).where(
                    OperationAttemptRecord.project_id == project_id,
                    OperationAttemptRecord.worker_id == DRY_RUN_MARKER,
                )
            )
        )
        claimed_rows = list(
            session.scalars(
                select(VideoJobProjectionRecord).where(
                    VideoJobProjectionRecord.project_id == project_id,
                    VideoJobProjectionRecord.external_job_id == external_job_id,
                )
            )
        )
        claim_owner_digests = {
            state["ownerDigest"]
            for claimed in claimed_rows
            for state in [claimed.payload.get("competitionWorker")]
            if type(state) is dict and type(state.get("ownerDigest")) is str
        }
    if (
        claims != 1
        or len(artifacts) != 1
        or len(attempts) != 1
        or len(claim_owner_digests) != 1
    ):
        raise CompetitionNoGpuDryRunError("dry-run CAS claim is not singular")
    artifact = artifacts[0]
    if (
        artifact.id != artifact_id
        or artifact.content_digest != artifact_digest
        or artifact.mime_type != "application/json"
        or artifact.logical_role != DRY_RUN_EVIDENCE_ROLE
        or artifact.status != "COMMITTED"
    ):
        raise CompetitionNoGpuDryRunError("dry-run CAS artifact is invalid")

    token = signer.issue(
        owner=DRY_RUN_OWNER,
        artifact_id=artifact_id,
        purpose="reference",
    )
    signed_url = f"/artifacts/{token}"
    head = client.head(signed_url)
    ranged = client.get(signed_url, headers={"Range": "bytes=0-31"})
    full = client.get(signed_url)
    if head.status_code != 200 or ranged.status_code != 206 or full.status_code != 200:
        raise CompetitionNoGpuDryRunError("signed dry-run artifact route failed")
    full_digest = sha256(full.content).hexdigest()
    if full_digest != artifact_digest or ranged.content != full.content[:32]:
        raise CompetitionNoGpuDryRunError("signed dry-run artifact SHA/range failed")
    try:
        downloaded = json.loads(full.content)
    except json.JSONDecodeError as exc:
        raise CompetitionNoGpuDryRunError("dry-run artifact is not JSON evidence") from exc
    if (
        downloaded.get("marker") != DRY_RUN_MARKER
        or downloaded.get("mediaRendered") is not False
        or downloaded.get("renderedFrameCount") != 0
        or downloaded.get("requestedContract") != frozen_no_gpu_contract()
    ):
        raise CompetitionNoGpuDryRunError("dry-run evidence claimed rendered media")

    return NoGpuDryRunReport(
        schema_version="amd.competition-no-gpu-dry-run-report.v1",
        marker=DRY_RUN_MARKER,
        project_id=str(project_id),
        external_job_id=external_job_id,
        authority_id=str(authority_id),
        authority_digest=authority["authorityDigest"],
        before_click_post_count=before_click_post_count,
        trigger_post_count=trigger_post_count,
        claim_owner_count=len(claim_owner_digests),
        claim_attempt_ordinal=int(worker["attemptOrdinal"]),
        checkpoint_completed_stage=checkpoint.completed_stage,
        checkpoint_revision=checkpoint.revision,
        stage_audit=stage_audit,
        cas_publication_claim_count=int(claims),
        artifact_id=str(artifact_id),
        artifact_digest=artifact_digest,
        signed_url=signed_url,
        head_status=head.status_code,
        range_status=ranged.status_code,
        full_status=full.status_code,
        full_download_sha256=full_digest,
        media_rendered=False,
        rendered_frame_count=0,
        final_user_click_performed=False,
        live_stage_factory_dependency=LIVE_STAGE_FACTORY_DEPENDENCY,
    )


__all__ = [
    "CompetitionNoGpuDryRunError",
    "DRY_RUN_AUTHORITY_FIELD",
    "DRY_RUN_EVIDENCE_FIELD",
    "DRY_RUN_EVIDENCE_ROLE",
    "DRY_RUN_MARKER",
    "DRY_RUN_OWNER",
    "DryRunCasArtifactGateway",
    "DryRunEvidencePublisher",
    "LIVE_STAGE_FACTORY_DEPENDENCY",
    "NoGpuDryRunReport",
    "PersistentStageInvocationLedger",
    "RestartAfterStageCheckpointPort",
    "SimulatedNoGpuRestart",
    "build_no_gpu_stage_factory",
    "frozen_no_gpu_contract",
    "late_bound_stage_factory",
    "probe_live_gpu_disabled_state",
    "run_competition_no_gpu_dry_run",
]
