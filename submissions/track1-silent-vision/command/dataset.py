from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from command.catalog import (
    PhraseCatalog,
    PhraseEntry,
    catalog_sha256,
    load_phrase_catalog,
    normalize_phrase,
)
from command.language import validate_recognition_language

INVENTORY_SCHEMA_VERSION = "silent-vision.dataset-inventory.v1"
MANIFEST_ROLES = (
    "train.jsonl",
    "calibration-known.jsonl",
    "calibration-unknown.jsonl",
    "evaluation-known.jsonl",
    "evaluation-unknown.jsonl",
)
KNOWN_MANIFEST_ROLES = frozenset(
    {"train.jsonl", "calibration-known.jsonl", "evaluation-known.jsonl"}
)
OFFICIAL_KNOWN_MINIMUMS = {
    "train.jsonl": 10,
    "calibration-known.jsonl": 2,
    "evaluation-known.jsonl": 3,
}
OFFICIAL_UNKNOWN_MINIMUMS = {
    "calibration-unknown.jsonl": 5,
    "evaluation-unknown.jsonl": 10,
}
INVENTORY_KEYS = frozenset(
    {
        "schemaVersion",
        "evidentiary",
        "catalogSha256",
        "seed",
        "counts",
        "exclusions",
        "duplicates",
        "intentMismatches",
        "manifestSha256",
        "splitMembership",
    }
)
MANIFEST_RECORD_KEYS = frozenset(
    {
        "sample_id",
        "phrase_id",
        "text",
        "language",
        "intent",
        "source_intent",
        "mouth_roi_npy",
        "source_metadata",
        "sha256",
    }
)


@dataclass(frozen=True)
class ManifestSample:
    sample_id: str
    phrase_id: str | None
    text: str
    language: str
    intent: str
    source_intent: str
    mouth_roi_npy: str
    source_metadata: str
    sha256: str


@dataclass(frozen=True)
class ValidatedDatasetBundle:
    inventory_sha256: str
    catalog_sha256: str
    seed: int
    manifest_sha256: dict[str, str]
    evidentiary: bool
    records: dict[str, tuple[dict[str, Any], ...]]

    def checkpoint_lineage(self) -> dict[str, Any]:
        return {
            "inventorySha256": self.inventory_sha256,
            "catalogSha256": self.catalog_sha256,
            "seed": self.seed,
            "manifestSha256": dict(self.manifest_sha256),
            "evidentiary": self.evidentiary,
        }


def classify_source(metadata: dict, catalog: PhraseCatalog):
    source_intent = str(metadata.get("intent", "UNKNOWN"))
    if source_intent == "UNKNOWN":
        return "unknown", None
    normalized = normalize_phrase(str(metadata.get("phrase", "")))
    by_text = {normalize_phrase(entry.text): entry for entry in catalog.entries}
    entry = by_text.get(normalized)
    if entry is None:
        return "excluded", "phrase text is not registered"
    return "known", entry


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _sort_samples(samples: list[ManifestSample], seed: int) -> list[ManifestSample]:
    return sorted(
        samples,
        key=lambda sample: hashlib.sha256(
            f"{seed}:{sample.sample_id}".encode()
        ).hexdigest(),
    )


def split_known(samples: list[ManifestSample], allow_small: bool):
    if not allow_small and len(samples) < 15:
        raise ValueError("official evidence requires 15 independent takes per phrase")
    if allow_small:
        if len(samples) == 1:
            return samples, [], []
        if len(samples) == 2:
            return samples[:1], [], samples[1:]
        return samples[2:], samples[1:2], samples[:1]
    return samples[5:], samples[3:5], samples[:3]


def split_unknown(samples: list[ManifestSample], allow_small: bool):
    if not allow_small and len(samples) < 15:
        raise ValueError("official evidence requires 15 unrelated clips")
    if allow_small:
        if len(samples) < 2:
            return [], samples
        return samples[:1], samples[1:]
    return samples[:5], samples[5:]


def _unknown_counts_by_language(samples: list[ManifestSample]) -> dict[str, int]:
    return {
        language: sum(sample.language == language for sample in samples)
        for language in ("zh", "en")
    }


def _manifest_sample(
    sample_dir: Path,
    metadata_path: Path,
    mouth_roi_path: Path,
    metadata: dict,
    entry: PhraseEntry | None,
    sha256: str,
) -> ManifestSample:
    source_intent = str(metadata.get("intent", "UNKNOWN"))
    return ManifestSample(
        sample_id=str(metadata.get("sampleId") or sample_dir.name),
        phrase_id=entry.phrase_id if entry else None,
        text=entry.text if entry else str(metadata.get("phrase", "")),
        language=(
            entry.language
            if entry
            else validate_recognition_language(metadata.get("language"))
        ),
        intent=entry.intent.value if entry else "UNKNOWN",
        source_intent=source_intent,
        mouth_roi_npy=str(mouth_roi_path.resolve()),
        source_metadata=str(metadata_path.resolve()),
        sha256=sha256,
    )


