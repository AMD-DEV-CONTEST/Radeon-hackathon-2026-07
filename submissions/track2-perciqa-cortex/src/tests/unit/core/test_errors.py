import pytest

from cortex.core.errors import (
    ArticleState,
    BrokerDisconnectError,
    CanonicalMismatchError,
    DeadlineExceededError,
    EmbedFailedError,
    InvalidTransition,
    ScopeViolationError,
    SignatureVerificationError,
    UnknownProducerError,
    transition,
)


def test_all_error_subclasses_exist_and_are_exceptions():
    for cls in [
        InvalidTransition,
        SignatureVerificationError,
        CanonicalMismatchError,
        UnknownProducerError,
        ScopeViolationError,
        DeadlineExceededError,
        EmbedFailedError,
        BrokerDisconnectError,
    ]:
        assert isinstance(cls, type)
        assert issubclass(cls, Exception)


def test_article_state_members():
    assert ArticleState.DRAFTED.value == "drafted"
    assert ArticleState.SIGNED.value == "signed"
    assert ArticleState.COSIGNED.value == "cosigned"
    assert ArticleState.INDEXED.value == "indexed"
    assert ArticleState.PUBLISHED.value == "published"
    assert ArticleState.CITED.value == "cited"
    assert ArticleState.ARCHIVED.value == "archived"


def test_transition_legal():
    assert transition(None, ArticleState.DRAFTED, ArticleState.SIGNED) is None
    assert transition(None, ArticleState.SIGNED, ArticleState.COSIGNED) is None
    assert transition(None, ArticleState.SIGNED, ArticleState.INDEXED) is None
    assert transition(None, ArticleState.COSIGNED, ArticleState.INDEXED) is None
    assert transition(None, ArticleState.INDEXED, ArticleState.PUBLISHED) is None
    assert transition(None, ArticleState.PUBLISHED, ArticleState.CITED) is None
    assert transition(None, ArticleState.PUBLISHED, ArticleState.ARCHIVED) is None
    assert transition(None, ArticleState.CITED, ArticleState.ARCHIVED) is None


def test_transition_illegal_raises():
    with pytest.raises(InvalidTransition):
        transition(None, ArticleState.DRAFTED, ArticleState.PUBLISHED)
    with pytest.raises(InvalidTransition):
        transition(None, ArticleState.ARCHIVED, ArticleState.PUBLISHED)
    with pytest.raises(InvalidTransition):
        transition(None, ArticleState.PUBLISHED, ArticleState.SIGNED)
