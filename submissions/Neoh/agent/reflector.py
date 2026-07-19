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
            if len(output) > 200:
                output = output[:200] + "..."
            results_text += f"步骤{i+1}: {step.get('description', '')}\n结果: {'成功' if success else '失败'}\n输出: {output}\n\n"

        prompt = f"""评估任务是否完成。

任务: {task}

执行结果:
{results_text}

只输出一个 JSON 对象，格式如下，不要输出任何其他内容：
{{"completed":true,"reason":"完成原因","suggestion":""}}

规则:
- 直接以 {{ 开头，以 }} 结尾
- 不要输出 ```json 标记
- 不要输出解释文字
- completed 为 true 或 false
- 只输出 JSON 本身"""

        response = self.engine.generate(prompt, max_tokens=200)

        result = self._extract_result(response)
        if result:
            return result

        logger.warning("Failed to parse reflection, using fallback")
        return self._parse_fallback_reflection(results)

    def _extract_result(self, text: str) -> Dict[str, Any]:
        """从模型输出中提取 JSON 对象。"""
        # 方法 1：直接解析
        try:
            data = json.loads(text.strip())
            if isinstance(data, dict) and "completed" in data:
                return data
        except json.JSONDecodeError:
            pass

        # 方法 2：提取所有 JSON 块
        json_blocks = re.findall(r'```(?:json)?\s*(.*?)\s*```', text, re.DOTALL)
        json_blocks.append(text)

        for block in json_blocks:
            # 找包含 completed 的 {...}
            matches = re.findall(r'\{[^{}]*"completed"[^{}]*\}', block, re.DOTALL)
            for match in matches:
                try:
                    data = json.loads(match)
                    if isinstance(data, dict) and "completed" in data:
                        return data
                except json.JSONDecodeError:
                    continue

        return None

    def _parse_fallback_reflection(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """fallback：根据执行结果判断。"""
        all_success = all(r.get("success", False) for r in results)
        if all_success and results:
            return {"completed": True, "reason": "所有步骤执行成功", "suggestion": ""}
        return {"completed": False, "reason": "部分步骤失败", "suggestion": "请重试"}
