"""Live-model response records.

Closed-set status tokens + a frozen ``LiveModelResponse`` dataclass
that captures whatever a provider returned without trusting it. The
record is the only output the compat harness produces; downstream
rungs consume it under quarantine.
"""

from __future__ import annotations

import enum
import json
from dataclasses import asdict, dataclass, field

LIVE_MODEL_RESPONSE_STATUS_TOKENS = (
    "MODEL_COMPAT_HARNESS_PASSED",
    "MODEL_COMPAT_HARNESS_BLOCKED_PROVIDER_UNAVAILABLE",
    "MODEL_COMPAT_HARNESS_BLOCKED_BAD_RESPONSE",
    "MODEL_COMPAT_HARNESS_BLOCKED_TIMEOUT",
    "MODEL_COMPAT_HARNESS_BLOCKED_SCHEMA_INVALID",
    "MODEL_COMPAT_HARNESS_BLOCKED_OVERSIZED",
    "MODEL_COMPAT_HARNESS_BLOCKED_EMPTY",
)


class ResponseKind(str, enum.Enum):
    OK = "MODEL_COMPAT_HARNESS_PASSED"
    PROVIDER_UNAVAILABLE = "MODEL_COMPAT_HARNESS_BLOCKED_PROVIDER_UNAVAILABLE"
    BAD_RESPONSE = "MODEL_COMPAT_HARNESS_BLOCKED_BAD_RESPONSE"
    TIMEOUT = "MODEL_COMPAT_HARNESS_BLOCKED_TIMEOUT"
    SCHEMA_INVALID = "MODEL_COMPAT_HARNESS_BLOCKED_SCHEMA_INVALID"
    OVERSIZED = "MODEL_COMPAT_HARNESS_BLOCKED_OVERSIZED"
    EMPTY = "MODEL_COMPAT_HARNESS_BLOCKED_EMPTY"


@dataclass(frozen=True)
class LiveModelResponse:
    status: str
    provider: str
    model_id: str
    task_class: str
    elapsed_ms: int = 0
    response_chars: int = 0
    schema_id: str = ""
    payload: dict[str, object] = field(default_factory=dict)
    trusted: bool = False  # always False at this rung
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @property
    def is_ok(self) -> bool:
        return self.status == "MODEL_COMPAT_HARNESS_PASSED"

    @property
    def is_blocked(self) -> bool:
        return self.status.startswith("MODEL_COMPAT_HARNESS_BLOCKED_")
