"""Stage C2: Qwen3-VL episode-end verifier.

After a pick-and-place episode finishes, feed Qwen3-VL the BEFORE and
AFTER world-camera RGB frames + the task instruction. It returns:

    {
        "success":      bool,
        "failure_type": "none" | "wrong_pick" | "not_landed" | "dropped" | "no_contact" | "unknown",
        "confidence":   0.0-1.0,
        "reasoning":    "short sentence"
    }

Same network caveat as qwen_planner.py: Qwen3-VL-8B was fetched from
ModelScope to
`/workspace/models/modelscope/models/Qwen--Qwen3-VL-8B-Instruct/snapshots/master`.
"""
from __future__ import annotations

import json
import time
from typing import Dict, Optional

import numpy as np

from qwen_planner import DEFAULT_MODEL_PATH  # reuse the same local path

VERIFY_PROMPT = """You are verifying whether a robot task succeeded.

Task instruction: {instruction}

Image 1 (Before): state before the robot acted.
Image 2 (After): state after the robot acted.

Decide if the object named in the instruction ended up inside its target bin.
Output ONLY valid JSON, no markdown:
{{
    "success": true|false,
    "failure_type": "none|wrong_pick|not_landed|dropped|no_contact|unknown",
    "confidence": 0.0-1.0,
    "reasoning": "one short sentence describing what changed"
}}"""


class Qwen3VLVerifier:
    """Loads Qwen3-VL-8B once; verifies task success from before/after images."""

    def __init__(self, model_path: str = DEFAULT_MODEL_PATH, device: str = "cuda"):
        self.model_path = model_path
        self.device = device
        self.model = None
        self.processor = None
        self.last_inference_ms = 0.0

    def load(self) -> "Qwen3VLVerifier":
        import torch
        from transformers import AutoModelForImageTextToText, AutoProcessor

        self.processor = AutoProcessor.from_pretrained(self.model_path)
        self.model = AutoModelForImageTextToText.from_pretrained(
            self.model_path, dtype=torch.float16, device_map=self.device
        )
        return self

    def verify(
        self,
        before_rgb: np.ndarray,
        after_rgb: np.ndarray,
        instruction: str,
    ) -> Dict:
        if self.model is None:
            return {"success": False, "failure_type": "unknown",
                    "confidence": 0.0, "reasoning": "no-VLM"}
        try:
            t0 = time.time()
            r = self._inference(before_rgb, after_rgb, instruction)
            self.last_inference_ms = (time.time() - t0) * 1000.0
            return r
        except Exception as e:  # pragma: no cover
            print(f"[Qwen3VLVerifier] inference failed: {e}")
            return {"success": False, "failure_type": "unknown",
                    "confidence": 0.0, "reasoning": f"exc:{e!r}"}

    def _inference(self, before_rgb, after_rgb, instruction):
        import torch
        from PIL import Image

        # Qwen3-VL accepts up to 2 images per turn (chat-template image slots).
        before_pil = Image.fromarray(before_rgb.astype(np.uint8))
        after_pil = Image.fromarray(after_rgb.astype(np.uint8))
        prompt = VERIFY_PROMPT.format(instruction=instruction)
        msgs = [{"role": "user", "content": [
            {"type": "image", "image": before_pil},
            {"type": "image", "image": after_pil},
            {"type": "text", "text": prompt},
        ]}]
        text = self.processor.apply_chat_template(
            msgs, tokenize=False, add_generation_prompt=True
        )
        inputs = self.processor(
            text=[text], images=[before_pil, after_pil], return_tensors="pt"
        ).to(self.model.device)
        with torch.no_grad():
            out = self.model.generate(
                **inputs, max_new_tokens=128, do_sample=False
            )
        response = self.processor.decode(out[0], skip_special_tokens=True)
        return self._parse(response)

    @staticmethod
    def _parse(response: str) -> Dict:
        ai = response.rfind("assistant")
        body = response[ai + len("assistant") :] if ai >= 0 else response
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
            return {"success": False, "failure_type": "unknown",
                    "confidence": 0.0, "reasoning": "parse-failed"}
        # Coerce and clamp.
        return {
            "success": bool(d.get("success", False)),
            "failure_type": str(d.get("failure_type", "unknown"))[:32],
            "confidence": max(0.0, min(1.0, float(d.get("confidence", 0.0)))),
            "reasoning": str(d.get("reasoning", ""))[:200],
        }


if __name__ == "__main__":
    import sys
    import cv2

    if len(sys.argv) < 3:
        print("usage: python qwen_verifier.py <before.jpg> <after.jpg> [instruction]")
        sys.exit(1)
    before = cv2.cvtColor(cv2.imread(sys.argv[1]), cv2.COLOR_BGR2RGB)
    after = cv2.cvtColor(cv2.imread(sys.argv[2]), cv2.COLOR_BGR2RGB)
    instr = sys.argv[3] if len(sys.argv) > 3 else "pick the red cube into the red bin"
    v = Qwen3VLVerifier().load()
    t0 = time.time()
    r = v.verify(before, after, instr)
    print(f"verify in {time.time()-t0:.2f}s:")
    print(json.dumps(r, indent=2, ensure_ascii=False))
