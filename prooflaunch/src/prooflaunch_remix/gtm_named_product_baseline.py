from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from .files import atomic_write_bytes, atomic_write_text, sha256_file


CAPTURE_SCHEMA = "ProofLaunchNamedProductBaselineCaptureV1"
KIT_SCHEMA = "ProofLaunchNamedProductBaselineCaptureKitV1"
REGISTRY_SCHEMA = "ProofLaunchNamedProductBaselineRegistryV1"
ALLOWED_ACQUISITION_METHODS = {
    "authorized_product_use",
    "user_owned_export",
    "official_public_demo",
}
REQUIRED_ATTESTATIONS = (
    "authorized_to_evaluate_and_retain",
    "same_frozen_brief_without_hidden_editing",
    "provider_and_version_recorded_truthfully",
)
_SLOT_ID = re.compile(r"^pk-[0-9a-f]{16}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class NamedProductBaselineError(ValueError):
    pass


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def content_sha256(value: Mapping[str, Any]) -> str:
    unsigned = dict(value)
    unsigned.pop("content_sha256", None)
    return hashlib.sha256(canonical_json_bytes(unsigned)).hexdigest()


def _verify_seal(payload: object, *, schema: str, label: str) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("schema") != schema:
        raise NamedProductBaselineError(f"{label} schema is invalid")
    supplied = payload.get("content_sha256")
    if not isinstance(supplied, str) or not _DIGEST.fullmatch(supplied):
        raise NamedProductBaselineError(f"{label} digest is missing")
    if content_sha256(payload) != supplied:
        raise NamedProductBaselineError(f"{label} digest is invalid")
    return payload


def validate_kit_manifest(payload: object, *, kit_root: Path | None = None) -> dict[str, Any]:
    manifest = _verify_seal(payload, schema=KIT_SCHEMA, label="capture kit")
    slots = manifest.get("capture_slots")
    if (
        manifest.get("category_count") != 13
        or manifest.get("capture_slot_count") != 130
        or not isinstance(slots, list)
        or len(slots) != 130
        or manifest.get("network_submission_enabled") is not False
        or manifest.get("automatic_product_execution_enabled") is not False
        or manifest.get("automatic_pk_promotion_enabled") is not False
        or manifest.get("human_review_required") is not True
    ):
        raise NamedProductBaselineError("capture kit contract is incomplete")
    slot_ids: set[str] = set()
    row_keys: set[tuple[str, str]] = set()
    for slot in slots:
        if not isinstance(slot, dict):
            raise NamedProductBaselineError("capture slot is invalid")
        slot_id = slot.get("capture_slot_id")
        category_id = slot.get("category_id")
        product = slot.get("reference_product")
        if (
            not isinstance(slot_id, str)
            or not _SLOT_ID.fullmatch(slot_id)
            or slot_id in slot_ids
            or not isinstance(category_id, str)
            or not category_id
            or not isinstance(product, str)
            or not product
            or (category_id, product) in row_keys
            or not _DIGEST.fullmatch(str(slot.get("frozen_brief_sha256", "")))
            or not isinstance(slot.get("allowed_extensions"), list)
            or not slot["allowed_extensions"]
            or not isinstance(slot.get("maximum_artifact_bytes"), int)
            or slot["maximum_artifact_bytes"] <= 0
            or slot.get("status") != "awaiting_authorized_baseline"
        ):
            raise NamedProductBaselineError("capture slot contract is invalid")
        slot_ids.add(slot_id)
        row_keys.add((category_id, product))
    if kit_root is not None:
        root = kit_root.resolve(strict=True)
        inventory = manifest.get("files")
        if not isinstance(inventory, dict):
            raise NamedProductBaselineError("capture kit file inventory is missing")
        for relative, metadata in inventory.items():
            if not isinstance(relative, str) or not isinstance(metadata, dict):
                raise NamedProductBaselineError("capture kit file inventory is invalid")
            path = (root / relative).resolve(strict=True)
            try:
                path.relative_to(root)
            except ValueError as error:
                raise NamedProductBaselineError("capture kit file escaped its root") from error
            if path.is_symlink() or not path.is_file():
                raise NamedProductBaselineError("capture kit file is missing or unsafe")
            if path.stat().st_size != metadata.get("bytes") or sha256_file(path) != metadata.get("sha256"):
                raise NamedProductBaselineError("capture kit file integrity check failed")
    return manifest


def validate_capture(
    payload: object,
    *,
    manifest: Mapping[str, Any],
    artifact_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    capture = _verify_seal(payload, schema=CAPTURE_SCHEMA, label="baseline capture")
    slots = {
        item["capture_slot_id"]: item
        for item in manifest.get("capture_slots", [])
        if isinstance(item, dict) and isinstance(item.get("capture_slot_id"), str)
    }
    slot = slots.get(capture.get("capture_slot_id"))
    if slot is None:
        raise NamedProductBaselineError("baseline capture slot is unknown")
    equality_fields = (
        "category_id",
        "reference_product",
        "reference_product_url",
        "frozen_brief_sha256",
    )
    if any(capture.get(field) != slot.get(field) for field in equality_fields):
        raise NamedProductBaselineError("baseline capture does not match its frozen slot")
    method = capture.get("acquisition_method")
    if method not in ALLOWED_ACQUISITION_METHODS:
        raise NamedProductBaselineError("baseline acquisition method is not admitted")
    operator = capture.get("operator_id")
    version = capture.get("provider_model_or_version")
    if not isinstance(operator, str) or not (3 <= len(operator.strip()) <= 120):
        raise NamedProductBaselineError("named operator identity is required")
    if not isinstance(version, str) or not (1 <= len(version.strip()) <= 240):
        raise NamedProductBaselineError("provider/model/version is required")
    captured_at = capture.get("captured_at")
    try:
        parsed = datetime.fromisoformat(str(captured_at).replace("Z", "+00:00"))
    except ValueError as error:
        raise NamedProductBaselineError("capture timestamp is invalid") from error
    if parsed.tzinfo is None:
        raise NamedProductBaselineError("capture timestamp must include a timezone")
    attestations = capture.get("rights_attestation")
    if not isinstance(attestations, dict) or any(attestations.get(key) is not True for key in REQUIRED_ATTESTATIONS):
        raise NamedProductBaselineError("all baseline rights and fidelity attestations are required")
    artifact = capture.get("artifact")
    if not isinstance(artifact, dict):
        raise NamedProductBaselineError("baseline artifact metadata is missing")
    path = artifact_path.resolve(strict=True)
    if path.is_symlink() or not path.is_file():
        raise NamedProductBaselineError("baseline artifact is missing or unsafe")
    if path.name != artifact.get("name"):
        raise NamedProductBaselineError("baseline artifact filename does not match the receipt")
    extension = path.suffix.casefold()
    if extension not in set(slot["allowed_extensions"]):
        raise NamedProductBaselineError("baseline artifact type is not admitted for this category")
    size = path.stat().st_size
    if size <= 0 or size > slot["maximum_artifact_bytes"]:
        raise NamedProductBaselineError("baseline artifact size is outside the admitted range")
    if artifact.get("bytes") != size or artifact.get("sha256") != sha256_file(path):
        raise NamedProductBaselineError("baseline artifact bytes do not match the receipt")
    if not _DIGEST.fullmatch(str(artifact.get("sha256", ""))):
        raise NamedProductBaselineError("baseline artifact digest is invalid")
    return capture, slot


def import_capture(
    *,
    manifest_path: Path,
    capture_path: Path,
    artifact_path: Path,
    store_root: Path,
) -> dict[str, Any]:
    if manifest_path.is_symlink() or capture_path.is_symlink() or artifact_path.is_symlink():
        raise NamedProductBaselineError("symlinked input is not admitted")
    manifest = validate_kit_manifest(
        json.loads(manifest_path.read_text(encoding="utf-8")),
        kit_root=manifest_path.parent,
    )
    capture, slot = validate_capture(
        json.loads(capture_path.read_text(encoding="utf-8")),
        manifest=manifest,
        artifact_path=artifact_path,
    )
    store = store_root.resolve()
    store.mkdir(parents=True, exist_ok=True)
    target = store / capture["capture_slot_id"]
    target.mkdir(mode=0o700, exist_ok=True)
    # Preserve the provider's original export filename. Renaming every capture to
    # ``baseline.<ext>`` breaks the receipt's immutable ``artifact.name`` binding
    # and makes a real import fail during registry recompilation.
    artifact_target = target / artifact_path.name
    receipt_target = target / "capture.json"
    if artifact_target.exists() or receipt_target.exists():
        if (
            artifact_target.is_file()
            and receipt_target.is_file()
            and sha256_file(artifact_target) == capture["artifact"]["sha256"]
            and json.loads(receipt_target.read_text(encoding="utf-8")) == capture
        ):
            return _compile_registry(manifest, store)
        raise NamedProductBaselineError("baseline slot is immutable and already contains different bytes")
    atomic_write_bytes(artifact_target, artifact_path.read_bytes())
    atomic_write_text(receipt_target, json.dumps(capture, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return _compile_registry(manifest, store)


def _compile_registry(manifest: Mapping[str, Any], store: Path) -> dict[str, Any]:
    captures: list[dict[str, Any]] = []
    for receipt_path in sorted(store.glob("pk-*/capture.json")):
        capture = json.loads(receipt_path.read_text(encoding="utf-8"))
        artifact_candidates = [
            path for path in receipt_path.parent.iterdir()
            if path.name != "capture.json" and path.is_file()
        ]
        if len(artifact_candidates) != 1:
            raise NamedProductBaselineError("stored baseline artifact inventory is invalid")
        validated, _ = validate_capture(capture, manifest=manifest, artifact_path=artifact_candidates[0])
        captures.append(
            {
                "capture_slot_id": validated["capture_slot_id"],
                "category_id": validated["category_id"],
                "reference_product": validated["reference_product"],
                "artifact_sha256": validated["artifact"]["sha256"],
                "capture_receipt_sha256": sha256_file(receipt_path),
                "status": "authorized_baseline_present_review_not_started",
            }
        )
    core: dict[str, Any] = {
        "schema": REGISTRY_SCHEMA,
        "source_capture_kit_sha256": manifest["content_sha256"],
        "capture_slot_count": 130,
        "authorized_baseline_count": len(captures),
        "remaining_baseline_count": 130 - len(captures),
        "captures": captures,
        "completed_product_pk_rows": 0,
        "submitted_human_review_count": 0,
        "effect_aligned_category_count": 0,
        "automatic_pairing_enabled": False,
        "automatic_pk_promotion_enabled": False,
        "human_review_required": True,
        "truth_boundary": (
            "An imported file proves only that an authorized, same-brief named-product baseline "
            "was captured and hash-bound. It is not a blind preference result, 4A proof, product "
            "victory, publication, lift or revenue evidence."
        ),
    }
    core["content_sha256"] = content_sha256(core)
    atomic_write_text(store / "registry.json", json.dumps(core, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return core
