"""Local Q&A dataset loading."""

from pathlib import Path

import orjson

from buildguard.rag.schemas import QAExample


def load_qa_dataset(path: Path) -> list[QAExample]:
    """Load a JSON array or one JSON object per line."""
    source = path.resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Q&A dataset does not exist: {source}")
    raw = source.read_bytes().strip()
    if not raw:
        return []
    if raw.startswith(b"["):
        payload = orjson.loads(raw)
        if not isinstance(payload, list):
            raise ValueError("Q&A JSON root must be a list")
        return [QAExample.model_validate(item) for item in payload]
    return [
        QAExample.model_validate(orjson.loads(line))
        for line in raw.splitlines()
        if line.strip()
    ]

