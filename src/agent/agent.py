from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.agent.domain_packs import detect_pack, pack_system_prompt
from src.agent.reflect import reflect_and_refine
from src.agent.tools import ToolRegistry, extract_json_action
from src.llm.backend import LLMBackend
from src.memory.memory import SessionMemory
from src.privacy.audit import AuditTrail
from src.privacy.guard import is_exfiltration_request, privacy_block_message, redact_text


SYSTEM_PROMPT = """You are PrivateLocalAgent, a practical private AI agent for office work.
You can reason, plan, use tools, manage memory, and execute tasks locally.

Rules:
1) Use recent dialogue + saved memory as context.
2) Short follow-ups continue the previous topic (e.g. "中文", "详细点").
3) Ground policy/FAQ answers on knowledge-base evidence; do not invent rules.
4) Answer in Chinese when the user writes Chinese.
5) Prefer concise, actionable answers (steps, owners, deadlines when relevant).
6) Never advise sending confidential data to public chatbots or WeChat.

Response format:
- Tool call: {"tool":"name","args":{...}}
- Final answer: {"final":"..."}
No markdown fences.
"""

CHAT_SYSTEM_PROMPT = """You are PrivateLocalAgent in plain chat mode.
Answer the user directly and conversationally. No tools, no JSON, no workflow routing.
Rules:
1) Use recent dialogue + saved preferences as context.
2) Answer in Chinese when the user writes Chinese.
3) Be concise and helpful.
4) Do not invent company internal policies; if asked, suggest switching to「本地知识助理 (RAG)」mode.
5) Never advise sending confidential data to public chatbots or WeChat.
Reply with plain text only.
"""

_FOLLOWUP_HINTS = {
    "中文", "英文", "继续", "详细点", "详细一点", "再说一遍", "换种说法",
    "总结一下", "用中文", "用英文", "why", "为什么", "然后呢", "呢", "好的", "嗯",
}


@dataclass
class AgentStep:
    thought: str
    action: dict | None = None
    observation: str | None = None


@dataclass
class AgentResult:
    answer: str
    steps: list[AgentStep] = field(default_factory=list)
    used_tools: list[str] = field(default_factory=list)
    pack: str | None = None


