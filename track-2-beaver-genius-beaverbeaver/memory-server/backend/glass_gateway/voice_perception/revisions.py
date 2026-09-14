from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def voice_model_revision_from_config(
    config_or_path: dict[str, Any] | str | Path,
) -> str:
    """Return the voice worker contract revision without importing its engine."""

    config = (
        config_or_path
        if isinstance(config_or_path, dict)
        else json.loads(Path(config_or_path).read_text(encoding="utf-8"))
    )
    payload = "\n".join(
        (
            str(config["diarization_model"]),
            str(config["diarization_model_revision"]),
            str(config["diarization_model_artifact_sha256"]),
            str(config["embedding_model"]),
            str(config["embedding_source_revision"]),
            str(config["embedding_model_artifact_sha256"]),
            str(config["candidate_threshold"]),
            str(config["minimum_turn_ms"]),
            str(config["speaker_count_projection"]["minimum_speaker_activity_ms"]),
            str(config["overlap_policy"]),
            str(config.get("engine_contract_version") or "overlap-turn-v1"),
            str((config.get("runtime_artifacts") or {})["wespeaker_config_sha256"]),
            str((config.get("runtime_artifacts") or {})["postprocessing_sha256"]),
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
