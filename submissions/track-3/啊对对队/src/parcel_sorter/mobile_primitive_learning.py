"""Event-based primitive segmentation for the mobile parcel demonstrations."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any, Iterable, Sequence

from .mobile_dataset import MOBILE_ACTION_NAMES, MOBILE_STAGE_NAMES


PROGRESS_ACTION_NAME = "primitive_progress"
MOBILE_PRIMITIVE_ACTION_NAMES = (*MOBILE_ACTION_NAMES, PROGRESS_ACTION_NAME)


@dataclass(frozen=True)
class PrimitiveSegment:
    primitive: str
    start_offset: int
    end_offset: int
    start_frame: int
    end_frame: int
    boundary_signal: str

    @property
    def length(self) -> int:
        return self.end_offset - self.start_offset + 1

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "length": self.length}


def segment_mobile_actions(
    actions: Sequence[Sequence[float]],
    *,
    frame_indices: Sequence[int] | None = None,
    base_motion_threshold: float = 0.005,
    min_motion_frames: int = 5,
) -> tuple[PrimitiveSegment, ...]:
    """Recover six parcel primitives without reading controller stage labels.

    The mobile expert has two observable base-motion intervals: parcel approach
    before suction attachment and payload transport after lift. Left tool-command
    sign changes mark physical attachment and release. These four events determine
    all six segments while leaving ``observation.stage_id`` available only for an
    independent agreement audit.
    """

    if len(actions) < 6:
        raise ValueError("primitive segmentation requires at least six frames")
    if not math.isfinite(base_motion_threshold) or base_motion_threshold <= 0.0:
        raise ValueError("base_motion_threshold must be finite and positive")
    if min_motion_frames < 1:
        raise ValueError("min_motion_frames must be positive")
    for offset, action in enumerate(actions):
        if len(action) != len(MOBILE_ACTION_NAMES):
            raise ValueError(
                f"frame {offset} action must have {len(MOBILE_ACTION_NAMES)} values"
            )
        if not all(math.isfinite(float(value)) for value in action):
            raise ValueError(f"frame {offset} action contains a non-finite value")

    frames = tuple(range(len(actions))) if frame_indices is None else tuple(frame_indices)
    if len(frames) != len(actions):
        raise ValueError("frame_indices length must equal action count")
    if any(right <= left for left, right in zip(frames, frames[1:])):
        raise ValueError("frame_indices must be strictly increasing")

    close_offset = _first_tool_transition(actions, start=1, attached=True)
    release_offset = _first_tool_transition(
        actions, start=close_offset + 1, attached=False
    )
    motion_mask = [
        math.sqrt(sum(float(value) ** 2 for value in action[:3]))
        >= base_motion_threshold
        for action in actions
    ]
    motion_runs = _true_runs(motion_mask, min_length=min_motion_frames)
    approach_runs = [run for run in motion_runs if run[0] < close_offset]
    transport_runs = [run for run in motion_runs if run[0] > close_offset]
    if not approach_runs:
        raise ValueError("no sustained base approach found before suction attachment")
    if not transport_runs:
        raise ValueError("no sustained payload transport found after suction attachment")
    approach_start, approach_end = approach_runs[-1]
    transport_start, transport_end = transport_runs[0]
    if approach_end >= close_offset:
        raise ValueError("base approach overlaps suction attachment")
    if not close_offset < transport_start <= transport_end < release_offset:
        raise ValueError("transport must occur after attachment and before release")

    boundaries = (
        ("pregrasp", 0, approach_start - 1, "first_sustained_base_motion"),
        (
            "grasp_approach",
            approach_start,
            close_offset - 1,
            "left_tri_suction_attach",
        ),
        ("lift", close_offset, transport_start - 1, "second_sustained_base_motion"),
        ("transport", transport_start, transport_end, "base_transport_stops"),
        ("place", transport_end + 1, release_offset - 1, "left_tri_suction_release"),
        ("release", release_offset, len(actions) - 1, "episode_end"),
    )
    segments = tuple(
        PrimitiveSegment(
            primitive=primitive,
            start_offset=start,
            end_offset=end,
            start_frame=int(frames[start]),
            end_frame=int(frames[end]),
            boundary_signal=signal,
        )
        for primitive, start, end, signal in boundaries
    )
    validate_segment_coverage(segments, frame_count=len(actions))
    return segments


def primitive_progress(
    segments: Sequence[PrimitiveSegment], *, frame_count: int
) -> tuple[float, ...]:
    validate_segment_coverage(segments, frame_count=frame_count)
    values = [math.nan] * frame_count
    for segment in segments:
        denominator = max(1, segment.length - 1)
        for local_offset, frame_offset in enumerate(
            range(segment.start_offset, segment.end_offset + 1)
        ):
            values[frame_offset] = local_offset / denominator
    if not all(math.isfinite(value) and 0.0 <= value <= 1.0 for value in values):
        raise RuntimeError("primitive progress generation left an invalid frame")
    return tuple(values)


def primitive_labels(
    segments: Sequence[PrimitiveSegment], *, frame_count: int
) -> tuple[str, ...]:
    validate_segment_coverage(segments, frame_count=frame_count)
    labels = [""] * frame_count
    for segment in segments:
        labels[segment.start_offset : segment.end_offset + 1] = [
            segment.primitive
        ] * segment.length
    return tuple(labels)


def primitive_task_text(task: str, primitive: str) -> str:
    if not task.strip():
        raise ValueError("base task text must be non-empty")
    descriptions = {
        "pregrasp": "Move to a safe pregrasp pose and align both arms",
        "grasp_approach": "Approach the parcel and attach the left tri-suction tool",
        "lift": "Lift the attached parcel while the right V-cradle supports it",
        "transport": "Transport the parcel with the mobile base and coordinated dual arms",
        "place": "Lower and place the parcel at the requested sorting station",
        "release": "Release suction and retreat without disturbing the placed parcel",
    }
    try:
        instruction = descriptions[primitive]
    except KeyError as exc:
        raise ValueError(f"unknown mobile primitive: {primitive!r}") from exc
    prefix = f"{instruction}. Parent task:"
    if task.strip().startswith(prefix):
        return task.strip()
    return f"{prefix} {task.strip()}"


def stage_agreement(
    predicted_labels: Sequence[str], observed_stage_ids: Iterable[int]
) -> dict[str, Any]:
    observed = tuple(int(value) for value in observed_stage_ids)
    if len(predicted_labels) != len(observed) or not observed:
        raise ValueError("stage agreement requires non-empty equally sized inputs")
    expected = tuple(MOBILE_STAGE_NAMES[index] for index in observed)
    matches = sum(left == right for left, right in zip(predicted_labels, expected))
    return {
        "frames": len(observed),
        "matches": matches,
        "accuracy": matches / len(observed),
        "observed_stage_used_for_segmentation": False,
    }


def validate_segment_coverage(
    segments: Sequence[PrimitiveSegment], *, frame_count: int
) -> None:
    if frame_count < 1 or len(segments) != len(MOBILE_STAGE_NAMES):
        raise ValueError("segments must cover one episode with all six primitives")
    cursor = 0
    for expected_name, segment in zip(MOBILE_STAGE_NAMES, segments):
        if segment.primitive != expected_name:
            raise ValueError("primitive order does not match the mobile task contract")
        if segment.start_offset != cursor or segment.end_offset < segment.start_offset:
            raise ValueError("primitive segments must be contiguous and non-empty")
        cursor = segment.end_offset + 1
    if cursor != frame_count:
        raise ValueError("primitive segments do not cover every frame exactly once")


def _first_tool_transition(
    actions: Sequence[Sequence[float]], *, start: int, attached: bool
) -> int:
    tool_index = MOBILE_ACTION_NAMES.index("left_gripper")
    for index in range(max(1, start), len(actions)):
        previous = float(actions[index - 1][tool_index])
        current = float(actions[index][tool_index])
        if attached and previous <= 0.0 < current:
            return index
        if not attached and previous > 0.0 >= current:
            return index
    event = "attachment" if attached else "release"
    raise ValueError(f"left tri-suction {event} transition was not observed")


def _true_runs(mask: Sequence[bool], *, min_length: int) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index, active in enumerate((*mask, False)):
        if active and start is None:
            start = index
        elif not active and start is not None:
            if index - start >= min_length:
                runs.append((start, index - 1))
            start = None
    return runs
