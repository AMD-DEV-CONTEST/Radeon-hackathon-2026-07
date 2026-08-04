from __future__ import annotations

from pathlib import Path

from policyseal.application.matrix import (
    build_xlsx_matrix,
    default_xlsx_contexts,
    evaluate_xlsx,
)
from policyseal.documents.xlsx import XlsxAdapter
from policyseal.domain.enums import RevisionStatus
from policyseal.evals.assets import load_eval_assets
from policyseal.policy.schema import PolicyPack


def test_four_recipient_matrix_has_three_outputs_and_one_block(
    xlsx_adapter: XlsxAdapter,
    policy_pack: PolicyPack,
    hero_xlsx: Path,
) -> None:
    parsed = xlsx_adapter.parse(hero_xlsx)

    matrix = build_xlsx_matrix(parsed, policy_pack, default_xlsx_contexts())

    assert tuple(cell.status for cell in matrix.cells) == (
        RevisionStatus.EXPORTABLE,
        RevisionStatus.EXPORTABLE,
        RevisionStatus.EXPORTABLE,
        RevisionStatus.BLOCKED,
    )
    assert matrix.cells[3].action_counts == (("block", len(parsed.regions)),)


def test_hero_matrix_matches_independent_golden_actions(
    xlsx_adapter: XlsxAdapter,
    policy_pack: PolicyPack,
    hero_xlsx: Path,
) -> None:
    parsed = xlsx_adapter.parse(hero_xlsx)
    contexts = default_xlsx_contexts()
    decisions_by_location = []
    region_locations = {region.id: region.location for region in parsed.regions}
    for context in contexts[:3]:
        decisions = evaluate_xlsx(parsed, policy_pack, context)
        decisions_by_location.append(
            {region_locations[decision.region_id]: decision for decision in decisions}
        )
    scenarios = {item.id: item for item in load_eval_assets().scenarios}

    for matrix_index, scenario_id in enumerate(("scenario-01", "scenario-02", "scenario-03")):
        actual = decisions_by_location[matrix_index]
        for expected in scenarios[scenario_id].decisions:
            decision = actual[expected.location]
            assert decision.action is expected.action
            assert decision.rule_ids == expected.rule_ids
            assert decision.transform == (
                expected.transform.value if expected.transform is not None else None
            )
            assert set(decision.evidence_ids).issuperset(expected.evidence_ids)
