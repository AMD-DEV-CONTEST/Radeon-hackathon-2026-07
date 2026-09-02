from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated

from pydantic import Field, model_validator

from colorgraph.evaluation.models import StrictEvaluationModel

LANDSCAPE_ACCEPTANCE_ANNOTATION_VERSION = "colorgraph.landscape-annotation/v2"
LANDSCAPE_ACCEPTANCE_ANNOTATION_SHA256 = (
    "7ec8236222ced022b184d0e6d6cc17d318e64b8d932db222c42dfebdc8257192"
)


class DatasetSplit(StrEnum):
    TRAIN = "train"
    CALIBRATION = "calibration"
    TEST = "test"


class EvaluationTask(StrEnum):
    SHOT_BOUNDARY = "shot_boundary"
    SCENE = "scene"
    ANALYSIS = "analysis"
    REPRESENTATIVE_FRAME = "representative_frame"
    SEMANTIC_MASK = "semantic_mask"
    TEMPORAL_MASK = "temporal_mask"
    DEPTH = "depth"
    COLOR = "color"
    RANKING = "ranking"
    REPAIR = "repair"
    ENGINEERING = "engineering"


class MediaOrigin(StrEnum):
    UNKNOWN = "unknown"
    PROCEDURAL = "procedural"
    CAMERA_ORIGINAL = "camera_original"
    LICENSED_STOCK = "licensed_stock"
    PUBLISHED_DATASET = "published_dataset"


class AnnotationMethod(StrEnum):
    UNKNOWN = "unknown"
    PROCEDURAL = "procedural"
    HUMAN = "human"
    IMPORTED_HUMAN_GROUND_TRUTH = "imported_human_ground_truth"


class LicenseRecord(StrictEvaluationModel):
    id: str
    name: str
    source_url: str
    rights_holder: str
    usage_grant: str
    commercial_use_allowed: bool
    redistribution_allowed: bool
    attribution: str | None = None
    evidence_path: str


class CaptureMetadata(StrictEvaluationModel):
    camera: str
    lens: str | None = None
    codec: str
    pixel_format: str
    bit_depth: Annotated[int, Field(gt=0, le=32)]
    color_primaries: str | None = None
    color_transfer: str | None = None
    color_matrix: str | None = None
    color_range: str | None = None
    input_color_space: str
    log_profile: str | None = None
    fps: Annotated[float, Field(gt=0)]
    width: Annotated[int, Field(gt=0)]
    height: Annotated[int, Field(gt=0)]


class AnnotationProvenance(StrictEvaluationModel):
    method: AnnotationMethod = AnnotationMethod.UNKNOWN
    guideline_version: str = "unversioned"
    annotator_ids: list[str] = Field(default_factory=list)
    reviewer_ids: list[str] = Field(default_factory=list)
    completed_at: datetime | None = None
    reviewed_at: datetime | None = None
    accepted: bool = False


class GoldSetItem(StrictEvaluationModel):
    id: str
    task: EvaluationTask
    split: DatasetSplit
    source_group_id: str
    media_path: str
    annotation_path: str
    media_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    annotation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    license_id: str
    media_origin: MediaOrigin = MediaOrigin.UNKNOWN
    annotation_provenance: AnnotationProvenance = Field(
        default_factory=AnnotationProvenance
    )
    capture: CaptureMetadata
    tags: list[str] = Field(min_length=1)
    frozen: bool = False


