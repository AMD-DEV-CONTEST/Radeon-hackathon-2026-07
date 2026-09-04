# -*- coding: utf-8 -*-
"""任务规划：把复杂请求拆解成多步子任务。

方法：先用 LLM 生成逐步计划，再让 Agent 按计划逐项执行（task planning）。
对简单问题直接回答，不进入规划。
"""
import json

from .llm import LLMBackend

PLAN_PROMPT = """你是任务规划器。用户有一个目标，请把它拆解为 1~5 个可执行的子任务步骤。
每一步必须能够独立执行（可能需要调用工具：rag_search 检索知识库、read_doc 读文档）。
如果目标是简单问题（一句话能回答，不需要检索），只输出 {"plan": []}。
严格只输出 JSON，格式：
{"plan": [{"step": 1, "task": "任务描述", "need_tools": true/false}]}
"""


class Planner:
    def __init__(self, llm: LLMBackend):
        self.llm = llm

    def plan(self, goal: str) -> list:
        """返回 [{'step','task','need_tools'}]，空列表=直接回答。"""
        resp = self.llm.chat([
            {"role": "system", "content": PLAN_PROMPT},
            {"role": "user", "content": f"目标：{goal}"},
        ], temperature=0.1, max_tokens=800)
        text = resp["content"].strip()
        # 剥掉 ```json 代码围栏（不能用 replace('json','')——会误伤含"json"的子任务文本）
        import re as _re
        m = _re.search(r"\{.*\}", text, _re.S)
        try:
            data = json.loads(m.group(0)) if m else json.loads(text)
            return data.get("plan", [])
        except Exception:
            return []


if __name__ == "__main__":
    from .llm import LLMBackend
    p = Planner(LLMBackend())
    for goal in ["总结报告.pdf 并给出行动项", "你好"]:
        print(goal, "->", p.plan(goal))
