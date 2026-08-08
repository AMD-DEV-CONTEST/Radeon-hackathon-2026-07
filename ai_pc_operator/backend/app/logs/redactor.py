"""Log redactor - removes sensitive information from logs."""

from __future__ import annotations

import re
from typing import Any


class LogRedactor:
    """Redacts sensitive information from logs."""

    # Patterns to redact
    SECRET_ASSIGNMENTS = [
        re.compile(r'\b(password|pwd)["\']?\s*[:=]\s*["\'][^"\']*["\']', re.IGNORECASE),
        re.compile(r'\b(token|api[_-]?key)["\']?\s*[:=]\s*["\'][^"\']*["\']', re.IGNORECASE),
    ]
    CREDIT_CARD_PATTERNS = [
        re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b"),
    ]
    SSN_PATTERNS = [
        re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    ]

    def redact(self, text: str) -> str:
        """Redact sensitive information from text."""
        if not isinstance(text, str):
            return text

        redacted = text

        for pattern in self.SECRET_ASSIGNMENTS:
            redacted = pattern.sub(lambda match: f'{match.group(1)}="[REDACTED]"', redacted)

        # Redact credit cards
        for pattern in self.CREDIT_CARD_PATTERNS:
            redacted = pattern.sub("[REDACTED_CC]", redacted)

        # Redact SSN
        for pattern in self.SSN_PATTERNS:
            redacted = pattern.sub("[REDACTED_SSN]", redacted)

        return redacted

    def redact_dict(self, data: Any) -> Any:
        """Redact sensitive information from nested dictionaries/lists."""
        if not isinstance(data, dict):
            if isinstance(data, list):
                return [self.redact_dict(item) for item in data]
            if isinstance(data, str):
                return self.redact(data)
            return data

        redacted = {}
        sensitive_keys = {
            "password", "pwd", "passwd",
            "token", "api_key", "secret",
            "credit_card", "cc_number",
            "ssn",
        }

        for key, value in data.items():
            if key.lower() in sensitive_keys:
                redacted[key] = "[REDACTED]"
            elif isinstance(value, str):
                redacted[key] = self.redact(value)
            elif isinstance(value, (dict, list)):
                redacted[key] = self.redact_dict(value)
            else:
                redacted[key] = value

        return redacted
