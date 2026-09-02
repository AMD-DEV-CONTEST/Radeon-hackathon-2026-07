from __future__ import annotations

import hashlib
from bisect import bisect_left
from datetime import UTC, datetime
from pathlib import Path

from pydantic import Field, HttpUrl, model_validator

from colorgraph.domain.grade_graph import ColorSpace, MediaInfo, TimeRange
from colorgraph.evaluation.manifest import (
    DatasetSplit,
    EvaluationTask,
    MediaOrigin,
)
from colorgraph.evaluation.models import StrictEvaluationModel
from colorgraph.media.probe import (
    VideoFrameTiming,
    probe_frame_timings,
    probe_media,
)
from colorgraph.media.shots import detect_shot_ranges


class SourceFetchAttempt(StrictEvaluationModel):
    at: datetime
    status: str
    reason: str


class GoldSourceCandidate(StrictEvaluationModel):
    id: str
    source_group_id: str
    title: str
    source_page_url: HttpUrl | None = None
    media_url: HttpUrl | None = None
    local_media_path: str
    rights_holder: str
    license: str
    license_url: HttpUrl | None = None
    license_evidence_path: str | None = None
    media_origin: MediaOrigin = MediaOrigin.PUBLISHED_DATASET
    commercial_use_allowed: bool
    redistribution_allowed: bool
    attribution: str
    capture_date: str
    camera: str
    camera_evidence: str
    proposed_split: DatasetSplit
    proposed_tasks: list[EvaluationTask] = Field(min_length=1)
    proposed_tags: list[str] = Field(min_length=1)
    capture_metadata_status: str
    declared_input_color_space: ColorSpace | None = None
    declared_log_profile: str | None = None
    annotation_status: str

    @model_validator(mode="after")
    def validate_candidate(self) -> GoldSourceCandidate:
        path = Path(self.local_media_path)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(
                f"candidate local path must be relative and contained: "
                f"{self.local_media_path!r}"
            )
        if self.license_evidence_path is not None:
            evidence = Path(self.license_evidence_path)
            if evidence.is_absolute() or ".." in evidence.parts:
                raise ValueError(
                    "candidate license evidence path must be relative and "
                    f"contained: {self.license_evidence_path!r}"
                )
        if self.source_page_url is None and self.license_evidence_path is None:
            raise ValueError(
                "candidate must provide either a public source page or "
                "contained private license evidence"
            )
        if self.media_origin in {
            MediaOrigin.UNKNOWN,
            MediaOrigin.PROCEDURAL,
        }:
            raise ValueError(
                "source candidates must identify a real-media origin"
            )
        if (
            self.declared_input_color_space == ColorSpace.LOG
            and not self.declared_log_profile
        ):
            raise ValueError(
                "a declared Log input requires a declared Log profile"
            )
        if (
            self.declared_input_color_space != ColorSpace.LOG
            and self.declared_log_profile is not None
        ):
            raise ValueError(
                "a declared Log profile requires input_color_space=log"
            )
        if not set(self.proposed_tasks).issubset(
            {
                EvaluationTask.SHOT_BOUNDARY,
                EvaluationTask.SCENE,
                EvaluationTask.SEMANTIC_MASK,
                EvaluationTask.TEMPORAL_MASK,
                EvaluationTask.DEPTH,
            }
        ):
            raise ValueError("source candidates may only propose landscape truth tasks")
        if len(self.proposed_tags) != len(set(self.proposed_tags)):
            raise ValueError("source candidate tags must be unique")
        return self


