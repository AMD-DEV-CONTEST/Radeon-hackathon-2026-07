from __future__ import annotations

import hashlib
import json
import math
import os
import random
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from command.catalog import catalog_records, catalog_sha256, load_phrase_catalog
from command.checkpoint import DECISION_POLICY, SCHEMA_VERSION, save_phrase_checkpoint
from command.dataset import validate_dataset_bundle
from command.language import score_language_candidates, validate_recognition_language
from command.model import (
    FIXED_CLIP_FRAMES,
    PARAMETER_CAP,
    build_fixed_phrase_model,
    count_trainable_parameters,
    normalize_clip_length,
)

BATCH_SIZE = 4
LEARNING_RATE = 3e-4
WEIGHT_DECAY = 1e-4
OFFICIAL_EPOCHS = 80
UNKNOWN_FALSE_ACCEPT_TARGET = 0.10


@dataclass(frozen=True)
class CalibrationRecord:
    expected_phrase_id: str | None
    predicted_phrase_id: str
    confidence: float
    distance: float


def require_rocm(torch_module) -> str:
    if not getattr(torch_module.version, "hip", None):
        raise RuntimeError("ROCm/HIP PyTorch is required")
    if not torch_module.cuda.is_available() or torch_module.cuda.device_count() < 1:
        raise RuntimeError("ROCm device cuda:0 is not available")
    return "cuda:0"


def accelerator_provenance(torch_module, device: str) -> dict[str, str | None]:
    hip_version = getattr(torch_module.version, "hip", None)
    return {
        "torchVersion": str(torch_module.__version__),
        "hipVersion": str(hip_version) if hip_version is not None else None,
        "device": str(device),
        "deviceName": str(torch_module.cuda.get_device_name(0)),
    }


def compute_class_centroids(embeddings, labels, class_count: int):
    import torch

    centroids = []
    for class_index in range(class_count):
        selected = embeddings[labels == class_index]
        if selected.shape[0] == 0:
            raise ValueError(f"class {class_index} has no training embedding")
        centroids.append(torch.nn.functional.normalize(selected.mean(dim=0), dim=0))
    return torch.stack(centroids)


def calibrate_thresholds(
    known_records: Sequence[CalibrationRecord],
    unknown_records: Sequence[CalibrationRecord],
    phrase_ids: Sequence[str],
    *,
    evidentiary: bool = True,
    training_records: Sequence[CalibrationRecord] = (),
) -> dict[str, Any]:
    ordered_phrase_ids = tuple(phrase_ids)
    if not ordered_phrase_ids or len(set(ordered_phrase_ids)) != len(
        ordered_phrase_ids
    ):
        raise ValueError("phrase_ids must be a non-empty unique sequence")

    radii: dict[str, float] = {}
    fallback_phrase_ids: list[str] = []
    for phrase_id in ordered_phrase_ids:
        correct_distances = [
            _distance(record)
            for record in known_records
            if record.expected_phrase_id == phrase_id
            and record.predicted_phrase_id == phrase_id
        ]
        if correct_distances:
            radii[phrase_id] = max(correct_distances)
            continue
        if evidentiary:
            raise ValueError(
                f"phrase {phrase_id!r} has no correctly classified known-calibration record"
            )
        training_distances = [
            _distance(record)
            for record in training_records
            if record.expected_phrase_id == phrase_id
        ]
        if not training_distances:
            raise ValueError(
                f"phrase {phrase_id!r} has no training distance for smoke fallback"
            )
        radii[phrase_id] = _percentile(training_distances, 0.95)
        fallback_phrase_ids.append(phrase_id)

    if not unknown_records:
        accepted_known = _accepted_known_count(known_records, radii, 0.85)
        return {
            "minProbability": 0.85,
            "maxCosineDistance": radii,
            "calibrationKnownCorrectAcceptedCount": accepted_known,
            "calibrationKnownRecordCount": len(known_records),
            "calibrationUnknownAcceptedCount": 0,
            "calibrationUnknownRecordCount": 0,
            "calibrationUnknownFalseAcceptRate": 0.0,
            "calibrationTargetMet": False,
            "radiusFallbackPhraseIds": fallback_phrase_ids,
            "evidentiary": False,
        }

    candidates = []
    for integer_threshold in range(50, 100):
        threshold = integer_threshold / 100.0
        accepted_unknown = _accepted_unknown_count(unknown_records, radii, threshold)
        false_accept_rate = accepted_unknown / len(unknown_records)
        accepted_known = _accepted_known_count(known_records, radii, threshold)
        candidates.append(
            (threshold, false_accept_rate, accepted_known, accepted_unknown)
        )

    eligible = [
        candidate
        for candidate in candidates
        if candidate[1] <= UNKNOWN_FALSE_ACCEPT_TARGET
    ]
    if eligible:
        chosen = max(eligible, key=lambda candidate: (candidate[2], candidate[0]))
        target_met = True
    else:
        chosen = min(
            candidates,
            key=lambda candidate: (candidate[1], -candidate[2], -candidate[0]),
        )
        target_met = False

    threshold, false_accept_rate, accepted_known, accepted_unknown = chosen
    return {
        "minProbability": threshold,
        "maxCosineDistance": radii,
        "calibrationKnownCorrectAcceptedCount": accepted_known,
        "calibrationKnownRecordCount": len(known_records),
        "calibrationUnknownAcceptedCount": accepted_unknown,
        "calibrationUnknownRecordCount": len(unknown_records),
        "calibrationUnknownFalseAcceptRate": false_accept_rate,
        "calibrationTargetMet": target_met,
        "radiusFallbackPhraseIds": fallback_phrase_ids,
        "evidentiary": bool(evidentiary and target_met and not fallback_phrase_ids),
    }


