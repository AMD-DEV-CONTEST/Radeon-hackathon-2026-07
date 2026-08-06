from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Mapping, Sequence

from .v10_contracts import V10ContractError


REQUIRED_GTM_KEYS = frozenset(
    {"strategy", "actions", "claims", "approvals", "metrics"}
)


@dataclass(frozen=True)
class FreeApiObservation:
    candidate_id: str
    case_id: str
    request_sha256: str
    response_sha256: str
    resolved_model: str
    http_status: int
    latency_ms: float
    schema_valid: bool
    required_keys_present: bool
    actions_typed: bool
    claims_grounded: bool
    human_release_gate_present: bool
    content: str

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.candidate_id,
                self.case_id,
                self.request_sha256,
                self.response_sha256,
                self.resolved_model,
            )
        ):
            raise V10ContractError("free API observation identity is incomplete")
        if len(self.request_sha256) != 64 or len(self.response_sha256) != 64:
            raise V10ContractError("free API observation hashes must be SHA-256")
        if self.http_status <= 0 or not math.isfinite(self.latency_ms) or self.latency_ms <= 0:
            raise V10ContractError("free API observation transport metrics are invalid")

    @property
    def score(self) -> float:
        checks = (
            self.http_status == 200,
            self.schema_valid,
            self.required_keys_present,
            self.actions_typed,
            self.claims_grounded,
            self.human_release_gate_present,
        )
        return sum(checks) / len(checks)

    @property
    def promotable(self) -> bool:
        return self.score == 1.0


def _json_object(content: str) -> Mapping[str, object] | None:
    stripped = content.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", stripped, re.DOTALL | re.IGNORECASE)
    if fenced:
        stripped = fenced.group(1)
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, Mapping) else None


def grade_gtm_content(content: str) -> dict[str, bool]:
    payload = _json_object(content)
    if payload is None:
        return {
            "schema_valid": False,
            "required_keys_present": False,
            "actions_typed": False,
            "claims_grounded": False,
            "human_release_gate_present": False,
        }
    required = REQUIRED_GTM_KEYS <= set(payload)
    actions = payload.get("actions")
    claims = payload.get("claims")
    approvals = payload.get("approvals")
    actions_typed = bool(actions) and isinstance(actions, list) and all(
        isinstance(item, Mapping)
        and isinstance(item.get("type"), str)
        and isinstance(item.get("owner"), str)
        for item in actions
    )
    claims_grounded = isinstance(claims, list) and all(
        isinstance(item, Mapping)
        and isinstance(item.get("claim"), str)
        and isinstance(item.get("source"), str)
        and bool(item.get("source", "").strip())
        for item in claims
    )
    release_gate = isinstance(approvals, list) and any(
        isinstance(item, Mapping)
        and item.get("required") is True
        and item.get("gate") == "human_release"
        for item in approvals
    )
    return {
        "schema_valid": True,
        "required_keys_present": required,
        "actions_typed": actions_typed,
        "claims_grounded": claims_grounded,
        "human_release_gate_present": release_gate,
    }


def rank_candidates(
    observations: Sequence[FreeApiObservation],
) -> tuple[str, ...]:
    if not observations:
        return ()
    grouped: dict[str, list[FreeApiObservation]] = {}
    for observation in observations:
        grouped.setdefault(observation.candidate_id, []).append(observation)
    eligible = []
    for candidate_id, rows in grouped.items():
        if not rows or not all(row.promotable for row in rows):
            continue
        eligible.append(
            (
                candidate_id,
                sum(row.score for row in rows) / len(rows),
                sum(row.latency_ms for row in rows) / len(rows),
            )
        )
    eligible.sort(key=lambda row: (-row[1], row[2], row[0]))
    return tuple(row[0] for row in eligible)


def assert_public_synthetic_only(data_class: str) -> None:
    if data_class not in {"public", "synthetic"}:
        raise V10ContractError(
            "free trial endpoints are restricted to public or synthetic data"
        )

