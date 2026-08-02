import json
import os

import cv2
import numpy as np

from .reference import PISTE_LENGTH, PISTE_WIDTH, piste_marks


class PisteMapper:
    """Homography between image coordinates and piste (ground) coordinates.

    Corners must be given in image coordinates in this order:
      1. far-left end of the strip (image top-left)
      2. far-right end (image top-right)
      3. near-right end (image bottom-right)
      4. near-left end (image bottom-left)
    They map to piste coordinates (0,0), (L,0), (L,W), (0,W).
    """

    def __init__(self, image_corners, piste_length=PISTE_LENGTH, piste_width=PISTE_WIDTH):
        self.image_corners = np.array(image_corners, dtype=np.float32)
        self.piste_length = float(piste_length)
        self.piste_width = float(piste_width)
        piste_points = np.array([
            [0, 0],
            [self.piste_length, 0],
            [self.piste_length, self.piste_width],
            [0, self.piste_width],
        ], dtype=np.float32)
        self.matrix = cv2.getPerspectiveTransform(self.image_corners, piste_points)
        self.inv_matrix = cv2.getPerspectiveTransform(piste_points, self.image_corners)

    def image_to_piste(self, point):
        if point is None:
            return None
        point = np.array(point, dtype=np.float32).reshape(-1, 1, 2)
        transformed = cv2.perspectiveTransform(point, self.matrix)
        return np.round(transformed[0][0], 3)

    def piste_to_image(self, point):
        if point is None:
            return None
        point = np.array(point, dtype=np.float32).reshape(-1, 1, 2)
        transformed = cv2.perspectiveTransform(point, self.inv_matrix)
        return np.round(transformed[0][0], 1)

    def draw_piste_overlay(self, image, color=(80, 200, 80)):
        overlay = image
        cv2.polylines(overlay, [self.image_corners.astype(int)], True, color, 2)
        marks = piste_marks(self.piste_length)
        styles = {
            "center": (color, 2),
            "en_garde_left": ((80, 160, 230), 1),
            "en_garde_right": ((80, 160, 230), 1),
            "warning_left": ((60, 60, 220), 1),
            "warning_right": ((60, 60, 220), 1),
        }
        for name, x in marks.items():
            if x < 0 or x > self.piste_length:
                continue
            p1 = self.piste_to_image([x, 0])
            p2 = self.piste_to_image([x, self.piste_width])
            line_color, thickness = styles[name]
            cv2.line(overlay, tuple(p1.astype(int)), tuple(p2.astype(int)), line_color, thickness)
        return overlay


def compute_expanded_roi(piste_corners, image_shape):
    """Pose-detection ROI from the piste corners: pad horizontally, keep the
    full image height (fencers' bodies extend far above the ground strip)."""
    height, width = image_shape[:2]
    points = np.array(piste_corners, dtype=np.int32)
    min_x = int(np.min(points[:, 0]))
    max_x = int(np.max(points[:, 0]))

    strip_width = max_x - min_x
    pad_x = max(12, int(strip_width * 0.05))

    x1 = max(0, min_x - pad_x)
    y1 = 0
    x2 = min(width - 1, max_x + pad_x)
    y2 = height - 1
    return [(x1, y1), (x2, y2)]


def save_piste_annotation(path, corners, piste_length, piste_width=PISTE_WIDTH):
    payload = {
        "corners": [[int(x), int(y)] for x, y in corners],
        "piste_length": float(piste_length),
        "piste_width": float(piste_width),
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def load_piste_annotation(path):
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    corners = [tuple(pt) for pt in payload["corners"]]
    return corners, payload.get("piste_length", PISTE_LENGTH), payload.get("piste_width", PISTE_WIDTH)


def parse_corners_arg(text):
    """Parse corners passed on the CLI as "x1,y1 x2,y2 x3,y3 x4,y4"."""
    parts = text.replace(";", " ").split()
    if len(parts) != 4:
        raise ValueError(f"Expected 4 corner points, got {len(parts)}: {text!r}")
    corners = []
    for part in parts:
        x, y = part.split(",")
        corners.append((int(float(x)), int(float(y))))
    return corners
