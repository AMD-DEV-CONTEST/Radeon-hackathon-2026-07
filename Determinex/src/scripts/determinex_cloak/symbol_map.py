"""
determinex_cloak/symbol_map.py — Component 3: SymbolMap.

Deterministic bidirectional mapping: private identifier → x_NNNN token.
Sorted case-insensitively so the same identifier always gets the same token
regardless of insertion order (stable across parallel workers).
"""

from __future__ import annotations

import dataclasses


@dataclasses.dataclass
class SymbolMap:
    forward: dict[str, str]  # original → x_NNNN
    reverse: dict[str, str]  # x_NNNN → original

    @classmethod
    def build(cls, private_ids: frozenset[str]) -> SymbolMap:
        """Deterministic: sort case-insensitive alphabetically, assign x_NNNN."""
        sorted_ids = sorted(private_ids, key=str.casefold)
        forward: dict[str, str] = {}
        reverse: dict[str, str] = {}
        for i, name in enumerate(sorted_ids):
            token = f"x_{i:04d}"
            forward[name] = token
            reverse[token] = name
        return cls(forward=forward, reverse=reverse)

    def to_dict(self) -> dict:
        return {"forward": self.forward, "reverse": self.reverse}

    @classmethod
    def from_dict(cls, d: dict) -> SymbolMap:
        return cls(forward=d["forward"], reverse=d["reverse"])