class ManifestDataset:
    def __init__(
        self,
        manifest_path: Path,
        phrase_index: dict[str, int],
        *,
        augment: bool = False,
        generator=None,
    ):
        self.records = _read_manifest(Path(manifest_path))
        for record in self.records:
            _validate_sample_sha256(record)
        self.phrase_index = dict(phrase_index)
        self.augment = augment
        self.generator = generator

    def __len__(self) -> int:
        return len(self.records)

    def __getitem__(self, index: int):
        import torch

        record = self.records[index]
        path_value = record.get("mouth_roi_npy")
        if not isinstance(path_value, str) or not path_value:
            raise ValueError("manifest record requires mouth_roi_npy")
        array = np.load(Path(path_value), allow_pickle=False)
        if array.ndim != 3 or tuple(array.shape[1:]) != (96, 96) or array.shape[0] < 1:
            raise ValueError(f"mouth ROI must have shape [T, 96, 96]: {path_value}")
        frames = torch.from_numpy(np.asarray(array)).clone()
        if self.augment:
            if self.generator is None:
                raise ValueError(
                    "training augmentation requires a seeded torch.Generator"
                )
            frames = augment_clip(frames, self.generator)
        phrase_id = record.get("phrase_id")
        if phrase_id is None:
            label = -1
        else:
            try:
                label = self.phrase_index[str(phrase_id)]
            except KeyError as exc:
                raise ValueError(
                    f"manifest phrase_id is not in catalog: {phrase_id!r}"
                ) from exc
        return frames, label


def augment_clip(frames, generator):
    import torch

    augmented = frames.to(dtype=torch.float32)
    brightness = torch.empty((), dtype=torch.float32).uniform_(
        0.9, 1.1, generator=generator
    )
    augmented = (augmented * brightness).clamp(0.0, 255.0)

    shift_y, shift_x = (
        int(value) for value in torch.randint(-2, 3, (2,), generator=generator).tolist()
    )
    augmented = _translate_frames(augmented, shift_y, shift_x)

    if augmented.shape[0] >= 3:
        operation = int(torch.randint(0, 3, (1,), generator=generator).item())
        if operation:
            frame_index = int(
                torch.randint(
                    1, augmented.shape[0] - 1, (1,), generator=generator
                ).item()
            )
            if operation == 1:
                augmented = torch.cat(
                    (augmented[:frame_index], augmented[frame_index + 1 :])
                )
            else:
                augmented = torch.cat(
                    (
                        augmented[: frame_index + 1],
                        augmented[frame_index : frame_index + 1],
                        augmented[frame_index + 1 :],
                    )
                )
    return augmented


