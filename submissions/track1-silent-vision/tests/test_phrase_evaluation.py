from __future__ import annotations

import inspect
import json
import subprocess
import sys
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from command.evaluation import (
    EvaluationRecord,
    _evaluate_dataset,
    _validate_checkpoint_lineage,
    _validate_partition_records,
    build_evaluation_report,
    evaluate_checkpoint,
)


def test_evaluation_manifest_records_require_a_supported_language():
    # Catches a regression that evaluates a clip without the language needed to
    # select its eligible phrase classes.
    _validate_partition_records(
        [{"phrase_id": "zh_light_on", "language": "zh"}], known=True
    )
    _validate_partition_records([{"phrase_id": None, "language": "en"}], known=False)

    with pytest.raises(ValueError, match="language"):
        _validate_partition_records([{"phrase_id": "zh_light_on"}], known=True)
    with pytest.raises(ValueError, match="language"):
        _validate_partition_records(
            [{"phrase_id": None, "language": "unknown"}], known=False
        )


def test_evaluation_passes_manifest_language_to_the_classifier():
    # Catches a regression that records language in the manifest but omits it
    # from the classifier call that produces the decision.
    class Frames:
        def numpy(self):
            return "frames"

    class Dataset:
        def __init__(self):
            self.records = [
                {
                    "sample_id": "sample-1",
                    "phrase_id": "zh_light_on",
                    "language": "zh",
                }
            ]

        def __getitem__(self, index):
            return Frames(), 0

    received = []

    class Backend:
        def predict(self, frames, language, metadata):
            received.append((frames, language, metadata))
            return SimpleNamespace(
                accepted=True,
                confidence=0.99,
                metadata={"predictedPhraseId": "zh_light_on", "openSetDistance": 0.01},
            )

    records = _evaluate_dataset(Backend(), Dataset(), Path("known.jsonl"))

    assert records[0].predicted_phrase_id == "zh_light_on"
    assert received == [
        (
            "frames",
            "zh",
            {"manifest": "known.jsonl", "sampleId": "sample-1"},
        )
    ]


def test_evaluation_metrics_keep_acceptance_and_accuracy_separate():
    known = [
        EvaluationRecord("a", "a", True, 0.9, 0.1),
        EvaluationRecord("a", "b", True, 0.9, 0.1),
        EvaluationRecord("b", "b", False, 0.4, 0.3),
    ]
    unknown = [
        EvaluationRecord(None, "a", False, 0.5, 0.4),
        EvaluationRecord(None, "b", True, 0.9, 0.1),
    ]

    report = build_evaluation_report(
        known,
        unknown,
        {"a": "LIGHT_ON", "b": "CHAT_OTHER"},
        {"thresholdSource": "checkpoint"},
    )

    assert report["phraseAccuracy"] == pytest.approx(2 / 3)
    assert report["mappedIntentAccuracy"] == pytest.approx(2 / 3)
    assert report["knownAcceptanceRate"] == pytest.approx(2 / 3)
    assert report["acceptedPhraseAccuracy"] == pytest.approx(1 / 2)
    assert report["acceptedPrecision"] == pytest.approx(1 / 3)
    assert report["rawCounts"]["acceptedPhraseAccuracy"] == {
        "numerator": 1,
        "denominator": 2,
    }
    assert report["rawCounts"]["acceptedPrecision"] == {
        "numerator": 1,
        "denominator": 3,
    }
    assert report["unknownFalseAcceptRate"] == pytest.approx(1 / 2)
    assert report["unknownRejectionRate"] == pytest.approx(1 / 2)
    assert report["confusionMatrix"]["a"] == {"a": 1, "b": 1}
    assert report["perPhrase"]["b"]["knownTotal"] == 1