def _write_jsonl(path: Path, samples: list[ManifestSample]) -> str:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for sample in samples:
            handle.write(
                json.dumps(asdict(sample), ensure_ascii=False, sort_keys=True) + "\n"
            )
    return _sha256_file(path)


def validate_dataset_bundle(
    catalog_path: Path,
    inventory_path: Path,
    manifest_paths: Mapping[str, Path],
    *,
    require_evidentiary: bool = False,
) -> ValidatedDatasetBundle:
    if set(manifest_paths) != set(MANIFEST_ROLES):
        raise ValueError("dataset bundle requires all five manifest roles exactly once")
    resolved_paths: dict[str, Path] = {}
    for role in MANIFEST_ROLES:
        path = Path(manifest_paths[role])
        if path.name != role:
            raise ValueError(
                f"{role} must reference a file named {role}, got {path.name}"
            )
        resolved_paths[role] = path

    catalog = load_phrase_catalog(Path(catalog_path))
    catalog_digest = catalog_sha256(catalog)
    inventory_path = Path(inventory_path)
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    if not isinstance(inventory, dict):
        raise ValueError("inventory must be a JSON object")  # noqa: TRY004
    if set(inventory) != INVENTORY_KEYS:
        raise ValueError("inventory must contain the complete strict schema")
    if inventory.get("schemaVersion") != INVENTORY_SCHEMA_VERSION:
        raise ValueError("unsupported dataset inventory schema")
    if inventory.get("catalogSha256") != catalog_digest:
        raise ValueError("inventory catalogSha256 does not match the catalog")
    seed = inventory.get("seed")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError("inventory seed must be an integer")  # noqa: TRY004

    expected_hashes = inventory.get("manifestSha256")
    if not isinstance(expected_hashes, dict) or set(expected_hashes) != set(
        MANIFEST_ROLES
    ):
        raise ValueError(
            "inventory manifestSha256 must contain all five manifest roles"
        )
    actual_hashes = {
        role: _sha256_file(resolved_paths[role]) for role in MANIFEST_ROLES
    }
    for role, digest in actual_hashes.items():
        if expected_hashes.get(role) != digest:
            raise ValueError(f"manifest SHA-256 does not match inventory role: {role}")

    records = {
        role: tuple(_read_manifest_records(resolved_paths[role]))
        for role in MANIFEST_ROLES
    }
    phrase_by_id = {entry.phrase_id: entry for entry in catalog.entries}
    seen_sample_ids: dict[str, str] = {}
    seen_roi_hashes: dict[str, str] = {}
    for role in MANIFEST_ROLES:
        known_role = role in KNOWN_MANIFEST_ROLES
        for record in records[role]:
            if set(record) != MANIFEST_RECORD_KEYS:
                raise ValueError(f"{role} record must contain the complete schema")
            sample_id = record.get("sample_id")
            if not isinstance(sample_id, str) or not sample_id.strip():
                raise ValueError(f"{role} record requires a non-blank sample_id")
            previous_role = seen_sample_ids.get(sample_id)
            if previous_role is not None:
                raise ValueError(
                    f"sample_id appears in multiple splits: {sample_id} "
                    f"({previous_role}, {role})"
                )
            seen_sample_ids[sample_id] = role

            roi_digest = _validated_record_roi_sha256(record, role)
            previous_roi_role = seen_roi_hashes.get(roi_digest)
            if previous_roi_role is not None:
                raise ValueError(
                    "ROI SHA-256 appears in multiple splits: "
                    f"{roi_digest} ({previous_roi_role}, {role})"
                )
            seen_roi_hashes[roi_digest] = role
            language = validate_recognition_language(record.get("language"))
            if not isinstance(record.get("text"), str) or not record["text"].strip():
                raise ValueError(f"{role} record requires non-blank text")
            if not isinstance(record.get("source_intent"), str):
                raise ValueError(  # noqa: TRY004
                    f"{role} record requires source_intent"
                )
            if (
                not isinstance(record.get("source_metadata"), str)
                or not record["source_metadata"]
            ):
                raise ValueError(f"{role} record requires source_metadata")
            phrase_id = record.get("phrase_id")
            if known_role:
                if not isinstance(phrase_id, str) or phrase_id not in phrase_by_id:
                    raise ValueError(f"{role} record requires a catalog phrase_id")
                entry = phrase_by_id[phrase_id]
                if language != entry.language:
                    raise ValueError(f"{role} record language does not match catalog")
                if (
                    record.get("text") != entry.text
                    or record.get("intent") != entry.intent.value
                ):
                    raise ValueError(f"{role} record metadata does not match catalog")
            elif phrase_id is not None or record.get("intent") != "UNKNOWN":
                raise ValueError(f"{role} records must be unrelated UNKNOWN samples")
            elif record.get("source_intent") != "UNKNOWN":
                raise ValueError(f"{role} records require source_intent UNKNOWN")

    membership = inventory.get("splitMembership")
    if not isinstance(membership, dict) or set(membership) != set(MANIFEST_ROLES):
        raise ValueError(
            "inventory splitMembership must contain all five manifest roles"
        )
    for role in MANIFEST_ROLES:
        actual_membership = [record["sample_id"] for record in records[role]]
        if membership.get(role) != actual_membership:
            raise ValueError(f"inventory splitMembership does not match {role}")

    _validate_deterministic_split_policy(records, tuple(phrase_by_id), seed)
    _validate_inventory_counts(inventory, records, tuple(phrase_by_id))
    _validate_inventory_audit_fields(inventory, records)
    derived_evidentiary = _derive_evidentiary(records, tuple(phrase_by_id))
    inventory_evidentiary = inventory.get("evidentiary")
    if not isinstance(inventory_evidentiary, bool):
        raise ValueError("inventory evidentiary must be a boolean")  # noqa: TRY004
    if inventory_evidentiary is not derived_evidentiary:
        raise ValueError("inventory evidentiary status does not match dataset policy")
    if require_evidentiary and not derived_evidentiary:
        raise ValueError("final evidence requires an evidentiary dataset bundle")

    return ValidatedDatasetBundle(
        inventory_sha256=_sha256_file(inventory_path),
        catalog_sha256=catalog_digest,
        seed=seed,
        manifest_sha256=actual_hashes,
        evidentiary=derived_evidentiary,
        records=records,
    )


