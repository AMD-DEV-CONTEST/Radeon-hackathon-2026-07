"""Deterministic incident workflow with local model synthesis."""

from dataclasses import asdict
import json
from typing import List, Optional
from uuid import uuid4

from .memory import CaseMemory
from .model import ModelClient
from .retrieval import LocalRetriever
from .schemas import AgentResponse, Evidence, PlanStep, ToolResult
from .tools import DiagnosticEnvironment, ToolBroker


class RadeonSentinel:
    def __init__(
        self,
        model: ModelClient,
        retriever: LocalRetriever,
        memory: CaseMemory,
        environment: DiagnosticEnvironment,
    ) -> None:
        self.model = model
        self.retriever = retriever
        self.memory = memory
        self.environment = environment
        self.tools = ToolBroker(environment)

    def investigate(
        self,
        query: str,
        case_id: Optional[str] = None,
        request_remediation: bool = True,
        approve_remediation: bool = False,
    ) -> AgentResponse:
        query = query.strip()
        if not query:
            raise ValueError("query must not be empty")
        case_id = case_id or f"case-{uuid4().hex[:10]}"
        self.memory.record_message(case_id, "user", query)

        evidence = self.retriever.search(query, top_k=3)
        self.memory.record_event(
            case_id,
            "retrieval_completed",
            {"sources": [asdict(item) for item in evidence]},
        )

        service = self._select_service(query)
        log_query = self._select_log_query(query)
        tool_results = [
            self.tools.execute(
                "inspect_service_health", {"service": service}
            ),
            self.tools.execute(
                "search_logs",
                {"service": service, "query": log_query, "limit": 10},
            ),
        ]
        if request_remediation:
            tool_results.append(
                self.tools.execute(
                    "restart_service",
                    {"service": service},
                    approved=approve_remediation,
                )
            )
        for result in tool_results:
            self.memory.record_event(
                case_id, "tool_result", asdict(result)
            )

        summary = self._synthesize(query, evidence, tool_results, case_id)
        self.memory.record_message(case_id, "assistant", summary)
        status = (
            "needs_approval"
            if any(
                result.status == "approval_required"
                for result in tool_results
            )
            else "completed"
        )
        plan = self._build_plan(tool_results, request_remediation)
        response = AgentResponse(
            case_id=case_id,
            status=status,
            summary=summary,
            plan=plan,
            evidence=evidence,
            tool_results=tool_results,
        )
        self.memory.record_event(
            case_id,
            "investigation_completed",
            {"status": status, "service": service},
        )
        return response

    def _select_service(self, query: str) -> str:
        lowered = query.lower()
        for service in self.environment.services:
            if service.lower() in lowered:
                return service
        return next(iter(self.environment.services))

    @staticmethod
    def _select_log_query(query: str) -> str:
        lowered = query.lower()
        for term in (
            "timeout",
            "latency",
            "config",
            "dependency",
            "connection",
            "error",
        ):
            if term in lowered:
                return term
        return "error"

    def _synthesize(
        self,
        query: str,
        evidence: List[Evidence],
        tool_results: List[ToolResult],
        case_id: Optional[str] = None,
    ) -> str:
        evidence_text = "\n".join(
            f"[{item.source}] {item.excerpt}" for item in evidence
        )
        tool_text = json.dumps(
            [asdict(result) for result in tool_results],
            ensure_ascii=False,
            sort_keys=True,
        )
        messages = [
            {
                "role": "system",
                "content": (
                    "You are Radeon Sentinel, a privacy-first local incident "
                    "response assistant. Use only the supplied evidence and "
                    "tool results, plus any prior turns in this case. "
                    "State uncertainty and never claim that a "
                    "simulated remediation changed a real system."
                ),
            },
        ]
        # Inject multi-turn history so follow-up questions see prior context.
        if case_id:
            for row in self.memory.history(case_id):
                role = row.get("role", "")
                content = row.get("content", "")
                if role in ("user", "assistant") and content:
                    messages.append({"role": role, "content": content})
        messages.append(
            {
                "role": "user",
                "content": (
                    f"INCIDENT QUERY\n{query}\n\n"
                    f"RUNBOOK EVIDENCE\n{evidence_text or 'No match'}\n\n"
                    f"TOOL RESULTS\n{tool_text}\n\n"
                    "Write a concise diagnosis and next action."
                ),
            },
        )
        return self.model.generate(messages, temperature=0.1)

    @staticmethod
    def _build_plan(
        tool_results: List[ToolResult], request_remediation: bool
    ) -> List[PlanStep]:
        plan = [
            PlanStep(
                title="Retrieve local runbooks",
                status="completed",
                detail="Ranked local evidence with source citations",
            ),
            PlanStep(
                title="Inspect service health",
                status=tool_results[0].status,
                detail="Read-only allow-listed diagnostic",
            ),
            PlanStep(
                title="Search incident logs",
                status=tool_results[1].status,
                detail="Read-only search over synthetic logs",
            ),
        ]
        if request_remediation:
            remediation = tool_results[-1]
            plan.append(
                PlanStep(
                    title="Simulate remediation",
                    status=remediation.status,
                    detail=(
                        "Requires explicit human approval; never touches a "
                        "production system"
                    ),
                )
            )
        plan.append(
            PlanStep(
                title="Produce evidence-backed diagnosis",
                status="completed",
            )
        )
        return plan

    def close(self) -> None:
        self.memory.close()
