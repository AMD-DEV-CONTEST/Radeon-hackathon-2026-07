import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.models_schema import CharacterCard, parse_character_json
from src.world import load_world


def _sample() -> dict:
    w = load_world()
    aff = {a.name: 50 for a in w.affinities}
    aff["Void"] = 90
    return {
        "name": "Paperfold Boy",
        "one_liner": "A spirit user who folds alleys into shortcuts",
        "appearance": "Black hair, teal coat, faint rift light on fingertips",
        "personality": "Quiet and observant",
        "backstory": "Grew up on the edge of the Qingxi Rift, used space folds for courier work.",
        "primary_affinity": "Void",
        "affinities": aff,
        "spirit_domain": "A paper alley that keeps folding inward",
        "ability_showcase": "Tears open a rift with a wave and vanishes in afterimages",
        "image_prompt": "anime boy, black hair, teal coat, spatial cracks, portrait",
        "image_negative": "blurry, lowres",
        "motion_prompt": "camera slow push-in, purple rift particles swirling",
    }


def test_parse_valid():
    card = parse_character_json(json.dumps(_sample(), ensure_ascii=False))
    assert isinstance(card, CharacterCard)
    assert card.primary_affinity == "Void"
    assert card.affinities["Void"] == 90


def test_rejects_bad_affinity():
    data = _sample()
    data["primary_affinity"] = "Fire"
    with pytest.raises(Exception):
        parse_character_json(json.dumps(data, ensure_ascii=False))


def test_clamps_scores():
    data = _sample()
    data["affinities"]["Form"] = 150
    card = parse_character_json(json.dumps(data, ensure_ascii=False))
    assert card.affinities["Form"] == 100


def test_extra_english_fields_ignored():
    data = _sample()
    data["name_en"] = "Legacy Field"
    data["lore_en"] = "Legacy field should not break validation"
    card = parse_character_json(json.dumps(data, ensure_ascii=False))
    assert card.primary_affinity == "Void"


def test_all_zero_affinities_get_fallback():
    data = _sample()
    data["affinities"] = {n: 0 for n in load_world().affinity_names()}
    card = parse_character_json(json.dumps(data, ensure_ascii=False))
    assert any(v > 0 for v in card.affinities.values())
    assert card.affinities["Void"] >= 80
    # fallback values must be distinct-ish and within range
    for v in card.affinities.values():
        assert 0 < v <= 100


def test_missing_affinity_keys_get_fallback():
    data = _sample()
    data["affinities"] = {}
    card = parse_character_json(json.dumps(data, ensure_ascii=False))
    assert any(v > 0 for v in card.affinities.values())


def test_extract_json_ignores_leading_prose():
    from src.models_schema import extract_json_object

    text = (
        "Here is your character:\n"
        + json.dumps(_sample(), ensure_ascii=False)
        + "\nHope you like it!"
    )
    raw = extract_json_object(text)
    card = parse_character_json(raw)
    assert card.primary_affinity == "Void"


def test_extract_json_takes_first_complete_object():
    from src.models_schema import extract_json_object

    # truncated first object (no closing brace) then garbage; real object follows
    text = '{"name": "cut off ' + 'x' * 50 + json.dumps(_sample(), ensure_ascii=False)
    raw = extract_json_object(text)
    card = parse_character_json(raw)
    assert card.primary_affinity == "Void"


def test_nested_dict_fields_flattened():
    data = _sample()
    data["appearance"] = {"clothing": "Teal robes", "accessories": "Paper lantern"}
    data["personality"] = ["Quiet", "Observant"]
    card = parse_character_json(json.dumps(data, ensure_ascii=False))
    assert isinstance(card.appearance, str)
    assert "clothing" in card.appearance
    assert isinstance(card.personality, str)
    assert "Quiet" in card.personality