def pad_clip_batch(batch):
    import torch

    if not batch:
        raise ValueError("cannot pad an empty batch")
    padded = []
    labels = []
    for frames, label in batch:
        padded.append(normalize_clip_length(frames))
        labels.append(label)
    return torch.stack(padded), torch.tensor(labels, dtype=torch.long)


def train_phrase_classifier(
    catalog_path: Path,
    inventory_path: Path,
    train_manifest: Path,
    calibration_known_manifest: Path,
    calibration_unknown_manifest: Path,
    evaluation_known_manifest: Path,
    evaluation_unknown_manifest: Path,
    output_path: Path,
    run_summary_path: Path,
    epochs: int,
    seed: int,
) -> dict[str, Any]:
    import torch

    device = require_rocm(torch)
    if not isinstance(epochs, int) or isinstance(epochs, bool) or epochs < 1:
        raise ValueError("epochs must be a positive integer")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError("seed must be an integer")  # noqa: TRY004

    _seed_everything(torch, seed)
    catalog = load_phrase_catalog(Path(catalog_path))
    manifest_paths = {
        "train.jsonl": Path(train_manifest),
        "calibration-known.jsonl": Path(calibration_known_manifest),
        "calibration-unknown.jsonl": Path(calibration_unknown_manifest),
        "evaluation-known.jsonl": Path(evaluation_known_manifest),
        "evaluation-unknown.jsonl": Path(evaluation_unknown_manifest),
    }
    bundle = validate_dataset_bundle(
        Path(catalog_path), Path(inventory_path), manifest_paths
    )
    inventory_evidentiary = bundle.evidentiary
    if inventory_evidentiary and epochs != OFFICIAL_EPOCHS:
        raise ValueError(f"official evidence requires exactly {OFFICIAL_EPOCHS} epochs")
    if bundle.seed != seed:
        raise ValueError("training seed must match inventory seed")

    catalog_digest = catalog_sha256(catalog)

    phrase_ids = tuple(entry.phrase_id for entry in catalog.entries)
    phrase_languages = tuple(entry.language for entry in catalog.entries)
    phrase_index = {phrase_id: index for index, phrase_id in enumerate(phrase_ids)}
    augmentation_generator = torch.Generator().manual_seed(seed)
    shuffle_generator = torch.Generator().manual_seed(seed)
    training_dataset = ManifestDataset(
        Path(train_manifest),
        phrase_index,
        augment=True,
        generator=augmentation_generator,
    )
    if not training_dataset:
        raise ValueError("training manifest has no samples")
    training_loader = torch.utils.data.DataLoader(
        training_dataset,
        batch_size=BATCH_SIZE,
        shuffle=True,
        generator=shuffle_generator,
        collate_fn=pad_clip_batch,
        num_workers=0,
    )

    model = build_fixed_phrase_model(len(phrase_ids)).to(device)
    parameter_count = count_trainable_parameters(model)
    optimizer = torch.optim.AdamW(
        model.parameters(), lr=LEARNING_RATE, weight_decay=WEIGHT_DECAY
    )
    for _ in range(epochs):
        model.train()
        for frames, labels in training_loader:
            frames = frames.to(device)
            labels = labels.to(device)
            optimizer.zero_grad(set_to_none=True)
            logits, _ = model(frames)
            loss = torch.nn.functional.cross_entropy(logits, labels)
            loss.backward()
            optimizer.step()

    plain_training_dataset = ManifestDataset(Path(train_manifest), phrase_index)
    training_embeddings, training_labels = _collect_embeddings(
        torch, model, plain_training_dataset, device
    )
    centroids = compute_class_centroids(
        training_embeddings, training_labels, len(phrase_ids)
    )
    training_records = _training_distance_records(
        training_embeddings, training_labels, centroids, phrase_ids
    )
    known_records = _calibration_records(
        torch,
        model,
        ManifestDataset(Path(calibration_known_manifest), phrase_index),
        centroids,
        phrase_ids,
        phrase_languages,
        device,
    )
    unknown_records = _calibration_records(
        torch,
        model,
        ManifestDataset(Path(calibration_unknown_manifest), phrase_index),
        centroids,
        phrase_ids,
        phrase_languages,
        device,
    )
    calibration = calibrate_thresholds(
        known_records,
        unknown_records,
        phrase_ids,
        evidentiary=inventory_evidentiary,
        training_records=training_records,
    )
    evidentiary = bool(inventory_evidentiary and calibration["evidentiary"])
    accelerator = accelerator_provenance(torch, device)

    training_summary = {
        **accelerator,
        "seed": seed,
        "catalogSha256": catalog_digest,
        "inventorySha256": bundle.inventory_sha256,
        "manifestSha256": bundle.manifest_sha256,
        "epochs": epochs,
        "parameterCount": parameter_count,
        "calibration": calibration,
        "evidentiary": evidentiary,
    }
    evidence_lineage = bundle.checkpoint_lineage()
    evidence_lineage["evidentiary"] = evidentiary
    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "modelState": {
            name: value.detach().cpu() for name, value in model.state_dict().items()
        },
        "phraseIds": list(phrase_ids),
        "phraseCatalog": catalog_records(catalog),
        "featureConfig": {
            "fps": 25,
            "frames": FIXED_CLIP_FRAMES,
            "height": 96,
            "width": 96,
            "downsample": 16,
        },
        "modelConfig": {"embeddingDim": 64, "parameterCap": PARAMETER_CAP},
        "decisionPolicy": dict(DECISION_POLICY),
        "decisionThresholds": {
            "minProbability": calibration["minProbability"],
            "maxCosineDistance": calibration["maxCosineDistance"],
        },
        "classCentroids": centroids.detach().cpu(),
        "evidenceLineage": evidence_lineage,
        "trainingSummary": training_summary,
    }
    checkpoint_digest = save_phrase_checkpoint(Path(output_path), payload)
    run_summary = {
        "checkpointSha256": checkpoint_digest,
        **training_summary,
    }
    _write_json_atomic(Path(run_summary_path), run_summary)
    return run_summary


