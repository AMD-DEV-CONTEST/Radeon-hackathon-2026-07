"""Exact allowlist and alias mapping for open-vocabulary prompts."""

from __future__ import annotations


class PromptClassMapper:
    """Map configured aliases while rejecting unapproved free-form prompts."""

    def __init__(
        self,
        allowlist: list[str],
        aliases: dict[str, str] | None = None,
    ) -> None:
        self._canonical = {item.casefold(): item for item in allowlist}
        self._aliases = {
            alias.casefold(): target
            for alias, target in (aliases or {}).items()
        }
        unknown_targets = set(self._aliases.values()) - set(allowlist)
        if unknown_targets:
            raise ValueError(
                f"Class aliases target non-allowlisted prompts: {sorted(unknown_targets)}"
            )

    def normalize(self, queries: list[str]) -> list[str]:
        normalized: list[str] = []
        rejected: list[str] = []
        for raw in queries:
            query = raw.strip()
            key = query.casefold()
            mapped = self._aliases.get(key)
            if mapped is None:
                mapped = self._canonical.get(key)
            if mapped is None:
                rejected.append(query)
                continue
            if mapped not in normalized:
                normalized.append(mapped)
        if rejected:
            raise ValueError(
                f"Open-vocabulary prompts are not allowlisted: {sorted(rejected)}"
            )
        if not normalized:
            raise ValueError("At least one allowlisted open-vocabulary prompt is required")
        return normalized