class GoldSetManifest(StrictEvaluationModel):
    schema_version: str = "colorgraph.gold-set-manifest/v1"
    id: str
    version: str
    created_at: datetime
    split_seed: Annotated[int, Field(ge=0)]
    test_frozen_at: datetime
    test_policy: str
    annotation_guideline_version: str = "unversioned"
    annotation_guideline_path: str | None = None
    annotation_guideline_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    licenses: list[LicenseRecord] = Field(min_length=1)
    items: list[GoldSetItem] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_manifest_contract(self) -> GoldSetManifest:
        if (self.annotation_guideline_path is None) != (
            self.annotation_guideline_sha256 is None
        ):
            raise ValueError(
                "annotation guideline path and SHA-256 must be supplied together"
            )
        if (
            self.annotation_guideline_version
            == LANDSCAPE_ACCEPTANCE_ANNOTATION_VERSION
            and (
                self.annotation_guideline_path is None
                or self.annotation_guideline_sha256
                != LANDSCAPE_ACCEPTANCE_ANNOTATION_SHA256
            )
        ):
            raise ValueError(
                "landscape annotation v2 requires its canonical frozen "
                "guideline path and SHA-256"
            )
        item_ids = [item.id for item in self.items]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("gold-set item ids must be unique")
        license_ids = [license_record.id for license_record in self.licenses]
        if len(license_ids) != len(set(license_ids)):
            raise ValueError("gold-set license ids must be unique")
        unknown_licenses = {
            item.license_id
            for item in self.items
            if item.license_id not in set(license_ids)
        }
        if unknown_licenses:
            raise ValueError(
                f"gold-set items reference unknown licenses: {sorted(unknown_licenses)}"
            )
        group_splits: dict[str, DatasetSplit] = {}
        for item in self.items:
            previous = group_splits.setdefault(item.source_group_id, item.split)
            if previous != item.split:
                raise ValueError(
                    f"source group {item.source_group_id!r} leaks across "
                    f"{previous.value!r} and {item.split.value!r}"
                )
            for relative_path in (
                item.media_path,
                item.annotation_path,
            ):
                path = Path(relative_path)
                if path.is_absolute() or ".." in path.parts:
                    raise ValueError(
                        f"gold-set paths must be relative and contained: {relative_path!r}"
                    )
            if item.split == DatasetSplit.TEST and not item.frozen:
                raise ValueError(f"test item {item.id!r} must be frozen")
            if item.split != DatasetSplit.TEST and item.frozen:
                    raise ValueError(
                        f"only test items may set frozen=true: {item.id!r}"
                    )
        if self.annotation_guideline_path is not None:
            guideline_path = Path(self.annotation_guideline_path)
            if (
                guideline_path.is_absolute()
                or ".." in guideline_path.parts
            ):
                raise ValueError(
                    "annotation guideline path must be relative and contained"
                )
        if not any(item.split == DatasetSplit.TEST for item in self.items):
            raise ValueError("gold-set manifest must contain a frozen test split")
        return self


class GoldSetAuditProfile(StrictEvaluationModel):
    name: str = "landscape-p0/v1"
    minimum_shot_boundary_items: Annotated[int, Field(ge=0)] = 50
    minimum_scene_items: Annotated[int, Field(ge=0)] = 30
    minimum_complex_mask_depth_source_groups: Annotated[
        int,
        Field(ge=0),
    ] = 10
    minimum_unique_cameras: Annotated[int, Field(ge=1)] = 3
    required_tags: list[str] = Field(
        default_factory=lambda: [
            "rec709",
            "log",
            "day",
            "night",
            "snow",
            "water",
            "fog",
            "trees",
            "mountain",
            "fast_motion",
            "occlusion",
        ]
    )
    require_commercial_use: bool = True


LANDSCAPE_P0_AUDIT_PROFILE = GoldSetAuditProfile()


class GoldSetAuditReport(StrictEvaluationModel):
    schema_version: str = "colorgraph.gold-set-audit/v1"
    manifest_id: str
    manifest_version: str
    profile: GoldSetAuditProfile
    total_items: int
    task_counts: dict[str, int]
    qualified_task_counts: dict[str, int]
    split_counts: dict[str, int]
    media_origin_counts: dict[str, int]
    unique_qualified_cameras: list[str]
    complex_mask_depth_source_groups: int
    covered_tags: list[str]
    missing_tags: list[str]
    quota_results: dict[str, bool]
    issues: list[str]
    passed: bool


_HUMAN_GOLD_TASKS = frozenset(
    {
        EvaluationTask.SHOT_BOUNDARY,
        EvaluationTask.SCENE,
        EvaluationTask.ANALYSIS,
        EvaluationTask.REPRESENTATIVE_FRAME,
        EvaluationTask.SEMANTIC_MASK,
        EvaluationTask.TEMPORAL_MASK,
        EvaluationTask.DEPTH,
        EvaluationTask.RANKING,
        EvaluationTask.REPAIR,
    }
)
_HUMAN_METHODS = frozenset(
    {
        AnnotationMethod.HUMAN,
        AnnotationMethod.IMPORTED_HUMAN_GROUND_TRUTH,
    }
)
_REAL_MEDIA_ORIGINS = frozenset(
    {
        MediaOrigin.CAMERA_ORIGINAL,
        MediaOrigin.LICENSED_STOCK,
        MediaOrigin.PUBLISHED_DATASET,
    }
)


