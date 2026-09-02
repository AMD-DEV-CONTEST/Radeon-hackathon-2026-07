from __future__ import annotations

import hashlib
import json
import math
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

import numpy as np
import torch
from PIL import Image
from pydantic import Field, model_validator

from colorgraph.agent.creative_compiler import CompiledGraphCandidate
from colorgraph.agent.creative_contracts import (
    ColorStrategy,
    CompiledCandidate,
    CreativeBrief,
    CreativeDirection,
    EvidenceKind,
    NonEmptyString,
    ProjectContextPack,
    Sha256,
    StrictFrozenModel,
    canonical_sha256,
)
from colorgraph.devices.base import ComputeBackend
from colorgraph.domain.grade_graph import (
    LEGACY_RENDERER_VERSION,
    ColorSpace,
    GradeGraph,
    NodeType,
)
from colorgraph.grading.color import convert_color_space
from colorgraph.grading.engine import GradeRenderEngine
from colorgraph.grading.looks import graph_digest
from colorgraph.grading.masks import GraphMaskResolver
from colorgraph.grading.precision import PREVIEW_PRECISION_BUDGET
from colorgraph.media.frames import extract_frame

CANDIDATE_SEARCH_VERSION = "colorgraph.budgeted-candidate-search/v2"
LOCAL_SEARCH_RENDERER_VERSION = "colorgraph.local-candidate-frame-renderer/v2"

_SAFE_COMPONENT = re.compile(r"[^A-Za-z0-9_.-]+")
_DIRECTION_ORDER = {
    CreativeDirection.FAITHFUL: 0,
    CreativeDirection.AMPLIFIED: 1,
    CreativeDirection.COUNTERPOINT: 2,
}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_component(value: str) -> str:
    label = _SAFE_COMPONENT.sub("-", value).strip("-")
    digest = hashlib.sha256(value.encode()).hexdigest()[:12]
    return f"{label[:48] or 'item'}-{digest}"


def _compact_run_component(value: str) -> str:
    return f"r-{hashlib.sha256(value.encode()).hexdigest()[:16]}"


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


class CandidateSearchStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    CANCELLED = "cancelled"
    BUDGET_EXHAUSTED = "budget_exhausted"
    COMPLETE = "complete"


class CandidateAttemptStatus(StrEnum):
    HARD_PASS = "hard_pass"
    HARD_FAIL = "hard_fail"
    RENDER_FAILED = "render_failed"


class CandidateSearchBudget(StrictFrozenModel):
    maximum_model_calls: int = Field(ge=0)
    maximum_rendered_frames: int = Field(gt=0)
    maximum_wall_seconds: float = Field(gt=0)
    maximum_cost_usd: float = Field(ge=0)
    maximum_refinements: int = Field(default=1, ge=0, le=1)


class CandidateSearchUsage(StrictFrozenModel):
    model_calls: int = Field(default=0, ge=0)
    rendered_frames: int = Field(default=0, ge=0)
    wall_seconds: float = Field(default=0, ge=0)
    cost_usd: float = Field(default=0, ge=0)
    candidate_attempts: int = Field(default=0, ge=0)
    cache_hits: int = Field(default=0, ge=0)
    refinements: int = Field(default=0, ge=0, le=1)


class CandidateSamplePoint(StrictFrozenModel):
    frame_index: int = Field(ge=0)
    time_seconds: float = Field(ge=0)
    reasons: list[NonEmptyString]


class RenderedSearchSample(StrictFrozenModel):
    frame_index: int = Field(ge=0)
    time_seconds: float = Field(ge=0)
    source_path: NonEmptyString
    source_sha256: Sha256
    current_path: NonEmptyString
    current_sha256: Sha256
    candidate_path: NonEmptyString
    candidate_sha256: Sha256
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    unclamped_finite_invalid: int = Field(default=0, ge=0)
    unclamped_output_outside_ratio: float = Field(default=0, ge=0, le=1)


class SearchHardGateCheck(StrictFrozenModel):
    check_id: NonEmptyString
    passed: bool
    observed: float
    threshold: float
    detail: NonEmptyString
    frame_indices: list[int]


class SearchQCEvaluation(StrictFrozenModel):
    schema_version: str = "colorgraph.search-hard-gates/v1"
    hard_passed: bool
    checks: list[SearchHardGateCheck]
    required_check_ids: list[NonEmptyString]
    technical_margin: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def cover_required_checks(self) -> SearchQCEvaluation:
        by_id = {item.check_id: item for item in self.checks}
        if set(by_id) != set(self.required_check_ids):
            raise ValueError("search QC must report every required hard check exactly once")
        if self.hard_passed != all(item.passed for item in self.checks):
            raise ValueError("search QC hard-pass flag differs from its checks")
        return self


