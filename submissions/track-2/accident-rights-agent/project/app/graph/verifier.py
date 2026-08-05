"""Composable fail-closed verification and final Policy Gate."""

from __future__ import annotations

from datetime import date
from typing import Any

from app.evidence.workspace import CaseWorkspace
from app.rag.corpus import LegalCorpusStore
from app.rules.repository import RuleRepository
from app.schemas.verification import PolicyGateDecision, RiskAction
from app.verifier.consistency import ConsistencyVerifier
from app.verifier.evidence import EvidenceCitationVerifier
from app.verifier.legal import LegalCitationVerifier
from app.verifier.policy_gate import FinalPolicyGate
from app.verifier.risk_language import RiskLanguagePolicy


class CaseVerifier:
    """Compatibility facade over the stage-specific verifier components."""

    def __init__(
        self,
        workspace: CaseWorkspace,
        corpus: LegalCorpusStore,
        *,
        as_of: date | None = None,
        rules: RuleRepository | None = None,
    ):
        self.workspace = workspace
        self.corpus = corpus
        self.as_of = as_of or date.today()
        self.rules = rules or RuleRepository()

    def verify(self, state: dict[str, Any]) -> dict[str, Any]:
        case_id = state["case_id"]
        exported = self.workspace.store(case_id).export_case(case_id)
        evidence = EvidenceCitationVerifier().verify(
            state=state,
            evidence_export=exported,
        )
        legal = LegalCitationVerifier(self.corpus, self.rules).verify(
            state=state,
            as_of_date=self.as_of,
            jurisdiction=str(state.get("jurisdiction", "CN")),
        )
        consistency = ConsistencyVerifier().verify(
            state=state,
            evidence_export=exported,
        )
        risk = RiskLanguagePolicy().scan(state)
        gate = FinalPolicyGate().evaluate(
            evidence=evidence,
            legal=legal,
            consistency=consistency,
            risk_language=risk,
            protected_fields_valid=bool(state.get("protected_fields_valid")),
            approval_state=str(state.get("approval_status", "pending")),
        )
        checks: dict[str, dict[str, Any]] = {
            "evidence_ids": {
                "passed": evidence.passed,
                "errors": [
                    item.model_dump(mode="json") for item in evidence.issues
                ],
            },
            "fact_ids": {
                "passed": not any(
                    "FACT" in item.code or "CHAIN" in item.code
                    for item in evidence.issues
                ),
                "errors": [
                    item.model_dump(mode="json")
                    for item in evidence.issues
                    if "FACT" in item.code or "CHAIN" in item.code
                ],
            },
            "legal_citations": {
                "passed": legal.passed,
                "errors": [item.model_dump(mode="json") for item in legal.issues],
                "count": len(legal.verified_ids),
            },
            "vehicle_compensation_consistency": {
                "passed": not any(
                    item.code == "CONSISTENCY-VEHICLE-COMPENSATION"
                    for item in consistency.issues
                ),
            },
            "fact_compatibility": {
                "passed": consistency.passed and evidence.passed,
                "errors": [
                    item.model_dump(mode="json")
                    for item in [*consistency.issues, *evidence.issues]
                ],
            },
            "no_unsupported_determinism": {
                "passed": not any(
                    item.action is RiskAction.HARD_BLOCK for item in risk.matches
                ),
                "markers": [
                    item.matched_text for item in risk.matches
                ],
            },
            "protected_fields": {
                "passed": bool(state.get("protected_fields_valid")),
                "error": (
                    ""
                    if state.get("protected_fields_valid")
                    else "No successful protected-field context audit."
                ),
            },
            "policy_gate": {
                "passed": gate.decision is not PolicyGateDecision.BLOCK,
                "decision": gate.decision.value,
            },
        }
        blocking_reasons = [
            name for name, result in checks.items() if not result["passed"]
        ]
        return {
            "passed": gate.decision is not PolicyGateDecision.BLOCK,
            "checks": checks,
            "blocking_reasons": blocking_reasons,
            "components": {
                "evidence": evidence.model_dump(mode="json"),
                "legal": legal.model_dump(mode="json"),
                "consistency": consistency.model_dump(mode="json"),
                "risk_language": risk.model_dump(mode="json"),
            },
            "policy_gate": gate.model_dump(mode="json"),
        }
