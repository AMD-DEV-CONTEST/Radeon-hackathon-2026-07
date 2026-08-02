"""YOLO pose detection with COCO 17 keypoint output.

COCO keypoint indices:
  0 nose, 1 left_eye, 2 right_eye, 3 left_ear, 4 right_ear,
  5 left_shoulder, 6 right_shoulder, 7 left_elbow, 8 right_elbow,
  9 left_wrist, 10 right_wrist, 11 left_hip, 12 right_hip,
  13 left_knee, 14 right_knee, 15 left_ankle, 16 right_ankle
"""

NOSE = 0
L_SHOULDER, R_SHOULDER = 5, 6
L_ELBOW, R_ELBOW = 7, 8
L_WRIST, R_WRIST = 9, 10
L_HIP, R_HIP = 11, 12
L_KNEE, R_KNEE = 13, 14
L_ANKLE, R_ANKLE = 15, 16

SKELETON_EDGES = [
    (5, 7), (7, 9), (6, 8), (8, 10),      # arms
    (5, 6), (5, 11), (6, 12), (11, 12),   # torso
    (11, 13), (13, 15), (12, 14), (14, 16),  # legs
    (0, 5), (0, 6),                        # head to shoulders
]


class YOLOPoseProcessor:
    """Ultralytics YOLO pose processor."""

    def __init__(self, model_path="yolo11n-pose.pt", device="auto", conf=0.25):
        from ultralytics import YOLO

        self.model_path = model_path
        self.conf = conf
        if device in (None, "auto"):
            selected = "cpu"
            try:
                import torch
                if torch.cuda.is_available():
                    selected = 0
            except Exception:
                selected = "cpu"
            self.device = selected
        else:
            self.device = device

        print(f"Initializing YOLO pose model (model: {self.model_path}, device: {self.device})")
        self.model = YOLO(self.model_path)

    def process_frame(self, frame):
        """Return (keypoints, scores, boxes) as numpy arrays, or (None, None, None)."""
        result = self.model(frame, conf=self.conf, device=self.device, verbose=False)[0]
        if result.keypoints is None or result.keypoints.xy is None:
            return None, None, None

        keypoints = result.keypoints.xy
        if keypoints.shape[0] == 0:
            return None, None, None

        scores = result.keypoints.conf
        boxes = result.boxes.xyxy if result.boxes is not None else None

        keypoints = keypoints.detach().cpu().numpy()
        scores = scores.detach().cpu().numpy() if scores is not None else None
        boxes = boxes.detach().cpu().numpy() if boxes is not None else None
        return keypoints, scores, boxes