def _read_manifest_records(path: Path) -> list[dict[str, Any]]:
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


def _validated_record_roi_sha256(record: dict[str, Any], role: str) -> str:
    digest = record.get("sha256")
    if not isinstance(digest, str) or len(digest) != 64:
        raise ValueError(f"{role} record requires a SHA-256")
    try:
        int(digest, 16)
    except ValueError as exc:
        raise ValueError(f"{role} record requires a hexadecimal SHA-256") from exc
    path_value = record.get("mouth_roi_npy")
    if not isinstance(path_value, str) or not path_value:
        raise ValueError(f"{role} record requires mouth_roi_npy")
    if _sha256_file(Path(path_value)) != digest.lower():
        raise ValueError(f"mouth ROI SHA-256 does not match manifest: {path_value}")
    return digest.lower()


def _validate_inventory_counts(
    inventory: dict[str, Any],
    records: Mapping[str, tuple[dict[str, Any], ...]],
    phrase_ids: tuple[str, ...],
) -> None:
    counts = inventory.get("counts")
    if not isinstance(counts, dict):
        raise ValueError("inventory counts must be an object")  # noqa: TRY004
    known_records = [
        record for role in KNOWN_MANIFEST_ROLES for record in records[role]
    ]
    unknown_records = [
        record for role in OFFICIAL_UNKNOWN_MINIMUMS for record in records[role]
    ]
    expected = {
        "known": len(known_records),
        "unknown": len(unknown_records),
        "unknownByLanguage": {
            language: sum(record["language"] == language for record in unknown_records)
            for language in ("zh", "en")
        },
        "byPhrase": {
            phrase_id: sum(record["phrase_id"] == phrase_id for record in known_records)
            for phrase_id in phrase_ids
        },
        **{
            role.removesuffix(".jsonl"): len(role_records)
            for role, role_records in records.items()
        },
    }
    for key, value in expected.items():
        if counts.get(key) != value:
            raise ValueError(f"inventory counts do not match dataset: {key}")


