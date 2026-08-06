# project/scripts/cognitive_manager.py
"""
R.A.G.E. Phase 4 - Module 1: The Cognitive Brain (Qwen3-VL)

Purpose
-------
This is the fusion point of the whole pipeline. On every decision cycle it
receives four independent streams of context and must collapse them into
ONE natural-language directive that Phase 5's EmbodiedPolicy can act on:

    1. image           - the live cam_top frame (H, W, 3 uint8) from Genesis
    2. yolo_summary     - a text summary of vision_process.py's detections
                           (cable/port colors, shapes, positions, confidence)
    3. sop_text         - the SOP text retrieved by vector_store.py's
                           SOPVectorStore.retrieve_sop() for the current
                           situation
    4. cds_schedule     - the ordered job list produced by
                           cds_heuristic.py's schedule_cable_insertions()
                           (Robot B's optimized cable pick order)

Output is always a short, imperative command string, e.g.:
    "Workspace clear: Execute CDS sequence: Yellow, Red, Blue."
    "SOP indicates misaligned insertion. Reset workspace."

That string is exactly what embodied_policy.py's `predict_action()` takes
as its `text_command` argument - this module never touches robot DOFs or
action vectors, it only reasons in language.

VRAM reality check (why mock_reasoning exists)
------------------------------------------------
Genesis (Vulkan rasterizer + MPM solver) and the YOLOv8 vision pipeline
are already resident on the same AMD GPU this hackathon rig has. A real
Qwen-VL checkpoint (even a "small" one) can easily blow the remaining
VRAM budget and OOM-crash the whole simulation mid-run. `mock_reasoning()`
is therefore the DEFAULT path: a fast, deterministic, rule-based
synthesizer that mimics what the VLM should conclude, so the full
pipeline (vision -> RAG -> schedule -> cognition -> action) can be
developed, tested, and demoed end-to-end without ever touching the real
model weights. The real Qwen-VL path exists and is fully wired, but is
opt-in (`use_mock=False`) for whenever VRAM headroom allows validating it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Sequence, Union

import numpy as np

# --------------------------------------------------------------------------- #
# Optional heavy deps - imported defensively so this module (and its mock
# path) works on a machine without transformers/torch installed at all.
# --------------------------------------------------------------------------- #
try:
    import torch
    _TORCH_AVAILABLE = True
except ImportError:
    _TORCH_AVAILABLE = False

try:
    # Qwen3-VL ships through transformers' generic Vision2Seq / causal-LM
    # loading path with trust_remote_code=True, same as Qwen2-VL before it.
    from transformers import AutoProcessor, AutoModelForVision2Seq
    _TRANSFORMERS_AVAILABLE = True
except ImportError:
    _TRANSFORMERS_AVAILABLE = False


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #

# Placeholder checkpoint name - swap for the actual Qwen3-VL release id
# once it's pinned for this project. Kept as a constructor default (not
# hardcoded deep in load_model) so Phase 4's run_pipeline.py can override
# it per-deployment.
DEFAULT_MODEL_NAME = "Qwen/Qwen2-VL-7B-Instruct"

MAX_NEW_TOKENS = 64  # directives are short imperative sentences, not essays


# --------------------------------------------------------------------------- #
# Data contracts
# --------------------------------------------------------------------------- #

@dataclass
class CognitiveContext:
    """Bundles the 4 input streams for one reasoning call. Optional so
    callers can construct this incrementally (e.g. while some streams are
    still being fetched) - reason() only requires it be complete by call
    time."""
    image: np.ndarray                     # (H, W, 3) uint8, e.g. cam_top.render()
    yolo_summary: str                     # text digest of Detection objects
    sop_text: str                         # retrieved SOPResult.text
    cds_schedule: Sequence[str]           # ordered job_ids, e.g. cds_heuristic's ScheduleResult.sequence


# --------------------------------------------------------------------------- #
# Helpers shared by both the real and mock reasoning paths
# --------------------------------------------------------------------------- #

_COLOR_FROM_JOB_ID = {
    "red": "Red",
    "blue": "Blue",
    "yellow": "Yellow",
}


def _job_id_to_color_label(job_id: str) -> str:
    """'cable_3_yellow' -> 'Yellow'. Falls back to the raw job_id (title
    cased) if no known color token is found, so this never raises on an
    unexpected naming scheme."""
    lowered = job_id.lower()
    for token, label in _COLOR_FROM_JOB_ID.items():
        if token in lowered:
            return label
    return job_id.replace("_", " ").title()


def _schedule_to_color_sequence(cds_schedule: Sequence[str]) -> List[str]:
    return [_job_id_to_color_label(job_id) for job_id in cds_schedule]


_MISALIGNMENT_KEYWORDS = ("misalign", "contact the port wall", "retract")
_DROPPED_KEYWORDS = ("dropped", "lost contact", "lost grip")


def _build_prompt(context: CognitiveContext) -> str:
    """Construct the text portion of the multimodal prompt sent to the
    real Qwen-VL model. Kept as a standalone function (not inlined in
    reason()) so its exact wording can be iterated on / unit tested
    independent of model loading."""
    color_sequence = ", ".join(_schedule_to_color_sequence(context.cds_schedule))
    return (
        "You are the supervisory controller for a bimanual server-assembly "
        "robot cell. Robot A is fixturing a GPU block; Robot B inserts "
        "cables into color/shape-matched ports.\n\n"
        f"Vision detections:\n{context.yolo_summary}\n\n"
        f"Retrieved standard operating procedure:\n{context.sop_text}\n\n"
        f"Planned insertion order (Campbell-Dudek-Smith schedule): {color_sequence}\n\n"
        "Given the camera image and the above context, output ONE short "
        "imperative command for Robot B. If the SOP indicates a fault "
        "condition (misalignment, dropped cable, collision risk), command "
        "a reset/recovery action instead of proceeding with the schedule."
    )


# --------------------------------------------------------------------------- #
# CognitiveManager
# --------------------------------------------------------------------------- #

class CognitiveManager:
    """Fuses vision + RAG + scheduling context into a single natural-
    language directive.

    Tensor/data flow
    -----------------
        image (np.ndarray, HWC uint8)
              |
              v  [real path: AutoProcessor -> pixel_values tensor on 'cuda']
        + yolo_summary / sop_text / cds_schedule (all plain Python)
              |
              v  [_build_prompt() -> single text prompt string]
        Qwen-VL .generate() -> token ids -> decoded string
              |
              v
        command: str   (e.g. "Workspace clear: Execute CDS sequence: Yellow, Red, Blue.")

    The mock path skips the tensor stage entirely and goes straight from
    the 4 raw inputs to a rule-derived command string.
    """

    def __init__(self, model_name: str = DEFAULT_MODEL_NAME,
                 device: str = "cuda", use_mock: bool = True):
        """
        model_name : HF checkpoint id for the VLM (real path only).
        device     : torch device string. 'cuda' is correct for BOTH
                     NVIDIA CUDA and ROCm-built PyTorch - ROCm exposes AMD
                     GPUs under the same 'cuda' namespace, there is no
                     separate 'rocm' device string to pass here.
        use_mock   : default True. This is a deliberate safety default -
                     see module docstring on VRAM budget. Set False only
                     when you've confirmed headroom to load real weights.
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
        """Attempt to load the real Qwen-VL model + processor. Any
        failure (missing deps, missing weights, OOM) is caught and logged;
        self.use_mock is flipped back to True so reason() degrades
        gracefully instead of crashing the pipeline."""
        if not (_TORCH_AVAILABLE and _TRANSFORMERS_AVAILABLE):
            print("[cognitive_manager] WARNING: torch/transformers not "
                  "installed. Install with `pip install torch transformers "
                  "--break-system-packages` to use the real Qwen-VL path. "
                  "Staying in mock mode.")
            self.use_mock = True
            return

        try:
            print(f"[cognitive_manager] Attempting to load '{self.model_name}' "
                  f"onto device '{self.device}'...")
            self._processor = AutoProcessor.from_pretrained(
                self.model_name, trust_remote_code=True,
            )
            self._model = AutoModelForVision2Seq.from_pretrained(
                self.model_name,
                trust_remote_code=True,
                torch_dtype=torch.float16,  # halve VRAM footprint vs fp32
            ).to(self.device)
            self._model.eval()
            self._model_loaded = True
            print(f"[cognitive_manager] Loaded '{self.model_name}' successfully.")
        except Exception as exc:  # noqa: BLE001 - any failure degrades to mock, on purpose
            print(f"[cognitive_manager] WARNING: could not load "
                  f"'{self.model_name}' ({exc!r}). Falling back to "
                  f"mock_reasoning() for the rest of this session.")
            self._model = None
            self._processor = None
            self._model_loaded = False
            self.use_mock = True

    # -- real inference ------------------------------------------------------ #

    def _run_real_reasoning(self, context: CognitiveContext) -> str:
        """Multimodal generate() call against the loaded Qwen-VL model.
        Only ever called when self._model_loaded is True."""
        prompt = _build_prompt(context)

        inputs = self._processor(
            text=prompt, images=context.image, return_tensors="pt",
        ).to(self.device)

        with torch.no_grad():
            output_ids = self._model.generate(
                **inputs, max_new_tokens=MAX_NEW_TOKENS, do_sample=False,
            )

        decoded = self._processor.batch_decode(
            output_ids, skip_special_tokens=True,
        )[0]

        # Most VLM chat templates echo the prompt back before the
        # completion; keep only whatever follows the prompt text itself so
        # callers get a clean directive, not the whole transcript.
        if prompt in decoded:
            decoded = decoded.split(prompt, 1)[-1]
        return decoded.strip()

    # -- mock inference (the path this pipeline runs on today) -------------- #

    def mock_reasoning(self, context: CognitiveContext) -> str:
        """Deterministic, rule-based stand-in for the VLM's judgment.
        Mirrors the priority order a real Qwen-VL call would be prompted
        to follow (see _build_prompt): fault conditions in the SOP text
        override proceeding with the planned schedule.
        """
        sop_lower = context.sop_text.lower()

        if any(kw in sop_lower for kw in _MISALIGNMENT_KEYWORDS):
            return "SOP indicates misaligned insertion. Reset workspace."

        if any(kw in sop_lower for kw in _DROPPED_KEYWORDS):
            return "SOP indicates a dropped cable. Reset workspace and re-localize."

        color_sequence = _schedule_to_color_sequence(context.cds_schedule)
        if not color_sequence:
            return "No schedule available. Hold position and await new plan."

        return (f"Workspace clear: Execute CDS sequence: "
                f"{', '.join(color_sequence)}.")

    # -- public entry point --------------------------------------------------- #

    def reason(self, image: np.ndarray, yolo_summary: str, sop_text: str,
               cds_schedule: Sequence[str],
               use_mock: Optional[bool] = None) -> str:
        """Single call site downstream code (Phase 4's run_pipeline.py)
        should use. Builds a CognitiveContext from the 4 raw inputs and
        routes to the real or mock reasoning path.

        use_mock: per-call override. None (default) defers to the
        instance's self.use_mock setting (set at construction time).
        """
        context = CognitiveContext(
            image=image, yolo_summary=yolo_summary,
            sop_text=sop_text, cds_schedule=list(cds_schedule),
        )

        route_to_mock = self.use_mock if use_mock is None else use_mock

        if not route_to_mock and self._model_loaded:
            return self._run_real_reasoning(context)

        return self.mock_reasoning(context)


