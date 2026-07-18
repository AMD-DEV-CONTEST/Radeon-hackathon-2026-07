from cortex.core import (
    AgentDID,
    ArticleId,
    OrgDID,
    sha256_hex,
)


def test_aliases_reexported():
    assert ArticleId is str
    assert AgentDID is str
    assert OrgDID is str


def test_transitive_callable():
    assert sha256_hex(b"abc") == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )
