"""Context Resolution — uses prior conversation/session context to fill gaps.

When a user says "open it" or "delete that", the Intent Engine needs to
know what "it" or "that" refers to. Context Resolution:

  - Maintains a short-term context (last N commands and their results)
  - Resolves pronouns (it, that, this, them) to recent entities
  - Resolves implicit references ("the file", "the app")
  - Resolves follow-up commands ("now close it" → close what was opened)
  - Provides default values for common parameters (e.g. "Downloads" folder)

The context is in-memory and per-session. It does not persist across
backend restarts.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional


@dataclass
class ContextEntry:
    """A single entry in the context history."""
    text: str
    intent: str
    params: Dict[str, Any]
    entities: List[Dict[str, Any]] = field(default_factory=list)
    result: Any = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict:
        return {
            "text": self.text,
            "intent": self.intent,
            "params": self.params,
            "entities": self.entities,
            "timestamp": self.timestamp,
        }


@dataclass
class ResolutionResult:
    """Result of context resolution."""
    resolved_params: Dict[str, Any]
    resolutions: List[Dict[str, Any]] = field(default_factory=list)
    # Each resolution: { param, source: 'context'|'default', value, confidence, ref }


class ContextResolver:
    """Resolves implicit references using prior context."""

    # Pronouns that refer to the most recent entity of a given type
    PRONOUNS = {
        "it": "last",
        "that": "last",
        "this": "last",
        "them": "last_plural",
        "those": "last_plural",
        "these": "last_plural",
    }

    # Default values for common parameters when not specified
    DEFAULTS = {
        "path": "C:\\Users\\brigh\\Downloads",
        "downloads_path": "C:\\Users\\brigh\\Downloads",
        "desktop_path": "C:\\Users\\brigh\\Desktop",
        "documents_path": "C:\\Users\\brigh\\Documents",
        "name": "chrome",
        "url": "https://www.google.com",
    }

    # Path keywords → default path mapping
    PATH_KEYWORDS = {
        "download": "C:\\Users\\brigh\\Downloads",
        "downloads": "C:\\Users\\brigh\\Downloads",
        "desktop": "C:\\Users\\brigh\\Desktop",
        "documents": "C:\\Users\\brigh\\Documents",
        "pictures": "C:\\Users\\brigh\\Pictures",
        "music": "C:\\Users\\brigh\\Music",
        "videos": "C:\\Users\\brigh\\Videos",
    }

    def __init__(self, max_history: int = 10):
        self.history: Deque[ContextEntry] = deque(maxlen=max_history)
        self._session_vars: Dict[str, Any] = {}

    def add_entry(self, entry: ContextEntry) -> None:
        """Add a command entry to the context history."""
        self.history.append(entry)

    def set_var(self, key: str, value: Any) -> None:
        """Set a session variable."""
        self._session_vars[key] = value

    def get_var(self, key: str, default: Any = None) -> Any:
        """Get a session variable."""
        return self._session_vars.get(key, default)

    def resolve(self, text: str, intent: str, params: Dict[str, Any]) -> ResolutionResult:
        """Resolve implicit references in the command.

        Returns ResolutionResult with resolved params and a list of
        resolutions applied.
        """
        resolved = dict(params)
        resolutions: List[Dict[str, Any]] = []
        text_lower = text.lower()

        # 1. Resolve pronouns
        for pronoun, ref_type in self.PRONOUNS.items():
            if re_search_word(pronoun, text_lower):
                ref_value = self._resolve_pronoun(ref_type, intent)
                if ref_value is not None:
                    # Apply to the most relevant param for this intent
                    target_param = self._pronoun_target_param(intent)
                    if target_param and target_param not in resolved:
                        resolved[target_param] = ref_value
                        resolutions.append({
                            "param": target_param,
                            "source": "context",
                            "value": ref_value,
                            "confidence": 0.7,
                            "ref": pronoun,
                        })

        # 2. Apply path keyword defaults
        if "path" in resolved or intent in ("list_files", "delete_files"):
            for keyword, default_path in self.PATH_KEYWORDS.items():
                if re_search_word(keyword, text_lower):
                    if not resolved.get("path") or resolved["path"] == ".":
                        resolved["path"] = default_path
                        resolutions.append({
                            "param": "path",
                            "source": "default",
                            "value": default_path,
                            "confidence": 0.9,
                            "ref": keyword,
                        })
                    break

        # 3. Apply built-in defaults for missing params
        for param_name, default_value in self.DEFAULTS.items():
            if param_name in resolved and (resolved[param_name] is None or resolved[param_name] == ""):
                resolved[param_name] = default_value
                resolutions.append({
                    "param": param_name,
                    "source": "default",
                    "value": default_value,
                    "confidence": 0.8,
                    "ref": None,
                })

        # 4. Carry forward from last command if intent is a follow-up
        if self.history and self._is_followup(text_lower):
            last = self.history[-1]
            for param_name, param_value in last.params.items():
                if param_name not in resolved or not resolved[param_name]:
                    # Only carry forward if the intent is related
                    if self._intents_related(intent, last.intent):
                        resolved[param_name] = param_value
                        resolutions.append({
                            "param": param_name,
                            "source": "context",
                            "value": param_value,
                            "confidence": 0.6,
                            "ref": "previous_command",
                        })

        return ResolutionResult(
            resolved_params=resolved,
            resolutions=resolutions,
        )

    def _resolve_pronoun(self, ref_type: str, current_intent: str) -> Optional[Any]:
        """Resolve a pronoun to a recent entity value."""
        if not self.history:
            return None

        # Look back through history for a matching entity
        for entry in reversed(self.history):
            # Match by intent compatibility
            if not self._intents_related(current_intent, entry.intent):
                continue
            # Return the most relevant param value
            for param_name, param_value in entry.params.items():
                if param_value:
                    return param_value
        return None

    def _pronoun_target_param(self, intent: str) -> Optional[str]:
        """Which param a pronoun should fill for a given intent."""
        mapping = {
            "open_website": "url",
            "open_app": "name",
            "browser_close": None,
            "delete_files": "path",
            "list_files": "path",
            "screen_click": "text",
            "search_web": "query",
            "download_file": "url",
            "login": "site",
        }
        return mapping.get(intent)

    def _is_followup(self, text_lower: str) -> bool:
        """Check if the command is a follow-up to a previous one."""
        followup_cues = [
            "now ", "then ", "also ", "too",
            "after that", "next", "again",
        ]
        return any(cue in text_lower for cue in followup_cues)

    def _intents_related(self, intent_a: str, intent_b: str) -> bool:
        """Check if two intents are related (for context carry-forward)."""
        related_groups = [
            {"open_website", "browser_close", "search_web", "download_file", "login"},
            {"open_app", "browser_close"},
            {"list_files", "delete_files"},
            {"screen_scan", "screen_click"},
        ]
        for group in related_groups:
            if intent_a in group and intent_b in group:
                return True
        return False

    def clear(self) -> None:
        """Clear all context."""
        self.history.clear()
        self._session_vars.clear()

    def snapshot(self) -> Dict[str, Any]:
        """Get a snapshot of the current context."""
        return {
            "history": [e.to_dict() for e in self.history],
            "session_vars": dict(self._session_vars),
        }


def re_search_word(word: str, text: str) -> bool:
    """Check if a word appears as a whole word in text."""
    import re
    return bool(re.search(rf"\b{re.escape(word)}\b", text))
