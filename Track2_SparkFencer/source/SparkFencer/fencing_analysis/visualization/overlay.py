from collections import deque

import cv2
import numpy as np

from ..detection.pose import SKELETON_EDGES

SIDE_COLORS = {
    "left": (60, 60, 230),   # red-ish (BGR)
    "right": (230, 140, 40),  # blue-ish
}
# Blade tips get their own per-side colors (distinct from the skeletons and
# from each other): left = orange, right = cyan.
TIP_COLORS = {
    "left": (0, 165, 255),
    "right": (255, 255, 0),
}
KP_CONF_THRESHOLD = 0.3


class OverlayRenderer:
    """Draws skeletons, piste lines, blade tip trails and a HUD on frames."""

    def __init__(self, piste_mapper, fps=30.0, show_skeletons=True, show_blade=True,
                 show_piste=True, show_hud=True, trail_length=25):
        self.mapper = piste_mapper
        self.fps = fps
        self.show_skeletons = show_skeletons
        self.show_blade = show_blade
        self.show_piste = show_piste
        self.show_hud = show_hud
        self.tip_trails = {"left": deque(maxlen=trail_length), "right": deque(maxlen=trail_length)}

    def reset_trails(self):
        for trail in self.tip_trails.values():
            trail.clear()

    def _draw_skeleton(self, frame, keypoints, scores, color):
        kp = np.asarray(keypoints)
        sc = np.asarray(scores) if scores is not None else np.ones(len(kp))
        for i, j in SKELETON_EDGES:
            if sc[i] < KP_CONF_THRESHOLD or sc[j] < KP_CONF_THRESHOLD:
                continue
            p1, p2 = kp[i], kp[j]
            if np.allclose(p1, 0) or np.allclose(p2, 0):
                continue
            cv2.line(frame, tuple(p1.astype(int)), tuple(p2.astype(int)), color, 2)
        for i in range(len(kp)):
            if sc[i] >= KP_CONF_THRESHOLD and not np.allclose(kp[i], 0):
                cv2.circle(frame, tuple(kp[i].astype(int)), 3, color, -1)

    def draw(self, frame, frame_index, fencer_records, blade_records=None, distance_m=None):
        if self.show_piste:
            self.mapper.draw_piste_overlay(frame)

        for side, record in fencer_records.items():
            if record is None:
                continue
            color = SIDE_COLORS[side]
            if self.show_skeletons:
                self._draw_skeleton(frame, record["keypoints"], record.get("kp_scores"), color)

            foot = np.asarray(record["foot_image"]).astype(int)
            cv2.circle(frame, tuple(foot), 5, color, -1)
            piste = record["piste"]
            label = f"{'L' if side == 'left' else 'R'} x={float(piste[0]):.2f}m v={record['speed']:.1f}m/s"
            cv2.putText(frame, label, (foot[0] - 60, foot[1] + 24),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2, cv2.LINE_AA)

        if self.show_blade and blade_records:
            for side, blade in blade_records.items():
                if blade is None:
                    continue
                tip_color = TIP_COLORS[side]
                tip = blade.get("tip_image")
                conf = blade.get("confidence", 0)
                # A predicted/coasting position is useful to the analysis
                # pipeline, but is not an observed sword tip.  Rendering it
                # as one makes a stale Kalman state look like a point on the
                # blade.  Draw only current, high-confidence observations.
                raw_tip = blade.get("tip_raw_image") or tip
                observed = raw_tip is not None and conf >= 0.25
                if observed:
                    # The current marker is the unfiltered observation, while
                    # the history uses the Kalman/EMA output.  This keeps the
                    # trail visually smooth without making the live marker
                    # trail behind a fast sword tip.
                    pt = tuple(np.int32(tip if tip is not None else raw_tip))
                    trail_prev = self.tip_trails[side]
                    # Re-locks must not create a diagonal trail across a
                    # fencer or the opponent's sword.
                    if trail_prev and np.hypot(pt[0] - trail_prev[-1][0][0],
                                               pt[1] - trail_prev[-1][0][1]) > frame.shape[1] * 0.12:
                        trail_prev.clear()
                    trail_prev.append((pt, conf))
                elif self.tip_trails[side]:
                    self.tip_trails[side].popleft()
                trail = list(self.tip_trails[side])
                for k in range(1, len(trail)):
                    fade = k / len(trail)
                    color = tuple(int(c * (0.35 + 0.65 * fade)) for c in tip_color)
                    cv2.line(frame, trail[k - 1][0], trail[k][0], color, 2, cv2.LINE_AA)
                if observed:
                    tip_pt = tuple(np.int32(raw_tip))
                    # White halo + colored dot so the tip reads on any background.
                    cv2.circle(frame, tip_pt, 7, (255, 255, 255), 2)
                    cv2.circle(frame, tip_pt, 5, tip_color, -1 if conf > 0.3 else 1)
                    cv2.putText(frame, "L" if side == "left" else "R",
                                (tip_pt[0] + 9, tip_pt[1] - 9),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, tip_color, 2, cv2.LINE_AA)

        if self.show_hud:
            time_sec = frame_index / self.fps if self.fps else 0
            lines = [f"t={time_sec:7.2f}s  frame {frame_index}"]
            if distance_m is not None:
                lines.append(f"distance: {distance_m:.2f} m")
            y = 30
            for text in lines:
                cv2.putText(frame, text, (16, y), cv2.FONT_HERSHEY_SIMPLEX,
                            0.7, (0, 0, 0), 4, cv2.LINE_AA)
                cv2.putText(frame, text, (16, y), cv2.FONT_HERSHEY_SIMPLEX,
                            0.7, (255, 255, 255), 2, cv2.LINE_AA)
                y += 30
        return frame
