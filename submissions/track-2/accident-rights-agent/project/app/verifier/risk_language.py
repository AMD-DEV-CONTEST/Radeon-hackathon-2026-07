"""Configurable Chinese/English high-risk language detection and safe rewrites."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.schemas.verification import (
    RiskAction,
    RiskLanguageMatch,
    RiskLanguageResult,
)


class RiskLanguagePolicy:
    def __init__(
        self,
        path: Path | str = Path("config/risk_language_policy.json"),
    ):
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if raw.get("schema_version") != 1:
            raise ValueError("Unsupported risk-language policy schema.")
        self.patterns = [
            {
                **item,
                "compiled": re.compile(str(item["regex"]), re.IGNORECASE),
            }
            for item in raw["patterns"]
        ]

    def scan(self, value: Any) -> RiskLanguageResult:
        matches: list[RiskLanguageMatch] = []
        rewritten: dict[str, str] = {}
        for path, text in _walk_strings(value):
            current = text
            for definition in self.patterns:
                for match in definition["compiled"].finditer(current):
                    action = RiskAction(definition["action"])
                    matches.append(
                        RiskLanguageMatch(
                            pattern_id=definition["pattern_id"],
                            matched_text=match.group(0),
                            action=action,
                            path=path,
                            suggested_rewrite=definition.get("suggested_rewrite"),
                        )
                    )
                    if (
                        action is RiskAction.REWRITE_REQUIRED
                        and definition.get("suggested_rewrite")
                    ):
                        current = definition["compiled"].sub(
                            definition["suggested_rewrite"], current
                        )
            if current != text:
                rewritten[path] = current
        return RiskLanguageResult(
            passed=not any(item.action is RiskAction.HARD_BLOCK for item in matches),
            matches=matches,
            rewritten_fields=rewritten,
        )

    def safe_text(self, text: str) -> tuple[str, list[str]]:
        result = self.scan(text)
        hard = [
            item.pattern_id
            for item in result.matches
            if item.action is RiskAction.HARD_BLOCK
        ]
        if hard:
            return "", hard
        return result.rewritten_fields.get("$", text), [
            item.pattern_id for item in result.matches
        ]


def _walk_strings(value: Any, path: str = "$"):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _walk_strings(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_strings(child, f"{path}[{index}]")
    elif isinstance(value, str):
        yield path, value
