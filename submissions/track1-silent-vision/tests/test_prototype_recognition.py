import numpy as np

from command.labels import CommandIntent
from command.prototype import (
    PrototypeSample,
    extract_roi_embedding,
    load_profile_prototypes,
    match_prototypes,
    save_prototype_sample,
)


def test_extract_roi_embedding_is_unit_normalized_and_deterministic():
    frames = np.zeros((10, 96, 96), dtype=np.uint8)
    frames[3:7, 32:64, 32:64] = 255

    first = extract_roi_embedding(frames, feature_dim=128)
    second = extract_roi_embedding(frames, feature_dim=128)

    assert first.shape == (128,)
    assert np.allclose(first, second)
    assert abs(float(np.linalg.norm(first)) - 1.0) < 1e-5


def test_save_and_load_profile_prototype(tmp_path):
    frames = np.ones((8, 96, 96), dtype=np.uint8) * 120

    path = save_prototype_sample(
        tmp_path,
        profile_id="global",
        intent=CommandIntent.LIGHT_ON.value,
        mouth_frames=frames,
        metadata={"language": "zh", "phrase": "请开灯"},
    )

    samples = load_profile_prototypes(tmp_path, "global")

    assert path.exists()
    assert len(samples) == 1
    assert samples[0].profile_id == "global"
    assert samples[0].intent == CommandIntent.LIGHT_ON.value
    assert samples[0].metadata["phrase"] == "请开灯"


def sample(intent: str, vector: np.ndarray, metadata: dict | None = None) -> PrototypeSample:
    return PrototypeSample(
        profile_id="global",
        intent=intent,
        embedding=vector.astype(np.float32),
        sample_path=None,
        metadata=metadata or {},
    )


def test_match_prototypes_accepts_clear_top1():
    query = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    samples = [
        sample("LIGHT_ON", np.array([1.0, 0.0, 0.0])),
        sample("LIGHT_OFF", np.array([0.0, 1.0, 0.0])),
    ]

    match = match_prototypes(query, samples, confidence_threshold=0.8, margin_threshold=0.2)

    assert match.accepted is True
    assert match.intent == "LIGHT_ON"
    assert match.reason == "accepted"


def test_match_prototypes_returns_matched_phrase_metadata():
    query = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    samples = [
        sample(
            "LIGHT_ON",
            np.array([1.0, 0.0, 0.0]),
            metadata={"phrase": "你好，请帮我打开灯", "language": "zh"},
        ),
        sample(
            "LIGHT_OFF",
            np.array([0.0, 1.0, 0.0]),
            metadata={"phrase": "please turn off the light", "language": "en"},
        ),
    ]

    match = match_prototypes(query, samples, confidence_threshold=0.8, margin_threshold=0.2)

    assert match.accepted is True
    assert match.intent == "LIGHT_ON"
    assert match.matched_metadata["phrase"] == "你好，请帮我打开灯"
    assert match.matched_metadata["language"] == "zh"


def test_match_prototypes_rejects_close_margin():
    query = np.array([1.0, 0.0], dtype=np.float32)
    samples = [
        sample("LIGHT_ON", np.array([1.0, 0.0])),
        sample("LIGHT_OFF", np.array([0.98, 0.2])),
    ]

    match = match_prototypes(query, samples, confidence_threshold=0.5, margin_threshold=0.2)

    assert match.accepted is False
    assert match.intent == "UNKNOWN"
    assert match.reason == "margin_below_threshold"
