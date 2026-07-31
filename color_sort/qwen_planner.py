"""Stage C1: Task planner using Qwen3-VL-8B.

Given a world-camera RGB image and a free-form language instruction
(e.g. "pick the red cube into the red bin"), query Qwen3-VL to extract a
structured task decomposition:

    {
        "pick_object":    "red_cube",          # entity name in scene_config
        "pick_color":     "red",
        "place_color":    "red",
        "place_container":"red_bin",
        "reasoning":      "..."                # short VLM rationale
    }

This is an UPPER-LAYER orchestrator (per spec §4 Stage C / Qwen3-VL
decision): invoked at episode START, NOT in the 30Hz control loop. The
parsed task is later fed as the SmolVLA / ACT language task string.

Network note: Qwen3-VL-8B was downloaded via ModelScope to
`/workspace/models/modelscope/models/Qwen--Qwen3-VL-8B-Instruct/snapshots/master`
because huggingface.co was network-unreachable on this cloud instance.
"""
from __future__ import annotations

import json
import os
import time
from typing import Dict, Optional

import numpy as np

# Default local path (downloaded via ModelScope).
DEFAULT_MODEL_PATH = "/workspace/models/modelscope/models/Qwen--Qwen3-VL-8B-Instruct/snapshots/master"

# Scene-aware vocabulary — keeps Qwen3-VL's output anchored to real entity names.
_KNOWN_COLORS = ("red", "blue", "green", "yellow", "purple")
_KNOWN_GEOMETRIES = ("cube", "cylinder", "sphere")
_KNOWN_BINS = tuple(f"{c}_bin" for c in _KNOWN_COLORS)

PLAN_PROMPT = """You are a robot task planner. Look at the tabletop scene from a top-down camera.

Task instruction: {instruction}

The scene contains colored geometric objects and colored bins.
Objects are named "<color>_<geometry>" (colors: {colors}; geometries: {geos}).
Bins are named "<color>_bin" (a bin matches an object by color).

Decompose the instruction into ONE pick-and-place step.
Output ONLY valid JSON, no markdown:
{{
    "pick_object": "<color>_<geometry>",
    "pick_color": "<color>",
    "place_color": "<color>",
    "place_container": "<color>_bin",
    "reasoning": "one short sentence"
}}
If the instruction does not name a specific object, pick the first matching one."""