def _validate_inventory_audit_fields(
    inventory: dict[str, Any],
    records: Mapping[str, tuple[dict[str, Any], ...]],
) -> None:
    exclusions = inventory.get("exclusions")
    if not isinstance(exclusions, list) or any(
        not isinstance(item, dict)
        or set(item) != {"sourceMetadata", "reason"}
        or not all(isinstance(value, str) and value for value in item.values())
        for item in exclusions
    ):
        raise ValueError("inventory exclusions must contain sourceMetadata and reason")
    if inventory["counts"].get("excluded") != len(exclusions):
        raise ValueError("inventory excluded count does not match exclusions")
    duplicates = inventory.get("duplicates")
    if (
        not isinstance(duplicates, int)
        or isinstance(duplicates, bool)
        or duplicates < 0
    ):
        raise ValueError("inventory duplicates must be a non-negative integer")
    known_records = [
        record for role in KNOWN_MANIFEST_ROLES for record in records[role]
    ]
    mismatch_count = sum(
        record["source_intent"] != record["intent"] for record in known_records
    )
    if inventory.get("intentMismatches") != mismatch_count:
        raise ValueError("inventory intentMismatches does not match manifests")


def _validate_deterministic_split_policy(
    records: Mapping[str, tuple[dict[str, Any], ...]],
    phrase_ids: tuple[str, ...],
    seed: int,
) -> None:
    actual = {
        role: [record["sample_id"] for record in records[role]]
        for role in MANIFEST_ROLES
    }
    all_known = [record for role in KNOWN_MANIFEST_ROLES for record in records[role]]
    all_unknown = [
        record for role in OFFICIAL_UNKNOWN_MINIMUMS for record in records[role]
    ]
    if any(
        actual
        == _expected_split_membership(
            all_known, all_unknown, phrase_ids, seed, allow_small
        )
        for allow_small in (False, True)
    ):
        return
    raise ValueError("manifest roles do not match the deterministic split policy")


def _expected_split_membership(
    known_records: list[dict[str, Any]],
    unknown_records: list[dict[str, Any]],
    phrase_ids: tuple[str, ...],
    seed: int,
    allow_small: bool,
) -> dict[str, list[str]]:
    expected = {role: [] for role in MANIFEST_ROLES}
    for phrase_id in phrase_ids:
        ordered = _sort_record_dicts(
            [record for record in known_records if record["phrase_id"] == phrase_id],
            seed,
        )
        if allow_small:
            if len(ordered) == 1:
                train, calibration, evaluation = ordered, [], []
            elif len(ordered) == 2:
                train, calibration, evaluation = ordered[:1], [], ordered[1:]
            else:
                train, calibration, evaluation = ordered[2:], ordered[1:2], ordered[:1]
        else:
            train, calibration, evaluation = ordered[5:], ordered[3:5], ordered[:3]
        expected["train.jsonl"].extend(record["sample_id"] for record in train)
        expected["calibration-known.jsonl"].extend(
            record["sample_id"] for record in calibration
        )
        expected["evaluation-known.jsonl"].extend(
            record["sample_id"] for record in evaluation
        )

    ordered_unknown = _sort_record_dicts(unknown_records, seed)
    if allow_small:
        if len(ordered_unknown) < 2:
            calibration_unknown, evaluation_unknown = [], ordered_unknown
        else:
            calibration_unknown, evaluation_unknown = (
                ordered_unknown[:1],
                ordered_unknown[1:],
            )
    else:
        calibration_unknown, evaluation_unknown = (
            ordered_unknown[:5],
            ordered_unknown[5:],
        )
    expected["calibration-unknown.jsonl"] = [
        record["sample_id"] for record in calibration_unknown
    ]
    expected["evaluation-unknown.jsonl"] = [
        record["sample_id"] for record in evaluation_unknown
    ]
    return expected


def _sort_record_dicts(
    records: list[dict[str, Any]], seed: int
) -> list[dict[str, Any]]:
    return sorted(
        records,
        key=lambda record: hashlib.sha256(
            f"{seed}:{record['sample_id']}".encode()
        ).hexdigest(),
    )


def _derive_evidentiary(
    records: Mapping[str, tuple[dict[str, Any], ...]], phrase_ids: tuple[str, ...]
) -> bool:
    for role, minimum in OFFICIAL_KNOWN_MINIMUMS.items():
        counts = Counter(record["phrase_id"] for record in records[role])
        if any(counts[phrase_id] < minimum for phrase_id in phrase_ids):
            return False
    if any(
        len(records[role]) < minimum
        for role, minimum in OFFICIAL_UNKNOWN_MINIMUMS.items()
    ):
        return False
    unknown_languages = {
        record["language"]
        for role in OFFICIAL_UNKNOWN_MINIMUMS
        for record in records[role]
    }
    return unknown_languages == {"zh", "en"}


