from __future__ import annotations

from enum import StrEnum


class CortexError(Exception):
    """Base for all cortex.core exceptions."""


class InvalidTransition(CortexError):
    """Raised when an article lifecycle move is illegal."""


class SignatureVerificationError(CortexError):
    """Raised when an Ed25519 signature fails verification."""


class CanonicalMismatchError(CortexError):
    """Raised when recomputed canonical bytes differ from expected."""


class UnknownProducerError(CortexError):
    """Raised when a producer agent/org is not registered or trusted."""


class ScopeViolationError(CortexError):
    """Raised when an article is accessed outside its declared scope."""


class DeadlineExceededError(CortexError):
    """Raised when a deadline (e.g. replay window) is exceeded."""


class EmbedFailedError(CortexError):
    """Raised when embedding generation fails."""


class BrokerDisconnectError(CortexError):
    """Raised when the broker connection is lost."""


class ArticleState(StrEnum):
    DRAFTED = "drafted"
    SIGNED = "signed"
    COSIGNED = "cosigned"
    INDEXED = "indexed"
    PUBLISHED = "published"
    CITED = "cited"
    ARCHIVED = "archived"


_LEGAL_TRANSITIONS = {
    (ArticleState.DRAFTED, ArticleState.SIGNED),
    (ArticleState.SIGNED, ArticleState.COSIGNED),
    (ArticleState.SIGNED, ArticleState.INDEXED),
    (ArticleState.SIGNED, ArticleState.ARCHIVED),
    (ArticleState.COSIGNED, ArticleState.INDEXED),
    (ArticleState.COSIGNED, ArticleState.ARCHIVED),
    (ArticleState.INDEXED, ArticleState.PUBLISHED),
    (ArticleState.INDEXED, ArticleState.ARCHIVED),
    (ArticleState.PUBLISHED, ArticleState.CITED),
    (ArticleState.PUBLISHED, ArticleState.ARCHIVED),
    (ArticleState.CITED, ArticleState.ARCHIVED),
}


def transition(article, from_state: ArticleState, to_state: ArticleState) -> None:
    """Validate a lifecycle move. Raises InvalidTransition on illegal moves.

    The `article` argument is accepted for API symmetry with future
    stateful validators but is not consulted here.
    """
    if (from_state, to_state) not in _LEGAL_TRANSITIONS:
        raise InvalidTransition(
            f"Illegal transition: {from_state.value} -> {to_state.value}"
        )
    return