def test_evaluation_report_exposes_every_rate_denominator_and_rejected_confusion():
    report = build_evaluation_report(
        [EvaluationRecord("a", "a", False, 0.7, 0.3)],
        [EvaluationRecord(None, "a", False, 0.6, 0.4)],
        {"a": "LIGHT_ON"},
        {"thresholdSource": "checkpoint"},
    )

    assert report["acceptedPhraseAccuracy"] is None
    assert report["acceptedPrecision"] is None
    assert report["rawCounts"] == {
        "phraseAccuracy": {"numerator": 1, "denominator": 1},
        "mappedIntentAccuracy": {"numerator": 1, "denominator": 1},
        "knownAcceptanceRate": {"numerator": 0, "denominator": 1},
        "acceptedPhraseAccuracy": {"numerator": 0, "denominator": 0},
        "acceptedPrecision": {"numerator": 0, "denominator": 0},
        "unknownFalseAcceptRate": {"numerator": 0, "denominator": 1},
        "unknownRejectionRate": {"numerator": 1, "denominator": 1},
    }
    assert report["confusionMatrix"] == {
        "a": {"UNKNOWN": 1},
        "UNKNOWN": {"UNKNOWN": 1},
    }


def test_evaluate_checkpoint_signature_has_no_calibration_inputs():
    parameters = inspect.signature(evaluate_checkpoint).parameters

    assert list(parameters) == [
        "checkpoint_path",
        "catalog_path",
        "inventory_path",
        "train_manifest",
        "calibration_known_manifest",
        "calibration_unknown_manifest",
        "known_manifest",
        "unknown_manifest",
        "output_path",
        "probability_override",
        "distance_override",
    ]


def test_final_evaluation_rejects_non_evidentiary_or_mismatched_checkpoint_lineage():
    from command.dataset import ValidatedDatasetBundle

    hashes = {
        "train.jsonl": "1" * 64,
        "calibration-known.jsonl": "2" * 64,
        "calibration-unknown.jsonl": "3" * 64,
        "evaluation-known.jsonl": "4" * 64,
        "evaluation-unknown.jsonl": "5" * 64,
    }
    bundle = ValidatedDatasetBundle(
        inventory_sha256="a" * 64,
        catalog_sha256="b" * 64,
        seed=17,
        manifest_sha256=hashes,
        evidentiary=True,
        records={role: () for role in hashes},
    )
    lineage = bundle.checkpoint_lineage()
    lineage["evidentiary"] = False
    with pytest.raises(ValueError, match="non-evidentiary checkpoint"):
        _validate_checkpoint_lineage(lineage, bundle)

    lineage["evidentiary"] = True
    lineage["manifestSha256"] = dict(hashes)
    lineage["manifestSha256"]["train.jsonl"] = "f" * 64
    with pytest.raises(ValueError, match="does not match inventory and manifests"):
        _validate_checkpoint_lineage(lineage, bundle)


def test_evaluate_checkpoint_rejects_non_final_partition_names_before_gpu_work(
    tmp_path,
):
    with pytest.raises(ValueError, match="evaluation-known.jsonl"):
        evaluate_checkpoint(
            checkpoint_path=tmp_path / "missing.pt",
            catalog_path=tmp_path / "missing-catalog.json",
            inventory_path=tmp_path / "missing-inventory.json",
            train_manifest=tmp_path / "train.jsonl",
            calibration_known_manifest=tmp_path / "calibration-known.jsonl",
            calibration_unknown_manifest=tmp_path / "calibration-unknown.jsonl",
            known_manifest=tmp_path / "calibration-known.jsonl",
            unknown_manifest=tmp_path / "evaluation-unknown.jsonl",
            output_path=tmp_path / "report.json",
            probability_override=None,
            distance_override=None,
        )


@pytest.mark.parametrize(
    ("script_name", "required_options"),
    [
        (
            "validate_command_classifier.py",
            (
                "--checkpoint",
                "--catalog",
                "--inventory",
                "--train-manifest",
                "--calibration-known",
                "--calibration-unknown",
                "--known-manifest",
                "--unknown-manifest",
                "--output",
            ),
        ),
        ("infer_command_clip.py", ("--checkpoint", "--mouth-roi", "--language")),
    ],
)
def test_phrase_cli_help_runs_without_torch(script_name, required_options):
    project_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(project_root / "scripts" / script_name), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert all(option in result.stdout for option in required_options)
    assert "--threshold" not in result.stdout
    assert "--margin" not in result.stdout


