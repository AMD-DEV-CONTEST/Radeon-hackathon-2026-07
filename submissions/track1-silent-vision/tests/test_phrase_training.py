from __future__ import annotations

import json
import subprocess
import sys
from contextlib import nullcontext
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from command.training import (
    CalibrationRecord,
    ManifestDataset,
    _calibration_records,
    calibrate_thresholds,
    compute_class_centroids,
    require_rocm,
    train_phrase_classifier,
)


class _FakeScalar:
    def __init__(self, value):
        self.value = float(value)

    def clamp(self, lower, upper):
        return _FakeScalar(min(upper, max(lower, self.value)))

    def __rsub__(self, other):
        return _FakeScalar(float(other) - self.value)

    def item(self):
        return self.value


class _FakeVector:
    def __init__(self, values):
        self.values = list(values)

    def __getitem__(self, index):
        return _FakeScalar(self.values[index])

    def detach(self):
        return self

    def cpu(self):
        return self

    def tolist(self):
        return list(self.values)

    def dot(self, other):
        return _FakeScalar(
            sum(left * right for left, right in zip(self.values, other.values))
        )


class _FakeMatrix:
    def __init__(self, rows):
        self.rows = [list(row) for row in rows]
        self.shape = (len(self.rows), len(self.rows[0]))

    def __getitem__(self, index):
        return _FakeVector(self.rows[index])

    def max(self, dim):
        assert dim == 1
        return (
            _FakeVector([max(row) for row in self.rows]),
            _FakeVector([row.index(max(row)) for row in self.rows]),
        )


class _FakeFrames:
    shape = (1, 96, 96)

    def to(self, device):
        return self


class _FakeModel:
    def eval(self):
        return None

    def __call__(self, input_frames):
        return (
            _FakeMatrix([[100.0, 1.0, 2.0, 0.0]]),
            _FakeMatrix([[1.0, 0.0]]),
        )


def test_calibration_scores_only_the_manifest_selected_language():
    # Catches a regression that calibrates against all classes, allowing the
    # excluded English class with logit 100 to become the prediction.
    frames = _FakeFrames()
    labels = _FakeVector([2])
    dataset = SimpleNamespace(records=[{"language": "zh"}])
    model = _FakeModel()
    fake_torch = SimpleNamespace(
        utils=SimpleNamespace(
            data=SimpleNamespace(DataLoader=lambda *args, **kwargs: [(frames, labels)])
        ),
        no_grad=lambda: nullcontext(),
    )

    records = _calibration_records(
        fake_torch,
        model,
        dataset,
        _FakeMatrix([[1.0, 0.0]] * 4),
        ("en_light_on", "zh_chat", "zh_light_on", "en_chat"),
        ("en", "zh", "zh", "en"),
        "cpu",
    )

    assert records[0].predicted_phrase_id == "zh_light_on"


def test_manifest_dataset_rejects_npy_modified_after_manifest_creation(tmp_path):
    clip = tmp_path / "clip.npy"
    np.save(clip, np.full((2, 96, 96), 1, dtype=np.uint8))
    original_digest = sha256(clip.read_bytes()).hexdigest()
    manifest = tmp_path / "train.jsonl"
    manifest.write_text(
        json.dumps(
            {"phrase_id": "a", "mouth_roi_npy": str(clip), "sha256": original_digest}
        )
        + "\n",
        encoding="utf-8",
    )
    np.save(clip, np.full((2, 96, 96), 2, dtype=np.uint8))

    with pytest.raises(ValueError, match="mouth ROI SHA-256"):
        ManifestDataset(manifest, {"a": 0})


def test_manifest_dataset_requires_per_sample_sha256(tmp_path):
    clip = tmp_path / "clip.npy"
    np.save(clip, np.full((2, 96, 96), 1, dtype=np.uint8))
    manifest = tmp_path / "train.jsonl"
    manifest.write_text(
        json.dumps({"phrase_id": "a", "mouth_roi_npy": str(clip)}) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="requires sha256"):
        ManifestDataset(manifest, {"a": 0})


def test_calibration_uses_known_radius_and_limits_unknown_false_accepts():
    known = [
        CalibrationRecord("a", "a", 0.92, 0.08),
        CalibrationRecord("a", "a", 0.88, 0.10),
        CalibrationRecord("b", "b", 0.91, 0.07),
        CalibrationRecord("b", "b", 0.86, 0.11),
    ]
    unknown = [
        CalibrationRecord(None, "a", 0.81, 0.09),
        CalibrationRecord(None, "b", 0.55, 0.30),
    ]

    result = calibrate_thresholds(known, unknown, ("a", "b"))

    assert result["maxCosineDistance"] == {"a": 0.10, "b": 0.11}
    assert result["minProbability"] >= 0.82
    assert result["calibrationUnknownFalseAcceptRate"] == 0.0
    assert result["calibrationTargetMet"] is True


def test_calibration_uses_highest_probability_threshold_when_known_acceptance_ties():
    known = [CalibrationRecord("a", "a", 0.90, 0.10)]
    unknown = [CalibrationRecord(None, "a", 0.49, 0.05)]

    result = calibrate_thresholds(known, unknown, ("a",))

    assert result["minProbability"] == 0.90
    assert result["calibrationKnownCorrectAcceptedCount"] == 1


def test_calibration_without_unknown_clips_uses_non_evidentiary_default():
    known = [CalibrationRecord("a", "a", 0.92, 0.10)]

    result = calibrate_thresholds(known, [], ("a",))

    assert result["minProbability"] == 0.85
    assert result["calibrationTargetMet"] is False
    assert result["evidentiary"] is False


def test_official_calibration_rejects_a_class_without_correct_known_record():
    known = [CalibrationRecord("a", "b", 0.92, 0.10)]

    with pytest.raises(
        ValueError, match="no correctly classified known-calibration record"
    ):
        calibrate_thresholds(known, [], ("a", "b"))


def test_smoke_calibration_uses_training_distance_fallback_and_records_it():
    training = [
        CalibrationRecord("a", "a", 1.0, 0.10),
        CalibrationRecord("a", "a", 1.0, 0.20),
    ]

    result = calibrate_thresholds(
        [],
        [CalibrationRecord(None, "a", 0.60, 0.15)],
        ("a",),
        evidentiary=False,
        training_records=training,
    )

    assert result["maxCosineDistance"]["a"] == pytest.approx(0.195)
    assert result["radiusFallbackPhraseIds"] == ["a"]
    assert result["evidentiary"] is False


def test_rocm_guard_does_not_accept_cuda_without_hip():
    fake = SimpleNamespace(
        version=SimpleNamespace(hip=None),
        cuda=SimpleNamespace(is_available=lambda: True, device_count=lambda: 1),
    )
    with pytest.raises(RuntimeError, match="ROCm/HIP"):
        require_rocm(fake)


def test_rocm_guard_requires_an_available_device():
    fake = SimpleNamespace(
        version=SimpleNamespace(hip="6.3"),
        cuda=SimpleNamespace(is_available=lambda: False, device_count=lambda: 0),
    )
    with pytest.raises(RuntimeError, match="cuda:0"):
        require_rocm(fake)


def test_rocm_guard_accepts_hip_cuda_zero():
    fake = SimpleNamespace(
        version=SimpleNamespace(hip="6.3"),
        cuda=SimpleNamespace(is_available=lambda: True, device_count=lambda: 1),
    )
    assert require_rocm(fake) == "cuda:0"


def test_accelerator_provenance_records_rocm_runtime_details():
    from command import training

    fake = SimpleNamespace(
        __version__="2.7.1+rocm6.3",
        version=SimpleNamespace(hip="6.3"),
        cuda=SimpleNamespace(get_device_name=lambda index: f"AMD Radeon {index}"),
    )

    assert training.accelerator_provenance(fake, "cuda:0") == {
        "torchVersion": "2.7.1+rocm6.3",
        "hipVersion": "6.3",
        "device": "cuda:0",
        "deviceName": "AMD Radeon 0",
    }


def test_training_checks_rocm_before_reading_catalog_or_samples(monkeypatch, tmp_path):
    fake = SimpleNamespace(
        version=SimpleNamespace(hip=None),
        cuda=SimpleNamespace(is_available=lambda: True, device_count=lambda: 1),
    )
    monkeypatch.setitem(sys.modules, "torch", fake)

    with pytest.raises(RuntimeError, match="ROCm/HIP"):
        train_phrase_classifier(
            catalog_path=tmp_path / "missing-catalog.json",
            inventory_path=tmp_path / "missing-inventory.json",
            train_manifest=tmp_path / "missing-train.jsonl",
            calibration_known_manifest=tmp_path / "missing-known.jsonl",
            calibration_unknown_manifest=tmp_path / "missing-unknown.jsonl",
            evaluation_known_manifest=tmp_path / "missing-evaluation-known.jsonl",
            evaluation_unknown_manifest=tmp_path / "missing-evaluation-unknown.jsonl",
            output_path=tmp_path / "model.pt",
            run_summary_path=tmp_path / "run.json",
            epochs=80,
            seed=17,
        )


