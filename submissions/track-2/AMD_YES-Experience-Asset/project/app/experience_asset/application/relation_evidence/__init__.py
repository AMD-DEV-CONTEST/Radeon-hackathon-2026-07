"""Ticket 08 — confirmation-bound evidence card and bounded detail read.

This package owns two things and nothing else: rendering the bilateral evidence
card deterministically from canonical content, and reading the bounded detail
set that card is allowed to quote. It creates no decisions and no relations
(ticket 07 owns those) and never writes a canonical snapshot.

The card is assembled by application code. There is no second model call, and no
generated summary, advice or next step, because the user's confirmation was the
last checkpoint: an artifact produced after that gate was never reviewed, would
be free to drift from the relation they approved, and would read as a faithful
description of it while drifting.
"""

from .card import (
    EvidenceCardRefusal,
    EvidenceCardRefusalReason,
    EvidenceCardResult,
    EvidenceCardV1,
    MappedRoleEvidenceV1,
    SideProvenanceV1,
    TransferBoundaryV1,
    compute_evidence_card_hash,
    render_evidence_card,
)
from .detail_read import (
    BoundedDetailRequest,
    BoundedDetailSet,
    resolve_bounded_detail,
)
from .traced_read import read_evidence_card_traced

__all__ = [
    "BoundedDetailRequest",
    "BoundedDetailSet",
    "EvidenceCardRefusal",
    "EvidenceCardRefusalReason",
    "EvidenceCardResult",
    "EvidenceCardV1",
    "MappedRoleEvidenceV1",
    "SideProvenanceV1",
    "TransferBoundaryV1",
    "compute_evidence_card_hash",
    "read_evidence_card_traced",
    "render_evidence_card",
    "resolve_bounded_detail",
]
