from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from colorgraph.domain.grade_graph import GradeGraph, MaskAsset
from colorgraph.evaluation.models import StrictEvaluationModel
from colorgraph.grading.looks import graph_digest
from colorgraph.vision.depth import DEPTH_TARGETS, DepthMaskProvider
from colorgraph.vision.semantic import SemanticMaskProvider
from colorgraph.vision.video_masks import (
    MaskGenerationResult,
    ProgressCallback,
    VideoMaskGenerator,
)

TRACKED_MASK_ASSET_SCHEMA = "colorgraph.formal-tracked-mask-assets/v1"


class TrackedMaskAssetEvidence(StrictEvaluationModel):
    asset_id: str = Field(min_length=1)
    target: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    model_revision: str = Field(min_length=1)
    checkpoint_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    checkpoint_hash_kind: str = Field(min_length=1)
    video_path: str = Field(min_length=1)
    video_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    frame_count: int = Field(gt=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    fps: float = Field(gt=0)
    storage_bit_depth: Literal[8, 16]
    tracking_algorithm: str = Field(min_length=1)


class TrackedMaskAssetObservation(StrictEvaluationModel):
    schema_version: str = TRACKED_MASK_ASSET_SCHEMA
    created_at: datetime
    status: Literal["completed"] = "completed"
    project_id: str = Field(min_length=1)
    source_path: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_graph_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_graph_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    semantic_model_id: str = Field(min_length=1)
    semantic_model_revision: str = Field(min_length=1)
    depth_model_id: str = Field(min_length=1)
    depth_model_revision: str = Field(min_length=1)
    maximum_edge: int = Field(gt=0)
    inference_interval_seconds: float = Field(gt=0)
    storage_bit_depth: Literal[8, 16]
    sequence_retained: bool
    frame_count: int = Field(gt=0)
    inference_frames: int = Field(gt=0)
    elapsed_seconds: float = Field(gt=0)
    assets: list[TrackedMaskAssetEvidence] = Field(min_length=1)
    benchmark_authorized: bool = True
    gold_quality_claim_authorized: bool = False
    production_default_authorized: bool = False

    @model_validator(mode="after")
    def validate_bundle(self) -> TrackedMaskAssetObservation:
        if self.schema_version != TRACKED_MASK_ASSET_SCHEMA:
            raise ValueError(
                f"unsupported tracked-mask observation: {self.schema_version}"
            )
        asset_ids = [asset.asset_id for asset in self.assets]
        if len(asset_ids) != len(set(asset_ids)):
            raise ValueError("tracked-mask observation repeats an asset id")
        if any(asset.frame_count != self.frame_count for asset in self.assets):
            raise ValueError("tracked-mask asset frame counts must match the source")
        semantic = [
            asset
            for asset in self.assets
            if asset.target not in DEPTH_TARGETS
        ]
        depth = [
            asset
            for asset in self.assets
            if asset.target in DEPTH_TARGETS
        ]
        if (
            not semantic
            or not depth
            or any(
                asset.provider != self.semantic_model_id
                or asset.model_revision != self.semantic_model_revision
                for asset in semantic
            )
            or any(
                asset.provider != self.depth_model_id
                or asset.model_revision != self.depth_model_revision
                for asset in depth
            )
        ):
            raise ValueError(
                "tracked-mask asset identities do not match the requested models"
            )
        return self


@dataclass(frozen=True, slots=True)
class TrackedMaskAssetGenerationResult:
    graph: GradeGraph
    observation: TrackedMaskAssetObservation


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(path)


def _asset_evidence(
    asset: MaskAsset,
    *,
    storage_bit_depth: Literal[8, 16],
) -> TrackedMaskAssetEvidence:
    metadata = asset.metadata
    tracking = metadata.get("tracking")
    if not isinstance(tracking, dict):
        raise ValueError(f"mask asset {asset.id} has no tracking evidence")
    required = {
        "provider": metadata.get("provider"),
        "model_revision": metadata.get("model_revision"),
        "checkpoint_sha256": metadata.get("checkpoint_sha256"),
        "checkpoint_hash_kind": metadata.get("checkpoint_hash_kind"),
        "video_path": metadata.get("video_path"),
        "video_sha256": metadata.get("video_sha256"),
        "width": metadata.get("width"),
        "height": metadata.get("height"),
        "fps": metadata.get("fps"),
        "tracking_algorithm": tracking.get("algorithm"),
    }
    missing = sorted(
        key for key, value in required.items() if value in {None, ""}
    )
    if missing:
        raise ValueError(
            f"mask asset {asset.id} lacks formal evidence: {missing}"
        )
    video_path = Path(str(required["video_path"]))
    if (
        not video_path.is_file()
        or _sha256(video_path) != required["video_sha256"]
    ):
        raise ValueError(f"mask asset {asset.id} video identity is invalid")
    return TrackedMaskAssetEvidence(
        asset_id=asset.id,
        target=asset.target,
        kind=asset.kind.value,
        provider=str(required["provider"]),
        model_revision=str(required["model_revision"]),
        checkpoint_sha256=str(required["checkpoint_sha256"]),
        checkpoint_hash_kind=str(required["checkpoint_hash_kind"]),
        video_path=str(video_path),
        video_sha256=str(required["video_sha256"]),
        frame_count=asset.frame_count,
        width=int(required["width"]),
        height=int(required["height"]),
        fps=float(required["fps"]),
        storage_bit_depth=storage_bit_depth,
        tracking_algorithm=str(required["tracking_algorithm"]),
    )


def generate_tracked_mask_asset_bundle(
    source_path: str | Path,
    graph: GradeGraph,
    output_root: str | Path,
    report_output_path: str | Path,
    *,
    semantic_provider: SemanticMaskProvider,
    depth_provider: DepthMaskProvider,
    semantic_model_revision: str,
    depth_model_revision: str,
    targets: list[str] | None = None,
    inference_interval_seconds: float = 1.5,
    maximum_edge: int = 640,
    storage_bit_depth: Literal[8, 16] = 16,
    retain_mask_sequence: bool = False,
    progress: ProgressCallback | None = None,
) -> TrackedMaskAssetGenerationResult:
    source = Path(source_path).resolve()
    report_path = Path(report_output_path).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if report_path == source:
        raise ValueError("tracked-mask report cannot overwrite the source")
    if semantic_provider.model_revision != semantic_model_revision:
        raise ValueError("semantic provider revision is not frozen as requested")
    if depth_provider.model_revision != depth_model_revision:
        raise ValueError("depth provider revision is not frozen as requested")

    source_sha256 = _sha256(source)
    input_digest = graph_digest(graph)
    started = time.perf_counter()
    generated: MaskGenerationResult = VideoMaskGenerator(
        semantic_provider,
        depth_provider,
    ).generate(
        source,
        graph,
        output_root,
        targets=targets,
        inference_interval_seconds=inference_interval_seconds,
        maximum_edge=maximum_edge,
        storage_bit_depth=storage_bit_depth,
        retain_mask_sequence=retain_mask_sequence,
        progress=progress,
    )
    generated_ids = {f"mask_{target}" for target in generated.targets}
    updated_masks: list[MaskAsset] = []
    for asset in generated.graph.masks:
        if asset.id not in generated_ids:
            updated_masks.append(asset)
            continue
        updated_masks.append(
            asset.model_copy(
                update={
                    "metadata": {
                        **asset.metadata,
                        "source_path": str(source),
                        "source_sha256": source_sha256,
                    }
                },
                deep=True,
            )
        )
    updated_graph = generated.graph.model_copy(
        update={"masks": updated_masks},
        deep=True,
    )
    generated_assets = [
        asset for asset in updated_graph.masks if asset.id in generated_ids
    ]
    evidence = [
        _asset_evidence(
            asset,
            storage_bit_depth=storage_bit_depth,
        )
        for asset in generated_assets
    ]
    if any(
        asset.model_revision != semantic_model_revision
        for asset in evidence
        if asset.target not in DEPTH_TARGETS
    ):
        raise ValueError("semantic asset resolved a different model revision")
    if any(
        asset.model_revision != depth_model_revision
        for asset in evidence
        if asset.target in DEPTH_TARGETS
    ):
        raise ValueError("depth asset resolved a different model revision")

    observation = TrackedMaskAssetObservation(
        created_at=datetime.now(UTC),
        project_id=graph.project_id,
        source_path=str(source),
        source_sha256=source_sha256,
        input_graph_digest=input_digest,
        output_graph_digest=graph_digest(updated_graph),
        semantic_model_id=semantic_provider.provider_id,
        semantic_model_revision=semantic_model_revision,
        depth_model_id=depth_provider.provider_id,
        depth_model_revision=depth_model_revision,
        maximum_edge=maximum_edge,
        inference_interval_seconds=inference_interval_seconds,
        storage_bit_depth=storage_bit_depth,
        sequence_retained=retain_mask_sequence,
        frame_count=generated.frame_count,
        inference_frames=generated.inference_frames,
        elapsed_seconds=max(time.perf_counter() - started, 1e-9),
        assets=evidence,
    )
    _atomic_write(report_path, observation.model_dump_json(indent=2))
    return TrackedMaskAssetGenerationResult(
        graph=updated_graph,
        observation=observation,
    )
