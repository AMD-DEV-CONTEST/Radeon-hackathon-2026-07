# -*- coding: utf-8 -*-
"""Agent 主循环：感知 → 规划 → 工具调用 → 回答 → 引用校验。

流程（完整闭环）：
  意图门控（复杂问题才进入规划，省一次 LLM 调用）
    → 任务规划 (Planner, 拆解多步子任务)
    → 逐步执行（流式工具循环，每步调用工具/检索）
    → 汇总综合（多步骤时）
    → 引用可信度校验（groundedness + citation precision）

流式协议（供 UI 渲染活动时间线，yield 事件 dict）：
  {"type":"plan",           "steps":[...]}
  {"type":"plan_step_start","step":i,"task":...}
  {"type":"plan_step_done", "step":i,"task":...}
  {"type":"tool",           "name":...,"args":...,"result":...}
  {"type":"delta",          "text":...}          # 打字机输出
  {"type":"done",           "verification":..., "trace":...}
"""
import json
import re
from typing import Optional

from .llm import LLMBackend
from .rag import RAGStore
from .memory import Memory
from .planner import Planner
from .tools import build_tools
from .verify import groundedness, verify_citations, extract_citations

SYSTEM_TMPL = """你是一个运行在本地、完全离线的私有 AI 助手，帮助用户处理他们的私有文档。

规则：
1. 当问题需要知识库内容时，必须先调用工具 rag_search 检索，再基于检索结果回答。
2. 回答要准确，必须用 [来源:文档名] 格式注明引用来源（来自 rag_search 结果里的"来源:"标注）；
   知识库里没有的不要编造，坦率说明"知识库中没有相关信息"。
3. 如需读取某个文档全文，调用 read_doc；查看有哪些文档调用 list_docs。
4. 遵循用户已知偏好（见"记忆"）。

{memory}

请用中文回答。
"""

# 触发规划的问题特征词（命中才调用 Planner，普通问题直接问答省一次调用）
COMPLEX_KEYWORDS = [
    "计划", "规划", "步骤", "流程", "如何", "怎么", "怎么做", "比较", "对比",
    "分析", "评估", "总结", "综合", "方案", "分步骤", "依次", "首先", "然后",
    "roadmap", "plan", "compare", "analyze", "summarize", "如何实现",
]

SYNTHESIZE_PLAN_PROMPT = """你是资深分析师。用户有一个复杂目标，你已经把它拆成多个步骤并逐一执行完毕，下面是每个步骤的结论：

<user_goal>
{goal}
</user_goal>

<step_results>
{steps}
</step_results>

请把各步骤结论整合成一份**结构化、完整、有逻辑**的最终答案：
1. 用清晰的标题/分点组织。
2. 综合而非罗列，把各步骤信息整合成连贯叙述。
3. 保留 [来源:文档名] 引用标注（若有）。
4. 结尾用一段话给出核心结论。
请用中文回答。
"""


