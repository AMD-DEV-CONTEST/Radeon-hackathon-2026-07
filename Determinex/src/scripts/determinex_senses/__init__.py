"""Determinex Diagnostics Layer — "Deep Senses".

Provides LSP, divergence, and syscall-differential diagnostics as enrichment
for the compiler-oracle retry loop. The oracle remains the sole verdict;
these modules are senses, not judges.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class DiagnosticSection:
    """A single ranked section in a DiagnosticBundle."""

    kind: str  # "lsp" | "divergence" | "syscall_diff"
    rank: int  # lower = higher priority; 0 = compiler errors (injected externally)
    content: list[dict[str, Any]]
    token_estimate: int = 0

    def to_text(self, max_tokens: int = 0) -> str:
        """Render as prompt-injectable text, optionally token-capped."""
        lines: list[str] = []
        for item in self.content:
            line = _format_item(self.kind, item)
            if line:
                lines.append(line)
                if max_tokens and len(" ".join(lines)) // 4 > max_tokens:
                    lines.append("... (truncated)")
                    break
        return "\n".join(lines)


def _format_item(kind: str, item: dict[str, Any]) -> str:
    if kind == "lsp":
        sev = item.get("severity", "?")
        file_ = item.get("file", "?")
        line = item.get("line", "?")
        msg = item.get("message", "")
        code = item.get("code", "")
        code_str = f" [{code}]" if code else ""
        return f"  [{sev}]{code_str} {file_}:{line}: {msg}"
    if kind == "divergence":
        return f"  divergence @ {item.get('divergence_point', '?')}: {item.get('stack', '')[:120]}"
    if kind == "syscall_diff":
        return (
            f"  first-diff syscall: {item.get('first_diff', '?')} — {item.get('summary', '')[:120]}"
        )
    return str(item)


@dataclass
class DiagnosticBundle:
    """Token-budgeted enrichment bundle injected after compiler errors."""

    workspace: Path
    lang: str
    sections: list[DiagnosticSection] = field(default_factory=list)
    cloak_applied: bool = False

    # Hard cap: ~2000 tokens by default.  Lowest-rank sections truncated first.
    TOKEN_BUDGET: int = 2000

    def render(self) -> str:
        """Render all sections within TOKEN_BUDGET, lowest rank truncated first."""
        ordered = sorted(self.sections, key=lambda s: s.rank)
        parts: list[str] = []
        used = 0
        for sec in ordered:
            budget_left = max(0, self.TOKEN_BUDGET - used)
            if budget_left == 0:
                break
            text = sec.to_text(max_tokens=budget_left)
            if text.strip():
                header = f"[senses:{sec.kind}]"
                parts.append(f"{header}\n{text}")
                used += len(text) // 4
        return "\n\n".join(parts)

    def to_wal_dict(self) -> dict[str, Any]:
        return {
            "lang": self.lang,
            "workspace": str(self.workspace),
            "cloak_applied": self.cloak_applied,
            "sections": [
                {
                    "kind": s.kind,
                    "rank": s.rank,
                    "items": len(s.content),
                    "token_estimate": s.token_estimate,
                }
                for s in self.sections
            ],
        }
