import json
import subprocess
import sys
from hashlib import sha256
from pathlib import Path

import numpy as np
import pytest

from command.dataset import (
    MANIFEST_ROLES,
    build_dataset_manifests,
    validate_dataset_bundle,
)


def save_sample(
    root: Path,
    sample_id: str,
    phrase: str,
    intent: str,
    value: int,
    language: str = "zh",
):
    sample = root / "global" / intent / sample_id
    sample.mkdir(parents=True)
    metadata = {
        "sampleId": sample_id,
        "phrase": phrase,
        "intent": intent,
        "language": language,
    }
    (sample / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False), encoding="utf-8"
    )
    np.save(sample / "mouth_roi.npy", np.full((8, 96, 96), value, dtype=np.uint8))
    return sample / "metadata.json"


def save_official_known_samples(root: Path) -> None:
    phrases = [
        ("zh_light_on_hello", "你好，请帮我打开灯", "LIGHT_ON", "zh"),
        ("zh_chat_meal", "你吃饭了吗？", "CHAT_OTHER", "zh"),
        ("en_light_on_hello", "Hello, please turn on the light.", "LIGHT_ON", "en"),
        ("en_chat_meal", "Have you eaten?", "CHAT_OTHER", "en"),
    ]
    for phrase_offset, (phrase_id, phrase, intent, language) in enumerate(phrases):
        for take in range(15):
            save_sample(
                root,
                f"{phrase_id}-{take}",
                phrase,
                intent,
                phrase_offset * 100 + take,
                language,
            )


def test_catalog_corrects_source_intent_without_mutating_metadata(tmp_path):
    source = save_sample(tmp_path, "meal-1", "你吃饭了吗？", "LIGHT_ON", 7)
    original = source.read_bytes()
    inventory = build_dataset_manifests(
        tmp_path,
        Path("command/phrase_catalog.json"),
        tmp_path / "out",
        allow_small_dataset=True,
        seed=17,
    )
    records = [
        json.loads(line)
        for line in (tmp_path / "out/train.jsonl").read_text().splitlines()
    ]
    records += [
        json.loads(line)
        for line in (tmp_path / "out/calibration-known.jsonl").read_text().splitlines()
    ]
    records += [
        json.loads(line)
        for line in (tmp_path / "out/evaluation-known.jsonl").read_text().splitlines()
    ]
    meal = next(record for record in records if record["sample_id"] == "meal-1")
    assert meal["phrase_id"] == "zh_chat_meal"
    assert meal["intent"] == "CHAT_OTHER"
    assert meal["source_intent"] == "LIGHT_ON"
    assert source.read_bytes() == original
    assert inventory["intentMismatches"] == 1


def test_duplicate_mouth_arrays_are_never_split_across_partitions(tmp_path):
    save_sample(tmp_path, "a", "你好，请帮我打开灯", "LIGHT_ON", 1)
    save_sample(tmp_path, "b", "你好，请帮我打开灯", "LIGHT_ON", 1)
    inventory = build_dataset_manifests(
        tmp_path, Path("command/phrase_catalog.json"), tmp_path / "out", True, 17
    )
    assert inventory["duplicates"] == 1