def test_training_cli_help_runs_without_torch():
    project_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            "python3",
            str(project_root / "scripts/train_command_classifier.py"),
            "--help",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "--calibration-known" in result.stdout
    assert "--calibration-unknown" in result.stdout
    assert "--evaluation-known" in result.stdout
    assert "--evaluation-unknown" in result.stdout
    assert "--run-summary" in result.stdout


def test_centroids_are_class_means_normalized():
    torch = pytest.importorskip("torch")
    embeddings = torch.tensor([[1.0, 0.0], [0.8, 0.2], [0.0, 1.0]])

    centroids = compute_class_centroids(embeddings, torch.tensor([0, 0, 1]), 2)

    assert centroids.shape == (2, 2)
    assert torch.allclose(centroids.norm(dim=1), torch.ones(2))


def test_centroids_reject_a_class_without_training_embeddings():
    torch = pytest.importorskip("torch")

    with pytest.raises(ValueError, match="class 1"):
        compute_class_centroids(torch.tensor([[1.0, 0.0]]), torch.tensor([0]), 2)


def test_manifest_dataset_loads_only_listed_npy_and_normalizes_fixed_clip_length(
    tmp_path,
):
    torch = pytest.importorskip("torch")
    from command.training import pad_clip_batch

    first = tmp_path / "first.npy"
    second = tmp_path / "second.npy"
    unlisted = tmp_path / "unlisted.npy"
    np.save(first, np.full((2, 96, 96), 1, dtype=np.uint8))
    np.save(second, np.full((3, 96, 96), 2, dtype=np.uint8))
    np.save(unlisted, np.full((4, 96, 96), 9, dtype=np.uint8))
    manifest = tmp_path / "train.jsonl"
    manifest.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "phrase_id": "a",
                        "mouth_roi_npy": str(first),
                        "sha256": sha256(first.read_bytes()).hexdigest(),
                    }
                ),
                json.dumps(
                    {
                        "phrase_id": "b",
                        "mouth_roi_npy": str(second),
                        "sha256": sha256(second.read_bytes()).hexdigest(),
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    dataset = ManifestDataset(manifest, {"a": 0, "b": 1})
    frames, labels = pad_clip_batch([dataset[0], dataset[1]])

    assert frames.shape == (2, 125, 96, 96)
    assert labels.tolist() == [0, 1]
    assert torch.equal(frames[0, -1], frames[0, -2])


def test_clip_logits_and_embeddings_do_not_depend_on_longer_batch_peer():
    # Catches batch-maximum padding changing a short clip's temporal input and
    # therefore its calibrated logits and embedding.
    torch = pytest.importorskip("torch")
    from command.model import build_fixed_phrase_model
    from command.training import pad_clip_batch

    torch.manual_seed(17)
    model = build_fixed_phrase_model(4).eval()
    short = (
        torch.arange(3 * 96 * 96, dtype=torch.float32).reshape(3, 96, 96) % 256
    )
    longer = torch.flip(
        torch.arange(7 * 96 * 96, dtype=torch.float32).reshape(7, 96, 96) % 256,
        dims=(0,),
    )
    alone, _ = pad_clip_batch([(short, 0)])
    with_peer, _ = pad_clip_batch([(short, 0), (longer, 1)])

    with torch.inference_mode():
        alone_logits, alone_embedding = model(alone)
        mixed_logits, mixed_embedding = model(with_peer)

    torch.testing.assert_close(alone_logits[0], mixed_logits[0])
    torch.testing.assert_close(alone_embedding[0], mixed_embedding[0])


def test_seeded_training_augmentation_is_reproducible():
    torch = pytest.importorskip("torch")
    from command.training import augment_clip

    frames = torch.arange(5 * 96 * 96, dtype=torch.float32).reshape(5, 96, 96)
    first = augment_clip(frames, torch.Generator().manual_seed(17))
    second = augment_clip(frames, torch.Generator().manual_seed(17))

    assert torch.equal(first, second)
    assert first.shape[0] in {4, 5, 6}


def test_rocm_training_writes_checkpoint_and_external_run_summary(tmp_path):
    torch = pytest.importorskip("torch")
    if not getattr(torch.version, "hip", None) or not torch.cuda.is_available():
        pytest.skip("requires a Radeon ROCm/HIP device")
    from command.catalog import catalog_sha256, load_phrase_catalog
    from command.dataset import INVENTORY_SCHEMA_VERSION, MANIFEST_ROLES

    project_root = Path(__file__).resolve().parents[1]
    catalog_path = project_root / "command/phrase_catalog.json"
    catalog = load_phrase_catalog(catalog_path)
    manifests = {}
    for manifest_name in MANIFEST_ROLES:
        manifests[manifest_name] = tmp_path / manifest_name

    train_records = []
    for index, entry in enumerate(catalog.entries):
        train_clip = tmp_path / f"train-{index}.npy"
        np.save(train_clip, np.full((3, 96, 96), 20 + index * 100, dtype=np.uint8))
        train_records.append(
            {
                "sample_id": f"train-{index}",
                "phrase_id": entry.phrase_id,
                "text": entry.text,
                "language": entry.language,
                "intent": entry.intent.value,
                "source_intent": entry.intent.value,
                "mouth_roi_npy": str(train_clip),
                "source_metadata": str(tmp_path / f"metadata-{index}.json"),
                "sha256": sha256(train_clip.read_bytes()).hexdigest(),
            }
        )
    manifests["train.jsonl"].write_text(
        "".join(json.dumps(record) + "\n" for record in train_records), encoding="utf-8"
    )
    for role in MANIFEST_ROLES[1:]:
        manifests[role].write_text("", encoding="utf-8")
    manifest_hashes = {
        name: sha256(path.read_bytes()).hexdigest() for name, path in manifests.items()
    }
    inventory_path = tmp_path / "inventory.json"
    inventory_path.write_text(
        json.dumps(
            {
                "schemaVersion": INVENTORY_SCHEMA_VERSION,
                "evidentiary": False,
                "seed": 17,
                "catalogSha256": catalog_sha256(catalog),
                "manifestSha256": manifest_hashes,
                "counts": {
                    "known": len(train_records),
                    "unknown": 0,
                    "unknownByLanguage": {"zh": 0, "en": 0},
                    "excluded": 0,
                    "byPhrase": {entry.phrase_id: 1 for entry in catalog.entries},
                    **{
                        role.removesuffix(".jsonl"): len(train_records)
                        if role == "train.jsonl"
                        else 0
                        for role in MANIFEST_ROLES
                    },
                },
                "exclusions": [],
                "duplicates": 0,
                "intentMismatches": 0,
                "splitMembership": {
                    role: [record["sample_id"] for record in train_records]
                    if role == "train.jsonl"
                    else []
                    for role in MANIFEST_ROLES
                },
            }
        ),
        encoding="utf-8",
    )
    checkpoint_path = tmp_path / "fixed-phrase.pt"
    summary_path = tmp_path / "fixed-phrase-run.json"

    result = train_phrase_classifier(
        catalog_path=catalog_path,
        inventory_path=inventory_path,
        train_manifest=manifests["train.jsonl"],
        calibration_known_manifest=manifests["calibration-known.jsonl"],
        calibration_unknown_manifest=manifests["calibration-unknown.jsonl"],
        evaluation_known_manifest=manifests["evaluation-known.jsonl"],
        evaluation_unknown_manifest=manifests["evaluation-unknown.jsonl"],
        output_path=checkpoint_path,
        run_summary_path=summary_path,
        epochs=1,
        seed=17,
    )

    assert (
        result["checkpointSha256"] == sha256(checkpoint_path.read_bytes()).hexdigest()
    )
    assert result["device"] == "cuda:0"
    assert result["epochs"] == 1
    assert result["evidentiary"] is False
    assert json.loads(summary_path.read_text(encoding="utf-8")) == result
    checkpoint = torch.load(checkpoint_path, map_location="cpu")
    assert checkpoint["decisionThresholds"]["minProbability"] == 0.85
    assert tuple(checkpoint["classCentroids"].shape) == (len(catalog.entries), 64)
    assert checkpoint["trainingSummary"]["torchVersion"] == str(torch.__version__)
    assert checkpoint["trainingSummary"]["hipVersion"] == str(torch.version.hip)
    assert checkpoint["trainingSummary"]["device"] == "cuda:0"
    assert checkpoint["trainingSummary"]["deviceName"] == str(
        torch.cuda.get_device_name(0)
    )