class Agent:
    def __init__(self, llm: LLMBackend = None, rag: RAGStore = None):
        self.llm = llm or LLMBackend()
        self.rag = rag or RAGStore(self.llm)
        self.memory = Memory()
        self.planner = Planner(self.llm)
        self.tools = build_tools(self.rag)
        self.max_steps = 6
        # UI 展示用状态
        self.trace: list = []            # 工具调用日志
        self.plan: list = []             # 本次的规划步骤
        self.verification = None         # 引用可信度校验结果
        self._retrieved_sources = set()  # 本次检索到的来源集合

    # ------------------------------------------------------------------
    def _system(self) -> str:
        return SYSTEM_TMPL.format(
            memory=self.memory.recall() or "（无长期记忆）",
        )

    def _looks_complex(self, msg: str) -> bool:
        m = msg.lower()
        return any(k.lower() in m for k in COMPLEX_KEYWORDS)

    # ------------------------------------------------------------ 核心循环
    def _run_loop_events(self, messages: list, emit: bool = True, tools_enabled: bool = True):
        """单遍流式工具循环。

        流式产出 delta（emit=True 时），工具调用在流结尾拿到完整列表并执行。
        tools_enabled=False 时走"纯问答"（不触发工具，直接回答）。
        Returns: 本轮循环生成的完整文本。
        """
        final_text = ""
        tool_calls = []
        for step in range(self.max_steps):
            tool_calls = []
            step_text = ""
            stream = self.llm.chat_stream_full(messages,
                                               tools=self.tools.schemas() if tools_enabled else None)
            for ev in stream:
                if ev["tool_calls"]:
                    tool_calls = ev["tool_calls"]
                    continue
                if ev["delta"]:
                    step_text += ev["delta"]
                    final_text += ev["delta"]
                    if emit:
                        yield {"type": "delta", "text": ev["delta"]}
            if tool_calls:
                for tc in tool_calls:
                    name, args = tc["name"], tc.get("arguments") or {}
                    result = self.tools.call(name, args)
                    self._record_tool(name, args, result)
                    yield {"type": "tool", "name": name,
                           "args": args, "result": str(result)[:220],
                           "status": "ok"}
                    messages.append({
                        "role": "tool",
                        "content": str(result),
                        "name": name,
                    })
                continue
            # 无工具调用 = 本轮答案完成
            return final_text
        return final_text

    def _record_tool(self, name: str, args: dict, result: str):
        self.trace.append({
            "name": name, "args": args,
            "result": str(result)[:300], "status": "ok",
        })
        # 从 rag_search 结果里收集真实来源，供引用校验
        if name == "rag_search":
            for m in re.finditer(r"\[来源[:：]?\s*([^\]\[]+?)\]", str(result)):
                src = m.group(1).strip()
                # 去掉"相关度:x.xx"等后缀噪声，取第一个 token
                src = re.split(r"[\s，。；,;（(]+", src)[0]
                if src:
                    self._retrieved_sources.add(src)
        print(f"    [tool] {name}({json.dumps(args, ensure_ascii=False)}) -> {str(result)[:80]}...")

    # ------------------------------------------------------------------
    def ask_events(self, user_msg: str, use_planning: bool = True, tools_enabled: bool = True):
        """富事件流（UI 主用）。

        tools_enabled=False 时纯问答（不触发工具调用、不规划），用于"工具调用"开关。
        """
        self.trace = []
        self.plan = []
        self.verification = None
        self._retrieved_sources = set()
        self.memory.add_short("user", user_msg)

        messages = [{"role": "system", "content": self._system()}]
        messages += self.memory.short_messages()[:-1]
        messages.append({"role": "user", "content": user_msg})

        # ---- 规划阶段（仅复杂问题且启用工具时）----
        plan = []
        if use_planning and tools_enabled and self._looks_complex(user_msg):
            try:
                plan = self.planner.plan(user_msg)
            except Exception as e:
                print(f"[warn] planner failed: {e}")
                plan = []
            if plan:
                self.plan = plan
                yield {"type": "plan", "steps": [p.get("task", "") for p in plan]}

        final_text = ""
        if plan:
            step_results = []
            total = len(plan)
            for i, p in enumerate(plan, 1):
                task = p.get("task", "")
                yield {"type": "plan_step_start", "step": i, "task": task, "total": total}
                step_msg = [
                    {"role": "system", "content": SYSTEM_TMPL.format(
                        memory=self.memory.recall() or "（无长期记忆）")},
                    {"role": "user", "content":
                        f"【子任务 {i}/{total}】{task}\n\n执行这个子任务（需要就调用工具），"
                        f"然后直接给出这一步的结论（不超过300字）。"},
                ]
                txt = ""
                for ev in self._run_loop_events(step_msg, emit=False, tools_enabled=tools_enabled):
                    txt += ev["text"] if ev["type"] == "delta" else ""
                step_results.append(f"【步骤{i}】{task}\n{txt.strip()}")
                yield {"type": "plan_step_done", "step": i, "task": task}
            # 汇总
            yield {"type": "synthesize"}
            synth_msg = [{"role": "system", "content": SYNTHESIZE_PLAN_PROMPT.format(
                goal=user_msg, steps="\n\n".join(step_results))},
                {"role": "user", "content": "请给出综合结论。"}]
            for ev in self._run_loop_events(synth_msg, emit=True, tools_enabled=tools_enabled):
                if ev["type"] == "delta":
                    final_text += ev["text"]
                yield ev
        else:
            # 直接问答
            for ev in self._run_loop_events(messages, emit=True, tools_enabled=tools_enabled):
                if ev["type"] == "delta":
                    final_text += ev["text"]
                yield ev

        # ---- 引用可信度校验 ----
        if self._retrieved_sources:
            # 用文档全文比对（而非截断的工具结果），grounding 更准确
            full_sources = []
            for src in self._retrieved_sources:
                try:
                    text = self.rag.get_document(src, limit=6000)
                    if text:
                        full_sources.append(text)
                except Exception:
                    full_sources.append(src)
            g_score, sents = groundedness(final_text, full_sources or list(self._retrieved_sources))
            cite_p, cite_checks = verify_citations(final_text, self._retrieved_sources)
            self.verification = {
                "grounding": g_score,
                "sentences": sents,
                "cite_precision": cite_p,
                "cites": cite_checks,
            }
        yield {"type": "done", "verification": self.verification, "trace": self.trace}

        if final_text:
            self.memory.add_short("assistant", final_text)

    def ask(self, user_msg: str, use_planning: bool = True) -> str:
        """同步版：返回最终回答字符串（CLI 用）。"""
        text = ""
        for ev in self.ask_events(user_msg, use_planning=use_planning):
            if ev["type"] == "delta":
                text += ev["text"]
        return text

    def ask_stream(self, user_msg: str, use_planning: bool = True):
        """兼容版流式：yield 纯文本（简单调用方用）。"""
        for ev in self.ask_events(user_msg, use_planning=use_planning):
            if ev["type"] == "delta":
                yield ev["text"]
            elif ev["type"] == "tool":
                yield f"\n[工具 {ev['name']} 执行中...]"

    # ---------------------------------------------------------------- 入库
    def ingest(self, path: str) -> int:
        return self.rag.add_document(path)

    def ingest_dir(self, path: Optional[str] = None) -> int:
        return self.rag.index_dir(path)


if __name__ == "__main__":
    agent = Agent()
    print("== Agent 自测 ==")
    print(agent.ask("你好"))
    print(agent.ask("分析我的项目用了什么技术栈？"))
    print("verification:", agent.verification)
