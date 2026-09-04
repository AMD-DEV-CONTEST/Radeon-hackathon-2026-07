"""Evidence/Fact ID existence, status, case-scope, and citation-chain checks."""

from __future__ import annotations

from typing import Any

from app.schemas.verification import (
    ComponentVerifierResult,
    VerificationIssue,
    VerificationSeverity,
)

USABLE_FACT_STATUSES = {"verified", "confirmed"}
FACT_ID_PREFIXES = ("FACT-",)
EVIDENCE_ID_PREFIXES = ("NODE-", "EVID-", "SRC-")


class EvidenceCitationVerifier:
    def verify(
        self,
        *,
        state: dict[str, Any],
        evidence_export: dict[str, Any],
    ) -> ComponentVerifierResult:
        case_id = str(state["case_id"])
        sources = {str(item["source_id"]): item for item in evidence_export["sources"]}
        nodes = {
            str(item["node_id"]): item for item in evidence_export["evidence_nodes"]
        }
        facts = {str(item["fact_id"]): item for item in evidence_export["facts"]}
        valid_evidence_ids = set(sources) | set(nodes)
        fact_refs, evidence_refs = _collect_reference_ids(state)
        issues: list[VerificationIssue] = []

        for field_kind, field_name, reference_id in _collect_mistyped_ids(state):
            expected = (
                "/".join(FACT_ID_PREFIXES)
                if field_kind == "fact"
                else "/".join(EVIDENCE_ID_PREFIXES)
            )
            issues.append(
                _issue(
                    f"EVIDENCE-{field_kind.upper()}-ID-TYPE-MISMATCH",
                    (
                        f"{field_name} contains an ID of the wrong type: "
                        f"{reference_id}; expected prefix {expected}."
                    ),
                    [reference_id],
                    (
                        "Move the ID to its matching Fact/Evidence/Law field and "
                        "rerun verification."
                    ),
                )
            )

        for fact_id in sorted(fact_refs - set(facts)):
            issues.append(
                _issue(
                    "EVIDENCE-FACT-NOT-FOUND",
                    f"Referenced Fact ID does not exist in this case: {fact_id}",
                    [fact_id],
                    "Remove the reference or attach the fact to the current case.",
                )
            )
        for evidence_id in sorted(evidence_refs - valid_evidence_ids):
            issues.append(
                _issue(
                    "EVIDENCE-ID-NOT-FOUND",
                    f"Referenced Evidence ID does not exist in this case: {evidence_id}",
                    [evidence_id],
                    "Remove the reference or ingest the evidence into this case.",
                )
            )
        for fact_id in sorted(fact_refs & set(facts)):
            fact = facts[fact_id]
            if str(fact.get("case_id")) != case_id:
                issues.append(
                    _issue(
                        "EVIDENCE-CROSS-CASE-FACT",
                        f"Fact {fact_id} belongs to another case.",
                        [fact_id],
                        "Use only facts stored under the current case.",
                    )
                )
            if str(fact.get("status", "")).lower() == "rejected":
                issues.append(
                    _issue(
                        "EVIDENCE-REJECTED-FACT",
                        f"Rejected fact is referenced: {fact_id}",
                        [fact_id],
                        "Remove rejected facts from all conclusions and drafts.",
                    )
                )

        findings = {
            str(item.get("behavior_id")): item
            for item in state.get("violation_matrix", [])
            if item.get("behavior_id")
        }
        for behavior_id, finding in findings.items():
            if finding.get("status") != "confirmed":
                continue
            linked_facts = [str(value) for value in finding.get("fact_ids", [])]
            linked_evidence = [
                str(value) for value in finding.get("evidence_ids", [])
            ]
            if not linked_facts or not linked_evidence:
                issues.append(
                    _issue(
                        "EVIDENCE-BROKEN-FINDING-CHAIN",
                        f"Confirmed finding {behavior_id} lacks Fact/Evidence links.",
                        [behavior_id],
                        "Link the finding to existing facts and their source evidence.",
                    )
                )
                continue
            for fact_id in linked_facts:
                fact = facts.get(fact_id)
                if not fact:
                    continue
                status = str(fact.get("status", "")).lower()
                if status not in USABLE_FACT_STATUSES:
                    issues.append(
                        _issue(
                            "EVIDENCE-UNVERIFIED-DETERMINISM",
                            (
                                f"Confirmed finding {behavior_id} relies on "
                                f"{status or 'unknown'} fact {fact_id}."
                            ),
                            [behavior_id, fact_id],
                            "Downgrade the finding or verify the fact.",
                        )
                    )
                source_nodes = set(fact.get("source_node_ids", []))
                if not source_nodes or not source_nodes & set(linked_evidence):
                    issues.append(
                        _issue(
                            "EVIDENCE-CHAIN-DISCONNECTED",
                            (
                                f"Finding {behavior_id} -> Fact {fact_id} -> "
                                "Evidence chain is disconnected."
                            ),
                            [behavior_id, fact_id, *linked_evidence],
                            "Use evidence IDs that are actual sources of the fact.",
                        )
                    )

        for hypothesis in state.get("liability_hypotheses", []):
            for finding_id in hypothesis.get("supporting_findings", []):
                finding = findings.get(str(finding_id))
                if not finding:
                    issues.append(
                        _issue(
                            "EVIDENCE-HYPOTHESIS-FINDING-MISSING",
                            (
                                f"Liability hypothesis references unknown finding "
                                f"{finding_id}."
                            ),
                            [str(finding_id)],
                            "Reference an existing violation/causation finding.",
                        )
                    )
        return ComponentVerifierResult(
            verifier="evidence",
            passed=not issues,
            issues=issues,
            verified_ids=sorted(
                (fact_refs & set(facts)) | (evidence_refs & valid_evidence_ids)
            ),
        )


