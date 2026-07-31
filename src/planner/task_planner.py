"""
Task Planner — LLM-based task graph generation.
Replaces rule-based parser with structured task decomposition.

Input: Natural language instruction
Output: Ordered list of actions (Task Graph)
"""
import json
import time
from typing import List, Dict


# ── Task Graph Schema ────────────────────────────────────────

EXAMPLE_TASK_GRAPH = {
    "reasoning": "User wants to move the red cup into the blue box",
    "steps": [
        {"action": "pick", "object": "red cup", "description": "Grasp the red cup"},
        {"action": "place", "target": "blue box", "description": "Place cup in blue box"},
    ]
}

MULTI_STEP_EXAMPLE = {
    "reasoning": "User wants to first move apple to box, then pick up cup",
    "steps": [
        {"action": "pick", "object": "apple", "description": "Grasp the apple"},
        {"action": "place", "target": "blue box", "description": "Place apple in box"},
        {"action": "pick", "object": "red cup", "description": "Grasp the red cup"},
        {"action": "place", "target": "table", "description": "Place cup on table"},
    ]
}


PLANNER_PROMPT = """You are a robot task planner. Given a natural language instruction, decompose it into a sequence of atomic actions.

Available actions: pick, place, move, wait

Objects in scene: red cup, blue box, apple, bottle, table

Output ONLY valid JSON:
{
    "reasoning": "brief explanation",
    "steps": [
        {"action": "pick", "object": "object name", "description": "what to do"},
        {"action": "place", "target": "target name", "description": "where to put"}
    ]
}

Examples:

Instruction: "Pick up the red cup and place it in the blue box"
Output: """ + json.dumps(EXAMPLE_TASK_GRAPH, indent=2) + """

Instruction: "Move the apple into the box, then pick up the cup"
Output: """ + json.dumps(MULTI_STEP_EXAMPLE, indent=2) + """

Now plan for this instruction:
"""


