"""
Qwen3-VL Perception Module
Uses official AutoModelForImageTextToText API (transformers>=4.57).
Outputs relative spatial descriptions, not absolute coordinates.
Scene memory resolves to precise Genesis coordinates.
"""
import numpy as np
import json
import time
from typing import Dict, Optional, List


GROUNDING_PROMPT = """You are a robot vision system analyzing a tabletop scene.

User instruction: {instruction}

Available objects and their approximate positions:
{object_list}

Determine:
1. Which object to PICK (name from the list above)
2. WHERE to PLACE it — describe relative to another object or table area

Output ONLY valid JSON:
{{
    "pick": "object_name",
    "place_relative": "description like 'right of blue_cube' or 'center of table'",
    "reasoning": "brief explanation"
}}

Do NOT output coordinates — the system will compute exact positions."""


class QwenVLWrapper:
    def __init__(self, model_name: str = "Qwen/Qwen3-VL-8B-Instruct"):
        self.model_name = model_name
        self.model = None
        self.processor = None
        self.last_inference_time = 0.0

    def load(self):
        try:
            import torch
            from transformers import AutoModelForImageTextToText, AutoProcessor

            self.processor = AutoProcessor.from_pretrained(self.model_name)
            self.model = AutoModelForImageTextToText.from_pretrained(
                self.model_name,
                dtype="auto",
                device_map="auto",
            )
            print(f"Qwen3-VL loaded: {self.model_name} on {self.model.device}")
        except Exception as e:
            print(f"Qwen3-VL load failed: {e}")
        return self

    def understand(self, image, instruction, objects: dict, table_top=0.05):
        start = time.time()
        if self.model is not None:
            result = self._inference(image, instruction, objects, table_top)
        else:
            result = self._rule_based(instruction, objects, table_top)
        self.last_inference_time = (time.time() - start) * 1000
        return result

    def _inference(self, image, instruction, objects, table_top):
        from PIL import Image
        import torch

        pil_img = Image.fromarray(image)

        # Build object list with positions
        obj_lines = []
        for name, ent in objects.items():
            pos = ent.get_pos().cpu().numpy()
            obj_lines.append(f"  - {name}: at [{pos[0]:.2f}, {pos[1]:.2f}, z={pos[2]:.2f}]")
        obj_list_str = "\n".join(obj_lines)

        prompt = GROUNDING_PROMPT.format(
            instruction=instruction,
            object_list=obj_list_str,
        )

        messages = [{"role": "user", "content": [
            {"type": "image", "image": pil_img},
            {"type": "text", "text": prompt},
        ]}]

        text = self.processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True)
        inputs = self.processor(
            text=[text], images=[pil_img], return_tensors="pt"
        ).to(self.model.device)

        with torch.no_grad():
            output = self.model.generate(
                **inputs, max_new_tokens=256, do_sample=False)

        response = self.processor.decode(output[0], skip_special_tokens=True)
        return self._parse(response, objects, table_top)

    def _parse(self, response, objects, table_top):
        try:
            s = response.rfind("```json")
            e = response.rfind("```")
            block = response[s+7:e].strip() if s >= 0 and e > s else response[response.find("{"):response.rfind("}")+1]
            r = json.loads(block)
            pick = r.get("pick", "")
            if pick not in objects:
                pick = list(objects.keys())[0] if objects else "red_cube"
            return {
                "pick": pick,
                "place_relative": r.get("place_relative", "right of the scene"),
                "reasoning": r.get("reasoning", ""),
            }
        except Exception:
            return self._rule_based(response, objects, table_top)

    def _rule_based(self, instruction, objects, table_top):
        lower = instruction.lower()
        pick = list(objects.keys())[0] if objects else "red_cube"
        for name in objects:
            if name.split("_")[0] in lower:
                pick = name
                break
        return {
            "pick": pick,
            "place_relative": "right of the scene",
            "reasoning": "Rule-based fallback",
        }

    def get_inference_time(self):
        return self.last_inference_time


def resolve_place_position(place_relative: str, objects: dict, table_top=0.0, cube_size=0.04):
    """Convert relative description to exact Genesis coordinates.

    Uses scene memory (object positions) for precise placement.
    """
    lower = place_relative.lower()

    # Try to find a reference object
    ref_name = None
    for name in objects:
        if name in lower or name.split("_")[0] in lower:
            ref_name = name
            break

    if ref_name and ref_name in objects:
        ref_obj = objects[ref_name]
        # Handle both entity objects and position lists
        if hasattr(ref_obj, 'get_pos'):
            ref_pos = ref_obj.get_pos().cpu().numpy()
        elif hasattr(ref_obj, 'cpu'):
            ref_pos = ref_obj.cpu().numpy()
        else:
            ref_pos = np.array(ref_obj)
        gap = cube_size * 1.5  # 6cm — one cube width + small gap
        # Place next to reference object
        if "right" in lower or "east" in lower:
            return [ref_pos[0] + gap, ref_pos[1], table_top + cube_size / 2]
        elif "left" in lower or "west" in lower:
            return [ref_pos[0] - gap, ref_pos[1], table_top + cube_size / 2]
        elif "behind" in lower or "north" in lower:
            return [ref_pos[0], ref_pos[1] + gap, table_top + cube_size / 2]
        elif "front" in lower or "south" in lower:
            return [ref_pos[0], ref_pos[1] - gap, table_top + cube_size / 2]
        else:
            return [ref_pos[0] + gap, ref_pos[1], table_top + cube_size / 2]

    # Default: center of table
    return [0.55, 0.0, table_top + cube_size / 2]
