from __future__ import annotations

import re

from .contracts import CampaignRequest, CampaignState, Claim, CreativeBrief


class SourceBoundEvidenceMiner:
    """Extracts only verbatim, non-empty spans from the supplied specification."""

    def __init__(self, max_claims: int = 4) -> None:
        self.max_claims = max_claims

    def extract(self, request: CampaignRequest) -> list[Claim]:
        source = request.specification_text.strip()
        if not source:
            return []
        spans = [
            span.strip()
            for span in re.split(r"(?<=[.!?])\s+|[\n;]+", source)
            if span.strip()
        ]
        claims: list[Claim] = []
        for index, span in enumerate(spans[: self.max_claims], start=1):
            claims.append(
                Claim(
                    id=f"CLM-{index:03d}",
                    text=span,
                    source_ref="campaign-request:specification_text",
                    source_span=span,
                    approved=span in source,
                    confidence=1.0 if span in source else 0.0,
                )
            )
        return claims


class DeterministicCreativeDirector:
    """Builds a bounded brief whose visible claim is an exact approved span."""

    def __init__(self, max_briefs: int = 1) -> None:
        self.max_briefs = max_briefs

    def plan(self, state: CampaignState) -> list[CreativeBrief]:
        approved = [claim for claim in state.claims if claim.approved]
        if not approved:
            return []
        briefs: list[CreativeBrief] = []
        for index, claim in enumerate(approved[: self.max_briefs], start=1):
            briefs.append(
                CreativeBrief(
                    id=f"BRF-{index:03d}",
                    headline=f"{state.request.product_name} — {claim.text}",
                    claim_ids=(claim.id,),
                    visual_direction=(
                        f"Evidence-led {state.request.goal} creative for "
                        f"{state.request.market}; preserve the supplied product."
                    ),
                    target_emotion=state.request.target_emotion,
                )
            )
        return briefs
