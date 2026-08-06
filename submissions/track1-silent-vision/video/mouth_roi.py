from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from backend.config import Settings
from video.types import MouthFrame
from vision.mouth import crop_mouth


@dataclass(frozen=True)
class MouthRoiClip:
    frames: tuple[MouthFrame, ...]
    mouth_frames: np.ndarray
    aligned_face_frames: np.ndarray
    detected_frames: int
    reused_frames: int


def extract_mouth_roi_clip(
    *,
    frames: Sequence[np.ndarray],
    face_detector: object,
    settings: Settings,
) -> MouthRoiClip:
    mouth_frames: list[MouthFrame] = []
    aligned_face_frames: list[np.ndarray] = []
    last_image: np.ndarray | None = None
    last_aligned_face: np.ndarray | None = None
    detected = 0
    reused = 0
    smoothed_box: dict[str, float] | None = None
    alpha = 0.65
    for index, image in enumerate(frames, start=1):
        detection = face_detector.detect(image)
        if detection.face_detected:
            crop = crop_mouth(image, detection.landmarks, settings.mouth_size)
            box = crop.box.model_dump()
            if smoothed_box is None:
                smoothed_box = box
            else:
                smoothed_box = {
                    key: smoothed_box[key] * alpha + box[key] * (1.0 - alpha)
                    for key in ("x", "y", "width", "height")
                }
            mouth_image = _crop_box(image, smoothed_box, settings.mouth_size)
            aligned_face = _crop_aligned_face(image, smoothed_box)
            last_image = mouth_image.copy()
            last_aligned_face = aligned_face.copy()
            detected += 1
            aligned_face_frames.append(aligned_face)
            mouth_frames.append(
                MouthFrame(
                    sequence=index,
                    received_at_ms=int((index - 1) * 1000 / settings.command_clip_fps),
                    image=mouth_image,
                    debug_image=image.copy(),
                    debug_mouth_box=smoothed_box,
                    debug_landmarks=tuple(detection.landmarks),
                )
            )
        elif last_image is not None:
            reused += 1
            if last_aligned_face is not None:
                aligned_face_frames.append(last_aligned_face.copy())
            mouth_frames.append(
                MouthFrame(
                    sequence=index,
                    received_at_ms=int((index - 1) * 1000 / settings.command_clip_fps),
                    image=last_image.copy(),
                    debug_image=image.copy(),
                    debug_mouth_box=smoothed_box,
                )
            )
    if not mouth_frames:
        raise ValueError("no mouth ROI frames could be extracted from uploaded clip")
    stacked = np.stack([frame.image for frame in mouth_frames]).astype("uint8", copy=False)
    aligned_stacked = np.stack(aligned_face_frames).astype("uint8", copy=False)
    return MouthRoiClip(
        frames=tuple(mouth_frames),
        mouth_frames=stacked,
        aligned_face_frames=aligned_stacked,
        detected_frames=detected,
        reused_frames=reused,
    )


def write_mouth_roi_video(mouth_frames: np.ndarray, path: Path, fps: int) -> Path:
    return _write_rgb_or_gray_video(mouth_frames, path, fps)


def write_aligned_face_video(aligned_face_frames: np.ndarray, path: Path, fps: int) -> Path:
    return _write_rgb_or_gray_video(aligned_face_frames, path, fps)


def _write_rgb_or_gray_video(frames: np.ndarray, path: Path, fps: int) -> Path:
    av = _import_av()
    path.parent.mkdir(parents=True, exist_ok=True)
    with av.open(str(path), "w") as container:
        stream = container.add_stream("libx264", rate=fps)
        stream.width = int(frames.shape[2])
        stream.height = int(frames.shape[1])
        stream.pix_fmt = "yuv420p"
        for frame in frames:
            rgb = np.stack([frame, frame, frame], axis=-1) if frame.ndim == 2 else frame
            video_frame = av.VideoFrame.from_ndarray(rgb, format="rgb24")
            for packet in stream.encode(video_frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    return path


def _crop_box(image_rgb: np.ndarray, box: dict[str, float], mouth_size: int) -> np.ndarray:
    height, width = image_rgb.shape[:2]
    left = round(max(0.0, box["x"]) * width)
    top = round(max(0.0, box["y"]) * height)
    right = round(min(1.0, box["x"] + box["width"]) * width)
    bottom = round(min(1.0, box["y"] + box["height"]) * height)
    if right <= left or bottom <= top:
        raise ValueError("invalid smoothed mouth ROI box")
    crop = image_rgb[top:bottom, left:right]
    if crop.size == 0:
        raise ValueError("empty smoothed mouth ROI crop")
    resized = Image.fromarray(crop).convert("L").resize((mouth_size, mouth_size), Image.Resampling.BOX)
    return np.asarray(resized, dtype=np.uint8)


def _crop_aligned_face(image_rgb: np.ndarray, mouth_box: dict[str, float], output_size: int = 224) -> np.ndarray:
    center_x = mouth_box["x"] + mouth_box["width"] / 2
    center_y = mouth_box["y"] + mouth_box["height"] / 2 - mouth_box["height"] * 1.45
    side = max(mouth_box["width"] * 4.8, mouth_box["height"] * 6.4)
    face_box = {
        "x": max(0.0, center_x - side / 2),
        "y": max(0.0, center_y - side / 2),
        "width": min(1.0, side),
        "height": min(1.0, side),
    }
    height, width = image_rgb.shape[:2]
    left = round(face_box["x"] * width)
    top = round(face_box["y"] * height)
    right = round(min(1.0, face_box["x"] + face_box["width"]) * width)
    bottom = round(min(1.0, face_box["y"] + face_box["height"]) * height)
    crop = image_rgb[top:bottom, left:right]
    if crop.size == 0:
        raise ValueError("empty aligned face crop")
    resized = Image.fromarray(crop).convert("RGB").resize((output_size, output_size), Image.Resampling.BOX)
    return np.asarray(resized, dtype=np.uint8)


def _import_av():
    try:
        import av
    except Exception as exc:
        raise RuntimeError("PyAV is required for mouth ROI debug video export. Install package 'av'.") from exc
    return av
