from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Mapping, Sequence

from PIL import Image, ImageStat

from .v10_contracts import V10ContractError
from .v10_image_mastering import PixelBox
from .v10_supply_chain import stable_sha256


UHD_LANDSCAPE = (3840, 2160)
UHD_PORTRAIT = (2160, 3840)
UHD_SQUARE = (3840, 3840)
MASTER_DURATION_SECONDS = 8
MASTER_FPS = 24
MASTER_FRAME_COUNT = MASTER_DURATION_SECONDS * MASTER_FPS
_HEX = frozenset("0123456789abcdef")


def _require_sha256(value: str, field_name: str) -> None:
    if len(value) != 64 or any(character not in _HEX for character in value):
        raise V10ContractError(f"{field_name} must be a lowercase SHA-256")


def _require_unit(value: float, field_name: str) -> None:
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise V10ContractError(f"{field_name} must be in the unit interval")


class VideoRole(str, Enum):
    DIRECTOR = "director"
    IDENTITY_GUARDIAN = "identity_guardian"
    AV_QUALITY_EDITOR = "av_quality_editor"


@dataclass(frozen=True)
class KeyframeRef:
    frame_index: int
    image_sha256: str
    purpose: str

    def __post_init__(self) -> None:
        if not 0 <= self.frame_index < MASTER_FRAME_COUNT:
            raise V10ContractError("keyframe is outside the eight-second master")
        _require_sha256(self.image_sha256, "image_sha256")
        if not self.purpose.strip():
            raise V10ContractError("keyframe purpose is required")


@dataclass(frozen=True)
class Shot:
    shot_id: str
    start_frame: int
    end_frame: int
    purpose: str
    first_keyframe: KeyframeRef
    last_keyframe: KeyframeRef

    def __post_init__(self) -> None:
        if not self.shot_id.strip() or not self.purpose.strip():
            raise V10ContractError("shot identity and purpose are required")
        if not 0 <= self.start_frame <= self.end_frame < MASTER_FRAME_COUNT:
            raise V10ContractError("shot frame range is invalid")
        if self.first_keyframe.frame_index != self.start_frame:
            raise V10ContractError("first keyframe must bind the shot start")
        if self.last_keyframe.frame_index != self.end_frame:
            raise V10ContractError("last keyframe must bind the shot end")


@dataclass(frozen=True)
class Storyboard:
    storyboard_id: str
    shots: tuple[Shot, ...]
    roles: tuple[VideoRole, ...]
    fps: int = MASTER_FPS
    duration_seconds: int = MASTER_DURATION_SECONDS

    def __post_init__(self) -> None:
        if not self.storyboard_id.strip() or not self.shots:
            raise V10ContractError("storyboard identity and shots are required")
        if self.roles != tuple(VideoRole):
            raise V10ContractError("the three video roles must be explicit and ordered")
        if self.fps != MASTER_FPS or self.duration_seconds != MASTER_DURATION_SECONDS:
            raise V10ContractError("competition master must be exactly eight seconds at 24 FPS")
        cursor = 0
        identifiers: set[str] = set()
        for shot in self.shots:
            if shot.shot_id in identifiers or shot.start_frame != cursor:
                raise V10ContractError("shots must be unique and cover the timeline without gaps")
            identifiers.add(shot.shot_id)
            cursor = shot.end_frame + 1
        if cursor != MASTER_FRAME_COUNT:
            raise V10ContractError("storyboard must cover all 192 frames")

    @property
    def digest(self) -> str:
        return stable_sha256(asdict(self))


@dataclass(frozen=True)
class ShotGraph:
    nodes: tuple[str, ...]
    edges: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if len(self.nodes) != len(set(self.nodes)) or not self.nodes:
            raise V10ContractError("shot graph nodes must be nonempty and unique")
        node_set = set(self.nodes)
        if any(left not in node_set or right not in node_set or left == right for left, right in self.edges):
            raise V10ContractError("shot graph edge is invalid")
        adjacency = {node: [] for node in self.nodes}
        for left, right in self.edges:
            adjacency[left].append(right)
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node: str) -> None:
            if node in visiting:
                raise V10ContractError("shot graph must be acyclic")
            if node in visited:
                return
            visiting.add(node)
            for child in adjacency[node]:
                visit(child)
            visiting.remove(node)
            visited.add(node)

        for node in self.nodes:
            visit(node)