class TaskPlanner:
    def __init__(self, vlm_proc=None, vlm_model=None):
        self.vlm_proc = vlm_proc
        self.vlm_model = vlm_model
        self.last_plan = None
        self.last_inference_ms = 0.0

    def plan(self, instruction: str, image=None) -> Dict:
        start = time.time()

        if self.vlm_proc is not None and self.vlm_model is not None:
            result = self._llm_plan(instruction, image)
        else:
            result = self._smart_parse(instruction)

        self.last_inference_ms = (time.time() - start) * 1000
        result["inference_ms"] = self.last_inference_ms
        self.last_plan = result
        return result

    def _llm_plan(self, instruction: str, image=None) -> Dict:
        import torch
        from PIL import Image as PILImage

        prompt = PLANNER_PROMPT + f'"{instruction}"\nOutput:'

        if image is not None:
            pil_img = PILImage.fromarray(image)
            messages = [{"role": "user", "content": [
                {"type": "image", "image": pil_img},
                {"type": "text", "text": prompt},
            ]}]
        else:
            messages = [{"role": "user", "content": prompt}]

        text = self.vlm_proc.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = self.vlm_proc(text=[text], images=[pil_img] if image is not None else None, return_tensors="pt").to(self.vlm_model.device)

        with torch.no_grad():
            output = self.vlm_model.generate(**inputs, max_new_tokens=256, do_sample=False)

        response = self.vlm_proc.decode(output[0], skip_special_tokens=True)
        return self._parse_json(response)

    def _smart_parse(self, instruction: str) -> Dict:
        """Enhanced rule-based parser with multi-step pick-place pairs.

        Splits compound instructions on connectors ("then", "and", ";", Chinese
        punctuation). Each segment adds an action; consecutive pick/place
        fragments are stitched into full pick-then-place units. Produces a
        flat list that an ActionScheduler loops over until done.
        """
        lower = instruction.lower()
        steps = []

        # Split by sentence-level connectors
        import re
        segments = re.split(
            r'\s+then\s+|, then\s+| and then\s+| after that\s+|\s+and\s+|，|。|;|\s+after\s+that\s+',
            lower,
        )

        last_pick_object = None
        for seg in segments:
            seg = seg.strip()
            if not seg:
                continue

            pick_detected = any(kw in seg for kw in ["pick", "grab", "lift", "拿", "抓", "取"])
            place_detected = any(kw in seg for kw in ["place", "put", "放", "进", "到"])
            move_detected = any(kw in seg for kw in ["move", "移"])

            if pick_detected:
                obj = self._find_object(seg)
                steps.append({"action": "pick", "object": obj,
                              "description": f"Grasp the {obj}"})
                last_pick_object = obj
            elif place_detected:
                tgt = self._find_target(seg)
                obj = last_pick_object or self._find_object(seg)
                steps.append({"action": "place", "object": obj, "target": tgt,
                              "description": f"Place {obj} at {tgt}"})
                last_pick_object = None  # consumed
            elif move_detected:
                obj = self._find_object(seg)
                tgt = self._find_target(seg)
                if last_pick_object is None and obj:
                    steps.append({"action": "pick", "object": obj,
                                  "description": f"Grasp the {obj}"})
                    last_pick_object = obj
                if tgt:
                    steps.append({"action": "place", "object": last_pick_object or obj,
                                  "target": tgt,
                                  "description": f"Place at {tgt}"})
                    last_pick_object = None
            else:
                # Fallback within segment: detect both
                obj = self._find_object(seg)
                tgt = self._find_target(seg)
                if obj and (pick_detected or last_pick_object is None):
                    steps.append({"action": "pick", "object": obj,
                                  "description": f"Grasp the {obj}"})
                    last_pick_object = obj
                if tgt:
                    steps.append({"action": "place", "object": last_pick_object or obj,
                                  "target": tgt,
                                  "description": f"Place at {tgt}"})
                    last_pick_object = None

        # Final fallback: nothing parsed -> default single pick-place
        if not steps:
            obj = self._find_object(lower)
            tgt = self._find_target(lower)
            steps = [
                {"action": "pick", "object": obj,
                 "description": f"Grasp the {obj}"},
                {"action": "place", "object": obj, "target": tgt,
                 "description": f"Place {obj} at {tgt}"},
            ]

        return {
            "reasoning": f"Parsed from instruction: {instruction}",
            "steps": steps,
        }


    def _find_object(self, text: str) -> str:
        objects = [
            ("red_cube", ["red cube", "red_cube", "red cup", "cup", "红色", "杯子", "red"]),
            ("blue_cube", ["blue cube", "blue_cube", "blue cup", "蓝色", "blue"]),
            ("green_cube", ["green cube", "green_cube", "绿色", "green"]),
            ("yellow_cube", ["yellow cube", "yellow_cube", "黄色", "yellow"]),
            ("yellow_cylinder", ["yellow cylinder", "yellow_cylinder", "cylinder", "圆柱", "柱子", "黄色圆柱"]),
            ("purple_sphere", ["purple sphere", "purple_sphere", "sphere", "球", "紫色球", "紫色"]),
            ("orange_cube", ["orange cube", "orange_cube", "橙色", "orange"]),
            ("cyan_cube", ["cyan cube", "cyan_cube", "青色", "cyan"]),
            ("white_cube", ["white cube", "white_cube", "白色", "white"]),
            ("apple", ["apple", "苹果"]),
            ("bottle", ["bottle", "瓶子"]),
        ]
        for name, keywords in objects:
            for kw in keywords:
                if kw in text:
                    return name
        return "red_cube"

    def _find_target(self, text: str) -> str:
        targets = [
            ("blue_cube", ["blue cube", "blue_cube", "blue box", "蓝色", "blue"]),
            ("red_cube", ["red cube", "red_cube", "red", "红色"]),
            ("green_cube", ["green cube", "green_cube", "green", "绿色"]),
            ("yellow_cylinder", ["yellow cylinder", "yellow_cylinder", "cylinder", "圆柱"]),
            ("purple_sphere", ["purple sphere", "purple_sphere", "sphere", "球"]),
            ("table", ["table", "桌子"]),
        ]
        for name, keywords in targets:
            for kw in keywords:
                if kw in text:
                    return name
        return "blue_cube"

    def _parse_json(self, response: str) -> Dict:
        try:
            start = response.find("{")
            end = response.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(response[start:end])
        except json.JSONDecodeError:
            pass
        return {"reasoning": "parse failed", "steps": []}
