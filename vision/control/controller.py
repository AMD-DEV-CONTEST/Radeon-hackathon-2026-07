# -*- coding: utf-8 -*-
"""Lateral control law for the ground roll, driven purely by DeviationNet output.

Pure functions / small state — no simulator or I/O dependencies, so the same
code runs against any source of (cross_track, heading_err): the vision model,
telemetry, or the MuJoCo cockpit robot pipeline.

Sign conventions (must match the model):
    cross_track  meters, positive = aircraft right of centerline
    heading_err  degrees, positive = nose pointing right of runway heading
    rudder       positive = yaw right
"""
import math


class PID:
    def __init__(self, kp, ki, kd, out_limit):
        self.kp, self.ki, self.kd = kp, ki, kd
        self.out_limit = out_limit
        self.i = 0.0
        self.prev_e = None
        self.prev_t = None

    def step(self, e, t):
        d = 0.0
        if self.prev_t is not None:
            dt = max(t - self.prev_t, 1e-3)
            self.i += e * dt
            lim = self.out_limit / max(self.ki, 1e-9)
            self.i = max(min(self.i, lim), -lim) if self.ki > 0 else 0.0
            d = (e - self.prev_e) / dt
        self.prev_e, self.prev_t = e, t
        u = self.kp * e + self.ki * self.i + self.kd * d
        return max(min(u, self.out_limit), -self.out_limit)


class VisionFilter:
    """Robustness layer between raw per-frame model output and the controller:
    sanity gate, per-update step clamp, and EMA smoothing."""

    def __init__(self, ema_alpha=0.4, max_step_m=1.0, sane_m=12.0,
                 stale_sec=0.5):
        self.a = ema_alpha
        self.max_step = max_step_m
        self.sane_m = sane_m
        self.stale_sec = stale_sec
        self.cross = None
        self.herr = None
        self.ts = 0.0

    def update(self, cross_m, herr_deg, now):
        if abs(cross_m) > self.sane_m:        # reject implausible output
            return
        if self.cross is None:
            self.cross, self.herr = cross_m, herr_deg
        else:
            step = max(min(cross_m - self.cross, self.max_step), -self.max_step)
            self.cross += self.a * step
            self.herr = (1 - self.a) * self.herr + self.a * herr_deg
        self.ts = now

    def fresh(self, now):
        return self.cross is not None and now - self.ts <= self.stale_sec


# outer loop: 0.5 deg of heading correction per meter of cross-track error,
# capped at 4 deg — deliberately conservative, recovery is gradual by design
K_CT = math.radians(0.5)
MAX_CORR = math.radians(4.0)
MAX_RUDDER = 0.5

rudder_pid = PID(kp=1.2, ki=0.05, kd=0.35, out_limit=MAX_RUDDER)


def lateral_error(cross_m, herr_deg, target_offset_m=0.0):
    """Two-loop error collapsed to one term, both inputs from the model:
    outer loop turns cross-track into a desired heading correction, inner
    loop is the heading error itself:  e = corr - herr."""
    corr = max(min(K_CT * (target_offset_m - cross_m), MAX_CORR), -MAX_CORR)
    return corr - math.radians(herr_deg)


def rudder_command(cross_m, herr_deg, t, target_offset_m=0.0):
    """One control tick: model estimate in, rudder deflection [-0.5, 0.5] out."""
    return rudder_pid.step(lateral_error(cross_m, herr_deg, target_offset_m), t)
