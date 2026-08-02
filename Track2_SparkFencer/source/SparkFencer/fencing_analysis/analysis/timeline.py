"""Load detections.jsonl into aligned numpy time series for offline analysis.

All arrays are indexed by frame (row i = frame i+1) with NaN for missing
values. Sign convention used downstream: "forward" velocity is toward the
opponent, so it is +dx/dt for the left fencer and -dx/dt for the right one.
"""

import json

import numpy as np

from ..detection.pose import (
    L_ANKLE, L_ELBOW, L_SHOULDER, L_WRIST,
    R_ANKLE, R_ELBOW, R_SHOULDER, R_WRIST,
)
from ..piste.mapper import PisteMapper

SIDES = ("left", "right")
KP_CONF_THRESHOLD = 0.3
# Blade detector requires score >= 0.62 (MIN_CV_SCORE) to report a fresh tip;
# only smoother-held/interpolated frames fall below this, tagged ~0.1. Gating
# on 0.5 keeps genuine CV/pose detections while dropping held-over guesses.
TIP_CONF_THRESHOLD = 0.5


def moving_average(values, window):
    """NaN-tolerant centered moving average."""
    if window <= 1:
        return values.copy()
    result = np.full_like(values, np.nan, dtype=float)
    n = len(values)
    half = window // 2
    for i in range(n):
        lo, hi = max(0, i - half), min(n, i + half + 1)
        chunk = values[lo:hi]
        valid = chunk[~np.isnan(chunk)]
        if len(valid):
            result[i] = valid.mean()
    return result


def nan_gradient(values, dt):
    """Gradient that ignores NaN gaps shorter than a few frames."""
    filled = values.copy()
    # Forward/backward fill short gaps so the gradient stays defined.
    isnan = np.isnan(filled)
    if isnan.all():
        return np.full_like(values, np.nan)
    idx = np.where(~isnan)[0]
    filled = np.interp(np.arange(len(values)), idx, filled[idx])
    grad = np.gradient(filled, dt)
    grad[isnan] = np.nan
    return grad


def _angle_deg(a, b, c):
    """Angle ABC in degrees (at vertex b)."""
    v1, v2 = a - b, c - b
    n1, n2 = np.linalg.norm(v1), np.linalg.norm(v2)
    if n1 < 1e-3 or n2 < 1e-3:
        return np.nan
    cosang = np.clip(np.dot(v1, v2) / (n1 * n2), -1.0, 1.0)
    return float(np.degrees(np.arccos(cosang)))


