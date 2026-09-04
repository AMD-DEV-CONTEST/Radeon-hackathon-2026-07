import dataclasses

import pytest

from policyseal.domain.enums import Action, Classification, ContentCategory, RevisionStatus
from policyseal.domain.errors import InvalidDecisionError
from policyseal.domain.models import DisclosureContext, PolicyDecision, SourceFingerprint


def test_context_is_immutable_and_uses_controlled_values() -> None:
    context = DisclosureContext.supplier_bidder_corporate_email()

    assert context.classification is Classification.CONFIDENTIAL
    with pytest.raises(dataclasses.FrozenInstanceError):
        context.channel = "personal_email"  # type: ignore[misc]


def test_all_p0_actions_and_statuses_are_frozen() -> None:
    assert {item.value for item in Action} == {
        "keep",
        "mask",
        "remove",
        "filter",
        "generalize",
        "require_approval",
        "block",
    }
    assert len(RevisionStatus) == 9


def test_source_fingerprint_is_stable() -> None:
    assert SourceFingerprint.from_bytes(b"synthetic").sha256 == (
        "b3cc0475bb78a5026098858e9889acf666d31062d513d303314eca31d36e72f2"
    )


def test_decision_requires_rule_evidence() -> None:
    with pytest.raises(InvalidDecisionError):
        PolicyDecision(
            region_id="xlsx:sheet1:A1",
            category=ContentCategory.GENERAL_BUSINESS,
            action=Action.KEEP,
            rule_ids=(),
            evidence_ids=("EV-GEN-003",),
            reason_code="controlled_purpose",
            reason="Allowed for the controlled purpose.",
            policy_version="1.0.0",
            policy_sha256="a" * 64,
        )
