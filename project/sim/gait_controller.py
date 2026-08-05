"""
Central Pattern Generator (CPG) trot-gait controller for a quadruped robot.

Why a CPG instead of a trained RL policy?
- Guaranteed to work out of the box (no training time / convergence risk).
- Biologically inspired: real quadrupeds use spinal CPGs to generate rhythmic
  locomotion patterns, which cortical/RL-style control then modulates.
- Leaves room to layer perception / terrain-adaptation on top (see
  perception/terrain_classifier.py) which is where the "innovation" and
  Radeon GPU usage come in.

Leg order (matches Unitree Go1 actuator order in mujoco_menagerie):
    0: FR (front right)   1: FL (front left)
    2: RR (rear right)    3: RL (rear left)

Trot gait: diagonal leg pairs (FR+RL) and (FL+RR) move together, 180 degrees
out of phase with each other.
"""

import numpy as np


class TrotGaitCPG:
    def __init__(
        self,
        freq_hz: float = 1.5,
        stance_ratio: float = 0.55,
        hip_amplitude: float = 0.0,
        thigh_amplitude: float = 0.35,
        calf_amplitude: float = 0.35,
        base_thigh: float = 0.9,
        base_calf: float = -1.6,
    ):
        self.freq_hz = freq_hz
        self.stance_ratio = stance_ratio
        self.hip_amplitude = hip_amplitude
        self.thigh_amplitude = thigh_amplitude
        self.calf_amplitude = calf_amplitude
        self.base_thigh = base_thigh
        self.base_calf = base_calf

        # Phase offsets per leg for a trot gait (FR, FL, RR, RL)
        self.phase_offset = np.array([0.0, np.pi, np.pi, 0.0])

    def leg_targets(self, t: float, speed_scale: float = 1.0):
        """Return target (hip, thigh, calf) angles for all 4 legs at time t."""
        phase = 2 * np.pi * self.freq_hz * speed_scale * t
        targets = np.zeros((4, 3))
        for leg in range(4):
            th = phase + self.phase_offset[leg]
            swing = np.sin(th)
            # Simple swing/stance shaping: faster lift during swing phase
            targets[leg, 0] = self.hip_amplitude * np.sin(th * 0.5)
            targets[leg, 1] = self.base_thigh + self.thigh_amplitude * swing
            targets[leg, 2] = self.base_calf - self.calf_amplitude * max(swing, 0)
        return targets  # shape (4, 3): [hip, thigh, calf] per leg

    def action(self, t: float, speed_scale: float = 1.0):
        """Flatten to the 12-dim actuator order used by the Go1 model:
        FR_hip, FR_thigh, FR_calf, FL_hip, FL_thigh, FL_calf,
        RR_hip, RR_thigh, RR_calf, RL_hip, RL_thigh, RL_calf
        """
        return self.leg_targets(t, speed_scale).flatten()
