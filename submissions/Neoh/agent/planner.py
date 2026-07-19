import logging
import json
import re
from typing import List, Dict, Any
from inference.engine import InferenceEngine

logger = logging.getLogger(__name__)


class Planner:
    def __init__(self, engine: InferenceEngine):
        self.engine = engine

    def plan(self, task: str, tool_descriptions: str) -> List[Dict[str, Any]]:
        prompt = f"""你是任务规划器。将任务分解为可执行步骤。

任务: {task}

可用工具:
{tool_descriptions}

只输出一个 JSON 数组，格式如下，不要输出任何其他内容：
[{{"step":1,"description":"步骤描述","tool":"read_file","arguments":{{"file_path":"config.yaml"}}}}]

规则:
- 直接以 [ 开头，以 ] 结尾
- 不要输出 ```json 标记
- 不要输出解释文字
- tool 为 null 表示不需要工具
- 最多 3 个步骤
- 只输出 JSON 数组本身"""

        response = self.engine.generate(prompt, max_tokens=500)

        # 尝试提取 JSON
        steps = self._extract_steps(response)
        if steps:
            logger.info(f"Generated {len(steps)} steps")
            return steps[:5]  # 最多 5 步

        logger.warning("Failed to parse plan, using fallback")
        return self._parse_fallback_plan(task)

    def _extract_steps(self, text: str) -> List[Dict[str, Any]]:
        """从模型输出中提取步骤列表，处理多种格式。"""
        # 方法 1：直接解析（纯 JSON 数组）
        try:
            data = json.loads(text.strip())
            if isinstance(data, list):
                return data
            if isinstance(data, dict) and "steps" in data:
                return data["steps"]
        except json.JSONDecodeError:
            pass

        # 方法 2：提取所有 JSON 块，找第一个有效的
        # 匹配 ```json ... ``` 或 ``` ... ``` 或裸 JSON
        json_blocks = re.findall(r'```(?:json)?\s*(.*?)\s*```', text, re.DOTALL)
        json_blocks.append(text)  # 也尝试整个文本

        for block in json_blocks:
            # 尝试找 {...} 格式（带 steps 键）
            obj_match = re.search(r'\{[^{}]*"steps"[^{}]*\[.*?\][^{}]*\}', block, re.DOTALL)
            if obj_match:
                try:
                    data = json.loads(obj_match.group())
                    if isinstance(data, dict) and "steps" in data:
                        return data["steps"]
                except json.JSONDecodeError:
                    pass

            # 尝试找 [...] 格式（直接数组）
            arr_match = re.search(r'\[\s*\{.*?\}\s*\]', block, re.DOTALL)
            if arr_match:
                try:
                    data = json.loads(arr_match.group())
                    if isinstance(data, list) and len(data) > 0:
                        return data
                except json.JSONDecodeError:
                    pass

        return None

    def _parse_fallback_plan(self, task: str) -> List[Dict[str, Any]]:
        """fallback：返回单步任务。"""
        return [{
            "step": 1,
            "description": f"执行任务: {task}",
            "tool": None,
            "arguments": {},
        }]
