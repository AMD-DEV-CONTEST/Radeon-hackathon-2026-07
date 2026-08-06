"""Typed placeholder for E5 endpoints whose handler is not written yet.

Ticket 01 registers every E5 route so that four parallel Wave-1 branches never
touch `api/main.py`. Four branches each adding a registration line there would
conflict, and the conflict lands on a regenerated 151 KB OpenAPI document where
a hand-resolved merge easily drops a field.

The placeholder is deliberately explicit rather than a bare 501. A generic
"Not Implemented" reads to a reviewer as "the feature exists and is broken",
which is a different and more alarming claim than "the handler is not written
yet". Naming the owning ticket also tells a reader where the work actually is.

**This response is not shippable.** Ticket 10's public QA fails if any
`NOT_IMPLEMENTED` route remains at the evidence head, because an evidence packet
that reaches a placeholder has proven nothing about the behaviour it claims to
cover.
"""

from __future__ import annotations

from typing import Literal

from fastapi import HTTPException

from app.experience_asset.domain.models import ContractModel, NonEmptyText

NOT_IMPLEMENTED_STATUS = 501


class NotImplementedDetailV1(ContractModel):
    """Body of a placeholder response, naming the ticket that will replace it."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    reason_code: Literal["E5_HANDLER_NOT_IMPLEMENTED"] = "E5_HANDLER_NOT_IMPLEMENTED"
    owning_ticket: NonEmptyText
    detail: NonEmptyText
    shippable: Literal[False] = False


def not_implemented(owning_ticket: str, operation: str) -> HTTPException:
    """Raise the typed placeholder for an unimplemented E5 operation."""

    return HTTPException(
        status_code=NOT_IMPLEMENTED_STATUS,
        detail=NotImplementedDetailV1(
            owning_ticket=owning_ticket,
            detail=(
                f"{operation} is registered by the E5 contract freeze but its "
                f"handler is owned by ticket {owning_ticket} and is not written "
                "yet. This response is not shippable and must not appear at an "
                "evidence head."
            ),
        ).model_dump(mode="json"),
    )


NOT_IMPLEMENTED_RESPONSES: dict[int | str, dict] = {
    NOT_IMPLEMENTED_STATUS: {
        "description": (
            "The route is registered by the E5 contract freeze but its handler is "
            "not written yet. Not shippable: ticket 10's public QA fails if any "
            "route still answers this at an evidence head."
        ),
        "model": NotImplementedDetailV1,
    }
}
"""Documented on every E5 route.

A 501 that exists at runtime but not in the OpenAPI document is invisible to
anyone reading the contract, so a consumer generating a client from it would
believe the endpoint only ever succeeds or returns 422 — and would have no
branch for the response it will actually receive today.
"""