class Timeline:
    def __init__(self, detections_path, metadata):
        self.metadata = metadata
        self.fps = metadata["video"]["fps"]
        self.dt = 1.0 / self.fps
        corners = metadata["piste"]["corners"]
        self.mapper = PisteMapper(
            corners,
            piste_length=metadata["piste"]["length_m"],
            piste_width=metadata["piste"]["width_m"],
        )
        self.piste_length = metadata["piste"]["length_m"]

        records = []
        with open(detections_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        n = max((r["frame"] for r in records), default=0)
        self.n_frames = n
        self.t = (np.arange(n) + 1) * self.dt

        shape = (n,)
        self.x = {s: np.full(shape, np.nan) for s in SIDES}            # piste x of foot center
        self.ankle_spread = {s: np.full(shape, np.nan) for s in SIDES}  # |ankle dx| on piste (m)
        self.elbow_angle = {s: np.full(shape, np.nan) for s in SIDES}   # leading-arm elbow angle (deg)
        self.wrist_x = {s: np.full(shape, np.nan) for s in SIDES}       # leading wrist piste x
        self.wrist_img = {s: np.full((n, 2), np.nan) for s in SIDES}    # leading wrist image xy
        self.tip_img = {s: np.full((n, 2), np.nan) for s in SIDES}
        self.tip_conf = {s: np.zeros(shape) for s in SIDES}
        self.distance = np.full(shape, np.nan)

        for rec in records:
            i = rec["frame"] - 1
            if i < 0 or i >= n:
                continue
            if rec.get("distance_m") is not None:
                self.distance[i] = rec["distance_m"]
            for side in SIDES:
                fencer = (rec.get("fencers") or {}).get(side)
                if fencer:
                    self._fill_fencer(i, side, fencer)
                blade = (rec.get("blade") or {}).get(side)
                if blade and blade.get("tip_image") is not None:
                    self.tip_img[side][i] = blade["tip_image"]
                    self.tip_conf[side][i] = blade.get("confidence", 0.0)

        self._compute_derived()

    def _fill_fencer(self, i, side, fencer):
        piste = fencer.get("piste")
        if piste:
            self.x[side][i] = piste[0]

        kp = np.asarray(fencer["keypoints"], dtype=float)
        sc = fencer.get("kp_scores")
        sc = np.asarray(sc, dtype=float) if sc is not None else np.ones(len(kp))

        def ok(idx):
            return sc[idx] >= KP_CONF_THRESHOLD and not np.allclose(kp[idx], 0)

        # Ankle spread along the piste.
        if ok(L_ANKLE) and ok(R_ANKLE):
            a1 = self.mapper.image_to_piste(kp[L_ANKLE])
            a2 = self.mapper.image_to_piste(kp[R_ANKLE])
            self.ankle_spread[side][i] = abs(float(a1[0]) - float(a2[0]))

        # Leading arm: wrist most advanced toward the opponent.
        arms = []
        for w, e, s_ in ((L_WRIST, L_ELBOW, L_SHOULDER), (R_WRIST, R_ELBOW, R_SHOULDER)):
            if ok(w) and ok(e) and ok(s_):
                arms.append((kp[w], kp[e], kp[s_]))
        if arms:
            if len(arms) == 2:
                arms.sort(key=lambda a: a[0][0], reverse=(side == "left"))
            wrist, elbow, shoulder = arms[0]
            self.wrist_img[side][i] = wrist
            self.elbow_angle[side][i] = _angle_deg(shoulder, elbow, wrist)
            wrist_piste = self.mapper.image_to_piste(wrist)
            self.wrist_x[side][i] = float(wrist_piste[0])

    def _compute_derived(self):
        win = max(3, int(round(self.fps * 0.25)) | 1)
        self.x_smooth = {}
        self.v = {}
        self.forward_v = {}
        self.wrist_speed_img = {}
        max_speed = 9.0  # m/s — anything above this is a tracking glitch
        for side in SIDES:
            self.x_smooth[side] = moving_average(self.x[side], win)
            v = nan_gradient(self.x_smooth[side], self.dt)
            v[np.abs(v) > max_speed] = np.nan
            self.v[side] = v
            sign = 1.0 if side == "left" else -1.0
            self.forward_v[side] = sign * self.v[side]

            wrist = self.wrist_img[side]
            speed = np.full(self.n_frames, np.nan)
            diffs = np.linalg.norm(np.diff(wrist, axis=0), axis=1) / self.dt
            speed[1:] = diffs
            self.wrist_speed_img[side] = moving_average(speed, max(3, win // 2))

        self.distance_smooth = moving_average(self.distance, win)
        self.closing_speed = -nan_gradient(self.distance_smooth, self.dt)

        # Blade-tip-derived signals, gated to confident (non held-over) frames.
        # These measure the weapon itself rather than a body-pose proxy, so
        # they corroborate/refine the elbow-angle and wrist-speed heuristics
        # used for attack/parry/counter classification.
        self.tip_reach_img = {}   # tip-to-wrist distance (px) — direct blade extension
        self.tip_forward_v = {}   # signed piste-forward tip speed (m/s)
        self.tip_lateral_speed = {}  # unsigned piste-lateral tip speed (m/s) — deflection cue
        tip_win = max(3, win // 2)
        for side in SIDES:
            confident = self.tip_conf[side] >= TIP_CONF_THRESHOLD
            tip = np.where(confident[:, None], self.tip_img[side], np.nan)

            reach = np.linalg.norm(tip - self.wrist_img[side], axis=1)
            self.tip_reach_img[side] = moving_average(reach, tip_win)

            piste_xy = np.full((self.n_frames, 2), np.nan)
            valid = confident & ~np.isnan(tip).any(axis=1)
            for i in np.nonzero(valid)[0]:
                piste_xy[i] = self.mapper.image_to_piste(tip[i])

            sign = 1.0 if side == "left" else -1.0
            fwd = nan_gradient(moving_average(piste_xy[:, 0], tip_win), self.dt)
            fwd[np.abs(fwd) > max_speed * 3.0] = np.nan  # tip moves faster than the body
            self.tip_forward_v[side] = sign * fwd

            lat = nan_gradient(moving_average(piste_xy[:, 1], tip_win), self.dt)
            lat[np.abs(lat) > max_speed * 3.0] = np.nan
            self.tip_lateral_speed[side] = np.abs(lat)

    def coverage(self, side):
        return float(np.mean(~np.isnan(self.x[side])))