class GoldSourceRegistry(StrictEvaluationModel):
    schema_version: str = "colorgraph.gold-source-candidates/v1"
    created_at: datetime
    status: str
    source_catalog: str
    catalog_api: HttpUrl
    license_evidence_policy: str
    last_fetch_attempt: SourceFetchAttempt
    remaining_coverage_gaps: list[str]
    candidates: list[GoldSourceCandidate] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_registry(self) -> GoldSourceRegistry:
        ids = [candidate.id for candidate in self.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("source candidate ids must be unique")
        groups = [
            candidate.source_group_id for candidate in self.candidates
        ]
        if len(groups) != len(set(groups)):
            raise ValueError("source candidate groups must be unique")
        paths = [
            candidate.local_media_path for candidate in self.candidates
        ]
        if len(paths) != len(set(paths)):
            raise ValueError("source candidate local paths must be unique")
        return self


class GoldSourceStatus(StrictEvaluationModel):
    schema_version: str = "colorgraph.gold-source-status/v1"
    registry_path: str
    candidates: int
    documented_camera_candidates: int
    commercial_use_candidates: int
    downloaded_candidates: int
    missing_candidates: list[str]
    zero_byte_candidates: list[str]
    missing_license_evidence_candidates: list[str]
    zero_byte_license_evidence_candidates: list[str]
    ready_for_annotation: bool


class InspectedGoldSource(StrictEvaluationModel):
    candidate_id: str
    source_group_id: str
    local_media_path: str
    media_sha256: str
    media_bytes: int
    camera: str
    camera_evidence: str
    license: str
    source_page_url: HttpUrl | None
    license_evidence_path: str | None = None
    media_origin: MediaOrigin = MediaOrigin.PUBLISHED_DATASET
    capture_metadata_status: str = "not_recorded"
    declared_input_color_space: ColorSpace | None = None
    declared_log_profile: str | None = None
    proposed_split: DatasetSplit
    proposed_tasks: list[EvaluationTask]
    proposed_tags: list[str]
    probe: MediaInfo
    frame_timing_count: int = Field(gt=0)
    frame_timing_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    draft_shot_ranges: list[TimeRange]
    draft_only: bool = True
    annotation_status: str = "pending_independent_human_annotation"


class GoldSourceInspectionReport(StrictEvaluationModel):
    schema_version: str = "colorgraph.gold-source-inspection/v1"
    generated_at: datetime
    registry_path: str
    sources: list[InspectedGoldSource]
    total_source_groups: int
    total_draft_shots: int
    warning: str = (
        "Machine-generated ranges are intake drafts and never count as human "
        "Gold Set truth."
    )


class AnnotationFrameTiming(StrictEvaluationModel):
    frame_index: int = Field(ge=0)
    pts_seconds: float
    timeline_seconds: float = Field(ge=0)
    duration_seconds: float | None = Field(default=None, gt=0)


class AnnotationDraftRange(StrictEvaluationModel):
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    first_frame_index: int = Field(ge=0)
    last_frame_index: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_range(self) -> AnnotationDraftRange:
        if self.end_seconds <= self.start_seconds:
            raise ValueError("annotation draft range must have positive duration")
        if self.last_frame_index < self.first_frame_index:
            raise ValueError("annotation draft range frame indexes are reversed")
        return self


class AnnotationWorkItem(StrictEvaluationModel):
    candidate_id: str
    source_group_id: str
    local_media_path: str
    media_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    camera: str
    license: str
    source_page_url: HttpUrl | None
    license_evidence_path: str | None = None
    media_origin: MediaOrigin = MediaOrigin.PUBLISHED_DATASET
    capture_metadata_status: str = "not_recorded"
    declared_input_color_space: ColorSpace | None = None
    declared_log_profile: str | None = None
    proposed_split: DatasetSplit
    proposed_tasks: list[EvaluationTask]
    proposed_tags: list[str]
    annotation_output_path: str
    signoff_template_path: str = "annotation-signoff-template.json"
    frame_count: int = Field(gt=0)
    frame_timing_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    frame_timings: list[AnnotationFrameTiming] = Field(min_length=1)
    draft_ranges: list[AnnotationDraftRange] = Field(min_length=1)
    truth_status: str = "pending_independent_human_annotation"


class AnnotationWorkPack(StrictEvaluationModel):
    schema_version: str = "colorgraph.annotation-work-pack/v1"
    generated_at: datetime
    annotation_guideline_version: str = "colorgraph.landscape-annotation/v1"
    annotation_guideline_path: str = "docs/LANDSCAPE_ANNOTATION_V1.md"
    inspection_report_path: str
    inspection_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    required_roles: list[str] = Field(
        default_factory=lambda: ["annotator", "independent_reviewer"]
    )
    items: list[AnnotationWorkItem] = Field(min_length=1)
    status: str = "pending_independent_human_annotation"
    warning: str = (
        "Draft ranges and frame indexes are machine-generated work aids. "
        "Only accepted annotations signed by disjoint annotator and reviewer "
        "identities count as Gold Set truth."
    )


def load_source_registry(path: str | Path) -> GoldSourceRegistry:
    source = Path(path).resolve()
    return GoldSourceRegistry.model_validate_json(
        source.read_text(encoding="utf-8")
    )


def source_registry_status(
    registry_path: str | Path,
    *,
    root: str | Path | None = None,
) -> GoldSourceStatus:
    source = Path(registry_path).resolve()
    registry = load_source_registry(source)
    dataset_root = (
        Path(root).resolve() if root is not None else source.parent.resolve()
    )
    missing: list[str] = []
    zero_byte: list[str] = []
    missing_license_evidence: list[str] = []
    zero_byte_license_evidence: list[str] = []
    downloaded = 0
    for candidate in registry.candidates:
        path = (dataset_root / candidate.local_media_path).resolve()
        if not path.is_relative_to(dataset_root):
            raise ValueError(
                f"candidate path escapes intake root: {candidate.local_media_path}"
            )
        if not path.is_file():
            missing.append(candidate.id)
        elif path.stat().st_size == 0:
            zero_byte.append(candidate.id)
        else:
            downloaded += 1
        if candidate.license_evidence_path is not None:
            evidence_path = (
                dataset_root / candidate.license_evidence_path
            ).resolve()
            if not evidence_path.is_relative_to(dataset_root):
                raise ValueError(
                    "candidate license evidence path escapes intake root: "
                    f"{candidate.license_evidence_path}"
                )
            if not evidence_path.is_file():
                missing_license_evidence.append(candidate.id)
            elif evidence_path.stat().st_size == 0:
                zero_byte_license_evidence.append(candidate.id)
    documented_cameras = sum(
        "not specified" not in candidate.camera.lower()
        and "unspecified" not in candidate.camera.lower()
        for candidate in registry.candidates
    )
    commercial = sum(
        candidate.commercial_use_allowed
        for candidate in registry.candidates
    )
    return GoldSourceStatus(
        registry_path=str(source),
        candidates=len(registry.candidates),
        documented_camera_candidates=documented_cameras,
        commercial_use_candidates=commercial,
        downloaded_candidates=downloaded,
        missing_candidates=missing,
        zero_byte_candidates=zero_byte,
        missing_license_evidence_candidates=missing_license_evidence,
        zero_byte_license_evidence_candidates=zero_byte_license_evidence,
        ready_for_annotation=(
            not missing
            and not zero_byte
            and not missing_license_evidence
            and not zero_byte_license_evidence
        ),
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_source_inspection(path: str | Path) -> GoldSourceInspectionReport:
    source = Path(path).resolve()
    return GoldSourceInspectionReport.model_validate_json(
        source.read_text(encoding="utf-8")
    )


def _frame_timing_sha256(timings: list[VideoFrameTiming]) -> str:
    digest = hashlib.sha256()
    for index, timing in enumerate(timings):
        duration = (
            ""
            if timing.duration_seconds is None
            else f"{timing.duration_seconds:.12f}"
        )
        digest.update(
            f"{index}\0{timing.pts_seconds:.12f}\0{duration}\n".encode()
        )
    return digest.hexdigest()


def _map_draft_ranges_to_frames(
    ranges: list[TimeRange],
    timings: list[VideoFrameTiming],
) -> list[AnnotationDraftRange]:
    first_pts = timings[0].pts_seconds
    timestamps = [timing.pts_seconds - first_pts for timing in timings]
    mapped: list[AnnotationDraftRange] = []
    for draft in ranges:
        first = bisect_left(timestamps, draft.start_seconds - 1e-9)
        if first >= len(timestamps):
            raise ValueError(
                f"draft range starts after the final frame: {draft.start_seconds}"
            )
        end_exclusive = bisect_left(timestamps, draft.end_seconds - 1e-9)
        last = min(len(timestamps) - 1, max(first, end_exclusive - 1))
        mapped.append(
            AnnotationDraftRange(
                start_seconds=draft.start_seconds,
                end_seconds=draft.end_seconds,
                first_frame_index=first,
                last_frame_index=last,
            )
        )
    return mapped


def create_annotation_work_pack(
    inspection_path: str | Path,
    output_path: str | Path,
    *,
    root: str | Path | None = None,
) -> AnnotationWorkPack:
    source = Path(inspection_path).resolve()
    inspection = load_source_inspection(source)
    intake_root = (
        Path(root).resolve() if root is not None else source.parent.resolve()
    )
    work_items: list[AnnotationWorkItem] = []
    for inspected in inspection.sources:
        media_path = (intake_root / inspected.local_media_path).resolve()
        if not media_path.is_relative_to(intake_root):
            raise ValueError(
                f"inspected media path escapes intake root: "
                f"{inspected.local_media_path}"
            )
        if not media_path.is_file():
            raise FileNotFoundError(f"inspected media is missing: {media_path}")
        actual_hash = _sha256(media_path)
        if actual_hash != inspected.media_sha256:
            raise ValueError(
                f"inspected media checksum changed for "
                f"{inspected.candidate_id}: expected "
                f"{inspected.media_sha256}, got {actual_hash}"
            )
        timings = probe_frame_timings(media_path)
        timing_hash = _frame_timing_sha256(timings)
        if len(timings) != inspected.frame_timing_count:
            raise ValueError(
                f"frame timing count mismatch for {inspected.candidate_id}: "
                f"inspection={inspected.frame_timing_count}, "
                f"timings={len(timings)}"
            )
        if timing_hash != inspected.frame_timing_sha256:
            raise ValueError(
                f"frame timing checksum changed for "
                f"{inspected.candidate_id}: expected "
                f"{inspected.frame_timing_sha256}, got {timing_hash}"
            )
        work_items.append(
            AnnotationWorkItem(
                candidate_id=inspected.candidate_id,
                source_group_id=inspected.source_group_id,
                local_media_path=inspected.local_media_path,
                media_sha256=inspected.media_sha256,
                camera=inspected.camera,
                license=inspected.license,
                source_page_url=inspected.source_page_url,
                license_evidence_path=inspected.license_evidence_path,
                media_origin=inspected.media_origin,
                capture_metadata_status=inspected.capture_metadata_status,
                declared_input_color_space=(
                    inspected.declared_input_color_space
                ),
                declared_log_profile=inspected.declared_log_profile,
                proposed_split=inspected.proposed_split,
                proposed_tasks=inspected.proposed_tasks,
                proposed_tags=inspected.proposed_tags,
                annotation_output_path=(
                    f"annotations/{inspected.candidate_id}.json"
                ),
                frame_count=len(timings),
                frame_timing_sha256=timing_hash,
                frame_timings=[
                    AnnotationFrameTiming(
                        frame_index=index,
                        pts_seconds=timing.pts_seconds,
                        timeline_seconds=(
                            timing.pts_seconds - timings[0].pts_seconds
                        ),
                        duration_seconds=timing.duration_seconds,
                    )
                    for index, timing in enumerate(timings)
                ],
                draft_ranges=_map_draft_ranges_to_frames(
                    inspected.draft_shot_ranges,
                    timings,
                ),
            )
        )
    pack = AnnotationWorkPack(
        generated_at=datetime.now(UTC),
        inspection_report_path=str(source),
        inspection_report_sha256=_sha256(source),
        items=work_items,
    )
    destination = Path(output_path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(pack.model_dump_json(indent=2), encoding="utf-8")
    return pack


def inspect_source_registry(
    registry_path: str | Path,
    output_path: str | Path,
    *,
    root: str | Path | None = None,
) -> GoldSourceInspectionReport:
    source = Path(registry_path).resolve()
    registry = load_source_registry(source)
    status = source_registry_status(source, root=root)
    if not status.ready_for_annotation:
        raise FileNotFoundError(
            "source registry has missing or zero-byte media: "
            f"missing={status.missing_candidates}, "
            f"zero_byte={status.zero_byte_candidates}"
        )
    dataset_root = (
        Path(root).resolve() if root is not None else source.parent.resolve()
    )
    inspected: list[InspectedGoldSource] = []
    for candidate in registry.candidates:
        media_path = (dataset_root / candidate.local_media_path).resolve()
        draft_ranges = detect_shot_ranges(media_path)
        probe = probe_media(media_path)
        frame_timings = probe_frame_timings(media_path)
        inspected.append(
            InspectedGoldSource(
                candidate_id=candidate.id,
                source_group_id=candidate.source_group_id,
                local_media_path=candidate.local_media_path,
                media_sha256=_sha256(media_path),
                media_bytes=media_path.stat().st_size,
                camera=candidate.camera,
                camera_evidence=candidate.camera_evidence,
                license=candidate.license,
                source_page_url=candidate.source_page_url,
                license_evidence_path=candidate.license_evidence_path,
                media_origin=candidate.media_origin,
                capture_metadata_status=candidate.capture_metadata_status,
                declared_input_color_space=(
                    candidate.declared_input_color_space
                ),
                declared_log_profile=candidate.declared_log_profile,
                proposed_split=candidate.proposed_split,
                proposed_tasks=candidate.proposed_tasks,
                proposed_tags=candidate.proposed_tags,
                probe=probe.model_copy(
                    update={"frame_count": len(frame_timings)}
                ),
                frame_timing_count=len(frame_timings),
                frame_timing_sha256=_frame_timing_sha256(frame_timings),
                draft_shot_ranges=draft_ranges,
            )
        )
    report = GoldSourceInspectionReport(
        generated_at=datetime.now(UTC),
        registry_path=str(source),
        sources=inspected,
        total_source_groups=len(inspected),
        total_draft_shots=sum(
            len(item.draft_shot_ranges) for item in inspected
        ),
    )
    destination = Path(output_path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return report
