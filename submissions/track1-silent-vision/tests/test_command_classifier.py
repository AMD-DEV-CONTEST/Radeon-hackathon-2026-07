import numpy as np
import pytest
from pydantic import ValidationError

from agent.agent import AgentPolicy
from backend.config import Settings
from backend.schemas import CommandDecision
from command.inference import build_command_classifier, reject_by_thresholds
from command.labels import CommandIntent
from command.prototype import save_prototype_sample


def test_threshold_and_margin_accept_strong_light_on():
    decision = reject_by_thresholds(
        intent=CommandIntent.LIGHT_ON,
        confidence=0.92,
        second_confidence=0.51,
        threshold=0.85,
        top1_margin=0.20,
        logits=[0.1, 4.0, 0.3, 0.2, 0.1],
    )

    assert decision.accepted is True
    assert decision.intent == CommandIntent.LIGHT_ON
    assert decision.margin == 0.41


def test_threshold_rejects_low_confidence_without_accepting_tools():
    decision = reject_by_thresholds(
        intent=CommandIntent.LIGHT_ON,
        confidence=0.60,
        second_confidence=0.52,
        threshold=0.85,
        top1_margin=0.20,
        logits=[0.1, 2.0, 1.8, 0.2, 0.1],
    )

    assert decision.accepted is False
    assert decision.intent == CommandIntent.UNKNOWN
    assert decision.reason == "below confidence threshold"


def test_command_decision_schema_serializes_logits_and_metadata():
    decision = CommandDecision(
        intent=CommandIntent.CHAT_OTHER,
        accepted=True,
        executable=False,
        confidence=0.91,
        margin=0.33,
        topK=[{"intent": "CHAT_OTHER", "confidence": 0.91}],
        logits=[0.0, 0.1, 0.2],
        reason="accepted non-executable intent",
        metadata={"frames": 75},
    )

    dumped = decision.model_dump()
    assert dumped["intent"] == "CHAT_OTHER"
    assert dumped["logits"] == [0.0, 0.1, 0.2]
    assert dumped["metadata"]["frames"] == 75


def test_agent_result_uses_display_text_and_language_from_command_metadata():
    decision = CommandDecision(
        intent=CommandIntent.LIGHT_ON,
        accepted=True,
        executable=True,
        confidence=0.99,
        margin=0.9,
        topK=[],
        logits={},
        reason="accepted",
        metadata={
            "language": "zh",
            "displayText": "你好，请帮我打开灯",
            "matchedPhrase": "你好，请帮我打开灯",
        },
    )

    result = AgentPolicy(threshold=0.55).decide_command(decision)

    assert result.action == "execute"
    assert result.language == "zh"
    assert result.text == "你好，请帮我打开灯"


def test_builds_prototype_backend(tmp_path, monkeypatch):
    monkeypatch.setenv("PERSISTENCE_ROOT", str(tmp_path))
    monkeypatch.setenv("COMMAND_BACKEND", "prototype")

    backend = build_command_classifier(Settings())

    assert backend.__class__.__name__ == "PrototypeCommandClassifierBackend"


def test_fake_backend_rejects_an_invalid_selected_language():
    # Catches a regression that lets callers bypass the common language contract.
    backend = build_command_classifier(Settings(command_backend="fake"))
    frames = np.zeros((2, 96, 96), dtype=np.uint8)

    with pytest.raises(ValueError, match="recognition language"):
        backend.predict(frames, "unknown", {})


def test_settings_support_only_new_checkpoint_driven_torch_backend(tmp_path):
    checkpoint = tmp_path / "fixed-phrase.pt"

    settings = Settings(
        persistence_root=tmp_path,
        command_backend="torch",
        command_classifier_checkpoint=checkpoint,
        command_phrase_probability_override=0.90,
        command_phrase_distance_override=0.10,
    )

    assert settings.command_backend == "torch"
    assert settings.command_classifier_checkpoint == checkpoint
    assert settings.command_phrase_probability_override == 0.90
    assert settings.command_phrase_distance_override == 0.10


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("command_phrase_probability_override", -0.01),
        ("command_phrase_probability_override", 1.01),
        ("command_phrase_distance_override", -0.01),
        ("command_phrase_distance_override", 1.01),
    ],
)
def test_settings_reject_out_of_range_torch_threshold_overrides(field, value):
    with pytest.raises(ValidationError, match=field):
        Settings(**{field: value})