def _distance(record: CalibrationRecord) -> float:
    distance = float(record.distance)
    if not math.isfinite(distance) or not 0.0 <= distance <= 2.0:
        raise ValueError("calibration distances must be finite values between 0 and 2")
    return distance


def _accepted(
    record: CalibrationRecord, radii: dict[str, float], threshold: float
) -> bool:
    radius = radii.get(record.predicted_phrase_id)
    confidence = float(record.confidence)
    if radius is None or not math.isfinite(confidence):
        return False
    return confidence >= threshold and _distance(record) <= radius


def _accepted_known_count(
    records: Sequence[CalibrationRecord], radii: dict[str, float], threshold: float
) -> int:
    return sum(
        record.expected_phrase_id == record.predicted_phrase_id
        and _accepted(record, radii, threshold)
        for record in records
    )


def _accepted_unknown_count(
    records: Sequence[CalibrationRecord], radii: dict[str, float], threshold: float
) -> int:
    return sum(_accepted(record, radii, threshold) for record in records)


def _percentile(values: Sequence[float], quantile: float) -> float:
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _translate_frames(frames, shift_y: int, shift_x: int):
    translated = frames.new_zeros(frames.shape)
    source_y_start = max(0, -shift_y)
    source_y_end = frames.shape[1] - max(0, shift_y)
    source_x_start = max(0, -shift_x)
    source_x_end = frames.shape[2] - max(0, shift_x)
    target_y_start = max(0, shift_y)
    target_y_end = target_y_start + (source_y_end - source_y_start)
    target_x_start = max(0, shift_x)
    target_x_end = target_x_start + (source_x_end - source_x_start)
    translated[:, target_y_start:target_y_end, target_x_start:target_x_end] = frames[
        :, source_y_start:source_y_end, source_x_start:source_x_end
    ]
    return translated


