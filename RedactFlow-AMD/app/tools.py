from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Pattern:
    kind: str
    regex: re.Pattern[str]
    replacement: str


PATTERNS = [
    Pattern("email", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I), "[EMAIL]"),
    Pattern("phone", re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)"), "[PHONE]"),
    Pattern("cn_id", re.compile(r"(?<!\d)\d{17}[0-9Xx](?!\d)"), "[ID_NUMBER]"),
    Pattern("api_key", re.compile(r"\b(?:sk|rk|api)[-_][A-Za-z0-9]{16,}\b", re.I), "[API_KEY]"),
    Pattern("ipv4", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "[IP_ADDRESS]"),
]


def scan_sensitive(text: str) -> list[dict]:
    findings: list[dict] = []
    for pattern in PATTERNS:
        for match in pattern.regex.finditer(text):
            findings.append(
                {
                    "kind": pattern.kind,
                    "value": match.group(0),
                    "start": match.start(),
                    "end": match.end(),
                    "replacement": pattern.replacement,
                }
            )
    findings.sort(key=lambda item: item["start"])
    return findings


def redact_text(text: str, findings: list[dict] | None = None) -> str:
    findings = findings if findings is not None else scan_sensitive(text)
    redacted = text
    for finding in sorted(findings, key=lambda item: item["start"], reverse=True):
        redacted = redacted[: finding["start"]] + finding["replacement"] + redacted[finding["end"] :]
    return redacted

