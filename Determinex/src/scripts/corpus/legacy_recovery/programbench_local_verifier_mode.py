from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class LocalVerifierMode:
    allowed: bool
    reason: str
    command: str = ""
    limitations: list[str] = field(default_factory=list)
    verifier_scope: str = "local_replay"
    declared: bool = False


def evaluate_local_verifier(candidate: dict[str, Any], root: Path) -> LocalVerifierMode:
    """Return whether a candidate explicitly supports local no-image replay."""
    metadata = _metadata(candidate, root)
    if metadata.get("local_verifier_allowed") is not True:
        return LocalVerifierMode(False, "local_verifier_not_declared", declared=bool(metadata))
    command = str(metadata.get("local_verifier_command") or "").strip()
    if not command:
        return LocalVerifierMode(False, "local_verifier_command_missing", declared=True)
    if metadata.get("network_required") is True:
        return LocalVerifierMode(False, "local_verifier_requires_network", declared=True)
    if metadata.get("deterministic") is False:
        return LocalVerifierMode(False, "local_verifier_not_deterministic", declared=True)
    fixtures = metadata.get("required_fixtures") or []
    missing = [fixture for fixture in fixtures if not (root / str(fixture)).exists()]
    if missing:
        return LocalVerifierMode(
            False, "local_verifier_fixtures_missing:" + ",".join(map(str, missing)), declared=True
        )
    return LocalVerifierMode(
        True,
        "explicit_local_verifier_metadata",
        command=command,
        limitations=[
            "verifier_scope=local_replay",
            "not_official_programbench_score",
        ],
        declared=True,
    )


def _metadata(candidate: dict[str, Any], root: Path) -> dict[str, Any]:
    inline = candidate.get("local_verifier")
    if isinstance(inline, dict):
        return inline
    for name in ("local_verifier.json", "replay_verifier.json"):
        path = root / name
        if not path.is_file():
            continue
        try:
            import json

            data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        if isinstance(data, dict):
            return data
    return {}
