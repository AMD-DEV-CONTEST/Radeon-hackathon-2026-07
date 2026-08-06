"""Discovery fingerprint canonicalization and the retry envelope around it.

The fingerprint answers one question: did anything that could change the answer
actually change? Ticket 01 froze *which* fields it covers. This module freezes
*how* they are serialized, because the two are equally load-bearing — two callers
serializing the same logical input under different rules produce different
digests, and the cache then stops working while still appearing correct: every
search looks fresh, every repeat spends another model call, and nothing reports
a fault.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from typing import Any
from uuid import UUID

from app.experience_asset.domain.enums import DiscoveryFailureClass
from app.experience_asset.domain.relation import DiscoveryFingerprintV1

FINGERPRINT_SCHEMA_VERSION = "e5-fingerprint/v1"
FINGERPRINT_HASH_ALGORITHM = "sha256"
FINGERPRINT_UNICODE_FORM = "NFC"
FINGERPRINT_ENCODING = "utf-8"

# NFC, not NFKC. The lexical index uses NFKC because a search for a halfwidth
# digit should match its fullwidth twin. Identity is the opposite problem: NFKC
# folds those compatibility characters together, so two genuinely different
# model or prompt identifiers could normalize onto one digest, and an upgraded
# model would keep serving the previous model's cached NO_MATCH — the exact
# failure the fingerprint covers model identity to prevent.

MAX_DISCOVERY_ATTEMPTS = 3
DISCOVERY_LEASE_SECONDS = 120
RETRY_BACKOFF_BASE_SECONDS = 2.0

RETRYABLE_FAILURE_CLASSES: frozenset[DiscoveryFailureClass] = frozenset(
    {
        DiscoveryFailureClass.MODEL_UNAVAILABLE,
        DiscoveryFailureClass.MODEL_TIMED_OUT,
        DiscoveryFailureClass.MALFORMED_MODEL_OUTPUT,
        DiscoveryFailureClass.STORAGE_CONFLICT,
        DiscoveryFailureClass.LEASE_EXPIRED,
    }
)
"""Failure classes an explicit retry may follow.

`RUNTIME_VALIDATION_REJECTED` is excluded on purpose: the same inputs failed a
deterministic check, so the same fingerprint will fail it again. Retrying would
hammer local inference with a request that cannot succeed, and the budget would
be spent proving something the first attempt already established.

`LEASE_EXPIRED` is included: nothing is known about whether the model was ever
asked, so the question is genuinely unanswered and a retry can settle it.

`STALE_BINDING` is excluded for the opposite reason: the inputs are no longer
current, so the correct next step is a *new* fingerprint, not another attempt
under this one.
"""


def is_retryable(failure_class: DiscoveryFailureClass) -> bool:
    return failure_class in RETRYABLE_FAILURE_CLASSES


def retry_backoff_seconds(next_attempt_number: int) -> float:
    """Delay before attempt `next_attempt_number`, counting from 1."""
    if next_attempt_number < 1:
        raise ValueError("attempt numbers start at 1")
    if next_attempt_number == 1:
        return 0.0
    return RETRY_BACKOFF_BASE_SECONDS ** (next_attempt_number - 1)


def _canonical_text(value: str) -> str:
    return unicodedata.normalize(FINGERPRINT_UNICODE_FORM, value)


def _canonical_value(value: Any) -> Any:
    if isinstance(value, UUID):
        # Lowercase hyphenated. A UUID rendered in braces or uppercase is the
        # same identity, so allowing either would let one logical input hash two
        # ways depending on which caller built the record.
        return str(value).lower()
    if isinstance(value, str):
        return _canonical_text(value)
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        # Floats have no single decimal representation across platforms and
        # runtimes, so one would make the digest environment-dependent. No
        # frozen fingerprint field is a float; this refuses rather than guesses
        # if one is ever added.
        raise TypeError(
            "fingerprint fields must not be floats; encode the value as a "
            "string or an integer with a stated unit"
        )
    if value is None:
        # Null is rendered, never omitted. Dropping the key would make an absent
        # field and a present-but-null field hash identically.
        return None
    if isinstance(value, list):
        # Order is preserved rather than sorted here: the one list in the
        # frozen contract already carries a sort invariant of its own, and
        # re-sorting arbitrary lists would silently erase a meaningful order in
        # any field added later.
        return [_canonical_value(item) for item in value]
    if isinstance(value, dict):
        return {_canonical_text(str(key)): _canonical_value(item) for key, item in value.items()}
    raise TypeError(f"fingerprint fields must be JSON-canonical, got {type(value)!r}")


def canonical_fingerprint_payload(fingerprint: DiscoveryFingerprintV1) -> str:
    """Serialize the frozen fingerprint fields under one stated encoding.

    Rules, all load-bearing: keys sorted lexicographically so field order in the
    model definition cannot change the digest; no insignificant whitespace;
    non-ASCII preserved rather than escaped, then NFC-normalized; empty
    collections rendered as `[]` and nulls as `null` rather than omitted; UUIDs
    lowercase hyphenated; integers in decimal; floats refused.
    """
    payload = _canonical_value(fingerprint.model_dump(mode="python"))
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def compute_discovery_fingerprint(fingerprint: DiscoveryFingerprintV1) -> str:
    """Return the digest of one discovery input under the frozen encoding."""
    if fingerprint.fingerprint_schema_version != FINGERPRINT_SCHEMA_VERSION:
        raise ValueError(
            "fingerprint schema version mismatch; a digest computed under one "
            "version must never be compared against another"
        )
    payload = canonical_fingerprint_payload(fingerprint)
    return hashlib.new(
        FINGERPRINT_HASH_ALGORITHM, payload.encode(FINGERPRINT_ENCODING)
    ).hexdigest()
