import math
from contextlib import nullcontext
from types import SimpleNamespace

import numpy as np
import pytest

from backend.config import Settings
from command.catalog import PhraseCatalog, catalog_sha256
from command.dataset import MANIFEST_ROLES
from command.inference import (
    ThresholdResolution,
    TorchCommandClassifierBackend,
    build_command_classifier,
    evaluate_phrase_rejection,
    resolve_thresholds,
)
from command.language import score_language_candidates, validate_recognition_language


def test_language_scores_rank_and_normalize_only_selected_language_candidates():
    # Catches a regression that scores all classes before language selection, allowing
    # the excluded English class at index 0 to suppress Chinese recognition.
    scores = score_language_candidates(
        np.array([100.0, 1.0, 2.0, 0.0]),
        ["en", "zh", "zh", "en"],
        "zh",
    )

    assert scores.eligible_indices == (1, 2)
    assert scores.ranked_indices == (2, 1)
    assert scores.probabilities[2] > scores.probabilities[1]
    assert sum(scores.probabilities.values()) == pytest.approx(1.0)
    assert 0 not in scores.ranked_indices
    assert 0 not in scores.probabilities


@pytest.mark.parametrize("language", [None, "unknown", "fr", ["zh"]])
def test_language_validation_rejects_missing_unknown_and_unsupported_values(language):
    # Catches a regression that silently defaults malformed language selection.
    with pytest.raises(ValueError):
        validate_recognition_language(language)


@pytest.mark.parametrize("language", [None, "unknown"])
def test_torch_backend_rejects_invalid_language_before_model_execution(
    mouth_clip, language
):
    # Catches a regression that validates after tensor allocation and model inference.
    class Tensor:
        def unsqueeze(self, dimension):
            return self

        def to(self, device):
            return self

    class Torch:
        def from_numpy(self, frames):
            return Tensor()

        def inference_mode(self):
            return nullcontext()

    model_calls = []

    def model(tensor):
        model_calls.append(tensor)
        raise AssertionError("model must not run for invalid language")

    backend = object.__new__(TorchCommandClassifierBackend)
    backend.torch = Torch()
    backend.device = "cpu"
    backend.loaded_checkpoint = SimpleNamespace(model=model)

    with pytest.raises(ValueError, match="recognition language"):
        backend.predict(mouth_clip, language, {})

    assert model_calls == []


@pytest.fixture
def mouth_clip():
    clip = np.zeros((12, 96, 96), dtype=np.uint8)
    clip[:, 32:64, 24:72] = np.arange(12, dtype=np.uint8)[:, None, None] * 10
    return clip