class SearchCandidateRecord(StrictFrozenModel):
    candidate_id: NonEmptyString
    parent_candidate_id: NonEmptyString | None = None
    scene_id: NonEmptyString
    brief_id: NonEmptyString
    direction: CreativeDirection
    strategy_id: NonEmptyString
    compiled_graph_digest: Sha256
    cache_key: Sha256
    cache_hit: bool
    status: CandidateAttemptStatus
    samples: list[RenderedSearchSample]
    qc: SearchQCEvaluation | None = None
    failure_detail: NonEmptyString | None = None
    graph_path: NonEmptyString
    undo_graph_path: NonEmptyString
    contract_path: NonEmptyString
    is_refinement: bool

    @model_validator(mode="after")
    def validate_attempt(self) -> SearchCandidateRecord:
        if self.status == CandidateAttemptStatus.RENDER_FAILED:
            if self.failure_detail is None or self.qc is not None:
                raise ValueError("render failure requires detail and no QC")
        else:
            if self.qc is None or self.failure_detail is not None:
                raise ValueError("rendered candidate requires QC and no failure detail")
            if (
                self.status == CandidateAttemptStatus.HARD_PASS
            ) != self.qc.hard_passed:
                raise ValueError("candidate status differs from QC")
        return self


class CandidateSearchState(StrictFrozenModel):
    schema_version: str = "colorgraph.candidate-search-state/v2"
    run_id: NonEmptyString
    plan_digest: Sha256
    source_graph_digest: Sha256
    context_digest: Sha256
    renderer_version: NonEmptyString
    status: CandidateSearchStatus
    usage: CandidateSearchUsage
    candidates: list[SearchCandidateRecord]
    survivor_candidate_ids: list[NonEmptyString]
    preferred_candidate_id: NonEmptyString | None = None
    runner_up_candidate_id: NonEmptyString | None = None
    selection_status: NonEmptyString


@dataclass(frozen=True, slots=True)
class SearchCandidateInput:
    brief: CreativeBrief
    strategy: ColorStrategy
    compiled: CompiledGraphCandidate
    model_calls: int = 0
    model_cost_usd: float = 0
    is_refinement: bool = False
    parent_candidate_id: str | None = None

    def __post_init__(self) -> None:
        if self.model_calls < 0 or self.model_cost_usd < 0:
            raise ValueError("candidate model usage cannot be negative")
        if self.brief.brief_id != self.strategy.brief_id:
            raise ValueError("candidate strategy does not serve its brief")
        if self.compiled.contract.strategy_id != self.strategy.strategy_id:
            raise ValueError("compiled candidate does not belong to its strategy")
        if self.is_refinement != (self.parent_candidate_id is not None):
            raise ValueError("refinement candidates require exactly one parent ID")


@dataclass(frozen=True, slots=True)
class CandidateSearchResult:
    state: CandidateSearchState

    @property
    def survivors(self) -> tuple[SearchCandidateRecord, ...]:
        survivor_ids = set(self.state.survivor_candidate_ids)
        return tuple(
            item
            for item in self.state.candidates
            if item.candidate_id in survivor_ids
        )


class CandidateFrameRenderer(Protocol):
    renderer_version: str

    def render(
        self,
        *,
        candidate: SearchCandidateInput,
        current_graph: GradeGraph,
        samples: tuple[CandidateSamplePoint, ...],
        output_dir: Path,
    ) -> list[RenderedSearchSample]: ...


class SearchHardGateEvaluator(Protocol):
    def evaluate(
        self,
        *,
        candidate: SearchCandidateInput,
        samples: list[RenderedSearchSample],
        required_check_ids: list[str],
    ) -> SearchQCEvaluation: ...


