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
        prompt = f"""你是一个任务规划专家。请将以下任务分解为可执行的步骤列表。

任务: {task}

可用工具:
{tool_descriptions}

请只输出 JSON 数组，不要输出任何解释文字、markdown 标记或额外说明。直接以 [ 开头，以 ] 结尾。

格式:
[
  {{"step": 1, "description": "步骤描述", "tool": "工具名称或null", "arguments": {{"参数名": "值"}}}}
]

注意:
- tool 字段为 null 表示不需要工具调用
- 参数值根据任务内容合理推断
- 最多 5 个步骤
- 只输出 JSON，不要任何其他文字
"""

        response = self.engine.generate(prompt, max_tokens=800)

        # 尝试提取 JSON 数组
        steps = self._extract_json_array(response)
        if steps is not None:
            logger.info(f"Generated {len(steps)} steps")
            return steps

        # fallback
        logger.warning(f"Failed to parse plan, using fallback")
        return self._parse_fallback_plan(response)

    def _extract_json_array(self, text: str) -> List[Dict[str, Any]]:
        """从文本中提取 JSON 数组，处理 LLM 输出带额外文字的情况。"""
        # 方法 1：直接解析
        try:
            data = json.loads(text)
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass

        # 方法 2：用正则提取第一个 [...] 块
        patterns = [
            r'```json\s*(\[.*?\])\s*```',  # ```json [...] ```
            r'```\s*(\[.*?\])\s*```',       # ``` [...] ```
            r'(\[\s*\{.*?\}\s*\])',          # [...] 包含 {...}
        ]
        for pattern in patterns:
            matches = re.findall(pattern, text, re.DOTALL)
            if matches:
                for match in matches:
                    try:
                        data = json.loads(match)
                        if isinstance(data, list) and len(data) > 0:
                            return data
                    except json.JSONDecodeError:
                        continue

        return None

    def _parse_fallback_plan(self, text: str) -> List[Dict[str, Any]]:
        """最终 fallback：返回单步任务，让 Executor 直接处理。"""
        return [{
            "step": 1,
            "description": text[:200] if text else "执行任务",
            "tool": None,
            "arguments": {},
        }]