@pytest.fixture(scope="module")
def rocm_evaluation_artifacts(tmp_path_factory):
    torch = pytest.importorskip("torch")
    if not getattr(torch.version, "hip", None) or not torch.cuda.is_available():
        pytest.skip("requires a Radeon ROCm/HIP device")

    from command.catalog import catalog_records, load_phrase_catalog
    from command.checkpoint import save_phrase_checkpoint
    from command.dataset import (
        MANIFEST_ROLES,
        build_dataset_manifests,
        validate_dataset_bundle,
    )
    from command.model import build_fixed_phrase_model, normalize_clip_length

    root = tmp_path_factory.mktemp("phrase-evaluation")
    project_root = Path(__file__).resolve().parents[1]
    catalog_path = project_root / "command/phrase_catalog.json"
    catalog = load_phrase_catalog(catalog_path)
    sample_number = 1
    for entry in catalog.entries:
        for take in range(15):
            sample_dir = (
                root
                / "profiles/global"
                / entry.intent.value
                / f"{entry.phrase_id}-{take}"
            )
            sample_dir.mkdir(parents=True)
            (sample_dir / "metadata.json").write_text(
                json.dumps(
                    {
                        "sampleId": f"{entry.phrase_id}-{take}",
                        "phrase": entry.text,
                        "intent": entry.intent.value,
                        "language": entry.language,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            np.save(
                sample_dir / "mouth_roi.npy",
                np.full((3, 96, 96), sample_number, dtype=np.uint8),
            )
            sample_number += 1
    for language, count in (("zh", 8), ("en", 7)):
        for take in range(count):
            sample_id = f"unknown-{language}-{take}"
            sample_dir = root / "profiles/global/UNKNOWN" / sample_id
            sample_dir.mkdir(parents=True)
            (sample_dir / "metadata.json").write_text(
                json.dumps(
                    {
                        "sampleId": sample_id,
                        "phrase": "unrelated",
                        "intent": "UNKNOWN",
                        "language": language,
                    }
                ),
                encoding="utf-8",
            )
            np.save(
                sample_dir / "mouth_roi.npy",
                np.full((3, 96, 96), sample_number, dtype=np.uint8),
            )
            sample_number += 1
    manifests_root = root / "manifests"
    build_dataset_manifests(root / "profiles", catalog_path, manifests_root, False, 17)
    manifest_paths = {role: manifests_root / role for role in MANIFEST_ROLES}
    bundle = validate_dataset_bundle(
        catalog_path,
        manifests_root / "inventory.json",
        manifest_paths,
        require_evidentiary=True,
    )
    known_record = json.loads(
        manifest_paths["evaluation-known.jsonl"]
        .read_text(encoding="utf-8")
        .splitlines()[0]
    )
    mouth_roi = Path(known_record["mouth_roi_npy"])
    clip = np.load(mouth_roi, allow_pickle=False)

    model = build_fixed_phrase_model(4).eval()
    with torch.no_grad():
        model.classifier.weight.zero_()
        model.classifier.bias.copy_(torch.tensor([10.0, -10.0, 10.0, -10.0]))
        normalized_clip = normalize_clip_length(torch.from_numpy(clip))
        _, embedding = model(normalized_clip.unsqueeze(0))
    checkpoint = root / "fixed-phrase.pt"
    save_phrase_checkpoint(
        checkpoint,
        {
            "schemaVersion": "silent-vision.fixed-phrase.v2",
            "modelState": model.state_dict(),
            "phraseIds": [entry.phrase_id for entry in catalog.entries],
            "phraseCatalog": catalog_records(catalog),
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
                "minProbability": 0.99,
                "maxCosineDistance": {
                    entry.phrase_id: 0.05 for entry in catalog.entries
                },
            },
            "classCentroids": torch.cat(
                [embedding, -embedding, embedding, -embedding], dim=0
            ),
            "evidenceLineage": bundle.checkpoint_lineage(),
            "trainingSummary": {
                "seed": 17,
                "evidentiary": True,
                "torchVersion": str(torch.__version__),
                "hipVersion": str(torch.version.hip),
                "device": "cuda:0",
                "deviceName": str(torch.cuda.get_device_name(0)),
            },
        },
    )
    return {
        "checkpoint": checkpoint,
        "catalog": catalog_path,
        "inventory": manifests_root / "inventory.json",
        "manifest_paths": manifest_paths,
        "known_manifest": manifest_paths["evaluation-known.jsonl"],
        "unknown_manifest": manifest_paths["evaluation-unknown.jsonl"],
        "mouth_roi": mouth_roi,
        "root": root,
    }


def test_checkpoint_evaluation_uses_resolved_checkpoint_thresholds_and_hashes(
    rocm_evaluation_artifacts,
):
    torch = pytest.importorskip("torch")
    paths = rocm_evaluation_artifacts
    output = paths["root"] / "evaluation.json"

    report = evaluate_checkpoint(
        checkpoint_path=paths["checkpoint"],
        catalog_path=paths["catalog"],
        inventory_path=paths["inventory"],
        train_manifest=paths["manifest_paths"]["train.jsonl"],
        calibration_known_manifest=paths["manifest_paths"]["calibration-known.jsonl"],
        calibration_unknown_manifest=paths["manifest_paths"][
            "calibration-unknown.jsonl"
        ],
        known_manifest=paths["known_manifest"],
        unknown_manifest=paths["unknown_manifest"],
        output_path=output,
        probability_override=None,
        distance_override=None,
    )

    assert report["thresholdSource"] == "checkpoint"
    assert report["effectiveThresholds"] == {
        "minProbability": 0.99,
        "maxCosineDistance": {
            "zh_light_on_hello": 0.05,
            "zh_chat_meal": 0.05,
            "en_light_on_hello": 0.05,
            "en_chat_meal": 0.05,
        },
    }
    assert (
        report["checkpointSha256"]
        == sha256(paths["checkpoint"].read_bytes()).hexdigest()
    )
    assert report["manifestSha256"] == {
        role: sha256(path.read_bytes()).hexdigest()
        for role, path in paths["manifest_paths"].items()
    }
    assert report["evidenceStatus"] == {
        "evidentiary": True,
        "datasetEvidentiary": True,
        "checkpointEvidentiary": True,
        "lineageVerified": True,
        "thresholdsFrozen": True,
    }
    expected_accelerator = {
        "torchVersion": str(torch.__version__),
        "hipVersion": str(torch.version.hip),
        "device": "cuda:0",
        "deviceName": str(torch.cuda.get_device_name(0)),
    }
    assert report["trainingAccelerator"] == expected_accelerator
    assert report["evaluationAccelerator"] == expected_accelerator
    assert json.loads(output.read_text(encoding="utf-8")) == report


def test_single_clip_inference_prints_phrase_runtime_contract(
    rocm_evaluation_artifacts,
):
    paths = rocm_evaluation_artifacts
    project_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            sys.executable,
            str(project_root / "scripts/infer_command_clip.py"),
            "--checkpoint",
            str(paths["checkpoint"]),
            "--mouth-roi",
            str(paths["mouth_roi"]),
            "--language",
            "zh",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["intent"] == "LIGHT_ON"
    assert output["accepted"] is True
    assert output["confidence"] > 0.99
    assert output["margin"] > 0.99
    assert output["phraseId"] == "zh_light_on_hello"
    assert output["matchedPhrase"] == "你好，请帮我打开灯"
    assert output["backend"] == "torch"
    assert output["device"] == "cuda:0"
    assert output["thresholdSource"] == "checkpoint"
    assert output["openSetDistance"] == pytest.approx(0.0, abs=1e-5)