def human_truth_is_accepted(
    item: GoldSetItem,
    manifest: GoldSetManifest,
) -> bool:
    provenance = item.annotation_provenance
    return (
        provenance.method in _HUMAN_METHODS
        and provenance.guideline_version == manifest.annotation_guideline_version
        and manifest.annotation_guideline_version != "unversioned"
        and bool(provenance.annotator_ids)
        and bool(provenance.reviewer_ids)
        and set(provenance.annotator_ids).isdisjoint(provenance.reviewer_ids)
        and provenance.completed_at is not None
        and provenance.reviewed_at is not None
        and provenance.accepted
    )


def qualified_human_gold_items(
    manifest: GoldSetManifest,
    profile: GoldSetAuditProfile = LANDSCAPE_P0_AUDIT_PROFILE,
) -> list[GoldSetItem]:
    license_by_id = {record.id: record for record in manifest.licenses}
    qualified_items: list[GoldSetItem] = []
    for item in manifest.items:
        if item.task not in _HUMAN_GOLD_TASKS:
            continue
        license_record = license_by_id[item.license_id]
        license_is_qualified = (
            not profile.require_commercial_use
            or license_record.commercial_use_allowed
        )
        normalized_camera = item.capture.camera.strip().lower()
        camera_is_real = normalized_camera not in {
            "",
            "n/a",
            "not provided",
            "not specified",
            "unknown",
            "procedural",
            "unspecified",
        } and not any(
            marker in normalized_camera
            for marker in ("model not specified", "model unspecified")
        )
        if (
            item.media_origin in _REAL_MEDIA_ORIGINS
            and camera_is_real
            and license_is_qualified
            and human_truth_is_accepted(item, manifest)
        ):
            qualified_items.append(item)
    return qualified_items