@dataclass(frozen=True)
class VideoConstraint:
    product_source_sha256: str
    logo_source_sha256: str
    product_boxes: Mapping[int, PixelBox]
    logo_boxes: Mapping[int, PixelBox]
    maximum_center_velocity_px: float
    maximum_center_acceleration_px: float
    allowed_camera_moves: tuple[str, ...]
    forbidden_camera_moves: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_sha256(self.product_source_sha256, "product_source_sha256")
        _require_sha256(self.logo_source_sha256, "logo_source_sha256")
        if not self.product_boxes or set(self.product_boxes) != set(self.logo_boxes):
            raise V10ContractError("product and logo constraints must locate the same observed frames")
        if any(not 0 <= index < MASTER_FRAME_COUNT for index in self.product_boxes):
            raise V10ContractError("constraint frame is outside the master")
        if self.maximum_center_velocity_px <= 0 or self.maximum_center_acceleration_px <= 0:
            raise V10ContractError("motion bounds must be positive")
        if not self.allowed_camera_moves or not self.forbidden_camera_moves:
            raise V10ContractError("camera allow and deny lists are required")
        if set(self.allowed_camera_moves) & set(self.forbidden_camera_moves):
            raise V10ContractError("camera allow and deny lists overlap")


class TemporalRewardDimension(str, Enum):
    REGION = "temporal_region"
    PRODUCT_IDENTITY = "product_identity"
    LOGO_IDENTITY = "logo_identity"
    MOTION = "motion_continuity"
    CAMERA = "camera_continuity"


TEMPORAL_REWARD_FLOORS = {
    TemporalRewardDimension.REGION: 0.98,
    TemporalRewardDimension.PRODUCT_IDENTITY: 1.0,
    TemporalRewardDimension.LOGO_IDENTITY: 1.0,
    TemporalRewardDimension.MOTION: 0.97,
    TemporalRewardDimension.CAMERA: 0.97,
}


@dataclass(frozen=True)
class TemporalReward:
    values: Mapping[TemporalRewardDimension, float]
    locators: Mapping[TemporalRewardDimension, str]

    def __post_init__(self) -> None:
        if set(self.values) != set(TemporalRewardDimension) or set(self.locators) != set(TemporalRewardDimension):
            raise V10ContractError("every temporal reward dimension requires a value and locator")
        for dimension, value in self.values.items():
            _require_unit(value, dimension.value)
            if not self.locators[dimension].strip():
                raise V10ContractError("temporal reward locator cannot be empty")

    @property
    def passed(self) -> bool:
        return all(self.values[item] >= floor for item, floor in TEMPORAL_REWARD_FLOORS.items())


@dataclass(frozen=True)
class VideoComputePolicy:
    gpu_count: int
    teacher_parameter_billions: float
    operation: str
    artifact_revision: str
    artifact_sha256: str
    trainable: bool

    def __post_init__(self) -> None:
        if self.gpu_count < 1 or self.teacher_parameter_billions <= 0:
            raise V10ContractError("compute profile is invalid")
        _require_sha256(self.artifact_sha256, "artifact_sha256")
        if not self.artifact_revision.strip():
            raise V10ContractError("artifact revision must be pinned")

    @property
    def admitted(self) -> bool:
        if self.gpu_count == 1 and self.teacher_parameter_billions >= 10 and self.operation in {"pretrain", "finetune", "distill_teacher"}:
            return False
        if self.operation == "reuse_distilled_checkpoint":
            return not self.trainable
        return True


@dataclass(frozen=True)
class FrameChunkPlan:
    total_frames: int
    chunk_size: int
    overlap: int

    def __post_init__(self) -> None:
        if self.total_frames < 1 or self.chunk_size < 2 or not 1 <= self.overlap < self.chunk_size:
            raise V10ContractError("frame chunk plan is invalid")

    def windows(self) -> tuple[tuple[int, int], ...]:
        windows: list[tuple[int, int]] = []
        start = 0
        while start < self.total_frames:
            end = min(start + self.chunk_size, self.total_frames)
            windows.append((start, end))
            if end == self.total_frames:
                break
            start = end - self.overlap
        return tuple(windows)