class PrivateAgent:
    def __init__(
        self,
        llm: LLMBackend,
        tools: ToolRegistry,
        memory: SessionMemory,
        max_steps: int = 6,
        history_turns: int = 12,
        enable_reflect: bool = False,
        audit: AuditTrail | None = None,
    ) -> None:
        self.llm = llm
        self.tools = tools
        self.memory = memory
        self.max_steps = max_steps
        self.history_turns = history_turns
        self.enable_reflect = enable_reflect
        self.audit = audit

    def _search_query(self, user_query: str, prior: list[dict[str, str]]) -> str:
        q = user_query.strip()
        if not prior:
            return q
        last_user = next((h["content"] for h in reversed(prior) if h.get("role") == "user"), "")
        if not last_user:
            return q
        if q.lower() in _FOLLOWUP_HINTS or len(q) <= 24:
            return f"{last_user} {q}".strip()
        return q

    def _maybe_store_prefs(self, user_query: str) -> None:
        q = user_query.strip()
        if q in {"中文", "用中文"} or "用中文" in q:
            self.memory.add_fact("用户偏好：请用中文回答")
        elif q in {"英文", "用英文"} or "in English" in q.lower():
            self.memory.add_fact("User preference: answer in English")

    def _finish(self, answer: str, steps: list[AgentStep], used: list[str], pack: str | None, evidence: str, query: str) -> AgentResult:
        safe, hits = redact_text(answer)
        if hits:
            used = used + [f"privacy_redact:{','.join(hits)}"]
        if self.enable_reflect and len(query.strip()) > 8 and query.strip() not in _FOLLOWUP_HINTS:
            refined = reflect_and_refine(self.llm, query, evidence, safe)
            if refined and refined != safe:
                safe = refined
                used = used + ["reflect"]
        safe, _ = redact_text(safe)
        self.memory.append_history("assistant", safe)
        if self.audit:
            self.audit.log("answer", pack=pack, tools=used, answer_preview=safe[:240])
        return AgentResult(answer=safe, steps=steps, used_tools=used, pack=pack)

    def chat(self, user_query: str) -> AgentResult:
        """Plain multi-turn Q&A — no kb_search / tool loop (fast default)."""
        raw_query = user_query
        user_query, q_hits = redact_text(user_query)

        if is_exfiltration_request(raw_query):
            msg = privacy_block_message()
            self.memory.append_history("user", user_query)
            self.memory.append_history("assistant", msg)
            if self.audit:
                self.audit.log("privacy_block", query=user_query[:200])
            return AgentResult(answer=msg, used_tools=["privacy_guard"], pack="security")

        prior = self.memory.recent_turns(self.history_turns)
        self._maybe_store_prefs(user_query)
        self.memory.append_history("user", user_query)
        used: list[str] = ["chat"]
        if q_hits:
            used.append(f"privacy_redact:{','.join(q_hits)}")

        messages: list[dict[str, str]] = [
            {"role": "system", "content": CHAT_SYSTEM_PROMPT},
            {
                "role": "system",
                "content": "Saved preferences/notes:\n" + self.memory.recall(limit=8),
            },
        ]
        for turn in prior:
            role = turn.get("role", "")
            content = (turn.get("content") or "").strip()
            if not content:
                continue
            if role in {"user", "assistant"}:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": user_query})

        answer = (self.llm.chat(messages, max_tokens=512) or "").strip() or "（空回复，请再试一次）"
        return self._finish(answer, [], used, None, "", user_query)

    def run(self, user_query: str) -> AgentResult:
        raw_query = user_query
        user_query, q_hits = redact_text(user_query)

        if is_exfiltration_request(raw_query):
            msg = privacy_block_message()
            self.memory.append_history("user", user_query)
            self.memory.append_history("assistant", msg)
            if self.audit:
                self.audit.log("privacy_block", query=user_query[:200])
            return AgentResult(answer=msg, used_tools=["privacy_guard"], pack="security")

        prior = self.memory.recent_turns(self.history_turns)
        search_q = self._search_query(user_query, prior)
        self._maybe_store_prefs(user_query)
        pack = detect_pack(user_query)

        self.memory.append_history("user", user_query)
        steps: list[AgentStep] = []
        used: list[str] = []
        if q_hits:
            used.append(f"privacy_redact:{','.join(q_hits)}")
        if pack:
            used.append(f"domain_pack:{pack}")

        kb = self.tools.run("kb_search", {"query": search_q})
        used.append("kb_search")
        steps.append(
            AgentStep(
                thought='{"tool":"kb_search","args":{"query":"' + search_q[:80] + '"}}',
                action={"tool": "kb_search", "args": {"query": search_q}},
                observation=kb.output,
            )
        )
        if self.audit:
            self.audit.log("kb_search", query=search_q[:200], pack=pack)

        messages: list[dict[str, str]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "system", "content": self.tools.describe()},
        ]
        pack_prompt = pack_system_prompt(pack)
        if pack_prompt:
            messages.append({"role": "system", "content": pack_prompt})
        messages.extend(
            [
                {
                    "role": "system",
                    "content": "Saved memory (facts/notes):\n" + self.memory.recall(limit=10),
                },
                {
                    "role": "system",
                    "content": "Knowledge-base evidence (ground factual answers):\n" + kb.output,
                },
            ]
        )
        for turn in prior:
            role = turn.get("role", "")
            content = (turn.get("content") or "").strip()
            if not content:
                continue
            if role == "user":
                messages.append({"role": "user", "content": content})
            elif role == "assistant":
                messages.append({"role": "assistant", "content": content})

        messages.append(
            {
                "role": "user",
                "content": (
                    f"{user_query}\n\n"
                    f"[context] retrieval_query={search_q}; history_turns={len(prior)}; pack={pack or 'none'}. "
                    "Keep continuity. Return actionable final answer as {\"final\":\"...\"}."
                ),
            }
        )

        for _ in range(self.max_steps):
            raw = self.llm.chat(messages)
            action = extract_json_action(raw) or {}
            step = AgentStep(thought=raw, action=action)

            if "final" in action:
                answer = str(action["final"]).strip()
                step.observation = "FINAL"
                steps.append(step)
                return self._finish(answer, steps, used, pack, kb.output, user_query)

            tool_name = str(action.get("tool", "")).strip()
            args = action.get("args") or {}
            if not tool_name:
                steps.append(step)
                answer = raw.strip() or "未能解析模型输出，请重试。"
                return self._finish(answer, steps, used, pack, kb.output, user_query)

            # Redact tool args that may contain secrets before execution logging
            if isinstance(args, dict):
                safe_args: dict[str, Any] = {}
                for k, v in args.items():
                    if isinstance(v, str):
                        safe_args[k], _ = redact_text(v)
                    else:
                        safe_args[k] = v
                args = safe_args

            result = self.tools.run(tool_name, args if isinstance(args, dict) else {})
            used.append(tool_name)
            step.observation = result.output
            steps.append(step)
            if self.audit:
                self.audit.log("tool", tool=tool_name)
            messages.append({"role": "assistant", "content": raw})
            messages.append(
                {
                    "role": "user",
                    "content": f"Tool `{tool_name}` result:\n{result.output}\nNow return {{\"final\":\"...\"}}.",
                }
            )

        fallback = "步骤过多，请把问题写得更具体一些。"
        return self._finish(fallback, steps, used, pack, kb.output, user_query)
