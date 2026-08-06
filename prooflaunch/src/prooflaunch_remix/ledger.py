from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class LedgerEvent:
    sequence: int
    at: str
    run_id: str
    stage: str
    kind: str
    payload: dict[str, Any]
    previous_hash: str
    event_hash: str


class EvidenceLedger:
    """Append-only JSONL ledger with deterministic hash chaining."""

    def __init__(self, path: Path, run_id: str) -> None:
        self.path = path
        self.run_id = run_id
        self.sequence = 0
        self.previous_hash = "GENESIS"
        path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, stage: str, kind: str, payload: dict[str, Any]) -> LedgerEvent:
        self.sequence += 1
        core = {
            "sequence": self.sequence,
            "at": datetime.now(timezone.utc).isoformat(),
            "run_id": self.run_id,
            "stage": stage,
            "kind": kind,
            "payload": payload,
            "previous_hash": self.previous_hash,
        }
        digest = hashlib.sha256(canonical_json(core).encode("utf-8")).hexdigest()
        event = LedgerEvent(**core, event_hash=digest)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(canonical_json(asdict(event)) + "\n")
        self.previous_hash = digest
        return event

    @staticmethod
    def verify(path: Path) -> bool:
        if not path.is_file():
            return False
        previous = "GENESIS"
        expected_sequence = 1
        try:
            for raw_line in path.read_text(encoding="utf-8").splitlines():
                event = json.loads(raw_line)
                digest = event.pop("event_hash")
                if event["sequence"] != expected_sequence:
                    return False
                if event["previous_hash"] != previous:
                    return False
                if (
                    hashlib.sha256(canonical_json(event).encode("utf-8")).hexdigest()
                    != digest
                ):
                    return False
                previous = digest
                expected_sequence += 1
        except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError):
            return False
        return expected_sequence > 1
