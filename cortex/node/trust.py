from __future__ import annotations

from datetime import datetime
from typing import Any


class TrustEngine:
    def __init__(
        self,
        default_org_reputation: float = 0.5,
        reputation_overrides: dict[str, float] | None = None,
        half_life_days: int = 90,
        min_trust_default: float = 0.3,
    ) -> None:
        self.default_org_reputation = default_org_reputation
        self.reputation_overrides = reputation_overrides or {}
        self.half_life_days = half_life_days
        self.min_trust_default = min_trust_default
        self._cache: dict[tuple[str, int], float] = {}

    def recency_decay(self, delta_t_seconds: float) -> float:
        return float(0.5 ** (delta_t_seconds / (self.half_life_days * 86400.0)))

    def _reputation(self, org: str) -> float:
        return float(self.reputation_overrides.get(org, self.default_org_reputation))

    def trust_for(self, article: Any, now: datetime, store: Any, graph_version: int = 0) -> float:
        key = (article.id, graph_version)
        if key in self._cache:
            return self._cache[key]
        rcy = self.recency_decay((now - article.provenance.timestamp).total_seconds())
        R = self._reputation(article.provenance.producer_org)
        has_org_sign = 1 if getattr(article, "org_signature", None) else 0
        has_source_hash = 1 if getattr(article, "provenance_source_data_hash", None) or \
                              getattr(article.provenance, "source_data_hash", None) else 0
        base = R * rcy * (1 + 0.1 * has_org_sign) * (1 + 0.05 * has_source_hash)
        source_trust = 0.0
        source_penalty = 0.0
        cites = getattr(article, "cites", None) or []
        if cites:
            cited_trusts: list[float] = []
            for c in cites:
                cited = store.get(c)
                if cited is None:
                    continue
                cited_trusts.append(self.trust_for(cited, now, store, graph_version))
            if cited_trusts:
                source_trust = sum(cited_trusts) / len(cited_trusts)
                source_penalty = sum(1 for t in cited_trusts if t < 0.2) * 0.1
        t = max(0.0, min(1.0, 0.6 * base + 0.4 * source_trust - source_penalty))
        self._cache[key] = t
        return t