@pytest.fixture
def backend_factory(tmp_path, monkeypatch, mouth_clip):
    torch = pytest.importorskip("torch")
    from command.checkpoint import save_phrase_checkpoint
    from command.model import build_fixed_phrase_model, normalize_clip_length

    def build(
        *,
        reject_by_distance=False,
        classifier_bias=(100.0, 1.0, 3.0, 0.0),
        top1_margin=0.20,
    ):
        model = build_fixed_phrase_model(4).eval()
        with torch.no_grad():
            model.classifier.weight.zero_()
            model.classifier.bias.copy_(torch.tensor(classifier_bias))
            normalized_clip = normalize_clip_length(torch.from_numpy(mouth_clip))
            _, embedding = model(normalized_clip.unsqueeze(0))
        first_centroid = -embedding if reject_by_distance else embedding
        checkpoint = tmp_path / f"phrase-{reject_by_distance}.pt"
        phrase_catalog = [
            {
                "phraseId": "en_light_on_hello",
                "text": "Hello, please turn on the light.",
                "language": "en",
                "intent": "LIGHT_ON",
                "enabled": True,
            },
            {
                "phraseId": "zh_chat_meal",
                "text": "你吃饭了吗？",
                "language": "zh",
                "intent": "CHAT_OTHER",
                "enabled": True,
            },
            {
                "phraseId": "zh_light_on_hello",
                "text": "你好，请帮我打开灯",
                "language": "zh",
                "intent": "LIGHT_ON",
                "enabled": True,
            },
            {
                "phraseId": "en_chat_meal",
                "text": "Have you eaten?",
                "language": "en",
                "intent": "CHAT_OTHER",
                "enabled": True,
            },
        ]
        save_phrase_checkpoint(
            checkpoint,
            {
                "schemaVersion": "silent-vision.fixed-phrase.v2",
                "modelState": model.state_dict(),
                "phraseIds": [
                    "en_light_on_hello",
                    "zh_chat_meal",
                    "zh_light_on_hello",
                    "en_chat_meal",
                ],
                "phraseCatalog": phrase_catalog,
                "featureConfig": {
                    "fps": 25,
                    "frames": 125,
                    "height": 96,
                    "width": 96,
                    "downsample": 16,
                },
                "modelConfig": {"embeddingDim": 64, "parameterCap": 150000},
                "decisionPolicy": {
                    "languageSelectionRequired": True,
                    "probabilityNormalization": "selected-language-softmax",
                },
                "decisionThresholds": {
                    "minProbability": 0.80,
                    "maxCosineDistance": {
                        "en_light_on_hello": 0.05,
                        "zh_light_on_hello": 0.05,
                        "zh_chat_meal": 0.05,
                        "en_chat_meal": 0.05,
                    },
                },
                "classCentroids": torch.cat(
                    [-embedding, -embedding, first_centroid, -embedding], dim=0
                ),
                "evidenceLineage": {
                    "inventorySha256": "a" * 64,
                    "catalogSha256": catalog_sha256(
                        PhraseCatalog.from_records(phrase_catalog)
                    ),
                    "seed": 17,
                    "manifestSha256": {
                        role: str(index) * 64
                        for index, role in enumerate(MANIFEST_ROLES, start=1)
                    },
                    "evidentiary": False,
                },
                "trainingSummary": {
                    "seed": 17,
                    "evidentiary": False,
                    "torchVersion": str(torch.__version__),
                    "hipVersion": str(torch.version.hip)
                    if torch.version.hip is not None
                    else None,
                    "device": "cpu",
                    "deviceName": "synthetic CPU test fixture",
                },
            },
        )
        monkeypatch.setattr(
            "command.inference.require_rocm", lambda torch_module: "cpu"
        )
        return TorchCommandClassifierBackend(
            Settings(
                command_backend="torch",
                command_classifier_checkpoint=checkpoint,
                command_top1_margin=top1_margin,
            )
        )

    return build


def test_accepted_decision_uses_exact_catalog_phrase_and_phrase_top_k(
    backend_factory, mouth_clip
):
    decision = backend_factory().predict(mouth_clip, "zh", {})

    assert decision.accepted is True
    assert decision.executable is True
    assert decision.intent == "LIGHT_ON"
    assert decision.metadata["phraseId"] == "zh_light_on_hello"
    assert decision.metadata["matchedPhrase"] == "你好，请帮我打开灯"
    assert decision.metadata["displayText"] == "你好，请帮我打开灯"
    assert decision.metadata["language"] == "zh"
    assert decision.metadata["selectedLanguage"] == "zh"
    assert decision.metadata["eligiblePhraseIds"] == [
        "zh_chat_meal",
        "zh_light_on_hello",
    ]
    assert decision.metadata["backend"] == "torch"
    assert decision.metadata["thresholdSource"] == "checkpoint"
    assert decision.topK[0] == {
        "phraseId": "zh_light_on_hello",
        "text": "你好，请帮我打开灯",
        "language": "zh",
        "intent": "LIGHT_ON",
        "confidence": pytest.approx(decision.confidence),
    }
    assert [item["phraseId"] for item in decision.topK] == [
        "zh_light_on_hello",
        "zh_chat_meal",
    ]


def test_top1_margin_is_diagnostic_only(backend_factory, mouth_clip):
    decision = backend_factory(
        classifier_bias=(100.0, 1.0, 3.0, 0.0), top1_margin=0.99
    ).predict(mouth_clip, "zh", {})

    assert decision.margin < 0.99
    assert decision.accepted is True


