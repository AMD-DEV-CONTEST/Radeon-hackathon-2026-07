"""Ticket 07 — the user's explicit decision, and the access it grants.

A candidate is a proposal. Only the user's decision converts it into access, and
the grant is scoped to the one asset they were shown: a single approval that
widened retrieval to the corpus would mean their decision no longer matches what
they agreed to. They said this experience is worth comparing to that one; they
did not agree to open their archive.

This package creates decisions and relations. It never reads historical detail —
ticket 08 owns that. Keeping the grant separate from the read is what makes the
grant testable on its own: folded together, no test could show that a request
with a valid confirmation but a stale binding is refused, because the refusal and
the render would share a branch.
"""

from .service import DecisionRefused, DecisionService

__all__ = ["DecisionRefused", "DecisionService"]
