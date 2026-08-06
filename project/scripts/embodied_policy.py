# project/scripts/embodied_policy.py
"""
R.A.G.E. Phase 5 - Module 2: The Embodied Policy (LeRobot / OpenVLA)

Purpose
-------
Final stage of the pipeline. Takes the live Genesis camera frame plus the
natural-language directive produced by cognitive_manager.py's
CognitiveManager.reason() (e.g. "Workspace clear: Execute CDS sequence:
Yellow, Red, Blue.") and outputs a single continuous 7-DOF DELTA action:

    [dx, dy, dz, droll, dpitch, dyaw, grasp_state]

    dx, dy, dz             - end-effector position delta, meters, world frame
    droll, dpitch, dyaw    - end-effector orientation delta, radians
    grasp_state            - continuous gripper command in [-1, 1]:
                                  -1.0 = fully open
                                  +1.0 = fully closed
                              (matches the convention most VLA checkpoints,
                              including OpenVLA, are trained to output)

This action vector is the natural next input to
project/envs/server_assembly.py's `ArmIKController` for Robot B - e.g.
`robot_b.move_to(scene, current_pos + action[:3], delta_quat(action[3:6]),
...)` plus `set_gripper_force()` gated on `action[6]`. This module does
NOT talk to Genesis directly; it only produces the numeric contract Phase
4's run_pipeline.py will hand to the arm controller.

VRAM reality check (why mock_predict_action exists)
-----------------------------------------------------
Same constraint as cognitive_manager.py: Genesis + YOLOv8 (and possibly
Qwen-VL) are already resident on this hackathon rig's single AMD GPU. A
real OpenVLA/LeRobot checkpoint is another multi-GB model. `use_mock=True`
is therefore the default here too - `mock_predict_action()` returns a
deterministic, rule-derived 7-DOF NumPy array parsed straight from the
text command, so the full data-flow (camera -> vision -> RAG -> schedule
-> cognition -> action -> arm controller) can be built and demoed without
ever instantiating the real VLA weights.
"""

from __future__ import annotations

import re
from typing import Optional

import numpy as np

# --------------------------------------------------------------------------- #
# Optional heavy deps - imported defensively, same pattern as the other
# Phase 3/4 modules.
# --------------------------------------------------------------------------- #
try:
    import torch
    _TORCH_AVAILABLE = True
except ImportError:
    _TORCH_AVAILABLE = False

try:
    from transformers import AutoModelForVision2Seq, AutoProcessor
    _TRANSFORMERS_AVAILABLE = True
except ImportError:
    _TRANSFORMERS_AVAILABLE = False


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #

# Placeholder checkpoint id - swap for the actual OpenVLA / LeRobot policy
# id once one is fine-tuned/selected for this cell.
DEFAULT_MODEL_NAME = "openvla/openvla-7b"

ACTION_DIM = 7
GRASP_OPEN = -1.0
GRASP_CLOSED = 1.0

# Per-axis clip bounds for a single control-step delta action. Keeps a
# hallucinated / mock action from ever commanding an unsafe jump, and
# documents the expected magnitude range for whoever wires this into
# ArmIKController.move_to() next.
ACTION_LOW = np.array([-0.05, -0.05, -0.05, -0.20, -0.20, -0.20, -1.0], dtype=np.float32)
ACTION_HIGH = np.array([0.05, 0.05, 0.05, 0.20, 0.20, 0.20, 1.0], dtype=np.float32)


def clip_action(action: np.ndarray) -> np.ndarray:
    """Clamp a raw action vector into the cell's safe per-step delta
    bounds. Applied at the end of BOTH the real and mock prediction paths
    so callers always get a bounded action regardless of source."""
    return np.clip(action, ACTION_LOW, ACTION_HIGH).astype(np.float32)


# --------------------------------------------------------------------------- #
# Mock-path command parsing
# --------------------------------------------------------------------------- #

# Small per-color lateral nudge (meters) approximating "move toward that
# cable/port's known slot" - mirrors CABLE_SPACING_Y's slot layout in
# server_assembly.py (red = slot -1, blue = slot 0, yellow = slot +1),
# scaled down to a single control-step-sized delta rather than the full
# physical offset.
_COLOR_LATERAL_HINT = {
    "red": -0.03,
    "blue": 0.0,
    "yellow": 0.03,
}

_COLOR_PATTERN = re.compile(r"\b(red|blue|yellow)\b", re.IGNORECASE)


