from __future__ import annotations

import re

from .database import Database
from .llm import LocalModelRouter, validate_citation_labels
from .retrieval import HybridRetriever
from .schemas import AgentStep, ChatAnswer, Citation, RetrievalHit
from .tools import ToolRegistry
from .utils import new_id


class StrategyAgent:
    def __init__(self, database: Database, retriever: HybridRetriever, models: LocalModelRouter):
        self.database = database
        self.retriever = retriever
        self.models = models
        self.tools = ToolRegistry(database, retriever)

    def ask(self, question: str, session_id: str | None = None) -> ChatAnswer:
        question = question.strip()
        if not question:
            raise ValueError("question must not be empty")
        session_id = session_id or new_id("session")
        history = self.database.recent_messages(session_id)
        self.database.add_message(session_id, "user", question)

        intent = self._intent(question)
        steps = [
            AgentStep(name="Understand request", tool="intent_router", status="completed", detail=intent),
            AgentStep(name="Use local tool", tool=self._tool_for_intent(intent), status="running"),
            AgentStep(name="Ground answer", tool="citation_validator", status="planned"),
            AgentStep(name="Update memory", tool="conversation_memory", status="planned"),
        ]

        if intent == "remember":
            answer, citations, backend = self._remember(question)
        elif intent == "compare_cost":
            answer, citations, backend = self._compare_costs(question)
        elif intent in {"list", "cost_filter", "license_filter", "risk_filter"}:
            answer, citations, backend = self._list(question, intent)
        else:
            effective_question = self._with_followup_context(question, history)
            hits = self.tools.call("search_knowledge", query=effective_question, limit=8)
            answer, backend = self.models.answer(question, hits, history)
            answer = validate_citation_labels(answer, len(hits))
            referenced = {int(value) for value in re.findall(r"\[S(\d+)\]", answer)}
            if hits and not referenced:
                suffix = "来源：[S1]" if re.search(r"[\u4e00-\u9fff]", question) else "Source: [S1]"
                answer = f"{answer}\n\n{suffix}"
                referenced = {1}
            citations = [
                citation
                for index, citation in enumerate(self._citations(hits), 1)
                if index in referenced
            ]

        steps[1].status = "completed"
        steps[2].status = "completed"
        steps[3].status = "completed"
        self.database.add_message(
            session_id,
            "assistant",
            answer,
            [citation.model_dump() for citation in citations],
        )
        return ChatAnswer(
            session_id=session_id,
            answer=answer,
            citations=citations,
            steps=steps,
            backend=backend,
        )

    @staticmethod
    def _intent(question: str) -> str:
        lower = question.lower()
        if any(term in lower for term in ("记住", "remember", "以后只", "preference")):
            return "remember"
        cost_related = any(
            term in lower for term in ("交易成本", "手续费", "滑点", "transaction cost", "commission", "slippage")
        )
        comparison = any(term in lower for term in ("比较", "对比", "compare", "difference"))
        if cost_related and comparison:
            return "compare_cost"
        if cost_related and any(
            term in lower for term in ("哪些", "哪个", "which", "list", "show")
        ):
            return "cost_filter"
        if re.search(r"\b(?:mit|apache(?:-2\.0)?|bsd(?:-3-clause)?)\b", lower) and any(
            term in lower for term in ("哪些", "哪个", "which", "list", "show", "许可", "license")
        ):
            return "license_filter"
        if any(term in lower for term in ("风险", "risk flag", "risk_flags")) and any(
            term in lower for term in ("哪些", "哪个", "which", "list", "show")
        ):
            return "risk_filter"
        if any(term in lower for term in ("有哪些策略", "列出策略", "list strategies", "show strategies", "all strategies")):
            return "list"
        if any(term in lower for term in ("比较", "对比", "compare", "difference")):
            return "compare"
        if any(term in lower for term in ("来源", "出处", "source", "origin")):
            return "source_lookup"
        return "research"

    @staticmethod
    def _tool_for_intent(intent: str) -> str:
        return {
            "remember": "save_preference",
            "list": "list_strategy_cards",
            "compare_cost": "list_strategy_cards",
            "cost_filter": "list_strategy_cards",
            "license_filter": "list_strategy_cards",
            "risk_filter": "list_strategy_cards",
            "compare": "search_knowledge",
            "source_lookup": "search_knowledge",
        }.get(intent, "search_knowledge")

    def _remember(self, question: str) -> tuple[str, list[Citation], str]:
        value: dict[str, str] = {"instruction": question}
        if re.search(r"\bmit\b", question, re.I):
            value["license"] = "MIT"
        elif re.search(r"apache(?:-2\.0)?", question, re.I):
            value["license"] = "Apache-2.0"
        self.tools.call("save_preference", key="research_filter", value=value)
        chinese = bool(re.search(r"[\u4e00-\u9fff]", question))
        answer = "已将这项研究偏好保存在本地。" if chinese else "That research preference is now stored locally."
        return answer, [], "deterministic-tool"

    def _compare_costs(self, question: str) -> tuple[str, list[Citation], str]:
        cards = self.tools.call("list_strategy_cards", limit=50, offset=0)
        lower = question.lower()
        requested_types = []
        if any(term in lower for term in ("均值回归", "mean reversion")):
            requested_types.append("mean reversion")
        if any(term in lower for term in ("趋势", "动量", "trend", "momentum")):
            requested_types.append("momentum")
        if any(term in lower for term in ("配对", "pairs", "pair trading")):
            requested_types.append("pairs trading")
        if requested_types:
            cards = [card for card in cards if card.get("strategy_type") in requested_types]

        chinese = bool(re.search(r"[\u4e00-\u9fff]", question))
        if not cards:
            message = "没有足够的策略卡可用于成本披露比较。" if chinese else (
                "There are not enough strategy cards to compare cost disclosures."
            )
            return message, [], "deterministic-tool"

        lines = []
        citations = []
        for index, card in enumerate(cards, 1):
            status = card.get("cost_disclosure", "unknown")
            if chinese:
                status_text = {
                    "disclosed": "已披露手续费或滑点假设",
                    "not_disclosed": "来源明确显示未披露交易成本",
                }.get(status, "证据不足，状态未知")
            else:
                status_text = {
                    "disclosed": "discloses commission, fees, or slippage assumptions",
                    "not_disclosed": "the source explicitly leaves transaction costs undisclosed",
                }.get(status, "has insufficient evidence for a cost-disclosure status")
            lines.append(f"{index}. {card['title']}: {status_text} [S{index}]")
            citations.append(
                Citation(
                    label=f"S{index}",
                    title=card["title"],
                    url=card["immutable_url"],
                    quote=card.get("summary", "")[:240],
                )
            )
        intro = "按来源证据比较交易成本披露：" if chinese else "Source-grounded cost disclosure comparison:"
        return f"{intro}\n\n" + "\n".join(lines), citations, "deterministic-tool"

    def _list(self, question: str, intent: str = "list") -> tuple[str, list[Citation], str]:
        cards = self.tools.call("list_strategy_cards", limit=50, offset=0)
        chinese = bool(re.search(r"[\u4e00-\u9fff]", question))
        if intent == "cost_filter":
            wants_missing = bool(re.search(r"未披露|没有|missing|not disclose", question, re.I))
            expected = "not_disclosed" if wants_missing else "disclosed"
            cards = [card for card in cards if card.get("cost_disclosure") == expected]
        elif intent == "license_filter":
            match = re.search(r"\b(mit|apache(?:-2\.0)?|bsd(?:-3-clause)?)\b", question, re.I)
            if match:
                token = match.group(1).lower()
                if token.startswith("apache"):
                    requested = "apache-2.0"
                elif token.startswith("bsd"):
                    requested = "bsd-3-clause"
                else:
                    requested = token
                cards = [card for card in cards if card.get("license_spdx", "").lower() == requested]
        elif intent == "risk_filter":
            cards = [card for card in cards if card.get("risk_flags")]
        if not cards:
            return (
                "没有找到符合这些条件且有来源证据的策略。"
                if chinese
                else "No strategy with source evidence matches those conditions.",
                [],
                "deterministic-tool",
            )
        lines = []
        citations = []
        for index, card in enumerate(cards[:12], 1):
            markets = ", ".join(card.get("markets") or []) or "unknown"
            lines.append(
                f"{index}. {card['title']} | {card.get('strategy_type', 'unknown')} | "
                f"{markets} | {card.get('license_spdx', 'NOASSERTION')} [S{index}]"
            )
            citations.append(
                Citation(
                    label=f"S{index}",
                    title=card["title"],
                    url=card["immutable_url"],
                    quote=card.get("summary", "")[:240],
                )
            )
        intro = "符合条件的策略：" if chinese and intent != "list" else (
            "当前收录的策略：" if chinese else (
                "Matching strategies:" if intent != "list" else "Strategies currently indexed:"
            )
        )
        return f"{intro}\n\n" + "\n".join(lines), citations, "deterministic-tool"

    @staticmethod
    def _with_followup_context(question: str, history: list[dict]) -> str:
        if not re.search(r"它们|这些|上述|those|them|these", question, re.I):
            return question
        prior = next((item["content"] for item in reversed(history) if item.get("role") == "user"), "")
        return f"{prior}\n{question}" if prior else question

    @staticmethod
    def _citations(hits: list[RetrievalHit]) -> list[Citation]:
        citations = []
        for index, hit in enumerate(hits, 1):
            url = hit.immutable_url
            if "github.com/" in url and "/blob/" in url:
                url = f"{url.split('#', 1)[0]}#L{hit.start_line}-L{hit.end_line}"
            citations.append(
                Citation(
                    label=f"S{index}",
                    title=hit.card_title or "Source excerpt",
                    url=url,
                    quote=re.sub(r"\s+", " ", hit.text).strip()[:300],
                    line_start=hit.start_line,
                    line_end=hit.end_line,
                )
            )
        return citations