def _collect_reference_ids(value: Any) -> tuple[set[str], set[str]]:
    fact_ids: set[str] = set()
    evidence_ids: set[str] = set()

    def visit(item: Any, key: str = "") -> None:
        if isinstance(item, dict):
            for child_key, child in item.items():
                visit(child, str(child_key))
        elif isinstance(item, list):
            for child in item:
                visit(child, key)
        elif isinstance(item, str):
            lowered = key.lower()
            if ("fact_id" in lowered or item.startswith("FACT-")) and item.startswith(
                "FACT-"
            ):
                fact_ids.add(item)
            if (
                "evidence_id" in lowered
                or "source_node_id" in lowered
                or item.startswith(("NODE-", "EVID-", "SRC-"))
            ) and item.startswith(("NODE-", "EVID-", "SRC-")):
                evidence_ids.add(item)

    visit(value)
    return fact_ids, evidence_ids


def _collect_mistyped_ids(value: Any) -> list[tuple[str, str, str]]:
    """Return IDs placed in Fact/Evidence fields with incompatible prefixes."""

    mismatches: set[tuple[str, str, str]] = set()

    def visit(item: Any, key: str = "") -> None:
        if isinstance(item, dict):
            for child_key, child in item.items():
                visit(child, str(child_key))
        elif isinstance(item, list):
            for child in item:
                visit(child, key)
        elif isinstance(item, str):
            lowered = key.lower()
            if "fact_id" in lowered and not item.startswith(FACT_ID_PREFIXES):
                mismatches.add(("fact", key, item))
            if (
                "evidence_id" in lowered or "source_node_id" in lowered
            ) and not item.startswith(EVIDENCE_ID_PREFIXES):
                mismatches.add(("evidence", key, item))

    visit(value)
    return sorted(mismatches)


def _issue(
    code: str,
    message: str,
    related_ids: list[str],
    required_action: str,
) -> VerificationIssue:
    return VerificationIssue(
        code=code,
        message=message,
        severity=VerificationSeverity.BLOCKING,
        related_ids=related_ids,
        required_action=required_action,
    )
