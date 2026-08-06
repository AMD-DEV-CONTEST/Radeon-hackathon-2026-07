"""SAM2 video mask propagation wrapper (optional dependency).

Everything here is lazy and guarded: callers (tracker.refine_with_sam2) treat
any raised exception as "SAM2 unavailable" and fall back to rectangles.

Strategy:
1. Load a SAM2 video predictor — Hugging Face `from_pretrained` first, then a
   local `build_sam2_video_predictor` checkpoint fallback.
2. init_state on the proxy MP4; if the installed sam2 build cannot decode MP4
   directly, extract frames to a temp JPEG directory and retry.
3. Add a box prompt at each track's first keyframe, propagate_in_video, and
   collect boolean masks per frame within each track's time range.
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

DEFAULT_SAM2_CKPT = "models/sam2.1_hiera_small.pt"
DEFAULT_SAM2_CFG = "configs/sam2.1/sam2.1_hiera_s.yaml"


def _get_device(settings: Any) -> str:
    try:
        from policycut.core.device import get_device
        device = get_device()
    except Exception:
        try:
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            device = "cpu"
    if getattr(settings, "require_rocm", False) and device != "cuda":
        raise RuntimeError(
            "POLICYCUT_REQUIRE_ROCM=1 but no ROCm/CUDA device is available for SAM2"
        )
    return device


def _load_predictor(settings: Any, device: str):
    """Load a SAM2 video predictor; raises on total failure."""
    model_id = getattr(settings, "sam2_model", "facebook/sam2.1-hiera-small")
    errors: list[str] = []

    # Preferred: Hugging Face hub weights.
    try:
        from sam2.sam2_video_predictor import SAM2VideoPredictor  # type: ignore
        # sam2's from_pretrained defaults to device="cuda" internally, which
        # hard-crashes on CPU-only builds; pass the device explicitly (and
        # keep a no-kwarg fallback for older sam2 versions).
        try:
            predictor = SAM2VideoPredictor.from_pretrained(model_id, device=device)
        except TypeError:
            predictor = SAM2VideoPredictor.from_pretrained(model_id)
        try:
            predictor = predictor.to(device)
        except Exception:
            pass
        logger.info("SAM2 predictor %s loaded via from_pretrained on %s", model_id, device)
        return predictor
    except Exception as exc:
        errors.append(f"from_pretrained({model_id}): {exc}")

    # Fallback: local checkpoint + config.
    try:
        from sam2.build_sam import build_sam2_video_predictor  # type: ignore
        ckpt = os.environ.get("POLICYCUT_SAM2_CKPT", DEFAULT_SAM2_CKPT)
        cfg = os.environ.get("POLICYCUT_SAM2_CFG", DEFAULT_SAM2_CFG)
        if not Path(ckpt).is_file():
            raise FileNotFoundError(f"SAM2 checkpoint not found: {ckpt}")
        predictor = build_sam2_video_predictor(cfg, ckpt, device=device)
        logger.info("SAM2 predictor built from local checkpoint %s on %s", ckpt, device)
        return predictor
    except Exception as exc:
        errors.append(f"build_sam2_video_predictor: {exc}")

    raise RuntimeError("SAM2 unavailable: " + " | ".join(errors))


def _video_meta(proxy_path) -> tuple[float, int, int, int]:
    """Return (fps, width, height, frame_count) of the proxy video."""
    import cv2

    capture = cv2.VideoCapture(str(proxy_path))
    if not capture.isOpened():
        raise RuntimeError(f"Cannot open proxy video: {proxy_path}")
    try:
        fps = capture.get(cv2.CAP_PROP_FPS) or 0.0
        if fps <= 0.0 or fps != fps:
            fps = 30.0
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    finally:
        capture.release()
    if width <= 0 or height <= 0:
        raise RuntimeError(f"Invalid proxy video dimensions: {proxy_path}")
    return fps, width, height, frame_count


def _extract_frames(proxy_path, out_dir: Path) -> int:
    """Extract all frames as JPEGs named 00000.jpg... (sam2 frame-dir format)."""
    import cv2

    capture = cv2.VideoCapture(str(proxy_path))
    if not capture.isOpened():
        raise RuntimeError(f"Cannot open proxy video for frame extraction: {proxy_path}")
    count = 0
    try:
        while True:
            ok, frame = capture.read()
            if not ok or frame is None:
                break
            cv2.imwrite(str(out_dir / f"{count:05d}.jpg"), frame,
                        [int(cv2.IMWRITE_JPEG_QUALITY), 90])
            count += 1
    finally:
        capture.release()
    if count == 0:
        raise RuntimeError(f"No frames extracted from {proxy_path}")
    return count


def _report(progress_cb: Optional[Callable], fraction: float, message: str = "") -> None:
    if progress_cb is None:
        return
    fraction = max(0.0, min(1.0, fraction))
    try:
        progress_cb(fraction, message)
    except TypeError:
        try:
            progress_cb(fraction)
        except Exception:
            pass
    except Exception:
        pass


def propagate_tracks(tracks: list, proxy_path, settings: Any,
                     progress_cb: Optional[Callable] = None) -> dict:
    """Propagate a box prompt per track through the video with SAM2.

    Returns {track_id: {frame_idx: numpy bool mask (H, W) at proxy res}}.
    Raises on any failure — the caller downgrades that to rect_fallback.
    """
    import numpy as np
    import torch

    tracks = [t for t in tracks if getattr(t, "keyframes", None)]
    if not tracks:
        return {}

    device = _get_device(settings)
    if device != "cuda" and os.environ.get("POLICYCUT_SAM2_CPU", "0") != "1":
        # CPU propagation must run under bf16 autocast (SAM2 stores memory
        # features in bfloat16) and emulated bf16 matmuls are prohibitively
        # slow (~40s/frame). Opt in with POLICYCUT_SAM2_CPU=1 for testing;
        # the caller downgrades this to the box-interpolation fallback.
        raise RuntimeError(
            "SAM2 propagation skipped on CPU (set POLICYCUT_SAM2_CPU=1 to force); "
            "using box interpolation fallback"
        )
    predictor = _load_predictor(settings, device)
    fps, width, height, frame_count = _video_meta(proxy_path)
    if frame_count <= 0:
        frame_count = int(max(t.keyframes[-1][0] for t in tracks) * fps) + 1

    tmp_dir: Optional[tempfile.TemporaryDirectory] = None
    try:
        try:
            state = predictor.init_state(video_path=str(proxy_path))
        except Exception as exc:
            logger.info("SAM2 could not read MP4 directly (%s); extracting frames", exc)
            tmp_dir = tempfile.TemporaryDirectory(prefix="policycut_sam2_")
            extracted = _extract_frames(proxy_path, Path(tmp_dir.name))
            frame_count = extracted
            state = predictor.init_state(video_path=tmp_dir.name)

        # SAM2 stores its memory features in bfloat16 internally, so all
        # inference (box prompts included) must run under bf16 autocast on
        # CPU as well as GPU; without it memory attention mixes BFloat16 and
        # Float32 and raises "mat1 and mat2 must have the same dtype".
        autocast_ctx = torch.autocast(
            device_type="cuda" if device == "cuda" else "cpu",
            dtype=torch.bfloat16,
        )
        obj_to_track: dict[int, Any] = {}
        frame_ranges: dict[int, tuple[int, int]] = {}
        results: dict[str, dict[int, np.ndarray]] = {t.id: {} for t in tracks}
        with torch.inference_mode(), autocast_ctx:
            for obj_id, track in enumerate(tracks):
                t_first, box = track.keyframes[0]
                t_last = track.keyframes[-1][0]
                start_f = min(max(0, round(t_first * fps)), frame_count - 1)
                end_f = min(max(start_f, round(t_last * fps)), frame_count - 1)
                x, y, w, h = box
                box_abs = np.array(
                    [x * width, y * height, (x + w) * width, (y + h) * height],
                    dtype=np.float32,
                )
                predictor.add_new_points_or_box(
                    inference_state=state,
                    frame_idx=start_f,
                    obj_id=obj_id,
                    box=box_abs,
                )
                obj_to_track[obj_id] = track
                frame_ranges[obj_id] = (start_f, end_f)

            first_prompt_frame = min(r[0] for r in frame_ranges.values())
            for frame_idx, obj_ids, mask_logits in predictor.propagate_in_video(
                state, start_frame_idx=first_prompt_frame
            ):
                for k, obj_id in enumerate(obj_ids):
                    obj_id = int(obj_id)
                    track = obj_to_track.get(obj_id)
                    if track is None:
                        continue
                    start_f, end_f = frame_ranges[obj_id]
                    if frame_idx < start_f or frame_idx > end_f:
                        continue
                    mask = (mask_logits[k] > 0.0).squeeze()
                    mask_np = mask.detach().to("cpu").numpy().astype(bool)
                    if mask_np.ndim != 2 or not mask_np.any():
                        continue
                    results[track.id][int(frame_idx)] = mask_np
                if frame_count > 0:
                    _report(progress_cb, (frame_idx + 1) / frame_count,
                            f"SAM2 propagation frame {frame_idx + 1}/{frame_count}")
    finally:
        if tmp_dir is not None:
            tmp_dir.cleanup()

    non_empty = {tid: masks for tid, masks in results.items() if masks}
    logger.info(
        "SAM2 propagation: %d/%d tracks produced masks (%d frames total)",
        len(non_empty), len(tracks), sum(len(m) for m in non_empty.values()),
    )
    return non_empty


class _NullContext:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False
