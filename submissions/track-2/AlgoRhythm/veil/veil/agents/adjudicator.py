"""Adjudicator — the referee between five attackers.

Five personas attacking the same document produce overlapping, contradictory,
and occasionally overconfident claims. The adjudicator is what turns that into
a defensible finding list:

  1. deduplicate findings that point at the same span and say the same thing
  2. promote severity where independent personas corroborate each other
  3. demote or reject claims whose tier is not supported by their evidence
  4. rank by actionable risk, not by model confidence

Rule 3 is the one that matters. A model that says "this is definitely Sarah
Chen" on stylometric evidence gets its claim rewritten as a Tier S suggestion,
not passed through with a confident verb.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

from veil.types import Finding, Tier

# A Tier M claim must cite a span from a mechanical source. Anything else is
# a model asserting certainty it has not earned.
_MECHANICAL_SOURCES = {"metadata", "redaction_underlay", "revision"}

_CERTAINTY_VERBS = (
    "is definitely", "is certainly", "must be", "is clearly", "proves that",
    "confirms that", "without doubt", "unambiguously",
)


@dataclass
class Adjudication:
    accepted: list[Finding] = field(default_factory=list)
    merged: int = 0
    demoted: list[dict[str, Any]] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        by_tier = {t.value: 0 for t in Tier}
        for f in self.accepted:
            by_tier[f.tier.value] += 1
        return {
            "accepted": len(self.accepted),
            "by_tier": by_tier,
            "merged": self.merged,
            "demoted": len(self.demoted),
            "rejected": len(self.rejected),
        }


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _spans_overlap(a: Finding, b: Finding) -> bool:
    for sa in a.spans:
        for sb in b.spans:
            if not (sa.end <= sb.start or sa.start >= sb.end):
                return True
    return False


def _same_finding(a: Finding, b: Finding) -> bool:
    if a.tier is not b.tier:
        return False
    if _spans_overlap(a, b) and _similar(a.claim, b.claim) > 0.55:
        return True
    return _similar(a.claim, b.claim) > 0.85


def _soften(claim: str) -> str:
    out = claim
    for verb in _CERTAINTY_VERBS:
        out = out.replace(verb, "may be")
    return out


def _validate_tier(f: Finding) -> tuple[Finding, str | None]:
    """Return the finding at a tier its evidence actually supports."""
    if f.tier is Tier.MECHANICAL:
        sources = {s.source for s in f.spans}
        if not (sources & _MECHANICAL_SOURCES):
            demoted = Finding(
                persona=f.persona,
                tier=Tier.CORRELATIONAL,
                claim=_soften(f.claim),
                reasoning=f.reasoning,
                spans=f.spans,
                severity=f.severity * 0.7,
                candidate_set_size=f.candidate_set_size or 50,
                id=f.id,
            )
            return demoted, (
                "Claimed Tier M but cited no mechanically extracted span; "
                "demoted to Tier C with a default candidate set."
            )

    if f.tier is Tier.CORRELATIONAL and (f.candidate_set_size or 0) > 1000:
        f.severity = min(f.severity, 0.2)
        return f, "Candidate set over 1000 — severity capped; this is not a re-identification."

    if f.tier is Tier.STYLISTIC:
        f.claim = _soften(f.claim)
        f.severity = min(f.severity, 0.4)

    return f, None


def _severity_for(f: Finding, corroborators: int) -> float:
    base = f.severity
    if f.tier is Tier.MECHANICAL:
        base = max(base, 0.9)   # extracted text is not a probability
    elif f.tier is Tier.CORRELATIONAL:
        k = f.candidate_set_size or 1000
        if k <= 1:
            base = max(base, 0.95)
        elif k < 5:
            base = max(base, 0.8)
        elif k < 20:
            base = max(base, 0.6)
        elif k < 200:
            base = min(base, 0.45)
        else:
            base = min(base, 0.2)
    else:
        base = min(base, 0.4)

    # Independent corroboration is evidence; agreement between two personas
    # who used different tools is worth more than one persona's confidence.
    if corroborators > 1:
        base = min(1.0, base + 0.05 * (corroborators - 1))
    return round(base, 3)


def adjudicate(findings: list[Finding]) -> Adjudication:
    result = Adjudication()

    validated: list[Finding] = []
    for f in findings:
        if not f.claim.strip():
            result.rejected.append({"id": f.id, "reason": "empty claim"})
            continue
        fixed, note = _validate_tier(f)
        if note:
            result.demoted.append({"id": f.id, "persona": f.persona, "note": note})
        validated.append(fixed)

    clusters: list[list[Finding]] = []
    for f in validated:
        for cluster in clusters:
            if _same_finding(cluster[0], f):
                cluster.append(f)
                break
        else:
            clusters.append([f])

    for cluster in clusters:
        # Keep the best-evidenced representative: most spans, then longest
        # reasoning as a tiebreak.
        rep = max(cluster, key=lambda x: (len(x.spans), len(x.reasoning)))
        personas = sorted({c.persona for c in cluster})
        rep.severity = _severity_for(rep, len(personas))
        if len(cluster) > 1:
            result.merged += len(cluster) - 1
            rep.persona = " + ".join(personas)
            sizes = [c.candidate_set_size for c in cluster if c.candidate_set_size]
            if sizes:
                rep.candidate_set_size = min(sizes)   # the tightest defensible bound
        result.accepted.append(rep)

    tier_order = {Tier.MECHANICAL: 0, Tier.CORRELATIONAL: 1, Tier.STYLISTIC: 2}
    result.accepted.sort(key=lambda f: (tier_order[f.tier], -f.severity))
    return result
