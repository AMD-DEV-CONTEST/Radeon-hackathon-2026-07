"""
fleet.protocol -- the contribution wire schema (versioned, oracle-verifiable).
=============================================================================
A *shard* is one sealed upload from one contributor. It carries a list of *items*;
each item is a self-contained, re-verifiable unit:

    item = {
      "lang":   "rust" | "go" | "python" | "typescript" | ...,
      "files":  { "<relpath>": "<obfuscated source>" },   # a runnable workdir
      "pair":   { "conversations": [...], "metadata": {...} },  # ShareGPT training pair
      "origin": "verified_search" | "repair" | "flywheel" | ...,
      "id":     "<sha256 of canonical files+pair>",         # dedup key
    }

Load-bearing invariant: `files` must reconstruct a workdir that the node can drop
into a temp dir and run `get_oracle(lang).verify(workdir)` against. If it does not
PASS on the node, the item is dropped (see ingest_verify). Identifiers in both
`files` and `pair` are Cloak-obfuscated on the contributor side -- no real names
leave the contributor's machine.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from . import PROTOCOL_VERSION


def item_id(lang: str, files: dict[str, str], pair: dict[str, Any]) -> str:
    canon = json.dumps(
        {"lang": lang, "files": files, "pair": pair},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canon).hexdigest()


@dataclass
class ContributionItem:
    lang: str
    files: dict[str, str]
    pair: dict[str, Any]
    origin: str = "unknown"
    id: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = item_id(self.lang, self.files, self.pair)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict[str, Any]) -> ContributionItem:
        return ContributionItem(
            lang=d["lang"],
            files=d["files"],
            pair=d["pair"],
            origin=d.get("origin", "unknown"),
            id=d.get("id", ""),
        )


@dataclass
class Shard:
    items: list[ContributionItem]
    protocol_version: int = PROTOCOL_VERSION
    determinex_version: str = ""
    cloak_applied: bool = True
    created_at: float = field(default_factory=time.time)
    # NO contributor PII. An optional self-chosen handle only; default anonymous.
    contributor_handle: str = "anonymous"
    consent: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["items"] = [i.to_dict() for i in self.items]
        return d

    @staticmethod
    def from_dict(d: dict[str, Any]) -> Shard:
        s = Shard(items=[ContributionItem.from_dict(i) for i in d.get("items", [])])
        for k in (
            "protocol_version",
            "determinex_version",
            "cloak_applied",
            "created_at",
            "contributor_handle",
            "consent",
        ):
            if k in d:
                setattr(s, k, d[k])
        return s

    def summary(self) -> str:
        langs: dict[str, int] = {}
        for i in self.items:
            langs[i.lang] = langs.get(i.lang, 0) + 1
        parts = ", ".join(f"{n}×{l}" for l, n in sorted(langs.items()))
        return f"{len(self.items)} item(s) [{parts}]"