def _read_manifest(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as manifest_file:
        for line_number, line in enumerate(manifest_file, start=1):
            if not line.strip():
                continue
            record = json.loads(line)
            if not isinstance(record, dict):
                raise ValueError(  # noqa: TRY004
                    f"manifest line {line_number} must be a JSON object: {path}"
                )
            records.append(record)
    return records


def _read_json_object(path: Path, name: str) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{name} must be a JSON object")  # noqa: TRY004
    return payload


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_sample_sha256(record: dict[str, Any]) -> None:
    path_value = record.get("mouth_roi_npy")
    if not isinstance(path_value, str) or not path_value:
        raise ValueError("manifest record requires mouth_roi_npy")
    expected_digest = record.get("sha256")
    if not isinstance(expected_digest, str) or len(expected_digest) != 64:
        raise ValueError("manifest record requires sha256")
    try:
        int(expected_digest, 16)
    except ValueError as exc:
        raise ValueError(
            "manifest record requires sha256 as 64 hexadecimal characters"
        ) from exc
    actual_digest = _sha256_file(Path(path_value))
    if actual_digest != expected_digest.lower():
        raise ValueError(f"mouth ROI SHA-256 does not match manifest: {path_value}")


def _seed_everything(torch, seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.use_deterministic_algorithms(True)
    if hasattr(torch.backends, "cudnn"):
        torch.backends.cudnn.benchmark = False
        torch.backends.cudnn.deterministic = True


def _collect_embeddings(torch, model, dataset: ManifestDataset, device: str):
    if not dataset:
        raise ValueError("training manifest has no samples")
    loader = torch.utils.data.DataLoader(
        dataset,
        batch_size=BATCH_SIZE,
        shuffle=False,
        collate_fn=pad_clip_batch,
        num_workers=0,
    )
    embeddings = []
    labels = []
    model.eval()
    with torch.no_grad():
        for frames, batch_labels in loader:
            _, batch_embeddings = model(frames.to(device))
            embeddings.append(batch_embeddings)
            labels.append(batch_labels.to(device))
    return torch.cat(embeddings), torch.cat(labels)


def _training_distance_records(embeddings, labels, centroids, phrase_ids):
    records = []
    for embedding, label in zip(embeddings, labels):
        class_index = int(label.item())
        distance = float(
            (1.0 - embedding.dot(centroids[class_index])).clamp(0.0, 2.0).item()
        )
        phrase_id = phrase_ids[class_index]
        records.append(CalibrationRecord(phrase_id, phrase_id, 1.0, distance))
    return records


def _calibration_records(
    torch, model, dataset, centroids, phrase_ids, phrase_languages, device
):
    if not dataset:
        return []
    loader = torch.utils.data.DataLoader(
        dataset,
        batch_size=BATCH_SIZE,
        shuffle=False,
        collate_fn=pad_clip_batch,
        num_workers=0,
    )
    records = []
    manifest_index = 0
    model.eval()
    with torch.no_grad():
        for frames, labels in loader:
            logits, embeddings = model(frames.to(device))
            for row_index in range(frames.shape[0]):
                manifest_record = dataset.records[manifest_index]
                language = validate_recognition_language(
                    manifest_record.get("language")
                )
                scores = score_language_candidates(
                    logits[row_index].detach().cpu().tolist(),
                    phrase_languages,
                    language,
                )
                predicted_index = scores.ranked_indices[0]
                expected_index = int(labels[row_index].item())
                distance = float(
                    (1.0 - embeddings[row_index].dot(centroids[predicted_index]))
                    .clamp(0.0, 2.0)
                    .item()
                )
                expected_phrase_id = (
                    phrase_ids[expected_index] if expected_index >= 0 else None
                )
                records.append(
                    CalibrationRecord(
                        expected_phrase_id,
                        phrase_ids[predicted_index],
                        scores.probabilities[predicted_index],
                        distance,
                    )
                )
                manifest_index += 1
    return records


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            json.dump(
                payload, temporary_file, ensure_ascii=False, indent=2, sort_keys=True
            )
            temporary_file.write("\n")
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        temporary_path.replace(path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
