from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping, Sequence


SCHEMA = "ProofLaunchGTMGenomeLearningMemoryV1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_VERDICTS = {"promote", "repair", "retire"}


class GTMGenomeLearningMemoryError(ValueError):
    pass


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def compile_genome_learning_memory(observations: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not isinstance(observations, Sequence) or isinstance(observations, (str, bytes)) or len(observations) > 500:
        raise GTMGenomeLearningMemoryError("observations must be a bounded sequence")
    records = []
    seen: set[str] = set()
    for index, row in enumerate(observations):
        if not isinstance(row, Mapping):
            raise GTMGenomeLearningMemoryError(f"observations[{index}] must be an object")
        required = {
            "record_id", "genome_id", "verdict", "business_model", "platform", "category", "axis_pairs",
            "evidence_sha256", "approved_by", "human_approved",
        }
        if set(row) != required:
            raise GTMGenomeLearningMemoryError("observation fields do not match the closed contract")
        record_id = row["record_id"]
        if not isinstance(record_id, str) or not record_id.strip() or record_id in seen:
            raise GTMGenomeLearningMemoryError("record_id is invalid or duplicated")
        seen.add(record_id)
        if row["human_approved"] is not True:
            raise GTMGenomeLearningMemoryError("unapproved observations cannot enter learning memory")
        if row["verdict"] not in _VERDICTS:
            raise GTMGenomeLearningMemoryError("verdict is unsupported")
        if not isinstance(row["genome_id"], str) or not _SHA256.fullmatch(row["genome_id"]):
            raise GTMGenomeLearningMemoryError("genome_id must be a SHA-256 digest")
        if not isinstance(row["evidence_sha256"], str) or not _SHA256.fullmatch(row["evidence_sha256"]):
            raise GTMGenomeLearningMemoryError("evidence_sha256 must be a SHA-256 digest")
        if not isinstance(row["approved_by"], str) or not row["approved_by"].strip():
            raise GTMGenomeLearningMemoryError("approved_by is required")
        pairs = row["axis_pairs"]
        if not isinstance(pairs, list) or not 1 <= len(pairs) <= 3 or any(not isinstance(item, str) or ":" not in item for item in pairs):
            raise GTMGenomeLearningMemoryError("axis_pairs must contain one to three axis:value strings")
        records.append({field: row[field] for field in required if field != "human_approved"})
    payload = {
        "schema": SCHEMA,
        "record_count": len(records),
        "records": records,
        "automatic_promotion_count": 0,
        "human_approval_required": True,
        "current_run_mutation_allowed": False,
        "truth_boundary": "Memory contains named-human-approved mechanism priors only. It does not prove causality, virality, transferability or authorize current-run mutation.",
    }
    payload["content_sha256"] = _digest(payload)
    verify_genome_learning_memory(payload)
    return payload


def verify_genome_learning_memory(payload: Mapping[str, Any]) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != SCHEMA or supplied != _digest(unsigned):
        raise GTMGenomeLearningMemoryError("learning memory seal is invalid")
    if payload.get("record_count") != len(payload.get("records", [])):
        raise GTMGenomeLearningMemoryError("learning memory count drifted")
    if payload.get("automatic_promotion_count") != 0 or payload.get("current_run_mutation_allowed") is not False:
        raise GTMGenomeLearningMemoryError("learning memory enabled unsafe mutation")


__all__ = ["GTMGenomeLearningMemoryError", "SCHEMA", "compile_genome_learning_memory", "verify_genome_learning_memory"]
