from nexus.world.context import extract_context
from nexus.world.temporal import infer_time_of_day


def test_infers_night_from_explicit_context():
    context = extract_context(
        "A pine forest beneath the night sky and stars."
    )

    result = infer_time_of_day(context)

    assert result.value == "night"
    assert "night" in result.evidence
    assert result.confidence > 0.35


def test_infers_dawn_from_sunrise():
    context = extract_context(
        "The settlement wakes at dawn as the sun rises."
    )

    result = infer_time_of_day(context)

    assert result.value == "dawn"
    assert "dawn" in result.evidence


def test_infers_dusk_from_evening():
    context = extract_context(
        "The coastal village becomes quiet during the evening."
    )

    result = infer_time_of_day(context)

    assert result.value == "dusk"


def test_defaults_to_day_without_temporal_evidence():
    context = extract_context(
        "A temperate forest containing pine trees and stone paths."
    )

    result = infer_time_of_day(context)

    assert result.value == "day"
    assert result.confidence == 0.35
    assert result.evidence == []


def test_infers_dusk_from_setting_sun_phrase():
    context = extract_context(
        "The travellers watched the setting sun disappear behind the mountains."
    )

    result = infer_time_of_day(context)

    assert result.value == "dusk"
    assert "setting sun" in result.evidence


def test_infers_dusk_from_last_light_phrase():
    context = extract_context(
        "The last light vanished behind the distant peaks."
    )

    result = infer_time_of_day(context)

    assert result.value == "dusk"


def test_infers_dawn_from_first_light_phrase():
    context = extract_context(
        "At first light the travellers entered the forest."
    )

    result = infer_time_of_day(context)

    assert result.value == "dawn"


def test_infers_night_from_contextual_phrase():
    context = extract_context(
        "The village was silent under the stars."
    )

    result = infer_time_of_day(context)

    assert result.value == "night"