class Qwen3VLPlanner:
    """Loads Qwen3-VL-8B once; plans tasks from (image, instruction) pairs."""

    def __init__(self, model_path: str = DEFAULT_MODEL_PATH, device: str = "cuda"):
        self.model_path = model_path
        self.device = device
        self.model = None
        self.processor = None
        self.last_inference_ms = 0.0

    def load(self) -> "Qwen3VLPlanner":
        import torch
        from transformers import AutoModelForImageTextToText, AutoProcessor

        self.processor = AutoProcessor.from_pretrained(self.model_path)
        self.model = AutoModelForImageTextToText.from_pretrained(
            self.model_path, dtype=torch.float16, device_map=self.device
        )
        return self

    def plan(self, image_rgb: np.ndarray, instruction: str) -> Dict:
        """Return parsed task dict; falls back to rule-based on error."""
        if self.model is None:
            return self._rule_based(instruction)
        try:
            t0 = time.time()
            result = self._inference(image_rgb, instruction)
            self.last_inference_ms = (time.time() - t0) * 1000.0
            return result
        except Exception as e:  # pragma: no cover — defensive, real failures logged
            print(f"[Qwen3VLPlanner] inference failed: {e}")
            return self._rule_based(instruction)

    def _inference(self, image_rgb: np.ndarray, instruction: str) -> Dict:
        import torch
        from PIL import Image

        pil = Image.fromarray(image_rgb.astype(np.uint8))
        prompt = PLAN_PROMPT.format(
            instruction=instruction,
            colors=",".join(_KNOWN_COLORS),
            geos=",".join(_KNOWN_GEOMETRIES),
        )
        msgs = [{"role": "user", "content": [
            {"type": "image", "image": pil},
            {"type": "text", "text": prompt},
        ]}]
        text = self.processor.apply_chat_template(
            msgs, tokenize=False, add_generation_prompt=True
        )
        inputs = self.processor(
            text=[text], images=[pil], return_tensors="pt"
        ).to(self.model.device)
        with torch.no_grad():
            out = self.model.generate(
                **inputs, max_new_tokens=128, do_sample=False
            )
        response = self.processor.decode(out[0], skip_special_tokens=True)
        return self._parse(response, instruction)

    @staticmethod
    def _parse(response: str, instruction: str) -> Dict:
        """Extract the JSON block from a model response.

        The decoded chat-template output repeats the user prompt then a
        blank line then `assistant\n<generated text>`. We only parse
        what comes AFTER the last `assistant` marker, so prompt text
        with literal braces can't be mis-extracted as the JSON block.
        """
        # Strip everything up to the final assistant turn.
        ai_idx = response.rfind("assistant")
        body = response[ai_idx + len("assistant") :] if ai_idx >= 0 else response

        s = body.rfind("```json")
        if s >= 0:
            e = body.rfind("```", s + 7)
            block = body[s + 7 : e].strip() if e > s else body
        else:
            l = body.find("{")
            r = body.rfind("}")
            block = body[l : r + 1] if l >= 0 and r > l else body
        try:
            d = json.loads(block)
        except json.JSONDecodeError:
            return Qwen3VLPlanner._rule_based(instruction)
        # Sanity-clamp to known vocabulary.
        pick = str(d.get("pick_object", "")).lower()
        color = str(d.get("pick_color", "")).lower()
        geom = "_".join(pick.split("_")[1:]) if "_" in pick else ""
        if color not in _KNOWN_COLORS:
            color = Qwen3VLPlanner._scan_color(instruction)
        if not geom or geom not in _KNOWN_GEOMETRIES:
            geom = "cube"
        pick = f"{color}_{geom}"
        place_color = str(d.get("place_color", color)).lower()
        if place_color not in _KNOWN_COLORS:
            place_color = color
        return {
            "pick_object": pick,
            "pick_color": color,
            "place_color": place_color,
            "place_container": f"{place_color}_bin",
            "reasoning": str(d.get("reasoning", ""))[:200],
        }

    @staticmethod
    def _scan_color(text: str) -> str:
        low = text.lower()
        for c in _KNOWN_COLORS:
            if c in low:
                return c
        return _KNOWN_COLORS[0]

    @staticmethod
    def _rule_based(instruction: str) -> Dict:
        color = Qwen3VLPlanner._scan_color(instruction)
        low = instruction.lower()
        geom = "cube"
        for g in _KNOWN_GEOMETRIES:
            if g in low:
                geom = g
                break
        return {
            "pick_object": f"{color}_{geom}",
            "pick_color": color,
            "place_color": color,
            "place_container": f"{color}_bin",
            "reasoning": "rule-based fallback",
        }


# == Self-test / demo path ==
if __name__ == "__main__":
    import sys
    import cv2  # available via lerobot deps

    img_path = sys.argv[1] if len(sys.argv) > 1 else None
    instr = sys.argv[2] if len(sys.argv) > 2 else "pick the red cube into the red bin"
    if img_path is None:
        print("usage: python qwen_planner.py <image.jpg> [instruction]")
        sys.exit(1)
    img = cv2.cvtColor(cv2.imread(img_path), cv2.COLOR_BGR2RGB)
    planner = Qwen3VLPlanner().load()
    t0 = time.time()
    plan = planner.plan(img, instr)
    print(f"plan in {time.time()-t0:.2f}s:")
    print(json.dumps(plan, indent=2, ensure_ascii=False))
