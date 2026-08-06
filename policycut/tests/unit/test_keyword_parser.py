"""Tests for the deterministic keyword policy parser (LLM disabled).

Exercised through the contract-specified surface:
    parse_policy(text, use_llm=False) -> (PolicySpec, source)
"""

from __future__ import annotations

import pytest

from policycut.policy.parser import parse_policy


def parse(text: str):
    spec, source = parse_policy(text, use_llm=False)
    return spec, source


def vcats(spec) -> set[str]:
    return {t.category for t in spec.visual_targets}


def acats(spec) -> set[str]:
    return {t.category for t in spec.audio_targets}


def vtarget(spec, category):
    for t in spec.visual_targets:
        if t.category == category:
            return t
    raise AssertionError(f"no visual target {category!r} in {vcats(spec)}")


def atarget(spec, category):
    for t in spec.audio_targets:
        if t.category == category:
            return t
    raise AssertionError(f"no audio target {category!r} in {acats(spec)}")


class TestCategories:
    def test_all_visual_and_audio_categories(self):
        spec, source = parse(
            "Blur all faces. Blur license plates. Pixelate ID cards. "
            "Pixelate screens. Mute phone numbers. Beep emails. Mute addresses."
        )
        assert source == "keyword_fallback"
        assert vcats(spec) == {"face", "license_plate", "id_document", "screen"}
        assert acats(spec) == {"phone", "email", "address"}

    def test_prompts_populated_for_visual_targets(self):
        spec, _ = parse("blur faces and license plates")
        for t in spec.visual_targets:
            assert isinstance(t.prompts, list) and len(t.prompts) > 0
            assert all(isinstance(p, str) and p for p in t.prompts)

    def test_synonyms(self):
        spec, _ = parse(
            "Blur number plates. Pixelate computer monitors. "
            "Mute telephone numbers. Beep e-mails."
        )
        assert "license_plate" in vcats(spec)
        assert "screen" in vcats(spec)
        assert "phone" in acats(spec)
        assert "email" in acats(spec)

    def test_passport_maps_to_id_document(self):
        spec, _ = parse("blur passports")
        assert "id_document" in vcats(spec)


class TestActions:
    def test_visual_actions_mapped(self):
        spec, _ = parse("Blur all faces. Pixelate screens.")
        assert vtarget(spec, "face").action.type == "blur"
        assert vtarget(spec, "screen").action.type == "pixelate"

    def test_solid_action(self):
        spec, _ = parse("Put a solid black box over faces.")
        assert vtarget(spec, "face").action.type == "solid"

    def test_audio_actions_mapped(self):
        spec, _ = parse("Mute phone numbers. Beep emails.")
        assert atarget(spec, "phone").action.type == "mute"
        assert atarget(spec, "email").action.type == "beep"

    def test_bleep_synonym_for_beep(self):
        spec, _ = parse("Bleep out phone numbers.")
        assert atarget(spec, "phone").action.type == "beep"


class TestStrength:
    def test_strength_within_bounds(self):
        spec, _ = parse("heavily blur faces")
        s = vtarget(spec, "face").action.strength
        assert 1 <= s <= 100

    def test_heavy_at_least_as_strong_as_light(self):
        light, _ = parse("lightly blur faces")
        heavy, _ = parse("heavily blur faces")
        ls = vtarget(light, "face").action.strength
        hs = vtarget(heavy, "face").action.strength
        assert 1 <= ls <= 100 and 1 <= hs <= 100
        assert hs >= ls


class TestNegation:
    def test_do_not_blur_screens(self):
        spec, _ = parse("Blur faces. Do not blur screens.")
        assert "face" in vcats(spec)
        assert "screen" not in vcats(spec)

    def test_dont_pixelate_faces_alone(self):
        spec, _ = parse("don't pixelate faces")
        assert "face" not in vcats(spec)

    def test_but_not_faces(self):
        spec, _ = parse("Blur faces, screens and license plates but not faces.")
        assert "face" not in vcats(spec)
        assert "screen" in vcats(spec)
        assert "license_plate" in vcats(spec)

    def test_except_faces(self):
        spec, _ = parse("Blur everything sensitive: screens and faces, except faces.")
        assert "face" not in vcats(spec)

    def test_no_beeping_of_emails(self):
        spec, _ = parse("Beep phone numbers. No beeping of emails.")
        assert "phone" in acats(spec)
        assert "email" not in acats(spec)


class TestUnsupportedAndEmpty:
    def test_unsupported_terms_recorded(self):
        spec, _ = parse("blur tattoos and faces")
        assert "face" in vcats(spec)
        assert any("tattoo" in term.lower() for term in spec.unsupported_terms)

    def test_unsupported_not_added_as_target(self):
        spec, _ = parse("blur tattoos")
        assert vcats(spec) == set()

    def test_empty_text(self):
        spec, source = parse("")
        assert source == "keyword_fallback"
        assert spec.visual_targets == []
        assert spec.audio_targets == []

    @pytest.mark.parametrize("text", ["   ", "\n\t"])
    def test_whitespace_only(self, text):
        spec, _ = parse(text)
        assert spec.visual_targets == []
        assert spec.audio_targets == []

    def test_spec_is_valid_pydantic_model(self):
        spec, _ = parse("blur faces")
        dumped = spec.model_dump()
        assert dumped["schema_version"] == "1.0"
        assert isinstance(dumped["visual_targets"], list)
