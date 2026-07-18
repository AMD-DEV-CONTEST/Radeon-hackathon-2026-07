import logging
import json
import re
from typing import List, Dict, Any
from inference.engine import InferenceEngine

logger = logging.getLogger(__name__)


class Reflector:
    def __init__(self, engine: InferenceEngine):
        self.engine = engine

    def reflect(self, task: str, steps: List[Dict[str, Any]], results: List[Dict[str, Any]]) -> Dict[str, Any]:
        results_text = ""
        for i, (step, result) in enumerate(zip(steps, results)):
            success = result.get("success", False)
            output = str(result.get("output", "无输出"))
            # 截断过长的输出
            if len(output) > 300:
                output = output[:300] + "...[truncated]"
            results_text += f"步骤 {i+1}: {step.get('description', '')}\n结果: {'成功' if success else '失败'}\n输出: {output}\n\n"

        prompt = f"""请评估以下任务的执行结果是否完成。

任务: {task}

执行步骤和结果:
{results_text}

请只输出 JSON 对象，不要输出任何解释文字、markdown 标记或额外说明。直接以 {{ 开头，以 }} 结尾。

格式:
{{
  "completed": true或false,
  "reason": "完成或未完成的原因（一句话）",
  "suggestion": "如果未完成，建议的下一步操作；如果完成，填空字符串"
}}

只输出 JSON，不要任何其他文字。
"""

        response = self.engine.generate(prompt, max_tokens=300)

        # 尝试提取 JSON 对象
        result = self._extract_json_object(response)
        if result is not None:
            return result

        # fallback
        logger.warning("Failed to parse reflection, using fallback")
        return self._parse_fallback_reflection(response)

    def _extract_json_object(self, text: str) -> Dict[str, Any]:
        """从文本中提取 JSON 对象，处理 LLM 输出带额外文字的情况。"""
        # 方法 1：直接解析
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

        # 方法 2：用正则提取第一个 {...} 块
        patterns = [
            r'```json\s*(\{.*?\})\s*```',  # ```json {...} ```
            r'```\s*(\{.*?\})\s*```',       # ``` {...} ```
            r'(\{[^{}]*"completed"[^{}]*\})',  # {..."completed"...}
        ]
        for pattern in patterns:
            matches = re.findall(pattern, text, re.DOTALL)
            if matches:
                for match in matches:
                    try:
                        data = json.loads(match)
                        if isinstance(data, dict) and "completed" in data:
                            return data
                    except json.JSONDecodeError:
                        continue

        return None

    def _parse_fallback_reflection(self, text: str) -> Dict[str, Any]:
        if "完成" in text or "成功" in text or "true" in text.lower():
            return {"completed": True, "reason": "任务执行完成", "suggestion": ""}
        else:
            return {"completed": False, "reason": "任务未完成", "suggestion": "请重新执行"}