def test_prototype_backend_returns_matched_display_text_and_language(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("PERSISTENCE_ROOT", str(tmp_path))
    monkeypatch.setenv("COMMAND_BACKEND", "prototype")

    frames = np.zeros((25, 96, 96), dtype=np.uint8)
    frames[:, 36:60, 32:64] = 255
    save_prototype_sample(
        tmp_path,
        profile_id="global",
        intent=CommandIntent.LIGHT_ON.value,
        mouth_frames=frames,
        metadata={"language": "zh", "phrase": "你好，请帮我打开灯"},
    )

    backend = build_command_classifier(Settings())
    decision = backend.predict(frames, language="zh", metadata={"profileId": "abc"})

    assert decision.accepted is True
    assert decision.intent == CommandIntent.LIGHT_ON
    assert decision.metadata["displayText"] == "你好，请帮我打开灯"
    assert decision.metadata["language"] == "zh"
    assert decision.metadata["matchedPhrase"] == "你好，请帮我打开灯"


def test_prototype_backend_uses_global_samples_even_when_profile_id_is_present(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("PERSISTENCE_ROOT", str(tmp_path))
    monkeypatch.setenv("COMMAND_BACKEND", "prototype")

    frames = np.zeros((25, 96, 96), dtype=np.uint8)
    frames[:, 36:60, 32:64] = 255
    save_prototype_sample(
        tmp_path,
        profile_id="abc",
        intent=CommandIntent.LIGHT_OFF.value,
        mouth_frames=frames,
        metadata={"language": "zh", "phrase": "请关灯"},
    )
    save_prototype_sample(
        tmp_path,
        profile_id="global",
        intent=CommandIntent.LIGHT_ON.value,
        mouth_frames=frames,
        metadata={"language": "zh", "phrase": "请开灯"},
    )

    backend = build_command_classifier(Settings())
    decision = backend.predict(frames, language="zh", metadata={"profileId": "abc"})

    assert decision.accepted is True
    assert decision.intent == CommandIntent.LIGHT_ON
    assert decision.metadata["profileId"] == "global"
    assert decision.metadata["profileScope"] == "global"
    assert decision.metadata["displayText"] == "请开灯"


def test_prototype_backend_matches_only_samples_for_the_selected_language(
    tmp_path, monkeypatch
):
    # Catches a regression that lets an equal-scoring English sample create a
    # cross-language margin rejection for a Chinese request.
    monkeypatch.setenv("PERSISTENCE_ROOT", str(tmp_path))
    monkeypatch.setenv("COMMAND_BACKEND", "prototype")

    frames = np.zeros((25, 96, 96), dtype=np.uint8)
    frames[:, 36:60, 32:64] = 255
    save_prototype_sample(
        tmp_path,
        profile_id="global",
        intent=CommandIntent.LIGHT_OFF.value,
        mouth_frames=frames,
        metadata={"language": "en", "phrase": "Turn off the light."},
    )
    save_prototype_sample(
        tmp_path,
        profile_id="global",
        intent=CommandIntent.LIGHT_ON.value,
        mouth_frames=frames,
        metadata={"language": "zh", "phrase": "请开灯"},
    )

    backend = build_command_classifier(Settings())
    decision = backend.predict(frames, language="zh", metadata={})

    assert decision.accepted is True
    assert decision.intent == CommandIntent.LIGHT_ON
    assert decision.metadata["matchedPhrase"] == "请开灯"


def test_prototype_backend_rejects_without_samples(tmp_path, monkeypatch):
    monkeypatch.setenv("PERSISTENCE_ROOT", str(tmp_path))
    monkeypatch.setenv("COMMAND_BACKEND", "prototype")

    backend = build_command_classifier(Settings())
    frames = np.zeros((25, 96, 96), dtype=np.uint8)
    decision = backend.predict(frames, language="zh", metadata={"profileId": "abc"})

    assert decision.intent == "UNKNOWN"
    assert decision.accepted is False
    assert decision.reason == "no_prototypes"
