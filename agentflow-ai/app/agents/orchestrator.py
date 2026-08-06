from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, UTC
from time import perf_counter
from typing import Any, Iterator

from app.agents.memory import MemoryAgent
from app.agents.planner import PlannerAgent
from app.agents.research import ResearchAgent
from app.agents.reviewer import ReviewerAgent
from app.agents.tool import ToolAgent
from app.schemas import AgentResponse, PlanResult
from app.services.ollama_client import OllamaClient
from app.services.storage import SQLiteStorage


DRAFT_SYSTEM = """You are the synthesis engine inside AgentFlow AI, an autonomous multi-agent workflow platform.
You are not a generic chatbot.
Use the provided plan, local research snippets, memory context, and tool outputs to answer like an expert project operator.
Structure the answer with these sections when useful:
1. Outcome
2. Evidence / local knowledge
3. Tools executed
4. Risks or assumptions
5. Next steps
"""


@dataclass(slots=True)
class TimelineRecorder:
    entries: list[dict[str, Any]]

    @contextmanager
    def span(self, agent: str) -> Iterator[dict[str, Any]]:
        started_at_dt = datetime.now(UTC)
        started_at = started_at_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        started = perf_counter()
        payload: dict[str, Any] = {}
        try:
            yield payload
            status = payload.get("status", "completed")
        except Exception as exc:
            payload["summary"] = payload.get("summary", f"{agent} failed: {exc}")
            payload["status"] = "error"
            status = "error"
            raise
        finally:
            duration_ms = int((perf_counter() - started) * 1000)
            finished_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            self.entries.append(
                {
                    "agent": agent,
                    "status": status,
                    "started_at": started_at,
                    "finished_at": finished_at,
                    "duration_ms": duration_ms,
                    "summary": payload.get("summary", f"{agent} completed."),
                    "metadata": payload.get("metadata", {}),
                }
            )