@dataclass(frozen=True)
class VAETilePlan:
    canvas_size: tuple[int, int]
    tile_size: int
    overlap: int

    def __post_init__(self) -> None:
        if self.canvas_size not in {UHD_LANDSCAPE, UHD_PORTRAIT, UHD_SQUARE}:
            raise V10ContractError("VAE tile canvas must be an approved 4K master")
        if self.tile_size < 256 or not 32 <= self.overlap < self.tile_size:
            raise V10ContractError("VAE tile and overlap are invalid")

    def tiles(self) -> tuple[PixelBox, ...]:
        width, height = self.canvas_size
        step = self.tile_size - self.overlap
        xs = list(range(0, max(1, width - self.tile_size + 1), step))
        ys = list(range(0, max(1, height - self.tile_size + 1), step))
        if not xs or xs[-1] + self.tile_size < width:
            xs.append(max(0, width - self.tile_size))
        if not ys or ys[-1] + self.tile_size < height:
            ys.append(max(0, height - self.tile_size))
        return tuple(PixelBox(x, y, min(x + self.tile_size, width), min(y + self.tile_size, height)) for y in ys for x in xs)


@dataclass(frozen=True)
class FrameRepairRequest:
    frame_index: int
    repair_box: PixelBox
    observed_failure_box: PixelBox
    protected_boxes: tuple[PixelBox, ...]
    maximum_area_ratio: float = 0.08

    @property
    def admitted(self) -> bool:
        canvas_area = UHD_LANDSCAPE[0] * UHD_LANDSCAPE[1]
        return (
            0 <= self.frame_index < MASTER_FRAME_COUNT
            and self.repair_box.inside(self.observed_failure_box)
            and self.repair_box.area / canvas_area <= self.maximum_area_ratio
            and not any(self.repair_box.overlaps(box) for box in self.protected_boxes)
        )


@dataclass(frozen=True)
class VideoMasterSpec:
    variants: tuple[tuple[int, int], ...] = (UHD_LANDSCAPE, UHD_PORTRAIT, UHD_SQUARE)
    duration_seconds: int = MASTER_DURATION_SECONDS
    fps: int = MASTER_FPS
    audio_integrated_lufs: float = -16.0
    audio_true_peak_dbtp: float = -1.0

    def __post_init__(self) -> None:
        if self.variants != (UHD_LANDSCAPE, UHD_PORTRAIT, UHD_SQUARE):
            raise V10ContractError("the three exact 4K aspect masters are required")
        if self.duration_seconds != MASTER_DURATION_SECONDS or self.fps != MASTER_FPS:
            raise V10ContractError("master timing must be exactly eight seconds at 24 FPS")
        if self.audio_integrated_lufs != -16.0 or self.audio_true_peak_dbtp != -1.0:
            raise V10ContractError("audio master target must be -16 LUFS and -1 dBTP")


@dataclass(frozen=True)
class PronunciationLexicon:
    entries: Mapping[str, str]

    def validate_tokens(self, observed: Mapping[str, str]) -> bool:
        return bool(self.entries) and all(observed.get(token) == phonemes for token, phonemes in self.entries.items())


def exact_product_identity(frame: Image.Image, product: Image.Image, box: PixelBox) -> float:
    expected = product.convert("RGBA")
    if expected.size != (box.width, box.height):
        raise V10ContractError("product must be composited without resizing")
    observed = frame.convert("RGBA").crop((box.left, box.top, box.right, box.bottom))
    mask = expected.getchannel("A")
    expected_pixels = expected.convert("RGB")
    observed_pixels = observed.convert("RGB")
    compared = matched = 0
    expected_data = expected_pixels.get_flattened_data() if hasattr(expected_pixels, "get_flattened_data") else expected_pixels.getdata()
    observed_data = observed_pixels.get_flattened_data() if hasattr(observed_pixels, "get_flattened_data") else observed_pixels.getdata()
    mask_data = mask.get_flattened_data() if hasattr(mask, "get_flattened_data") else mask.getdata()
    for expected_pixel, observed_pixel, alpha in zip(expected_data, observed_data, mask_data):
        if alpha:
            compared += 1
            matched += expected_pixel == observed_pixel
    if not compared:
        raise V10ContractError("product contains no visible pixels")
    return matched / compared


