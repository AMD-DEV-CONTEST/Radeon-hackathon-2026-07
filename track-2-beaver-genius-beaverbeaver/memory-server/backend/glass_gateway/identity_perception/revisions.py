from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def model_revision_from_config(config_or_path: dict[str, Any] | str | Path) -> str:
    """Return the face worker contract revision without importing its engine."""

    config = (
        config_or_path
        if isinstance(config_or_path, dict)
        else json.loads(Path(config_or_path).read_text(encoding="utf-8"))
    )
    model = config["model"]
    payload = "\n".join(
        (
            str(model["pack"]),
            str(model["detector_sha256"]),
            str(model["recognizer_sha256"]),
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
