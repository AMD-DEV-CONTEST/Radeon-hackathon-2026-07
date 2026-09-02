import pytest

from radeon_home.language import DEFAULT_INSTRUCTION, parse_instruction
from radeon_home.models import ActionType


def test_combined_household_instruction() -> None:
    plan = parse_instruction(DEFAULT_INSTRUCTION)
    assert [step.object_id for step in plan.steps] == ["trash", "keys", "medicine"]
    assert plan.steps[2].action is ActionType.PLACE_NEAR
    assert plan.steps[2].reference_id == "cup"
    assert plan.steps[2].constraints[0].object_id == "cup"


def test_english_instruction() -> None:
    plan = parse_instruction(
        "Put the trash in the bin and the keys on the tray. "
        "Keep the medicine near the cup; do not touch the cup."
    )
    assert len(plan.steps) == 3


def test_unsupported_instruction_is_explicit() -> None:
    with pytest.raises(ValueError, match="No supported household task"):
        parse_instruction("turn on the light")

