import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.llm_role import generate_character
from src.models_schema import CharacterCard


def test_mock_generate_character():
    card = generate_character(
        user_text="A boy who loves origami, Void affinity",
        affinity_pref="Void",
        mock=True,
    )
    assert isinstance(card, CharacterCard)
    assert card.primary_affinity == "Void"
    assert card.image_prompt


def test_mock_card_all_english():
    card = generate_character("Life healer girl", affinity_pref="Life", mock=True)
    for field in (
        card.name,
        card.one_liner,
        card.appearance,
        card.personality,
        card.backstory,
        card.spirit_domain,
        card.ability_showcase,
        card.image_prompt,
        card.motion_prompt,
    ):
        assert all(ord(c) < 128 for c in field), f"non-ASCII in field: {field!r}"