def test_rejected_decision_is_unknown_and_omits_matched_phrase_text(
    backend_factory, mouth_clip
):
    decision = backend_factory(reject_by_distance=True).predict(
        mouth_clip,
        "zh",
        {
            "phraseId": "stale-id",
            "matchedPhrase": "stale matched text",
            "displayText": "stale display text",
            "language": "en",
        },
    )

    assert decision.accepted is False
    assert decision.executable is False
    assert decision.intent == "UNKNOWN"
    assert decision.reason == "embedding_distance"
    assert "phraseId" not in decision.metadata
    assert "matchedPhrase" not in decision.metadata
    assert "displayText" not in decision.metadata
    assert all("text" not in item for item in decision.topK)
    assert decision.metadata["predictedPhraseId"] == "zh_light_on_hello"
    assert decision.metadata["probability"] == pytest.approx(decision.confidence)
    assert decision.metadata["openSetDistance"] == pytest.approx(2.0)
    assert decision.metadata["thresholdSource"] == "checkpoint"
    assert decision.metadata["rejectionReason"] == "embedding_distance"
    assert decision.metadata["selectedLanguage"] == "zh"
    assert decision.metadata["eligiblePhraseIds"] == [
        "zh_chat_meal",
        "zh_light_on_hello",
    ]


def test_torch_builder_propagates_rocm_guard_failure(tmp_path, monkeypatch):
    torch = pytest.importorskip("torch")
    checkpoint = tmp_path / "phrase.pt"
    checkpoint.write_bytes(b"not loaded because the guard fails first")

    def fail_guard(torch_module):
        assert torch_module is torch
        raise RuntimeError("guard sentinel")

    monkeypatch.setattr("command.inference.require_rocm", fail_guard)

    with pytest.raises(RuntimeError, match="guard sentinel"):
        build_command_classifier(
            Settings(command_backend="torch", command_classifier_checkpoint=checkpoint)
        )


def test_both_probability_and_distance_must_pass():
    thresholds = ThresholdResolution(0.80, {"a": 0.20}, "checkpoint")

    assert evaluate_phrase_rejection(0.90, 0.10, "a", thresholds) == (True, None)
    assert evaluate_phrase_rejection(0.70, 0.10, "a", thresholds) == (
        False,
        "low_probability",
    )
    assert evaluate_phrase_rejection(0.90, 0.30, "a", thresholds) == (
        False,
        "embedding_distance",
    )


@pytest.mark.parametrize(
    ("probability", "distance"),
    [(math.nan, 0.1), (math.inf, 0.1), (0.99, math.nan), (0.99, math.inf)],
)
def test_non_finite_runtime_scores_fail_closed(probability, distance):
    # In particular, a passing probability cannot turn NaN cosine distance into
    # zero and bypass UNKNOWN rejection.
    thresholds = ThresholdResolution(0.80, {"a": 0.20}, "checkpoint")

    assert evaluate_phrase_rejection(probability, distance, "a", thresholds) == (
        False,
        "non_finite_score",
    )


@pytest.mark.parametrize(
    ("probability_override", "distance_override", "source"),
    [
        (None, None, "checkpoint"),
        (0.90, None, "override:probability"),
        (None, 0.10, "override:distance"),
        (0.90, 0.10, "override:probability,distance"),
    ],
)
def test_threshold_source_is_auditable(probability_override, distance_override, source):
    resolved = resolve_thresholds(
        {"minProbability": 0.80, "maxCosineDistance": {"a": 0.20, "b": 0.30}},
        probability_override=probability_override,
        distance_override=distance_override,
    )

    assert resolved.min_probability == (
        0.80 if probability_override is None else probability_override
    )
    expected_distance = (
        {"a": 0.20, "b": 0.30}
        if distance_override is None
        else {"a": distance_override, "b": distance_override}
    )
    assert resolved.max_cosine_distance == expected_distance
    assert resolved.source == source


@pytest.mark.parametrize(
    ("probability_override", "distance_override"),
    [
        (-0.01, None),
        (1.01, None),
        (math.nan, None),
        (None, -0.01),
        (None, 1.01),
        (None, math.inf),
    ],
)
def test_threshold_overrides_must_be_finite_unit_interval(
    probability_override, distance_override
):
    with pytest.raises(ValueError, match="override must be between 0 and 1"):
        resolve_thresholds(
            {"minProbability": 0.80, "maxCosineDistance": {"a": 0.20}},
            probability_override=probability_override,
            distance_override=distance_override,
        )
