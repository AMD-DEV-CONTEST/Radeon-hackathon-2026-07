"""
Camera Verifier — Close the perception-action loop.
After robot executes, verify task success via camera + VLM.

Flow:
    Before: Capture initial state
    Action: Execute pick & place
    After: Capture final state
    Verify: Compare before/after → Success/Failure
"""
import time
import json
import numpy as np
from typing import Dict


VERIFY_PROMPT = """Compare these two images of a robotic workspace.

Image 1 (Before): Initial state
Image 2 (After): State after robot action

Task: {instruction}

Did the robot successfully complete the task?
Output ONLY valid JSON:
{{"success": true/false, "confidence": 0.0-1.0, "reasoning": "brief explanation", "observed_changes": "what changed"}}"""


class CameraVerifier:
    def __init__(self, vlm_proc=None, vlm_model=None):
        self.vlm_proc = vlm_proc
        self.vlm_model = vlm_model
        self.before_image = None
        self.after_image = None
        self.last_result = None

    def capture_before(self, image: np.ndarray):
        self.before_image = image.copy()

    def capture_after(self, image: np.ndarray):
        self.after_image = image.copy()

    def verify(self, instruction: str = "") -> Dict:
        if self.before_image is None or self.after_image is None:
            return {"success": False, "reasoning": "Missing before/after images"}

        # Simple pixel-level comparison
        pixel_result = self._pixel_verify()

        # VLM-based verification (if available)
        vlm_result = None
        if self.vlm_proc is not None and self.vlm_model is not None:
            vlm_result = self._vlm_verify(instruction)

        # Combine results
        if vlm_result:
            result = vlm_result
        else:
            result = pixel_result

        self.last_result = result
        return result

    def _pixel_verify(self) -> Dict:
        """Simple pixel-level change detection."""
        diff = np.abs(self.before_image.astype(float) - self.after_image.astype(float))
        mean_diff = diff.mean()
        max_diff = diff.max()

        changed = mean_diff > 1.5 or max_diff > 100

        return {
            "success": changed,
            "confidence": min(mean_diff / 10.0, 1.0),
            "reasoning": f"Pixel difference: mean={mean_diff:.1f}, max={max_diff:.0f}",
            "method": "pixel",
        }

    def _vlm_verify(self, instruction: str) -> Dict:
        """VLM-based verification comparing before/after."""
        import torch
        from PIL import Image as PILImage

        before_pil = PILImage.fromarray(self.before_image)
        after_pil = PILImage.fromarray(self.after_image)

        prompt = VERIFY_PROMPT.format(instruction=instruction)

        messages = [{"role": "user", "content": [
            {"type": "image", "image": before_pil},
            {"type": "image", "image": after_pil},
            {"type": "text", "text": prompt},
        ]}]

        text = self.vlm_proc.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = self.vlm_proc(text=[text], images=[before_pil, after_pil], return_tensors="pt").to(self.vlm_model.device)

        start = time.time()
        with torch.no_grad():
            output = self.vlm_model.generate(**inputs, max_new_tokens=128, do_sample=False)
        elapsed = (time.time() - start) * 1000

        response = self.vlm_proc.decode(output[0], skip_special_tokens=True)
        result = self._parse_verify_response(response)
        result["vlm_inference_ms"] = elapsed
        result["method"] = "vlm"
        return result

    def _parse_verify_response(self, response: str) -> Dict:
        try:
            start = response.find("{")
            end = response.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(response[start:end])
        except json.JSONDecodeError:
            pass
        return {"success": False, "reasoning": "VLM parse failed"}

    def get_summary(self) -> Dict:
        return {
            "has_before": self.before_image is not None,
            "has_after": self.after_image is not None,
            "last_result": self.last_result,
        }
