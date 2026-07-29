from __future__ import annotations

import uuid

from .llm import LocalLLM
from .models import AgentPlan, EvidenceHit, ExecutionResult, PlanStep, SensitiveFinding
from .rag import search
from .store import Store
from .tools import redact_text, scan_sensitive


class RedactFlowAgent:
    def __init__(self, store: Store):
        self.store = store
        self.llm = LocalLLM()

    def create_plan(self, task: str) -> AgentPlan:
        plan = AgentPlan(
            id=f"plan_{uuid.uuid4().hex[:12]}",
            task=task,
            steps=[
                PlanStep(
                    id="retrieve",
                    title="Retrieve grounded evidence",
                    tool="local_rag_search",
                    description="Search only the local document vault for task-relevant passages.",
                    permission="read",
                ),
                PlanStep(
                    id="inspect",
                    title="Inspect sensitive content",
                    tool="sensitive_data_scan",
                    description="Detect emails, phone numbers, identity numbers, API keys, and IP addresses.",
                    permission="read",
                ),
                PlanStep(
                    id="redact",
                    title="Prepare safe release copies",
                    tool="redact_documents",
                    description="Replace detected values while preserving the source documents.",
                    permission="transform",
                    requires_approval=True,
                ),
                PlanStep(
                    id="remember",
                    title="Store an auditable decision memory",
                    tool="write_audit_memory",
                    description="Persist only summary metadata and counts to local SQLite.",
                    permission="write",
                    requires_approval=True,
                ),
            ],
        )
        self.store.put_plan(plan.id, plan.model_dump())
        self.store.remember("plan_created", {"plan_id": plan.id, "task": task})
        return plan

    def execute(self, plan_id: str, approved_tools: set[str]) -> ExecutionResult:
        payload = self.store.get_plan(plan_id)
        if not payload:
            raise KeyError(plan_id)
        plan = AgentPlan.model_validate(payload)
        blocked = [
            step.tool
            for step in plan.steps
            if step.requires_approval and step.tool not in approved_tools
        ]
        documents = self.store.list_documents()
        evidence = [EvidenceHit.model_validate(hit) for hit in search(plan.task, documents)]
        all_findings: list[SensitiveFinding] = []
        per_document: dict[str, list[dict]] = {}
        for document in documents:
            findings = scan_sensitive(document["content"])
            per_document[document["id"]] = findings
            all_findings.extend(SensitiveFinding.model_validate(item) for item in findings)

        if blocked:
            return ExecutionResult(
                plan_id=plan_id,
                status="blocked",
                summary="Execution paused before any transformative or persistent action.",
                findings=all_findings,
                evidence=evidence,
                redacted_documents={},
                blocked_tools=blocked,
            )

        redacted_documents = {
            document["name"]: redact_text(document["content"], per_document[document["id"]])
            for document in documents
        }
        self.store.remember(
            "release_review",
            {
                "plan_id": plan_id,
                "task": plan.task,
                "documents": len(documents),
                "findings": len(all_findings),
                "evidence_hits": len(evidence),
            },
        )
        model_note = self.llm.complete(
            "You are a local privacy review agent. Summarize the evidence without inventing facts.",
            f"Task: {plan.task}\nEvidence: {[hit.excerpt for hit in evidence]}",
        )
        summary = model_note or (
            f"Reviewed {len(documents)} local document(s), found {len(all_findings)} sensitive value(s), "
            f"and prepared {len(redacted_documents)} release-safe copy/copies."
        )
        return ExecutionResult(
            plan_id=plan_id,
            status="completed",
            summary=summary,
            findings=all_findings,
            evidence=evidence,
            redacted_documents=redacted_documents,
        )