def build_dataset_manifests(
    profile_root: Path,
    catalog_path: Path,
    output_dir: Path,
    allow_small_dataset: bool,
    seed: int,
) -> dict:
    catalog = load_phrase_catalog(catalog_path)
    root = profile_root.resolve()
    known_by_phrase: dict[str, list[ManifestSample]] = {
        entry.phrase_id: [] for entry in catalog.entries
    }
    unknown: list[ManifestSample] = []
    exclusions: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    seen_hashes: set[str] = set()
    duplicates = 0
    intent_mismatches = 0

    recordings_root = root / "global"
    if recordings_root.exists():
        sample_dirs = sorted(
            path
            for source_dir in recordings_root.iterdir()
            if source_dir.is_dir()
            for path in source_dir.iterdir()
            if path.is_dir()
        )
    else:
        sample_dirs = []

    for sample_dir in sample_dirs:
        metadata_path = sample_dir / "metadata.json"
        mouth_roi_path = sample_dir / "mouth_roi.npy"
        if not metadata_path.is_file() or not mouth_roi_path.is_file():
            raise ValueError(
                f"recording requires metadata.json and mouth_roi.npy: {sample_dir.resolve()}"
            )
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if not isinstance(metadata, dict):
            raise ValueError(  # noqa: TRY004
                f"recording metadata must be an object: {metadata_path.resolve()}"
            )
        sample_id = str(metadata.get("sampleId") or sample_dir.name)
        mouth_roi_sha256 = _sha256_file(mouth_roi_path)
        if sample_id in seen_ids or mouth_roi_sha256 in seen_hashes:
            duplicates += 1
            continue

        seen_ids.add(sample_id)
        seen_hashes.add(mouth_roi_sha256)

        kind, entry_or_reason = classify_source(metadata, catalog)
        if kind == "excluded":
            exclusions.append(
                {
                    "sourceMetadata": str(metadata_path.resolve()),
                    "reason": str(entry_or_reason),
                }
            )
            continue

        if kind == "known":
            entry = entry_or_reason
            assert isinstance(entry, PhraseEntry)
            sample = _manifest_sample(
                sample_dir,
                metadata_path,
                mouth_roi_path,
                metadata,
                entry,
                mouth_roi_sha256,
            )
            known_by_phrase[entry.phrase_id].append(sample)
            if sample.source_intent != sample.intent:
                intent_mismatches += 1
        else:
            unknown.append(
                _manifest_sample(
                    sample_dir,
                    metadata_path,
                    mouth_roi_path,
                    metadata,
                    None,
                    mouth_roi_sha256,
                )
            )

    train: list[ManifestSample] = []
    calibration_known: list[ManifestSample] = []
    evaluation_known: list[ManifestSample] = []
    for phrase_samples in known_by_phrase.values():
        phrase_train, phrase_calibration, phrase_evaluation = split_known(
            _sort_samples(phrase_samples, seed), allow_small_dataset
        )
        train.extend(phrase_train)
        calibration_known.extend(phrase_calibration)
        evaluation_known.extend(phrase_evaluation)

    unknown_by_language = _unknown_counts_by_language(unknown)
    if not allow_small_dataset and not all(unknown_by_language.values()):
        raise ValueError(
            "official evidence requires 15 unrelated clips in both zh and en"
        )

    calibration_unknown, evaluation_unknown = split_unknown(
        _sort_samples(unknown, seed), allow_small_dataset
    )
    manifests = {
        "train.jsonl": train,
        "calibration-known.jsonl": calibration_known,
        "evaluation-known.jsonl": evaluation_known,
        "calibration-unknown.jsonl": calibration_unknown,
        "evaluation-unknown.jsonl": evaluation_unknown,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_sha256 = {
        name: _write_jsonl(output_dir / name, samples)
        for name, samples in manifests.items()
    }
    inventory = {
        "schemaVersion": INVENTORY_SCHEMA_VERSION,
        "evidentiary": not allow_small_dataset,
        "catalogSha256": catalog_sha256(catalog),
        "seed": seed,
        "counts": {
            "known": sum(len(samples) for samples in known_by_phrase.values()),
            "unknown": len(unknown),
            "unknownByLanguage": unknown_by_language,
            "excluded": len(exclusions),
            "byPhrase": {
                phrase_id: len(samples)
                for phrase_id, samples in known_by_phrase.items()
            },
            **{
                name.removesuffix(".jsonl"): len(samples)
                for name, samples in manifests.items()
            },
        },
        "exclusions": exclusions,
        "duplicates": duplicates,
        "intentMismatches": intent_mismatches,
        "manifestSha256": manifest_sha256,
        "splitMembership": {
            name: [sample.sample_id for sample in samples]
            for name, samples in manifests.items()
        },
    }
    (output_dir / "inventory.json").write_text(
        json.dumps(inventory, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return inventory