class AgentOrchestrator:
    def __init__(
        self,
        *,
        storage: SQLiteStorage,
        ollama: OllamaClient,
        planner: PlannerAgent,
        research: ResearchAgent,
        memory: MemoryAgent,
        tools: ToolAgent,
        reviewer: ReviewerAgent,
    ) -> None:
        self.storage = storage
        self.ollama = ollama
        self.planner = planner
        self.research = research
        self.memory = memory
        self.tools = tools
        self.reviewer = reviewer

    def run(
        self,
        *,
        conversation_id: str | None,
        user_message: str,
        document_ids: list[str],
        requested_model: str | None,
    ) -> AgentResponse:
        overall_started = perf_counter()
        timeline: list[dict[str, Any]] = []
        recorder = TimelineRecorder(timeline)

        conversation = self.storage.create_or_get_conversation(conversation_id, user_message)
        self.storage.add_message(conversation["id"], "user", user_message)

        ollama_status = self.ollama.health()
        system_alert = None if ollama_status.running else ollama_status.message

        with recorder.span("Planner Agent") as span:
            plan, planner_model, planner_error = self.planner.run(user_message, requested_model=requested_model)
            if planner_error:
                span["summary"] = f"Planner used fallback decomposition because Ollama was unavailable: {planner_error}"
                span["status"] = "degraded"
            else:
                span["summary"] = f"Planner produced {len(plan.tasks)} executable tasks."
            span["metadata"] = {"tasks": plan.tasks, "tools": plan.tools}

        with recorder.span("Research Agent") as span:
            research = self.research.run(user_message, document_ids=document_ids)
            citations = research["citations"]
            if citations:
                span["summary"] = f"Research retrieved {len(citations)} grounded local evidence snippets from ChromaDB."
            else:
                span["summary"] = "Research found no matching uploaded evidence, so the response relies on conversation context and local tools."
            span["metadata"] = {"documents_consulted": [citation["filename"] for citation in citations]}

        with recorder.span("Memory Agent") as span:
            memory = self.memory.run(conversation["id"], user_message)
            span["summary"] = (
                f"Memory recalled {len(memory['recent_context'])} recent turns and {len(memory['memory_context'])} persistent notes."
            )
            span["metadata"] = {
                "recent_turns": len(memory["recent_context"]),
                "persistent_memories": len(memory["memory_context"]),
            }

        with recorder.span("Tool Agent") as span:
            tool_runs = self.tools.run(user_message, plan.tools)
            if tool_runs:
                span["summary"] = f"Tool Agent executed {len(tool_runs)} local tool(s)."
            else:
                span["summary"] = "Tool Agent determined no extra tool execution was required."
            span["metadata"] = {"tools": [tool["name"] for tool in tool_runs]}

        with recorder.span("Reviewer Agent") as span:
            draft = self._compose_draft(
                user_message=user_message,
                plan=plan,
                research=research,
                memory=memory,
                tool_runs=tool_runs,
                requested_model=requested_model,
            )
            final_response, reviewer_model, reviewer_error = self.reviewer.run(draft, requested_model=requested_model)
            if reviewer_error:
                span["summary"] = f"Reviewer preserved the synthesis draft because LLM polishing was unavailable: {reviewer_error}"
                span["status"] = "degraded"
            else:
                span["summary"] = "Reviewer refined the final response for completeness and clarity."
            span["metadata"] = {"model": reviewer_model or planner_model or ollama_status.selected_model}

        total_duration_ms = int((perf_counter() - overall_started) * 1000)
        active_model = reviewer_model or planner_model or ollama_status.selected_model
        benchmark = {
            "duration_ms": total_duration_ms,
            "documents_used": len(research["citations"]),
            "tools_used": len(tool_runs),
            "memory_items": len(memory["memory_context"]),
            "approx_prompt_chars": len(user_message),
            "approx_response_chars": len(final_response),
        }

        assistant_message_id = self.storage.add_message(
            conversation["id"],
            "assistant",
            final_response,
            model=active_model,
            plan=plan.model_dump(),
            timeline=timeline,
            citations=research["citations"],
            tools=tool_runs,
            benchmark=benchmark,
        )
        self.memory.remember(conversation["id"], user_message, final_response)
        self.storage.add_benchmark(
            conversation_id=conversation["id"],
            model=active_model,
            duration_ms=total_duration_ms,
            tools_used=len(tool_runs),
            citations_used=len(research["citations"]),
            success=True,
            metadata={"tool_names": [tool["name"] for tool in tool_runs]},
        )

        return AgentResponse(
            conversation_id=conversation["id"],
            message_id=assistant_message_id,
            model=active_model,
            response=final_response,
            planner=plan,
            citations=research["citations"],
            tools=tool_runs,
            timeline=timeline,
            benchmark=benchmark,
            system_alert=system_alert,
            agent_status={
                "ollama_running": ollama_status.running,
                "available_models": ollama_status.available_models,
                "selected_model": active_model,
                "preferred_models": list(self.ollama.config.preferred_models),
            },
        )

    def _compose_draft(
        self,
        *,
        user_message: str,
        plan: PlanResult,
        research: dict[str, Any],
        memory: dict[str, Any],
        tool_runs: list[dict[str, str]],
        requested_model: str | None,
    ) -> str:
        tool_section = "\n".join(
            f"- {tool['name']}: {tool['output']}" for tool in tool_runs
        ) or "No tools executed."
        prompt = f"""
User request:
{user_message}

Planner output:
Goal: {plan.goal}
Tasks: {plan.tasks}
Tools: {plan.tools}
Risks: {plan.risks}
Success criteria: {plan.success_criteria}

Research findings:
{research['summary']}

Memory context:
Recent turns: {memory['recent_context']}
Persistent memories: {memory['memory_context']}

Tool outputs:
{tool_section}
""".strip()
        try:
            response = self.ollama.generate_text(
                prompt=prompt,
                system=DRAFT_SYSTEM,
                requested_model=requested_model,
                temperature=0.2,
            )
            return response["content"]
        except Exception:
            return self._fallback_response(
                user_message=user_message,
                plan=plan,
                research=research,
                memory=memory,
                tool_runs=tool_runs,
            )

    @staticmethod
    def _fallback_response(
        *,
        user_message: str,
        plan: PlanResult,
        research: dict[str, Any],
        memory: dict[str, Any],
        tool_runs: list[dict[str, str]],
    ) -> str:
        tool_lines = "\n".join(f"- {tool['name']}: {tool['output']}" for tool in tool_runs) or "- No tools executed"
        evidence = research["summary"]
        memories = "\n".join(f"- {item}" for item in memory["memory_context"][:3]) or "- No persistent memory matches"
        return (
            f"Outcome\n{user_message}\n\n"
            f"Execution plan\n- Goal: {plan.goal}\n"
            + "\n".join(f"- {task}" for task in plan.tasks)
            + "\n\nEvidence / local knowledge\n"
            + evidence
            + "\n\nRecalled memory\n"
            + memories
            + "\n\nTools executed\n"
            + tool_lines
            + "\n\nNext steps\n- Start Ollama and install one of the preferred models for higher-quality reasoning.\n- Upload relevant PDFs or notes to strengthen local RAG results."
        )
