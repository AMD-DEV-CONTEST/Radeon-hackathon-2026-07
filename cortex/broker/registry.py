"""Organization registry loaded from org_registry.json."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class OrgRecord:
    did: str
    pubkey: str
    name: str
    topics: list[str] = field(default_factory=list)


class OrgRegistry:
    def __init__(self, records: dict[str, OrgRecord] | None = None) -> None:
        self._records: dict[str, OrgRecord] = dict(records or {})

    def get(self, org_did: str) -> OrgRecord | None:
        return self._records.get(org_did)

    def all_dids(self) -> list[str]:
        return list(self._records.keys())

    @classmethod
    def from_json_file(cls, path: Path) -> OrgRegistry:
        text = Path(path).read_text()
        raw = json.loads(text)
        records: dict[str, OrgRecord] = {}
        for did, body in raw.items():
            records[did] = OrgRecord(
                did=did,
                pubkey=body["pubkey"],
                name=body.get("name", ""),
                topics=list(body.get("topics", [])),
            )
        return cls(records)
