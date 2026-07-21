import pytest

from cortex.broker.acl import acl_allows

_ALPHA = "did:percq:org:soc-alpha"
_BETA = "did:percq:org:soc-beta"
_GAMMA = "did:percq:org:soc-gamma"


@pytest.mark.parametrize(
    "scope,src,dst,expected",
    [
        ("public", _ALPHA, _BETA, True),
        ("public", _ALPHA, _ALPHA, True),
        (f"partner:{_BETA}", _ALPHA, _BETA, True),
        (f"partner:{_BETA}", _ALPHA, _GAMMA, False),
        (f"partner:{_ALPHA}", _ALPHA, _BETA, False),
        ("private", _ALPHA, _BETA, False),
        ("private", _ALPHA, _ALPHA, True),
        ("anything-else", _ALPHA, _ALPHA, True),
    ],
)
def test_acl_allows_truth_table(scope, src, dst, expected):
    assert acl_allows(scope, src, dst) is expected


def test_acl_partner_scope_blocked_even_intra_org():
    # partner:gamma from alpha to alpha is blocked (partner targets gamma, not alpha)
    assert acl_allows("partner:did:percq:org:soc-gamma",
                     "did:percq:org:soc-alpha",
                     "did:percq:org:soc-alpha") is False