# --------------------------------------------------------------------------- #
# Standalone test block
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    print("=" * 70)
    print("[cognitive_manager] Standalone test")
    print("=" * 70)

    # Fake a cam_top-shaped frame without needing Genesis installed.
    fake_image = np.zeros((960, 960, 3), dtype=np.uint8)

    manager = CognitiveManager(use_mock=True)  # forced mock: VRAM-safe by default

    print("\n--- Scenario 1: clear workspace, proceed with CDS schedule ---")
    yolo_summary_1 = (
        "3 ports detected (red_square, blue_circle, yellow_triangle), "
        "3 cables detected (red, blue, yellow), no obstructions."
    )
    sop_text_1 = (
        "Align the cable connector plug's centroid with the port bin's "
        "centroid before descending. Approach along the port's normal axis."
    )
    cds_schedule_1 = ["cable_3_yellow", "cable_1_red", "cable_2_blue"]

    command_1 = manager.reason(fake_image, yolo_summary_1, sop_text_1, cds_schedule_1)
    print(f"    -> Command: {command_1!r}")
    assert "Execute CDS sequence" in command_1
    assert "Yellow, Red, Blue" in command_1

    print("\n--- Scenario 2: misalignment fault, should override schedule ---")
    sop_text_2 = (
        "If a connector plug contacts the port wall instead of the "
        "opening (misalignment > 5mm), immediately retract the arm."
    )
    command_2 = manager.reason(fake_image, yolo_summary_1, sop_text_2, cds_schedule_1)
    print(f"    -> Command: {command_2!r}")
    assert "Reset workspace" in command_2

    print("\n--- Scenario 3: dropped cable fault ---")
    sop_text_3 = (
        "If force feedback indicates the gripper has lost contact with a "
        "cable mid-transfer, halt arm motion immediately."
    )
    command_3 = manager.reason(fake_image, yolo_summary_1, sop_text_3, cds_schedule_1)
    print(f"    -> Command: {command_3!r}")
    assert "Reset workspace" in command_3

    print("\n[cognitive_manager] OK: all mock reasoning scenarios produced "
          "expected directives.")