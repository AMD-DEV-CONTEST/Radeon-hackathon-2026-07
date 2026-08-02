import os
import time

import cv2

from .config import load_config
from .data.writer import SCHEMA_VERSION, JsonlDetectionWriter, write_json
from .detection.blade import BladeTracker
from .detection.fencer_tracker import FencerTracker
from .detection.pose import YOLOPoseProcessor
from .detection.scene_gate import SceneGate
from .media import video_audio as vap
from .piste.mapper import PisteMapper, compute_expanded_roi, load_piste_annotation, save_piste_annotation
from .visualization.overlay import OverlayRenderer


class FencingAnalysisSystem:
    """Perception pass: pose + blade tip + piste mapping over every frame.

    Produces detections.jsonl, metadata.json and an annotated H.264 video in
    the output directory. Offline analysis passes (footwork, actions,
    reaction time, agents) consume these files afterwards.
    """

    def __init__(self, video_path, corners=None, output_dir=None, config=None,
                 config_path=None, show_display=False, keep_audio=True):
        self.video_path = video_path
        self.config = config or load_config(config_path)
        self.show_display = show_display
        self.keep_audio = keep_audio

        if not os.path.exists(self.video_path):
            raise FileNotFoundError(f"Input video not found: {self.video_path}")

        self.video_name = os.path.splitext(os.path.basename(video_path))[0]
        self.save_dir = output_dir or os.path.join("outputs", self.video_name)
        os.makedirs(self.save_dir, exist_ok=True)

        self.metadata_path = os.path.join(self.save_dir, "metadata.json")
        self.detections_path = os.path.join(self.save_dir, "detections.jsonl")
        self.annotation_path = os.path.join(self.save_dir, "piste_annotations.json")
        self.output_video_path = os.path.join(self.save_dir, f"annotated_{self.video_name}.mp4")
        self.first_frame_path = os.path.join(self.save_dir, "first_frame.png")

        self.corners = self._resolve_corners(corners)

        pose_cfg = self.config["pose"]
        self.pose_processor = YOLOPoseProcessor(
            model_path=pose_cfg["model"], device=pose_cfg["device"], conf=pose_cfg["conf"]
        )

    def _resolve_corners(self, corners):
        if corners is not None:
            return [tuple(pt) for pt in corners]
        if os.path.exists(self.annotation_path):
            saved, length, width = load_piste_annotation(self.annotation_path)
            self.config["piste"]["length"] = length
            self.config["piste"]["width"] = width
            print(f"Loaded piste annotation from {self.annotation_path}")
            return saved
        self.export_first_frame()
        raise RuntimeError(
            "No piste corners provided.\n"
            f"A reference frame was saved to {self.first_frame_path} — mark the 4 piste "
            "corners on it (far-left, far-right, near-right, near-left) and rerun with\n"
            '  --corners "x1,y1 x2,y2 x3,y3 x4,y4"\n'
            "or use the WebUI to click them interactively."
        )

    def export_first_frame(self):
        cap = cv2.VideoCapture(self.video_path)
        ret, frame = cap.read()
        cap.release()
        if ret:
            cv2.imwrite(self.first_frame_path, frame)

    def process_video(self, progress_callback=None):
        start_time = time.time()

        cap = cv2.VideoCapture(self.video_path)
        if not cap.isOpened():
            raise RuntimeError(f"Unable to open video: {self.video_path}")

        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        video_duration = total_frames / fps if fps else 0.0
        self.fps = fps

        piste_cfg = self.config["piste"]
        mapper = PisteMapper(self.corners, piste_length=piste_cfg["length"], piste_width=piste_cfg["width"])
        roi_corners = compute_expanded_roi(self.corners, (frame_height, frame_width))
        save_piste_annotation(self.annotation_path, self.corners, piste_cfg["length"], piste_cfg["width"])

        detection_writer = JsonlDetectionWriter(self.detections_path)
        tracker = FencerTracker(mapper, fps=fps, detection_writer=detection_writer)

        blade_tracker, blade_wants_bgr = None, False
        blade_cfg = self.config["blade"]
        if blade_cfg["enabled"]:
            detector = blade_cfg.get("detector", "cv")
            filter_kind = blade_cfg.get("filter", "kalman")
            ema_alpha = blade_cfg.get("ema_alpha", 0.45)
            model_path = blade_cfg.get("model_path")
            # `model_path` is intentionally optional in the conservative CV
            # default configuration.  When YOLO is explicitly requested from
            # the CLI, use the bundled fine-tuned weights instead of silently
            # falling back to CV.  A configured custom path still takes
            # precedence.
            if detector == "yolo" and not model_path:
                bundled_model = os.path.join("weights", "blade_best.pt")
                if os.path.exists(bundled_model):
                    model_path = bundled_model
                    # Preserve the effective model in run metadata as well.
                    blade_cfg["model_path"] = model_path
            if detector == "yolo" and model_path and os.path.exists(model_path):
                from .detection.blade_yolo import YoloBladeDetector
                blade_tracker = YoloBladeDetector(
                    model_path,
                    conf=blade_cfg.get("conf", 0.25),
                    imgsz=blade_cfg.get("imgsz", 1280),
                    smoother=filter_kind, ema_alpha=ema_alpha)
                blade_wants_bgr = True
            elif detector == "pose" and model_path and os.path.exists(model_path):
                from .detection.blade_pose import PoseBladeDetector
                blade_tracker = PoseBladeDetector(
                    model_path,
                    conf=blade_cfg.get("conf", 0.15),
                    imgsz=blade_cfg.get("imgsz", 1280),
                    smoother=filter_kind, ema_alpha=ema_alpha)
                blade_wants_bgr = True
            else:
                if detector in ("yolo", "pose"):
                    print(f"Blade model not found ({model_path}); using CV blade tracker.")
                blade_tracker = BladeTracker(smoother=filter_kind, ema_alpha=ema_alpha)
            effective_detector = detector if blade_wants_bgr else "cv"
            print(f"Blade: detector={effective_detector} filter={filter_kind}")
        renderer = OverlayRenderer(mapper, fps=fps)
        scene_gate = SceneGate(self.corners) if self.config["scene_gate"]["enabled"] else None
        # Write metadata after resolving the effective blade detector/model.
        self._write_metadata(fps, total_frames, video_duration, frame_width, frame_height, roi_corners)

        temp_video_path = os.path.join(self.save_dir, f"temp_{self.video_name}.mp4")
        writer = vap.setup_video_writer(frame_width, frame_height, fps, temp_video_path)

        (rx1, ry1), (rx2, ry2) = roi_corners
        frame_index = 0
        non_bout_frames = 0
        gap_frames = 0
        gap_reset = int(fps * 1.0)  # reset tracks after 1s away from the bout view
        log_interval = max(1, int(fps * 10))

        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                frame_index += 1

                # Broadcast footage: skip cutaways / replays / crowd shots.
                if scene_gate is not None and scene_gate.reference is not None \
                        and not scene_gate.is_bout_view(frame):
                    non_bout_frames += 1
                    gap_frames += 1
                    if gap_frames == gap_reset:
                        tracker.reset_tracks()
                        if blade_tracker is not None:
                            blade_tracker.reset()
                        renderer.reset_trails()
                    tracker.write_record(frame_index, {"left": None, "right": None},
                                         None, None, bout_view=False)
                    writer.write(frame)
                    if progress_callback is not None:
                        progress_callback(frame_index, total_frames)
                    continue
                gap_frames = 0

                roi = frame[ry1:ry2, rx1:rx2]
                keypoints, scores, boxes = self.pose_processor.process_frame(roi)
                if keypoints is not None:
                    keypoints = keypoints.copy()
                    keypoints[:, :, 0] += rx1
                    keypoints[:, :, 1] += ry1
                    if boxes is not None:
                        boxes = boxes.copy()
                        boxes[:, [0, 2]] += rx1
                        boxes[:, [1, 3]] += ry1

                fencer_records, distance_m = tracker.update(frame_index, keypoints, scores, boxes)

                # Lock the scene-gate reference the first time both fencers
                # stand on the piste — that frame is certainly the bout view.
                if scene_gate is not None and scene_gate.reference is None \
                        and fencer_records["left"] is not None and fencer_records["right"] is not None:
                    scene_gate.lock_reference(frame)

                blade_records = None
                if blade_tracker is not None:
                    blade_input = frame if blade_wants_bgr else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    blade_records = blade_tracker.update(blade_input, fencer_records)

                tracker.write_record(frame_index, fencer_records, blade_records, distance_m)

                frame = renderer.draw(frame, frame_index, fencer_records, blade_records, distance_m)

                if self.show_display:
                    cv2.imshow("SparkFencer", frame)
                    cv2.waitKey(1)
                writer.write(frame)

                if progress_callback is not None:
                    progress_callback(frame_index, total_frames)
                if frame_index % log_interval == 0:
                    elapsed = time.time() - start_time
                    rate = frame_index / elapsed if elapsed > 0 else 0
                    print(f"  frame {frame_index}/{total_frames} ({rate:.1f} fps)")
        finally:
            detection_writer.close()
            writer.release()
            cap.release()
            if self.show_display:
                cv2.destroyAllWindows()

        elapsed = time.time() - start_time
        print(f"\nPerception pass done: {frame_index} frames in {elapsed:.1f}s "
              f"({frame_index / elapsed if elapsed else 0:.1f} fps, video {video_duration:.1f}s)")
        if non_bout_frames:
            print(f"  scene gate: {non_bout_frames} non-bout frames skipped "
                  f"({non_bout_frames / frame_index * 100:.0f}%)")

        if self.keep_audio:
            video_exported = vap.process_video_with_audio(
                self.video_path, temp_video_path, self.output_video_path, self.save_dir)
        else:
            video_exported = vap.process_video_without_audio(temp_video_path, self.output_video_path)
        if not video_exported or not os.path.isfile(self.output_video_path):
            raise RuntimeError(
                "Analysis replay export failed. Install FFmpeg with libx264 support "
                "to produce a browser-compatible H.264 MP4.")

        return {
            "detections": self.detections_path,
            "metadata": self.metadata_path,
            "video": self.output_video_path,
        }

    def _write_metadata(self, fps, total_frames, video_duration, frame_width, frame_height, roi_corners):
        piste_cfg = self.config["piste"]
        metadata = {
            "schema_version": SCHEMA_VERSION,
            "video": {
                "path": os.path.abspath(self.video_path),
                "name": self.video_name,
                "fps": float(fps),
                "total_frames": int(total_frames),
                "duration_sec": float(video_duration),
                "width": int(frame_width),
                "height": int(frame_height),
            },
            "models": {
                "pose": self.config["pose"]["model"],
                "blade": self.config["blade"].get("model_path") or "cv-line-detector",
            },
            "piste": {
                "corners": self.corners,
                "roi_corners": roi_corners,
                "length_m": piste_cfg["length"],
                "width_m": piste_cfg["width"],
            },
            "weapon": self.config["weapon"],
            "outputs": {
                "video": self.output_video_path,
                "detections": self.detections_path,
            },
        }
        write_json(self.metadata_path, metadata)
