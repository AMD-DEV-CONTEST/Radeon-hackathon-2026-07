"""Bridge the immutable Evidence Graph into four-layer case memory."""

from __future__ import annotations

from app.evidence.workspace import CaseWorkspace
from app.memory.store import CaseMemoryStore
from app.schemas.memory import CaseCapsule, MemoryFactStatus


def bootstrap_case_memory(
    workspace: CaseWorkspace, case_id: str
) -> tuple[CaseMemoryStore, CaseCapsule]:
    evidence_store = workspace.store(case_id)
    memory = CaseMemoryStore(evidence_store.path, case_id)
    memory.initialize()
    facts = evidence_store.list_facts(case_id)
    for fact in facts:
        initial = {
            "verified": MemoryFactStatus.CONFIRMED,
            "disputed": MemoryFactStatus.DISPUTED,
        }.get(str(fact.get("status")), MemoryFactStatus.UNVERIFIED)
        memory.register_fact(fact["fact_id"], status=initial)
    existing = memory.latest_capsule()
    if existing:
        return memory, existing
    conflicts = evidence_store.export_case(case_id)["conflicts"]
    disputed_ids = {
        fact_id for conflict in conflicts for fact_id in conflict["fact_ids"]
    }
    capsule = CaseCapsule(
        confirmed_facts=[fact for fact in facts if fact.get("status") == "verified"],
        disputed_facts=[fact for fact in facts if fact["fact_id"] in disputed_ids],
        missing_evidence=[],
        vehicle_classification={
            "classification": "insufficient_evidence",
            "confidence": 0.0,
        },
        liability_hypotheses=[],
        legal_issues=[
            "车辆法律属性",
            "事故责任与赔偿路径应分别判断",
        ],
        rights_deadlines=[],
        next_actions=[],
        citations=[],
        last_updated_by="memory_bootstrap",
        version=1,
    )
    memory.save_capsule(capsule)
    return memory, capsule