def _first_color_in(text: str) -> Optional[str]:
    match = _COLOR_PATTERN.search(text)
    return match.group(1).lower() if match else None


# --------------------------------------------------------------------------- #
# EmbodiedPolicy
# --------------------------------------------------------------------------- #

class EmbodiedPolicy:
    """Wraps a Vision-Language-Action model and exposes a single
    `predict_action()` entry point that always returns a bounded,
    fixed-shape 7-DOF NumPy action, whether backed by real weights or the
    mock rule-based path.

    Tensor/data flow
    -----------------
        image (np.ndarray, HWC uint8) + text_command (str)
              |
              v  [real path: AutoProcessor -> {pixel_values, input_ids} on 'cuda']
        VLA model forward pass -> raw action logits/tokens
              |
              v  [de-tokenize / de-normalize per checkpoint's action stats]
        action: np.ndarray, shape (7,), dtype float32
              |
              v  [clip_action() -> safe per-step bounds]
        [dx, dy, dz, droll, dpitch, dyaw, grasp_state]

    The mock path skips straight from `text_command` to a rule-derived
    action array, then goes through the same clip_action() bound-check.
    """

    def __init__(self, model_name: str = DEFAULT_MODEL_NAME,
                 device: str = "cuda", use_mock: bool = True):
        """
        model_name : HF checkpoint id for the VLA (real path only).
        device     : torch device string. 'cuda' is correct for BOTH
                     NVIDIA CUDA and ROCm-built PyTorch - ROCm exposes AMD
                     GPUs under the same 'cuda' namespace.
        use_mock   : default True, for the same VRAM-budget reasons as
                     CognitiveManager. Flip to False only with confirmed
                     headroom for the real checkpoint.
        """
        self.model_name = model_name
        self.device = device
        self.use_mock = use_mock

        self._model = None
        self._processor = None
        self._model_loaded = False

        if not self.use_mock:
            self._try_load_model()

    # -- model loading (real path) ------------------------------------------ #

    def _try_load_model(self):
        """Attempt to load the real VLA model + processor. Any failure
        (missing deps, missing weights, OOM) is caught and logged;
        self.use_mock is flipped back to True so predict_action() degrades
        gracefully instead of crashing the control loop."""
        if not (_TORCH_AVAILABLE and _TRANSFORMERS_AVAILABLE):
            print("[embodied_policy] WARNING: torch/transformers not "
                  "installed. Install with `pip install torch transformers "
                  "--break-system-packages` to use the real VLA path. "
                  "Staying in mock mode.")
            self.use_mock = True
            return

        try:
            print(f"[embodied_policy] Attempting to load '{self.model_name}' "
                  f"onto device '{self.device}'...")
            self._processor = AutoProcessor.from_pretrained(
                self.model_name, trust_remote_code=True,
            )
            self._model = AutoModelForVision2Seq.from_pretrained(
                self.model_name,
                trust_remote_code=True,
                torch_dtype=torch.bfloat16,  # OpenVLA's reference dtype; halves VRAM vs fp32
            ).to(self.device)
            self._model.eval()
            self._model_loaded = True
            print(f"[embodied_policy] Loaded '{self.model_name}' successfully.")
        except Exception as exc:  # noqa: BLE001 - any failure degrades to mock, on purpose
            print(f"[embodied_policy] WARNING: could not load "
                  f"'{self.model_name}' ({exc!r}). Falling back to "
                  f"mock_predict_action() for the rest of this session.")
            self._model = None
            self._processor = None
            self._model_loaded = False
            self.use_mock = True

    # -- real inference ------------------------------------------------------ #

    def _run_real_inference(self, image: np.ndarray, text_command: str) -> np.ndarray:
        """Forward pass through the loaded VLA. Only ever called when
        self._model_loaded is True.

        OpenVLA-style checkpoints expose a `predict_action(**inputs,
        unnorm_key=..., do_sample=False)` convenience method on the model
        itself (via trust_remote_code) that handles action de-tokenization
        / de-normalization internally, which is what we call here rather
        than hand-rolling logit decoding.
        """
        prompt = f"In: What action should the robot take to {text_command}\nOut:"
        inputs = self._processor(prompt, image, return_tensors="pt").to(
            self.device, dtype=torch.bfloat16,
        )

        with torch.no_grad():
            raw_action = self._model.predict_action(
                **inputs, unnorm_key="bridge_orig", do_sample=False,
            )

        action = np.asarray(raw_action, dtype=np.float32).reshape(ACTION_DIM)
        return action

    # -- mock inference (the path this pipeline runs on today) -------------- #

    def mock_predict_action(self, text_command: str) -> np.ndarray:
        """Deterministic, rule-based stand-in for the VLA's output.
        Parses `text_command` (as produced by CognitiveManager.reason())
        for the two directive families it currently emits:

            "Reset workspace..."                 -> retreat + open gripper
            "...Execute CDS sequence: <colors>."  -> nudge toward the first
                                                      color's slot, gripper
                                                      open (pre-grasp
                                                      approach)

        Anything else falls through to a zero-motion "hold position"
        action, which is the safe default for an un-recognized directive.
        """
        command_lower = text_command.lower()

        if "reset" in command_lower:
            # Retreat straight up 5cm, no rotation change, gripper open -
            # a generic, safe disengage motion while a recovery plan is
            # formed upstream.
            action = np.array([0.0, 0.0, 0.05, 0.0, 0.0, 0.0, GRASP_OPEN], dtype=np.float32)
            return clip_action(action)

        if "execute" in command_lower:
            color = _first_color_in(text_command)
            lateral = _COLOR_LATERAL_HINT.get(color, 0.0) if color else 0.0
            # Small lateral nudge toward the next job's slot + a small
            # downward approach delta, gripper still open (this is a
            # pre-grasp approach step, not the grasp itself - grasp force
            # is applied by a later control step once aligned, mirroring
            # ArmIKController.set_gripper_force() in server_assembly.py).
            action = np.array([0.0, lateral, -0.02, 0.0, 0.0, 0.0, GRASP_OPEN], dtype=np.float32)
            return clip_action(action)

        # Unrecognized directive: hold position, leave gripper state
        # unchanged (0.0 is a neutral/no-op signal, not a real "half open"
        # position - downstream code should interpret grasp_state==0.0 as
        # "do not change gripper this step").
        return np.zeros(ACTION_DIM, dtype=np.float32)

    # -- public entry point --------------------------------------------------- #

    def predict_action(self, image: np.ndarray, text_command: str,
                        use_mock: Optional[bool] = None) -> np.ndarray:
        """Single call site downstream code (Phase 4's run_pipeline.py)
        should use. Always returns a shape-(7,) float32 NumPy array,
        already clipped to ACTION_LOW/ACTION_HIGH.

        use_mock: per-call override. None (default) defers to the
        instance's self.use_mock setting (set at construction time).
        """
        route_to_mock = self.use_mock if use_mock is None else use_mock

        if not route_to_mock and self._model_loaded:
            return clip_action(self._run_real_inference(image, text_command))

        return self.mock_predict_action(text_command)


