# coding: utf-8
"""RL Chase Agent for Booster Studio multi-robot SoccerSim.

Uses a trained ONNX policy (chase_v6_2048_policy.onnx) to output velocity commands
(vx, vy, vyaw) for the chaser role. Other roles use rule-based fallback.

The ONNX model takes 19-dim observation (ball position, velocity, goal direction
in body frame) and outputs 3-dim action (vx, vy, wz) clipped to [-0.8, 0.8]/[-1.0, 1.0]
(matching training config hl_clip_lin=0.8, hl_clip_ang=1.0).
"""
from __future__ import annotations

import math
import os
import threading
from pathlib import Path

import numpy as np

try:
    import onnxruntime as ort
except ImportError:
    ort = None

from booster_agent_framework import AgentBase, AgentFeatures

from .runtime import SoccerTeamRuntime
from .soccer_framework import SoccerConfig
from .soccer_framework.telemetry import SoccerLogger, create_soccer_logger


class RLChaseAgent(AgentBase):
    """Agent that uses ONNX RL policy for chasing + rule-based for other roles."""

    def __init__(self):
        super().__init__(AgentFeatures())
        self.config = SoccerConfig.from_env()
        self.soccer_logger = create_soccer_logger(
            self.logger,
            source=f"rl_chase.team{self.config.team_id}",
        )
        self._closing = False
        self._runtime_start_thread = None

        # Load ONNX policy
        onnx_path = self._find_onnx_model()
        self.onnx_session = None
        if onnx_path and ort:
            self.onnx_session = ort.InferenceSession(onnx_path)
            self.soccer_logger.info(f"ONNX policy loaded: {onnx_path}")
        else:
            self.soccer_logger.info("ONNX policy not found, using rule-based fallback")

        self._last_action = np.zeros(3, dtype=np.float32)
        self._prev_ball_pos = None
        self._prev_time = None

        self.runtime = SoccerTeamRuntime(
            logger=self.soccer_logger,
            config=self.config,
            onnx_session=self.onnx_session,
        )

    def _find_onnx_model(self) -> str | None:
        """Find the trained ONNX policy (chase_v6_2048) in agent dir or models/."""
        candidates = [
            "models/chase_v6_2048_policy.onnx",
            "models/chase_v6_policy.onnx",
            "/workspace/amd-physical-ai-soccer/models/chase_v6_2048_policy.onnx",
            os.path.join(os.path.dirname(__file__), "..", "models", "chase_v6_2048_policy.onnx"),
            # legacy fallback (stub — do not use)
            "models/chase_v3_policy.onnx",
        ]
        for path in candidates:
            if os.path.exists(path):
                return path
        return None

    def on_agent_activated(self):
        self.soccer_logger.info("RLChaseAgent activated")
        self._closing = False
        self._start_runtime_async()

    def on_agent_close(self):
        self.soccer_logger.info("RLChaseAgent closing")
        self._closing = True
        try:
            if self._runtime_start_thread and self._runtime_start_thread.is_alive():
                self._runtime_start_thread.join(timeout=5.0)
            self.runtime.stop()
        finally:
            self.soccer_logger.info("RLChaseAgent closed")

    def _start_runtime_async(self):
        if self._runtime_start_thread and self._runtime_start_thread.is_alive():
            return
        self._runtime_start_thread = threading.Thread(
            target=self._start_runtime,
            name="rl_chase_runtime",
            daemon=True,
        )
        self._runtime_start_thread.start()

    def _start_runtime(self):
        try:
            self.runtime.start()
        except Exception as exc:
            self._error(f"Runtime start failed: {exc}")
            self.runtime.stop()