def frame_luminance(image: Image.Image, excluded_box: PixelBox | None = None) -> float:
    luminance = image.convert("L")
    if excluded_box is not None:
        pixels = list(luminance.getdata())
        width, _ = luminance.size
        samples = [value for index, value in enumerate(pixels) if not (excluded_box.left <= index % width < excluded_box.right and excluded_box.top <= index // width < excluded_box.bottom)]
        return sum(samples) / len(samples) / 255.0
    return ImageStat.Stat(luminance).mean[0] / 255.0


def flicker_score(frames: Sequence[Image.Image], excluded_boxes: Sequence[PixelBox]) -> float:
    if len(frames) < 3 or len(frames) != len(excluded_boxes):
        raise V10ContractError("flicker requires at least three located frames")
    values = [frame_luminance(frame, box) for frame, box in zip(frames, excluded_boxes)]
    maximum_delta = max(abs(right - left) for left, right in zip(values, values[1:]))
    return max(0.0, 1.0 - maximum_delta)


def motion_continuity_score(boxes: Sequence[PixelBox], maximum_acceleration_px: float) -> float:
    if len(boxes) < 3 or maximum_acceleration_px <= 0:
        raise V10ContractError("motion continuity requires three boxes and a positive acceleration bound")
    centers = [((box.left + box.right) / 2, (box.top + box.bottom) / 2) for box in boxes]
    velocities = [(right[0] - left[0], right[1] - left[1]) for left, right in zip(centers, centers[1:])]
    accelerations = [math.hypot(right[0] - left[0], right[1] - left[1]) for left, right in zip(velocities, velocities[1:])]
    return max(0.0, 1.0 - max(accelerations) / maximum_acceleration_px)


@dataclass(frozen=True)
class TimedEvent:
    event_id: str
    timestamp_seconds: float

    def __post_init__(self) -> None:
        if not self.event_id.strip() or not 0 <= self.timestamp_seconds <= MASTER_DURATION_SECONDS:
            raise V10ContractError("timed event is invalid")


def av_alignment_score(video_events: Sequence[TimedEvent], audio_events: Sequence[TimedEvent], tolerance_seconds: float = 0.08) -> float:
    video = {item.event_id: item.timestamp_seconds for item in video_events}
    audio = {item.event_id: item.timestamp_seconds for item in audio_events}
    if not video or set(video) != set(audio) or tolerance_seconds <= 0:
        raise V10ContractError("A/V events must be paired by identity")
    return sum(abs(video[key] - audio[key]) <= tolerance_seconds for key in video) / len(video)


def safe_zone_pass(boxes: Sequence[PixelBox], safe_zone: PixelBox) -> bool:
    return bool(boxes) and all(box.inside(safe_zone) for box in boxes)


def cross_media_claim_pass(video_claims: Mapping[str, str], approved_claims: Mapping[str, str]) -> bool:
    return bool(video_claims) and all(identifier in approved_claims and approved_claims[identifier] == evidence for identifier, evidence in video_claims.items())


def frame_sha256(image: Image.Image) -> str:
    return hashlib.sha256(image.convert("RGBA").tobytes()).hexdigest()


def planned_video_pack_card() -> dict[str, object]:
    return {
        "schema": "ProofLaunch4KVideoPackCardV1",
        "status": "planned_not_executed",
        "master_spec_sha256": stable_sha256(asdict(VideoMasterSpec())),
        "model_runs": {
            "wan_2_2_5b": None,
            "wan_i2v": None,
            "ltx_fallback": None,
            "seedvr2": None,
            "rcm": None,
            "causal_forcing": None,
        },
        "outputs": {"landscape_4k": None, "portrait_4k": None, "square_4k": None},
        "audio_metrics": {"integrated_lufs": None, "true_peak_dbtp": None},
        "baselines": {"raw_wan": None, "frame_super_resolution": None, "mature_comfy_workflow": None},
        "frozen": False,
        "truth_boundary": "No generative video, restoration, audio mastering, baseline or frozen pack is claimed.",
    }