def audit_gold_set(
    manifest: GoldSetManifest,
    profile: GoldSetAuditProfile = LANDSCAPE_P0_AUDIT_PROFILE,
) -> GoldSetAuditReport:
    task_counts = {
        task.value: sum(item.task == task for item in manifest.items)
        for task in EvaluationTask
    }
    split_counts = {
        split.value: sum(item.split == split for item in manifest.items)
        for split in DatasetSplit
    }
    media_origin_counts = {
        origin.value: sum(item.media_origin == origin for item in manifest.items)
        for origin in MediaOrigin
    }

    qualified_items = qualified_human_gold_items(manifest, profile)

    qualified_task_counts = {
        task.value: sum(item.task == task for item in qualified_items)
        for task in EvaluationTask
    }
    complex_tasks = {
        EvaluationTask.SEMANTIC_MASK,
        EvaluationTask.TEMPORAL_MASK,
        EvaluationTask.DEPTH,
    }
    complex_groups = {
        item.source_group_id
        for item in qualified_items
        if item.task in complex_tasks
    }
    covered_tags = sorted(
        {
            tag.strip().lower()
            for item in qualified_items
            for tag in item.tags
            if tag.strip()
        }
    )
    missing_tags = sorted(set(profile.required_tags) - set(covered_tags))
    cameras = sorted({item.capture.camera for item in qualified_items})
    qualified_splits = {item.split for item in qualified_items}
    qualified_tasks = {item.task for item in qualified_items}
    mask_tasks = {
        EvaluationTask.SEMANTIC_MASK,
        EvaluationTask.TEMPORAL_MASK,
    }

    quota_results = {
        "versioned_annotation_guideline": (
            manifest.annotation_guideline_version != "unversioned"
        ),
        "shot_boundary_quota": (
            qualified_task_counts[EvaluationTask.SHOT_BOUNDARY.value]
            >= profile.minimum_shot_boundary_items
        ),
        "scene_quota": (
            qualified_task_counts[EvaluationTask.SCENE.value]
            >= profile.minimum_scene_items
        ),
        "complex_mask_depth_quota": (
            len(complex_groups)
            >= profile.minimum_complex_mask_depth_source_groups
        ),
        "mask_truth_present": bool(qualified_tasks & mask_tasks),
        "depth_truth_present": EvaluationTask.DEPTH in qualified_tasks,
        "camera_diversity": len(cameras) >= profile.minimum_unique_cameras,
        "required_content_coverage": not missing_tags,
        "all_splits_present": qualified_splits
        == {
            DatasetSplit.TRAIN,
            DatasetSplit.CALIBRATION,
            DatasetSplit.TEST,
        },
    }
    issue_messages = {
        "versioned_annotation_guideline": (
            "annotation_guideline_version must be a frozen, versioned identifier"
        ),
        "shot_boundary_quota": (
            "qualified real/human shot-boundary items are below "
            f"{profile.minimum_shot_boundary_items}"
        ),
        "scene_quota": (
            "qualified real/human scene items are below "
            f"{profile.minimum_scene_items}"
        ),
        "complex_mask_depth_quota": (
            "qualified complex mask/depth source groups are below "
            f"{profile.minimum_complex_mask_depth_source_groups}"
        ),
        "mask_truth_present": "no qualified human-reviewed mask truth is present",
        "depth_truth_present": "no qualified human-reviewed depth truth is present",
        "camera_diversity": (
            "qualified camera diversity is below "
            f"{profile.minimum_unique_cameras}"
        ),
        "required_content_coverage": (
            "qualified items do not cover required tags: "
            + ", ".join(missing_tags)
        ),
        "all_splits_present": (
            "qualified real/human items must cover train, calibration and test"
        ),
    }
    issues = [
        issue_messages[name]
        for name, passed in quota_results.items()
        if not passed
    ]
    return GoldSetAuditReport(
        manifest_id=manifest.id,
        manifest_version=manifest.version,
        profile=profile,
        total_items=len(manifest.items),
        task_counts=task_counts,
        qualified_task_counts=qualified_task_counts,
        split_counts=split_counts,
        media_origin_counts=media_origin_counts,
        unique_qualified_cameras=cameras,
        complex_mask_depth_source_groups=len(complex_groups),
        covered_tags=covered_tags,
        missing_tags=missing_tags,
        quota_results=quota_results,
        issues=issues,
        passed=all(quota_results.values()),
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_gold_set_manifest(path: str | Path) -> GoldSetManifest:
    manifest_path = Path(path).resolve()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    return GoldSetManifest.model_validate(payload)


def validate_gold_set_files(
    manifest: GoldSetManifest,
    root: str | Path,
) -> None:
    dataset_root = Path(root).resolve()
    if manifest.annotation_guideline_path is not None:
        guideline = (
            dataset_root / manifest.annotation_guideline_path
        ).resolve()
        if not guideline.is_relative_to(dataset_root) or not guideline.is_file():
            raise FileNotFoundError(
                "annotation guideline is missing or outside the dataset: "
                f"{guideline}"
            )
        actual_guideline_sha256 = _sha256(guideline)
        if actual_guideline_sha256 != manifest.annotation_guideline_sha256:
            raise ValueError(
                "annotation guideline checksum mismatch: "
                f"expected {manifest.annotation_guideline_sha256}, "
                f"got {actual_guideline_sha256}"
            )
    for license_record in manifest.licenses:
        evidence = (dataset_root / license_record.evidence_path).resolve()
        if not evidence.is_relative_to(dataset_root) or not evidence.is_file():
            raise FileNotFoundError(
                f"license evidence is missing or outside the dataset: {evidence}"
            )
    for item in manifest.items:
        for relative_path, expected_sha256, label in (
            (item.media_path, item.media_sha256, "media"),
            (item.annotation_path, item.annotation_sha256, "annotation"),
        ):
            path = (dataset_root / relative_path).resolve()
            if not path.is_relative_to(dataset_root) or not path.is_file():
                raise FileNotFoundError(
                    f"{item.id} {label} is missing or outside the dataset: {path}"
                )
            actual = _sha256(path)
            if actual != expected_sha256:
                raise ValueError(
                    f"{item.id} {label} checksum mismatch: "
                    f"expected {expected_sha256}, got {actual}"
                )