class LocalCandidateFrameRenderer:
    """Render real source frames through the same ColorGraph engine as final output."""

    renderer_version = LOCAL_SEARCH_RENDERER_VERSION

    def __init__(
        self,
        *,
        source: Path,
        backend: ComputeBackend,
        maximum_width: int = 960,
    ) -> None:
        self.source = source.resolve()
        self.backend = backend
        self.maximum_width = maximum_width
        self._source_stat: tuple[int, int, int] | None = None
        self._source_sha256: str | None = None
        if not self.source.is_file():
            raise FileNotFoundError(self.source)
        if maximum_width <= 0:
            raise ValueError("candidate renderer width must be positive")

    def input_digest(self, graph: GradeGraph) -> str:
        stat = self.source.stat()
        signature = (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
        if signature != self._source_stat:
            self._source_sha256 = _sha256_file(self.source)
            self._source_stat = signature
        storage: list[dict[str, object]] = []
        for asset in sorted(graph.masks, key=lambda item: item.id):
            preferred = asset.metadata.get("storage", {}).get(
                "preferred_decode"
            )
            value = (
                asset.metadata.get("video_path")
                if preferred == "video_ffmpeg"
                else asset.path
            )
            path = Path(str(value)).resolve()
            if path.is_file():
                item_stat = path.stat()
                actual = {
                    "kind": "file",
                    "size": item_stat.st_size,
                    "mtime_ns": item_stat.st_mtime_ns,
                    "ctime_ns": item_stat.st_ctime_ns,
                }
            elif path.is_dir():
                actual = {
                    "kind": "sequence",
                    "files": [
                        {
                            "name": item.name,
                            "size": item.stat().st_size,
                            "mtime_ns": item.stat().st_mtime_ns,
                            "ctime_ns": item.stat().st_ctime_ns,
                        }
                        for item in sorted(path.glob("*.png"))
                    ],
                }
            else:
                actual = {"kind": "missing"}
            storage.append(
                {
                    "asset_id": asset.id,
                    "declared_sequence_sha256": asset.metadata.get(
                        "sequence_sha256"
                    ),
                    "declared_video_sha256": asset.metadata.get("video_sha256"),
                    "actual_storage": actual,
                }
            )
        return canonical_sha256(
            {
                "renderer_version": self.renderer_version,
                "maximum_width": self.maximum_width,
                "backend": {
                    "runtime": self.backend.info.runtime,
                    "name": self.backend.info.name,
                    "torch_version": self.backend.info.torch_version,
                },
                "source_path": str(self.source),
                "source_sha256": self._source_sha256,
                "mask_storage": storage,
            }
        )

    def render(
        self,
        *,
        candidate: SearchCandidateInput,
        current_graph: GradeGraph,
        samples: tuple[CandidateSamplePoint, ...],
        output_dir: Path,
    ) -> list[RenderedSearchSample]:
        output_dir.mkdir(parents=True, exist_ok=True)
        engine = GradeRenderEngine(self.backend)
        current_resolver = GraphMaskResolver(current_graph)
        candidate_resolver = GraphMaskResolver(
            candidate.compiled.graph,
        )
        rendered: list[RenderedSearchSample] = []
        try:
            for sample in samples:
                stem = f"frame-{sample.frame_index:08d}"
                source_path = output_dir / f"{stem}-source.png"
                current_path = output_dir / f"{stem}-current.png"
                candidate_path = output_dir / f"{stem}-candidate.png"
                extract_frame(
                    self.source,
                    sample.time_seconds,
                    source_path,
                    maximum_width=self.maximum_width,
                    high_quality=True,
                )
                current_masks = (
                    current_resolver.load_batch([sample.frame_index])
                    if current_resolver.assets
                    else None
                )
                candidate_masks = (
                    candidate_resolver.load_batch([sample.frame_index])
                    if candidate_resolver.assets
                    else None
                )
                engine.render_image(
                    source_path,
                    current_path,
                    current_graph,
                    time_seconds=sample.time_seconds,
                    masks=current_masks,
                )
                with Image.open(source_path) as source_image:
                    source_array = (
                        np.asarray(source_image.convert("RGB"), dtype=np.float32) / 255
                    )
                source_tensor = (
                    torch.from_numpy(source_array)
                    .permute(2, 0, 1)
                    .unsqueeze(0)
                )
                raw_output, _ = engine.render_output_batch(
                    source_tensor,
                    candidate.compiled.graph,
                    timestamps=[sample.time_seconds],
                    masks=candidate_masks,
                    mixed_precision=(
                        PREVIEW_PRECISION_BUDGET.mixed_precision_allowed
                    ),
                    clamp_output=False,
                )
                finite = torch.isfinite(raw_output)
                invalid = int(raw_output.numel() - torch.count_nonzero(finite).item())
                outside = float(
                    torch.count_nonzero(
                        finite & ((raw_output < 0) | (raw_output > 1))
                    ).item()
                    / raw_output.numel()
                )
                display_output = torch.nan_to_num(
                    raw_output,
                    nan=0,
                    posinf=1,
                    neginf=0,
                ).clamp(0, 1)
                if candidate.compiled.graph.renderer_version != LEGACY_RENDERER_VERSION:
                    output_node = next(
                        node
                        for node in candidate.compiled.graph.ordered_nodes()
                        if node.type == NodeType.OUTPUT_TRANSFORM
                    )
                    destination_log_profile = output_node.parameters.get(
                        "destination_log_profile"
                    )
                    display_output = convert_color_space(
                        display_output,
                        candidate.compiled.graph.output_color_space,
                        ColorSpace.SRGB,
                        source_log_profile=(
                            destination_log_profile
                            if isinstance(destination_log_profile, str)
                            else None
                        ),
                    ).clamp(0, 1)
                output_array = (
                    display_output[0]
                    .permute(1, 2, 0)
                    .mul(255)
                    .round()
                    .byte()
                    .cpu()
                    .numpy()
                )
                Image.fromarray(output_array, mode="RGB").save(candidate_path)
                height, width = output_array.shape[:2]
                rendered.append(
                    RenderedSearchSample(
                        frame_index=sample.frame_index,
                        time_seconds=sample.time_seconds,
                        source_path=str(source_path.resolve()),
                        source_sha256=_sha256_file(source_path),
                        current_path=str(current_path.resolve()),
                        current_sha256=_sha256_file(current_path),
                        candidate_path=str(candidate_path.resolve()),
                        candidate_sha256=_sha256_file(candidate_path),
                        width=width,
                        height=height,
                        unclamped_finite_invalid=invalid,
                        unclamped_output_outside_ratio=outside,
                    )
                )
        finally:
            current_resolver.close()
            candidate_resolver.close()
        return rendered


def _image_array(path: str) -> np.ndarray:
    with Image.open(path) as image:
        return np.asarray(image.convert("RGB"), dtype=np.float32) / 255


def _structure_energy(image: np.ndarray) -> float:
    luminance = (
        image[..., 0] * 0.2126
        + image[..., 1] * 0.7152
        + image[..., 2] * 0.0722
    )
    horizontal = np.diff(luminance, axis=1)
    vertical = np.diff(luminance, axis=0)
    return float(
        math.sqrt(
            float(np.mean(horizontal * horizontal))
            + float(np.mean(vertical * vertical))
        )
    )


class DeterministicSearchHardGates:
    """Frame-level non-waivable gates; aesthetic preference is intentionally absent."""

    def evaluate(
        self,
        *,
        candidate: SearchCandidateInput,
        samples: list[RenderedSearchSample],
        required_check_ids: list[str],
    ) -> SearchQCEvaluation:
        arrays = [_image_array(item.candidate_path) for item in samples]
        current = [_image_array(item.current_path) for item in samples]
        checks: list[SearchHardGateCheck] = []
        for check_id in required_check_ids:
            if check_id == "color_pipeline_schema":
                graph = candidate.compiled.graph
                inputs = [
                    item for item in graph.nodes if item.type == NodeType.INPUT_TRANSFORM
                ]
                outputs = [
                    item for item in graph.nodes if item.type == NodeType.OUTPUT_TRANSFORM
                ]
                passed = len(inputs) == 1 and len(outputs) == 1
                observed = float(len(inputs) == 1) * float(len(outputs) == 1)
                threshold = 1
                detail = "Exactly one input and output transform must remain."
            elif check_id == "finite_values":
                invalid = sum(
                    int(array.size - np.count_nonzero(np.isfinite(array)))
                    + sample.unclamped_finite_invalid
                    for array, sample in zip(arrays, samples, strict=True)
                )
                passed = invalid == 0
                observed = float(invalid)
                threshold = 0
                detail = "Rendered candidate pixels must all be finite."
            elif check_id == "asset_integrity":
                missing = sum(
                    int(
                        not Path(item.candidate_path).is_file()
                        or _sha256_file(Path(item.candidate_path))
                        != item.candidate_sha256
                    )
                    for item in samples
                )
                passed = missing == 0
                observed = float(missing)
                threshold = 0
                detail = "Rendered files and their content digests must match."
            elif check_id == "legal_output_gamut":
                outside = max(
                    (item.unclamped_output_outside_ratio for item in samples),
                    default=0,
                )
                passed = outside == 0
                observed = outside
                threshold = 0
                detail = "Display-referred preview samples must remain normalized."
            elif check_id == "highlight_clipping":
                clipping = max(
                    (
                        float(np.mean(np.max(array, axis=2) >= 1))
                        for array in arrays
                    ),
                    default=0,
                )
                passed = clipping <= 0.08
                observed = clipping
                threshold = 0.08
                detail = "Highlight clipping ratio must remain bounded."
            elif check_id == "shadow_clipping":
                clipping = max(
                    (
                        float(np.mean(np.max(array, axis=2) <= 0))
                        for array in arrays
                    ),
                    default=0,
                )
                passed = clipping <= 0.08
                observed = clipping
                threshold = 0.08
                detail = "Shadow clipping ratio must remain bounded."
            elif check_id == "structure_loss":
                ratios = [
                    _structure_energy(candidate_image)
                    / max(_structure_energy(current_image), 1e-6)
                    for candidate_image, current_image in zip(
                        arrays,
                        current,
                        strict=True,
                    )
                ]
                minimum_ratio = min(ratios, default=1)
                passed = minimum_ratio >= 0.7
                observed = minimum_ratio
                threshold = 0.7
                detail = "Candidate edge energy must retain current-grade structure."
            else:
                passed = False
                observed = 0
                threshold = 1
                detail = "Required hard check is unsupported and therefore fails closed."
            checks.append(
                SearchHardGateCheck(
                    check_id=check_id,
                    passed=passed,
                    observed=observed,
                    threshold=threshold,
                    detail=detail,
                    frame_indices=[item.frame_index for item in samples],
                )
            )
        margins = [
            (
                1.0
                if item.passed and item.threshold == 0
                else max(
                    0.0,
                    min(
                        1.0,
                        (
                            item.observed / item.threshold
                            if item.passed and item.observed >= item.threshold
                            else 1 - item.observed / max(item.threshold, 1e-9)
                        ),
                    ),
                )
            )
            for item in checks
        ]
        return SearchQCEvaluation(
            hard_passed=all(item.passed for item in checks),
            checks=checks,
            required_check_ids=required_check_ids,
            technical_margin=min(margins, default=0),
        )


class CandidateSearchStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def run_dir(self, run_id: str) -> Path:
        compact = self.root / _compact_run_component(run_id)
        legacy = self.root / _safe_component(run_id)
        if legacy.exists():
            if compact.exists():
                raise ValueError(
                    "candidate search has both legacy and compact run directories"
                )
            return legacy
        return compact

    def state_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "state.json"

    def load_state(self, run_id: str) -> CandidateSearchState | None:
        path = self.state_path(run_id)
        if not path.is_file():
            return None
        return CandidateSearchState.model_validate_json(
            path.read_text(encoding="utf-8")
        )

    def save_state(self, state: CandidateSearchState) -> Path:
        path = self.state_path(state.run_id)
        _atomic_write(path, state.model_dump_json(indent=2))
        return path

    def cache_dir(self, run_id: str, cache_key: str) -> Path:
        # Keep the full SHA-256 inside render-manifest.json and every state record.
        # A bounded on-disk component avoids Win32 MAX_PATH failures for projects
        # stored below an already-deep user directory. Prefix collisions fail closed
        # because immutable assets and the manifest still validate the full key.
        return self.run_dir(run_id) / "cache" / f"k-{cache_key[:24]}"

    @staticmethod
    def _write_immutable(path: Path, content: str) -> None:
        if path.exists():
            if path.read_text(encoding="utf-8") != content:
                raise ValueError(f"immutable search asset differs: {path.name}")
            return
        _atomic_write(path, content)

    def persist_compiled_assets(
        self,
        run_id: str,
        cache_key: str,
        candidate: CompiledGraphCandidate,
    ) -> tuple[str, str, str]:
        directory = self.cache_dir(run_id, cache_key)
        graph_path = directory / "compiled-graph.json"
        undo_path = directory / "undo-graph.json"
        contract_path = directory / "compiled-contract.json"
        self._write_immutable(graph_path, candidate.graph.model_dump_json(indent=2))
        self._write_immutable(undo_path, candidate.undo_graph.model_dump_json(indent=2))
        self._write_immutable(contract_path, candidate.contract.model_dump_json(indent=2))
        return (
            str(graph_path.resolve()),
            str(undo_path.resolve()),
            str(contract_path.resolve()),
        )

    def load_render_cache(
        self,
        run_id: str,
        cache_key: str,
    ) -> list[RenderedSearchSample] | None:
        path = self.cache_dir(run_id, cache_key) / "render-manifest.json"
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if (
                payload.get("schema_version")
                != "colorgraph.candidate-render-cache/v2"
                or payload.get("cache_key") != cache_key
            ):
                return None
            samples = [
                RenderedSearchSample.model_validate(item)
                for item in payload["samples"]
            ]
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            return None
        for sample in samples:
            for file_path, expected_digest in (
                (sample.source_path, sample.source_sha256),
                (sample.current_path, sample.current_sha256),
                (sample.candidate_path, sample.candidate_sha256),
            ):
                path_value = Path(file_path).resolve()
                if not path_value.is_relative_to(
                    self.cache_dir(run_id, cache_key).resolve()
                ):
                    return None
                if (
                    not path_value.is_file()
                    or _sha256_file(path_value) != expected_digest
                ):
                    return None
        return samples

    def record_assets_valid(
        self,
        run_id: str,
        record: SearchCandidateRecord,
    ) -> bool:
        root = self.run_dir(run_id).resolve()
        paths = [
            Path(record.graph_path).resolve(),
            Path(record.undo_graph_path).resolve(),
            Path(record.contract_path).resolve(),
        ]
        if any(
            not path.is_relative_to(root) or not path.is_file()
            for path in paths
        ):
            return False
        try:
            graph = GradeGraph.model_validate_json(
                paths[0].read_text(encoding="utf-8")
            )
            undo = GradeGraph.model_validate_json(
                paths[1].read_text(encoding="utf-8")
            )
            contract = CompiledCandidate.model_validate_json(
                paths[2].read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            return False
        if (
            graph_digest(graph) != record.compiled_graph_digest
            or graph_digest(undo) != contract.undo_graph_digest
            or contract.candidate_id != record.candidate_id
            or contract.compiled_graph_digest != record.compiled_graph_digest
        ):
            return False
        if record.status == CandidateAttemptStatus.RENDER_FAILED:
            return not record.samples
        cached = self.load_render_cache(run_id, record.cache_key)
        return cached is not None and cached == record.samples

    def save_render_cache(
        self,
        run_id: str,
        cache_key: str,
        samples: list[RenderedSearchSample],
    ) -> None:
        path = self.cache_dir(run_id, cache_key) / "render-manifest.json"
        payload = {
            "schema_version": "colorgraph.candidate-render-cache/v2",
            "cache_key": cache_key,
            "samples": [item.model_dump(mode="json") for item in samples],
        }
        _atomic_write(
            path,
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        )


def select_candidate_samples(
    *,
    scene_id: str,
    context: ProjectContextPack,
    graph: GradeGraph,
    maximum_samples: int = 3,
) -> tuple[CandidateSamplePoint, ...]:
    if not 1 <= maximum_samples <= 3:
        raise ValueError("candidate search supports one to three samples per scene")
    reasons_by_frame: dict[int, set[str]] = {}
    times_by_frame: dict[int, float] = {}

    def add(frame_index: int, time_seconds: float, reason: str) -> None:
        clamped = min(
            max(0, frame_index),
            max(0, graph.media.frame_count - 1),
        )
        reasons_by_frame.setdefault(clamped, set()).add(reason)
        times_by_frame[clamped] = min(
            max(0, time_seconds),
            max(0, graph.media.duration_seconds - 1 / graph.media.fps),
        )

    for evidence in context.evidence:
        if (
            evidence.scene_id == scene_id
            and evidence.kind == EvidenceKind.FRAME
            and evidence.frame_index is not None
        ):
            add(
                evidence.frame_index,
                evidence.frame_index / graph.media.fps,
                f"context:{evidence.evidence_id}",
            )
    shots = [item for item in graph.shots if item.scene_id == scene_id]
    for shot in shots:
        start = round(shot.time_range.start_seconds * graph.media.fps)
        end_time = max(
            shot.time_range.start_seconds,
            shot.time_range.end_seconds - 1 / graph.media.fps,
        )
        end = round(end_time * graph.media.fps)
        midpoint_time = (
            shot.time_range.start_seconds + shot.time_range.end_seconds
        ) / 2
        add(start, shot.time_range.start_seconds, f"shot-start:{shot.id}")
        add(round(midpoint_time * graph.media.fps), midpoint_time, f"shot-mid:{shot.id}")
        add(end, end_time, f"shot-end:{shot.id}")
    if not reasons_by_frame:
        raise ValueError(f"scene {scene_id!r} has no representative frame scope")
    ordered = sorted(reasons_by_frame)
    if len(ordered) > maximum_samples:
        indexes = sorted(
            {
                round(index * (len(ordered) - 1) / (maximum_samples - 1))
                if maximum_samples > 1
                else len(ordered) // 2
                for index in range(maximum_samples)
            }
        )
        ordered = [ordered[index] for index in indexes]
    return tuple(
        CandidateSamplePoint(
            frame_index=frame_index,
            time_seconds=times_by_frame[frame_index],
            reasons=sorted(reasons_by_frame[frame_index]),
        )
        for frame_index in ordered
    )


def _cache_key(
    *,
    candidate: SearchCandidateInput,
    context: ProjectContextPack,
    current_graph: GradeGraph,
    renderer_version: str,
    renderer_input_digest: str,
    samples: tuple[CandidateSamplePoint, ...],
) -> str:
    return canonical_sha256(
        {
            "version": CANDIDATE_SEARCH_VERSION,
            "context": canonical_sha256(context),
            "brief": canonical_sha256(candidate.brief),
            "strategy": canonical_sha256(candidate.strategy),
            "current_graph": graph_digest(current_graph),
            "compiled_graph": candidate.compiled.contract.compiled_graph_digest,
            "renderer": renderer_version,
            "renderer_input": renderer_input_digest,
            "samples": [item.model_dump(mode="json") for item in samples],
        }
    )


def _plan_digest(
    *,
    context: ProjectContextPack,
    current_graph: GradeGraph,
    candidates: list[SearchCandidateInput],
    renderer_version: str,
    renderer_input_digest: str,
    budget: CandidateSearchBudget,
) -> str:
    return canonical_sha256(
        {
            "version": CANDIDATE_SEARCH_VERSION,
            "context": canonical_sha256(context),
            "current_graph": graph_digest(current_graph),
            "renderer": renderer_version,
            "renderer_input": renderer_input_digest,
            "budget": budget.model_dump(mode="json"),
            "candidates": [
                {
                    "brief": canonical_sha256(item.brief),
                    "strategy": canonical_sha256(item.strategy),
                    "compiled": item.compiled.contract.model_dump(mode="json"),
                    "is_refinement": item.is_refinement,
                    "parent_candidate_id": item.parent_candidate_id,
                    "model_calls": item.model_calls,
                    "model_cost_usd": item.model_cost_usd,
                }
                for item in candidates
            ],
        }
    )


def _validate_candidate_plan(
    candidates: list[SearchCandidateInput],
    *,
    current_graph: GradeGraph,
    context: ProjectContextPack,
) -> None:
    if not candidates:
        raise ValueError("candidate search plan cannot be empty")
    identifiers = [
        item.compiled.contract.candidate_id for item in candidates
    ]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("candidate search plan contains duplicate candidate IDs")
    base = [item for item in candidates if not item.is_refinement]
    refinements = [item for item in candidates if item.is_refinement]
    if len(refinements) > 1:
        raise ValueError("candidate search v1 permits at most one refinement")
    by_scene: dict[str, list[SearchCandidateInput]] = {}
    for item in base:
        by_scene.setdefault(item.brief.scene_id, []).append(item)
        if item.compiled.variant_id != "nominal":
            raise ValueError("base search directions must use nominal compiled candidates")
    if set(by_scene) != set(context.allowed_scene_ids):
        raise ValueError("base search plan must cover every context scene exactly once")
    if any(
        item.compiled.contract.source_graph_digest != graph_digest(current_graph)
        for item in candidates
    ):
        raise ValueError("compiled search candidate is stale")
    expected = set(CreativeDirection)
    for scene_id, scene_candidates in by_scene.items():
        directions = [item.brief.direction for item in scene_candidates]
        if len(directions) != 3 or set(directions) != expected:
            raise ValueError(
                f"scene {scene_id!r} must contain one nominal candidate per direction"
            )
    base_ids = {
        item.compiled.contract.candidate_id for item in base
    }
    if any(item.parent_candidate_id not in base_ids for item in refinements):
        raise ValueError("refinement parent is absent from the base search plan")
    base_by_id = {
        item.compiled.contract.candidate_id: item for item in base
    }
    if any(
        (
            item.brief.scene_id,
            item.brief.direction,
            item.brief.brief_id,
        )
        != (
            base_by_id[item.parent_candidate_id].brief.scene_id,
            base_by_id[item.parent_candidate_id].brief.direction,
            base_by_id[item.parent_candidate_id].brief.brief_id,
        )
        for item in refinements
        if item.parent_candidate_id is not None
    ):
        raise ValueError("refinement must preserve its parent brief and direction")


class BudgetedCandidateSearchRunner:
    def __init__(
        self,
        *,
        renderer: CandidateFrameRenderer,
        qc_evaluator: SearchHardGateEvaluator,
        store: CandidateSearchStore,
    ) -> None:
        self.renderer = renderer
        self.qc_evaluator = qc_evaluator
        self.store = store

    def _renderer_input_digest(self, graph: GradeGraph) -> str:
        provider = getattr(self.renderer, "input_digest", None)
        if callable(provider):
            value = provider(graph)
            if not isinstance(value, str) or not re.fullmatch(
                r"[0-9a-f]{64}",
                value,
            ):
                raise ValueError("renderer input digest must be a SHA-256 value")
            return value
        return canonical_sha256(
            {"renderer_version": self.renderer.renderer_version}
        )

    def run(
        self,
        *,
        run_id: str,
        context: ProjectContextPack,
        current_graph: GradeGraph,
        candidates: list[SearchCandidateInput],
        budget: CandidateSearchBudget,
        cancel_check: Callable[[], bool] | None = None,
        ranker: Callable[[list[SearchCandidateRecord]], list[str]] | None = None,
        progress_callback: Callable[[CandidateSearchState], None] | None = None,
    ) -> CandidateSearchResult:
        _validate_candidate_plan(
            candidates,
            current_graph=current_graph,
            context=context,
        )
        if sum(item.is_refinement for item in candidates) > budget.maximum_refinements:
            raise ValueError("candidate plan exceeds the refinement budget")
        renderer_input_digest = self._renderer_input_digest(current_graph)
        plan_digest = _plan_digest(
            context=context,
            current_graph=current_graph,
            candidates=candidates,
            renderer_version=self.renderer.renderer_version,
            renderer_input_digest=renderer_input_digest,
            budget=budget,
        )
        context_digest = canonical_sha256(context)
        source_digest = graph_digest(current_graph)
        existing = self.store.load_state(run_id)
        previously_attempted_ids: set[str] = set()
        if existing is not None:
            if (
                existing.plan_digest != plan_digest
                or existing.source_graph_digest != source_digest
                or existing.context_digest != context_digest
                or existing.renderer_version != self.renderer.renderer_version
            ):
                raise ValueError("saved candidate search state belongs to another plan")
            previously_attempted_ids = {
                item.candidate_id for item in existing.candidates
            }
            valid_records = [
                item
                for item in existing.candidates
                if self.store.record_assets_valid(run_id, item)
            ]
            if (
                existing.status == CandidateSearchStatus.COMPLETE
                and len(valid_records) == len(existing.candidates)
            ):
                return CandidateSearchResult(state=existing)
            state = existing.model_copy(
                update={
                    "status": CandidateSearchStatus.RUNNING,
                    "candidates": valid_records,
                    "survivor_candidate_ids": [],
                    "preferred_candidate_id": None,
                    "runner_up_candidate_id": None,
                    "selection_status": "search-running",
                }
            )
        else:
            state = CandidateSearchState(
                run_id=run_id,
                plan_digest=plan_digest,
                source_graph_digest=source_digest,
                context_digest=context_digest,
                renderer_version=self.renderer.renderer_version,
                status=CandidateSearchStatus.RUNNING,
                usage=CandidateSearchUsage(),
                candidates=[],
                survivor_candidate_ids=[],
                selection_status="search-running",
            )
        self.store.save_state(state)
        if progress_callback is not None:
            progress_callback(state)
        base_wall = state.usage.wall_seconds
        started = time.perf_counter()
        records = list(state.candidates)
        completed_ids = {item.candidate_id for item in records}
        usage = state.usage
        status = CandidateSearchStatus.RUNNING
        ordered_inputs = sorted(
            candidates,
            key=lambda item: (
                item.is_refinement,
                item.brief.scene_id,
                _DIRECTION_ORDER[item.brief.direction],
                item.compiled.contract.candidate_id,
            ),
        )
        cancellation = cancel_check or (lambda: False)

        def wall_seconds() -> float:
            return base_wall + (time.perf_counter() - started)

        for item in ordered_inputs:
            candidate_id = item.compiled.contract.candidate_id
            if candidate_id in completed_ids:
                continue
            if cancellation():
                status = CandidateSearchStatus.CANCELLED
                break
            samples = select_candidate_samples(
                scene_id=item.brief.scene_id,
                context=context,
                graph=current_graph,
            )
            cache_key = _cache_key(
                candidate=item,
                context=context,
                current_graph=current_graph,
                renderer_version=self.renderer.renderer_version,
                renderer_input_digest=renderer_input_digest,
                samples=samples,
            )
            cached = self.store.load_render_cache(run_id, cache_key)
            rendered_frames_needed = 0 if cached is not None else len(samples)
            projected = CandidateSearchUsage(
                model_calls=usage.model_calls
                + (
                    0
                    if candidate_id in previously_attempted_ids
                    else item.model_calls
                ),
                rendered_frames=usage.rendered_frames + rendered_frames_needed,
                wall_seconds=wall_seconds(),
                cost_usd=usage.cost_usd
                + (
                    0
                    if candidate_id in previously_attempted_ids
                    else item.model_cost_usd
                ),
                candidate_attempts=usage.candidate_attempts + 1,
                cache_hits=usage.cache_hits + int(cached is not None),
                refinements=usage.refinements
                + int(
                    item.is_refinement
                    and candidate_id not in previously_attempted_ids
                ),
            )
            if (
                projected.model_calls > budget.maximum_model_calls
                or projected.rendered_frames > budget.maximum_rendered_frames
                or projected.wall_seconds > budget.maximum_wall_seconds
                or projected.cost_usd > budget.maximum_cost_usd
                or projected.refinements > budget.maximum_refinements
            ):
                status = CandidateSearchStatus.BUDGET_EXHAUSTED
                break
            usage = projected
            graph_path, undo_path, contract_path = self.store.persist_compiled_assets(
                run_id,
                cache_key,
                item.compiled,
            )
            try:
                if cached is None:
                    rendered = self.renderer.render(
                        candidate=item,
                        current_graph=current_graph,
                        samples=samples,
                        output_dir=self.store.cache_dir(run_id, cache_key),
                    )
                    if len(rendered) != len(samples):
                        raise ValueError(
                            "candidate renderer did not return every requested frame"
                        )
                    self.store.save_render_cache(run_id, cache_key, rendered)
                    cache_hit = False
                else:
                    rendered = cached
                    cache_hit = True
                qc = self.qc_evaluator.evaluate(
                    candidate=item,
                    samples=rendered,
                    required_check_ids=item.compiled.required_qc_checks,
                )
                record = SearchCandidateRecord(
                    candidate_id=candidate_id,
                    parent_candidate_id=item.parent_candidate_id,
                    scene_id=item.brief.scene_id,
                    brief_id=item.brief.brief_id,
                    direction=item.brief.direction,
                    strategy_id=item.strategy.strategy_id,
                    compiled_graph_digest=(
                        item.compiled.contract.compiled_graph_digest
                    ),
                    cache_key=cache_key,
                    cache_hit=cache_hit,
                    status=(
                        CandidateAttemptStatus.HARD_PASS
                        if qc.hard_passed
                        else CandidateAttemptStatus.HARD_FAIL
                    ),
                    samples=rendered,
                    qc=qc,
                    graph_path=graph_path,
                    undo_graph_path=undo_path,
                    contract_path=contract_path,
                    is_refinement=item.is_refinement,
                )
            except Exception as exc:  # evidence is persisted; the run continues safely
                record = SearchCandidateRecord(
                    candidate_id=candidate_id,
                    parent_candidate_id=item.parent_candidate_id,
                    scene_id=item.brief.scene_id,
                    brief_id=item.brief.brief_id,
                    direction=item.brief.direction,
                    strategy_id=item.strategy.strategy_id,
                    compiled_graph_digest=(
                        item.compiled.contract.compiled_graph_digest
                    ),
                    cache_key=cache_key,
                    cache_hit=False,
                    status=CandidateAttemptStatus.RENDER_FAILED,
                    samples=[],
                    failure_detail=f"{type(exc).__name__}: {exc}",
                    graph_path=graph_path,
                    undo_graph_path=undo_path,
                    contract_path=contract_path,
                    is_refinement=item.is_refinement,
                )
            records.append(record)
            completed_ids.add(candidate_id)
            usage = usage.model_copy(update={"wall_seconds": wall_seconds()})
            state = state.model_copy(
                update={
                    "usage": usage,
                    "candidates": records,
                }
            )
            self.store.save_state(state)
            if progress_callback is not None:
                progress_callback(state)
            if cancellation():
                status = CandidateSearchStatus.CANCELLED
                break
            if usage.wall_seconds >= budget.maximum_wall_seconds:
                status = CandidateSearchStatus.BUDGET_EXHAUSTED
                break
        else:
            status = CandidateSearchStatus.COMPLETE

        survivors = [
            item for item in records if item.status == CandidateAttemptStatus.HARD_PASS
        ]
        if ranker is not None and survivors:
            ranked_ids = ranker(list(survivors))
            expected_ids = {item.candidate_id for item in survivors}
            if (
                len(ranked_ids) != len(set(ranked_ids))
                or set(ranked_ids) != expected_ids
            ):
                raise ValueError("candidate ranker must return every survivor exactly once")
            selection_status = "external-ranked-hard-pass"
        else:
            ranked_ids = [
                item.candidate_id
                for item in sorted(
                    survivors,
                    key=lambda value: (
                        value.scene_id,
                        _DIRECTION_ORDER[value.direction],
                        value.is_refinement,
                        value.candidate_id,
                    ),
                )
            ]
            selection_status = (
                "provisional-no-critic"
                if ranked_ids
                else "no-hard-pass-candidate"
            )
        usage = usage.model_copy(update={"wall_seconds": wall_seconds()})
        state = state.model_copy(
            update={
                "status": status,
                "usage": usage,
                "candidates": records,
                "survivor_candidate_ids": ranked_ids,
                "preferred_candidate_id": ranked_ids[0] if ranked_ids else None,
                "runner_up_candidate_id": (
                    ranked_ids[1] if len(ranked_ids) > 1 else None
                ),
                "selection_status": selection_status,
            }
        )
        self.store.save_state(state)
        if progress_callback is not None:
            progress_callback(state)
        return CandidateSearchResult(state=state)
