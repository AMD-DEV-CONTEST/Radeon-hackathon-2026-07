from __future__ import annotations

import pytest

from app.memory.service import bootstrap_case_memory
from app.schemas.memory import MemoryFactStatus


def test_memory_is_append_only_and_fact_transitions_are_valid(demo_case):
    workspace, case_id = demo_case
    original = workspace.store(case_id).export_case(case_id)
    memory, capsule = bootstrap_case_memory(workspace, case_id)
    transition = memory.transition_fact(
        "FACT-TEST-001",
        MemoryFactStatus.DISPUTED,
        actor="human_reviewer",
        reason="人工指出送达回证与正文日期存在冲突",
    )
    assert transition.from_status is MemoryFactStatus.CONFIRMED
    assert memory.fact_status("FACT-TEST-001") is MemoryFactStatus.DISPUTED
    assert [event.version for event in memory.list_events()] == sorted(
        event.version for event in memory.list_events()
    )
    assert capsule.version == 1
    assert len(capsule.confirmed_facts) == 5
    assert workspace.store(case_id).export_case(case_id)["facts"] == original["facts"]

    with pytest.raises(ValueError, match="Illegal fact transition"):
        memory.transition_fact(
            "FACT-TEST-001",
            MemoryFactStatus.UNVERIFIED,
            actor="human_reviewer",
            reason="不允许回退覆盖历史",
        )
