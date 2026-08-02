from collections import deque

import numpy as np

from .pose import L_ANKLE, R_ANKLE


KP_CONF_THRESHOLD = 0.3


class FencerTracker:
    """Assign detected persons to the two fencers (left / right of the piste)
    and track their piste positions and speeds.

    Bystanders (coaches, other athletes) are filtered out by requiring the
    mapped ground position to be on or near the piste strip, and by preferring
    candidates closest to the previously tracked positions.
    """

    def __init__(self, piste_mapper, fps=30.0, history_size=90, detection_writer=None):
        self.mapper = piste_mapper
        self.fps = fps
        self.detection_writer = detection_writer

        self.fencers = {"left": None, "right": None}  # last known piste position
        self.piste_history = {"left": deque(maxlen=history_size), "right": deque(maxlen=history_size)}
        self.speed = {"left": 0.0, "right": 0.0}
        self._speed_alpha = 0.3

        margin_x = 2.0
        self.x_range = (-margin_x, self.mapper.piste_length + margin_x)
        # Generous across-piste range: foot projection can land outside the
        # 1.5 m strip when the fencer leans or the annotation is rough.
        self.y_range = (-1.5, self.mapper.piste_width + 2.0)

    def _foot_point(self, keypoints, scores, box):
        """Ground contact point in image coordinates: ankle midpoint when
        available, else bottom-center of the bounding box."""
        ankles = []
        for idx in (L_ANKLE, R_ANKLE):
            kp = keypoints[idx]
            score = scores[idx] if scores is not None else 1.0
            if score >= KP_CONF_THRESHOLD and (kp[0] > 0 or kp[1] > 0):
                ankles.append(kp)
        if ankles:
            return np.mean(ankles, axis=0)
        if box is not None:
            return np.array([(box[0] + box[2]) / 2.0, box[3]])
        return None

    def _candidates(self, keypoints_list, scores_list, boxes):
        candidates = []
        n = len(keypoints_list)
        for i in range(n):
            scores = scores_list[i] if scores_list is not None else None
            box = boxes[i] if boxes is not None else None
            foot = self._foot_point(keypoints_list[i], scores, box)
            if foot is None:
                continue
            piste = self.mapper.image_to_piste(foot)
            if not (self.x_range[0] <= piste[0] <= self.x_range[1]):
                continue
            if not (self.y_range[0] <= piste[1] <= self.y_range[1]):
                continue
            area = 0.0
            if box is not None:
                area = float((box[2] - box[0]) * (box[3] - box[1]))
            candidates.append({
                "keypoints": keypoints_list[i],
                "kp_scores": scores,
                "box": box,
                "foot_image": foot,
                "piste": piste,
                "area": area,
            })
        return candidates

    def _assign(self, candidates):
        """Pick at most one candidate per side.

        Fencers cannot pass each other on the piste, so among the two chosen
        persons the leftmost is always "left" — a hard ordering rule. This is
        far more robust than nearest-neighbour continuity, which could let one
        identity capture the opponent's track after a detection gap (leaving
        the other fencer unassigned). Continuity and size are only used to
        decide WHICH two candidates are the fencers when extras (referee,
        coaches) stand on the piste.
        """
        assignment = {"left": None, "right": None}
        if not candidates:
            return assignment

        picked = candidates
        if len(candidates) > 2:
            def score(cand):
                s = cand["area"]
                for prev in (self.fencers["left"], self.fencers["right"]):
                    if prev is not None and abs(cand["piste"][0] - float(prev[0])) < 1.5:
                        s *= 2.0
                return s
            picked = sorted(candidates, key=score, reverse=True)[:2]

        if len(picked) == 1:
            cand = picked[0]
            side = "left" if cand["piste"][0] < self.mapper.piste_length / 2 else "right"
            assignment[side] = cand
        else:
            left_c, right_c = sorted(picked, key=lambda c: c["piste"][0])
            assignment["left"], assignment["right"] = left_c, right_c
        return assignment

    def update(self, frame_index, keypoints_list, scores_list, boxes):
        """Update tracks from this frame's pose detections. Returns
        (per-side record dict, distance_m). Does not write to disk — call
        write_record() after blade detection has run for this frame."""
        record = {"left": None, "right": None}

        if keypoints_list is not None and len(keypoints_list) > 0:
            candidates = self._candidates(keypoints_list, scores_list, boxes)
            assignment = self._assign(candidates)

            for side in ("left", "right"):
                cand = assignment[side]
                if cand is None:
                    continue
                piste = cand["piste"]
                prev = self.fencers[side]
                if prev is not None:
                    step = abs(float(piste[0]) - float(prev[0]))
                    # A re-found track after a gap would otherwise spike here.
                    inst_speed = min(step * self.fps, 12.0)
                    self.speed[side] = (
                        self._speed_alpha * inst_speed + (1 - self._speed_alpha) * self.speed[side]
                    )
                self.fencers[side] = piste
                self.piste_history[side].append(piste)
                record[side] = {
                    "bbox": cand["box"],
                    "keypoints": cand["keypoints"],
                    "kp_scores": cand["kp_scores"],
                    "foot_image": cand["foot_image"],
                    "piste": piste,
                    "speed": round(float(self.speed[side]), 3),
                }

        distance_m = None
        if self.fencers["left"] is not None and self.fencers["right"] is not None:
            distance_m = round(abs(float(self.fencers["right"][0]) - float(self.fencers["left"][0])), 3)

        return record, distance_m

    def reset_tracks(self):
        """Forget positions/speeds after the camera left the bout view, so the
        next bout frame starts a fresh assignment instead of a phantom jump."""
        self.fencers = {"left": None, "right": None}
        self.speed = {"left": 0.0, "right": 0.0}
        for side in ("left", "right"):
            self.piste_history[side].clear()

    def write_record(self, frame_index, record, blade_records=None, distance_m=None,
                     bout_view=True):
        if self.detection_writer is None:
            return
        payload = {
            "schema_version": "1.0",
            "frame": int(frame_index),
            "time_sec": round(frame_index / self.fps, 6) if self.fps else None,
            "fencers": record,
            "blade": blade_records or {"left": None, "right": None},
            "distance_m": distance_m,
        }
        if not bout_view:
            payload["bout_view"] = False
        self.detection_writer.write(payload)