# --------------------------------------------------------------------------- #
# Standalone test block
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    print("=" * 70)
    print("[embodied_policy] Standalone test")
    print("=" * 70)

    # Fake a cam_top-shaped frame without needing Genesis installed.
    fake_image = np.zeros((960, 960, 3), dtype=np.uint8)

    policy = EmbodiedPolicy(use_mock=True)  # forced mock: VRAM-safe by default

    test_commands = [
        "Workspace clear: Execute CDS sequence: Yellow, Red, Blue.",
        "SOP indicates misaligned insertion. Reset workspace.",
        "SOP indicates a dropped cable. Reset workspace and re-localize.",
        "Hold position, no schedule available.",
    ]

    for command in test_commands:
        action = policy.predict_action(fake_image, command)
        print(f"\nCommand : {command!r}")
        print(f"Action  : {np.round(action, 4).tolist()}")

        assert action.shape == (ACTION_DIM,), f"Expected shape ({ACTION_DIM},), got {action.shape}"
        assert action.dtype == np.float32
        assert np.all(action >= ACTION_LOW) and np.all(action <= ACTION_HIGH), \
            "Action exceeded configured safety bounds"

    # Spot-check the two documented directive families behave distinctly.
    reset_action = policy.predict_action(fake_image, "SOP indicates fault. Reset workspace.")
    execute_action = policy.predict_action(fake_image, "Execute CDS sequence: Red, Blue, Yellow.")
    assert reset_action[2] > 0, "Reset should command an upward (retreat) dz"
    assert execute_action[2] < 0, "Execute should command a downward (approach) dz"
    assert reset_action[6] == GRASP_OPEN and execute_action[6] == GRASP_OPEN

    print("\n[embodied_policy] OK: all mock action predictions well-formed "
          "and within safety bounds.")