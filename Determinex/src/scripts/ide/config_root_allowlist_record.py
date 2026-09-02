"""Records for CLAUDE_CONFIG_ROOT_ALLOWLIST_LOCK_001.

CLAUDE-AUTH-011 deferred risk: local model config save path is
inside the repo and there is no allowlist/bounded policy on which
config_root / workspace_root values are acceptable for Claude
IDE repair flows.

This rung defines a bounded allowlist and a normalizer that:

  * resolves the root to an absolute, real path
  * refuses path traversal (``..`` in the original input)
  * refuses dangerous/system roots (C:\\, /, /etc, /usr, /System,
    /Windows, C:\\Windows, C:\\Program Files, ...)
  * refuses untrusted config (root not inside any allowlisted parent)
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

CONFIG_ROOT_ALLOWLIST_STATUS_TOKENS = (
    "CONFIG_ROOT_ALLOWLIST_PASSED",
    "CONFIG_ROOT_BLOCKED_DISALLOWED_ROOT",
    "CONFIG_ROOT_BLOCKED_PATH_TRAVERSAL",
    "CONFIG_ROOT_BLOCKED_UNTRUSTED_CONFIG",
    "CONFIG_ROOT_BLOCKED_MALFORMED_PATH",
)


@dataclass(frozen=True)
class ConfigRootAllowlistRecord:
    decision: str
    requested_root: str
    resolved_root: str
    allowed_parent: str
    source_mutation_authorized: bool = False
    training_eligible: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @property
    def is_passed(self) -> bool:
        return self.decision == "CONFIG_ROOT_ALLOWLIST_PASSED"

    @property
    def is_blocked(self) -> bool:
        return self.decision.startswith("CONFIG_ROOT_BLOCKED_")


__all__ = [
    "CONFIG_ROOT_ALLOWLIST_STATUS_TOKENS",
    "ConfigRootAllowlistRecord",
]