def test_later_sample_id_duplicate_is_rejected_even_if_first_record_is_excluded(
    tmp_path,
):
    save_sample(tmp_path, "duplicate", "未注册短语", "LIGHT_ON", 1)
    sample = tmp_path / "global" / "second-source" / "second"
    sample.mkdir(parents=True)
    (sample / "metadata.json").write_text(
        json.dumps(
            {
                "sampleId": "duplicate",
                "phrase": "你好，请帮我打开灯",
                "intent": "LIGHT_ON",
                "language": "zh",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    np.save(sample / "mouth_roi.npy", np.full((8, 96, 96), 2, dtype=np.uint8))

    inventory = build_dataset_manifests(
        tmp_path, Path("command/phrase_catalog.json"), tmp_path / "out", True, 17
    )

    known_records = "".join(
        (tmp_path / "out" / name).read_text()
        for name in ("train.jsonl", "calibration-known.jsonl", "evaluation-known.jsonl")
    )
    assert '"sample_id": "duplicate"' not in known_records
    assert inventory["duplicates"] == 1


def test_official_gate_rejects_too_few_samples(tmp_path):
    save_sample(tmp_path, "a", "你好，请帮我打开灯", "LIGHT_ON", 1)
    with pytest.raises(ValueError, match="15 independent takes"):
        build_dataset_manifests(
            tmp_path, Path("command/phrase_catalog.json"), tmp_path / "out", False, 17
        )


def test_official_gate_rejects_unknown_clips_from_only_one_language(tmp_path):
    save_official_known_samples(tmp_path)
    for take in range(15):
        save_sample(
            tmp_path,
            f"unknown-zh-{take}",
            "今天天气不错",
            "UNKNOWN",
            20 + take,
            "zh",
        )

    with pytest.raises(ValueError, match="unrelated clips in both zh and en"):
        build_dataset_manifests(
            tmp_path, Path("command/phrase_catalog.json"), tmp_path / "out", False, 17
        )


def test_official_gate_accepts_bilingual_unknown_clips_and_reports_language_counts(
    tmp_path,
):
    save_official_known_samples(tmp_path)
    for take in range(8):
        save_sample(
            tmp_path,
            f"unknown-zh-{take}",
            "今天天气不错",
            "UNKNOWN",
            20 + take,
            "zh",
        )
    for take in range(7):
        save_sample(
            tmp_path,
            f"unknown-en-{take}",
            "What time is it?",
            "UNKNOWN",
            60 + take,
            "en",
        )

    inventory = build_dataset_manifests(
        tmp_path, Path("command/phrase_catalog.json"), tmp_path / "out", False, 17
    )

    assert inventory["evidentiary"] is True
    assert inventory["counts"]["unknownByLanguage"] == {"zh": 8, "en": 7}


def test_explicit_unknown_is_not_a_training_class(tmp_path):
    save_sample(tmp_path, "u", "今天天气不错", "UNKNOWN", 3)
    build_dataset_manifests(
        tmp_path, Path("command/phrase_catalog.json"), tmp_path / "out", True, 17
    )
    assert '"sample_id": "u"' not in (tmp_path / "out/train.jsonl").read_text()
    unknown_text = (tmp_path / "out/evaluation-unknown.jsonl").read_text()
    unknown_text += (tmp_path / "out/calibration-unknown.jsonl").read_text()
    assert '"sample_id": "u"' in unknown_text


@pytest.mark.parametrize("language", [None, "", "unknown", "fr"])
def test_unknown_source_requires_a_supported_language(tmp_path, language):
    source = save_sample(tmp_path, "u", "What time is it?", "UNKNOWN", 3)
    metadata = json.loads(source.read_text(encoding="utf-8"))
    if language is None:
        metadata.pop("language")
    else:
        metadata["language"] = language
    source.write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(ValueError, match="recognition language must be 'zh' or 'en'"):
        build_dataset_manifests(
            tmp_path, Path("command/phrase_catalog.json"), tmp_path / "out", True, 17
        )


def test_known_source_uses_catalog_language_instead_of_source_metadata(tmp_path):
    source = save_sample(
        tmp_path, "english-light", "Hello, please turn on the light.", "LIGHT_ON", 4
    )
    metadata = json.loads(source.read_text(encoding="utf-8"))
    metadata["language"] = "zh"
    source.write_text(json.dumps(metadata), encoding="utf-8")

    build_dataset_manifests(
        tmp_path, Path("command/phrase_catalog.json"), tmp_path / "out", True, 17
    )

    record = json.loads((tmp_path / "out/train.jsonl").read_text(encoding="utf-8"))
    assert record["phrase_id"] == "en_light_on_hello"
    assert record["language"] == "en"


def test_inventory_includes_per_phrase_counts_and_split_membership(tmp_path):
    for index in range(3):
        save_sample(tmp_path, f"light-{index}", "你好，请帮我打开灯", "LIGHT_ON", index)

    inventory = build_dataset_manifests(
        tmp_path, Path("command/phrase_catalog.json"), tmp_path / "out", True, 17
    )

    assert inventory["counts"]["byPhrase"] == {
        "zh_light_on_hello": 3,
        "zh_chat_meal": 0,
        "en_light_on_hello": 0,
        "en_chat_meal": 0,
    }
    assert inventory["counts"]["unknownByLanguage"] == {"zh": 0, "en": 0}
    membership = inventory["splitMembership"]
    recorded_ids = set().union(*map(set, membership.values()))
    assert recorded_ids == {"light-0", "light-1", "light-2"}


def test_manifest_cli_builds_small_dataset_artifacts(tmp_path):
    save_sample(tmp_path, "light", "你好，请帮我打开灯", "LIGHT_ON", 1)
    save_sample(tmp_path, "unknown", "今天天气不错", "UNKNOWN", 2)
    project_root = Path(__file__).resolve().parents[1]
    output_dir = tmp_path / "artifacts"
    result = subprocess.run(
        [
            sys.executable,
            str(project_root / "scripts" / "build_command_manifest.py"),
            "--profile-root",
            str(tmp_path),
            "--catalog",
            str(project_root / "command" / "phrase_catalog.json"),
            "--output-dir",
            str(output_dir),
            "--seed",
            "29",
            "--allow-small-dataset",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    for filename in (
        "train.jsonl",
        "calibration-known.jsonl",
        "evaluation-known.jsonl",
        "calibration-unknown.jsonl",
        "evaluation-unknown.jsonl",
        "inventory.json",
    ):
        assert (output_dir / filename).is_file()
    inventory = json.loads((output_dir / "inventory.json").read_text(encoding="utf-8"))
    assert inventory["evidentiary"] is False
    assert inventory["seed"] == 29
    assert json.loads(result.stdout)["evidentiary"] is False


def bundle_paths(root: Path) -> dict[str, Path]:
    return {role: root / role for role in MANIFEST_ROLES}


def test_evidence_validation_derives_status_instead_of_trusting_flag(tmp_path):
    save_sample(tmp_path, "light", "你好，请帮我打开灯", "LIGHT_ON", 1)
    output = tmp_path / "out"
    build_dataset_manifests(
        tmp_path, Path("command/phrase_catalog.json"), output, True, 17
    )
    inventory_path = output / "inventory.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    inventory["evidentiary"] = True
    inventory_path.write_text(json.dumps(inventory), encoding="utf-8")

    with pytest.raises(ValueError, match="evidentiary status does not match"):
        validate_dataset_bundle(
            Path("command/phrase_catalog.json"),
            inventory_path,
            bundle_paths(output),
        )


def test_evidence_validation_requires_all_exact_manifest_roles_and_hashes(tmp_path):
    save_sample(tmp_path, "light", "你好，请帮我打开灯", "LIGHT_ON", 1)
    output = tmp_path / "out"
    build_dataset_manifests(
        tmp_path, Path("command/phrase_catalog.json"), output, True, 17
    )
    with pytest.raises(FileNotFoundError):
        validate_dataset_bundle(
            Path("command/phrase_catalog.json"),
            output / "missing-inventory.json",
            bundle_paths(output),
        )

    inventory_path = output / "inventory.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    inventory["catalogSha256"] = "f" * 64
    wrong_inventory = output / "wrong-inventory.json"
    wrong_inventory.write_text(json.dumps(inventory), encoding="utf-8")
    with pytest.raises(ValueError, match="catalogSha256"):
        validate_dataset_bundle(
            Path("command/phrase_catalog.json"),
            wrong_inventory,
            bundle_paths(output),
        )

    incomplete = bundle_paths(output)
    incomplete.pop("evaluation-unknown.jsonl")
    with pytest.raises(ValueError, match="all five manifest roles"):
        validate_dataset_bundle(
            Path("command/phrase_catalog.json"), output / "inventory.json", incomplete
        )

    renamed = bundle_paths(output)
    renamed_path = output / "renamed-evaluation-known.jsonl"
    renamed_path.write_bytes((output / "evaluation-known.jsonl").read_bytes())
    renamed["evaluation-known.jsonl"] = renamed_path
    with pytest.raises(ValueError, match="must reference a file named"):
        validate_dataset_bundle(
            Path("command/phrase_catalog.json"), output / "inventory.json", renamed
        )

    (output / "train.jsonl").write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="SHA-256"):
        validate_dataset_bundle(
            Path("command/phrase_catalog.json"),
            output / "inventory.json",
            bundle_paths(output),
        )


def test_evidence_validation_rejects_cross_split_sample_and_roi_reuse(tmp_path):
    for index in range(3):
        save_sample(
            tmp_path,
            f"light-{index}",
            "你好，请帮我打开灯",
            "LIGHT_ON",
            index + 1,
        )
    output = tmp_path / "out"
    build_dataset_manifests(
        tmp_path, Path("command/phrase_catalog.json"), output, True, 17
    )
    train_path = output / "train.jsonl"
    evaluation_path = output / "evaluation-known.jsonl"
    train_record = json.loads(train_path.read_text(encoding="utf-8").splitlines()[0])
    evaluation_record = json.loads(evaluation_path.read_text(encoding="utf-8"))
    evaluation_record["sample_id"] = train_record["sample_id"]
    evaluation_path.write_text(json.dumps(evaluation_record) + "\n", encoding="utf-8")
    inventory_path = output / "inventory.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    inventory["manifestSha256"]["evaluation-known.jsonl"] = sha256(
        evaluation_path.read_bytes()
    ).hexdigest()
    inventory["splitMembership"]["evaluation-known.jsonl"] = [train_record["sample_id"]]
    inventory_path.write_text(json.dumps(inventory), encoding="utf-8")

    with pytest.raises(ValueError, match="sample_id appears in multiple splits"):
        validate_dataset_bundle(
            Path("command/phrase_catalog.json"),
            inventory_path,
            bundle_paths(output),
        )

    evaluation_record["sample_id"] = "unique-id"
    evaluation_record["sha256"] = train_record["sha256"]
    evaluation_record["mouth_roi_npy"] = train_record["mouth_roi_npy"]
    evaluation_path.write_text(json.dumps(evaluation_record) + "\n", encoding="utf-8")
    inventory["manifestSha256"]["evaluation-known.jsonl"] = sha256(
        evaluation_path.read_bytes()
    ).hexdigest()
    inventory["splitMembership"]["evaluation-known.jsonl"] = ["unique-id"]
    inventory_path.write_text(json.dumps(inventory), encoding="utf-8")

    with pytest.raises(ValueError, match="ROI SHA-256 appears in multiple splits"):
        validate_dataset_bundle(
            Path("command/phrase_catalog.json"),
            inventory_path,
            bundle_paths(output),
        )


def test_evidence_validation_rejects_mixed_roles_even_with_edited_inventory(tmp_path):
    for index in range(3):
        save_sample(
            tmp_path,
            f"light-{index}",
            "你好，请帮我打开灯",
            "LIGHT_ON",
            index + 1,
        )
    output = tmp_path / "out"
    build_dataset_manifests(
        tmp_path, Path("command/phrase_catalog.json"), output, True, 17
    )
    calibration_path = output / "calibration-known.jsonl"
    evaluation_path = output / "evaluation-known.jsonl"
    calibration_bytes = calibration_path.read_bytes()
    evaluation_bytes = evaluation_path.read_bytes()
    calibration_path.write_bytes(evaluation_bytes)
    evaluation_path.write_bytes(calibration_bytes)
    inventory_path = output / "inventory.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    for role, path in (
        ("calibration-known.jsonl", calibration_path),
        ("evaluation-known.jsonl", evaluation_path),
    ):
        inventory["manifestSha256"][role] = sha256(path.read_bytes()).hexdigest()
        inventory["splitMembership"][role] = [
            json.loads(path.read_text(encoding="utf-8"))["sample_id"]
        ]
    inventory_path.write_text(json.dumps(inventory), encoding="utf-8")

    with pytest.raises(ValueError, match="deterministic split policy"):
        validate_dataset_bundle(
            Path("command/phrase_catalog.json"),
            inventory_path,
            bundle_paths(output),
        )
