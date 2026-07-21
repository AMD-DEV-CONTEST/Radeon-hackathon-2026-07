
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from cortex.core.crypto import generate_agent_keypair, generate_org_keypair


def test_generate_org_keypair_returns_pem_pair():
    priv_pem, pub_pem = generate_org_keypair()
    assert priv_pem.startswith("-----BEGIN ")
    assert pub_pem.startswith("-----BEGIN ")
    assert "PRIVATE KEY" in priv_pem
    assert "PUBLIC KEY" in pub_pem


def test_generate_agent_keypair_returns_pem_pair():
    priv_pem, pub_pem = generate_agent_keypair()
    assert priv_pem.startswith("-----BEGIN ")
    assert pub_pem.startswith("-----BEGIN ")


def test_generated_keypair_roundtrips_sign_and_verify():
    priv_pem, pub_pem = generate_agent_keypair()
    pub = Ed25519PublicKey.from_public_bytes(
        serialization.load_pem_public_key(pub_pem.encode()).public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    )
    priv_obj = serialization.load_pem_private_key(
        priv_pem.encode(), password=None
    )
    msg = b"hello"
    sig = priv_obj.sign(msg)
    pub.verify(sig, msg)


def test_generate_keypairs_unique():
    p1 = generate_org_keypair()
    p2 = generate_org_keypair()
    assert p1[0] != p2[0]
    assert p1[1] != p2[1]


from cortex.core.crypto import load_private_pem, sign, verify

_FIXED_PRIVATE_PEM = """-----BEGIN PRIVATE KEY-----
MC4CAQAwBQYDK2VwBCIEIAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAB
-----END PRIVATE KEY-----
"""

_FIXED_PUBLIC_PEM = """-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEATLWr9q15+/WrvMr8wmnYXNJlHtS4hbWGnyQa7fCluik=
-----END PUBLIC KEY-----
"""

_FIXED_MSG = b'{"a":1}'
_FIXED_SIG_HEX = (
    "40dbb3a3e29fab5d3ef0d01c530cb57141efa2b95fa17b55128bb8cbc818251b"
    "b75a96a56a390f52cff88fe42d9379ab8b6f08cfda9df858bed42682807fa701"
)


def test_sign_known_vector():
    sig = sign(_FIXED_MSG, _FIXED_PRIVATE_PEM)
    assert sig.hex() == _FIXED_SIG_HEX
    assert len(sig) == 64


def test_verify_known_vector_succeeds():
    sig = bytes.fromhex(_FIXED_SIG_HEX)
    assert verify(_FIXED_MSG, sig, _FIXED_PUBLIC_PEM) is True


def test_verify_mutated_signature_fails():
    sig = bytes.fromhex(_FIXED_SIG_HEX)
    bad = bytearray(sig)
    bad[0] ^= 0xFF
    assert verify(_FIXED_MSG, bytes(bad), _FIXED_PUBLIC_PEM) is False


def test_verify_wrong_message_fails():
    sig = bytes.fromhex(_FIXED_SIG_HEX)
    assert verify(b'{"a":2}', sig, _FIXED_PUBLIC_PEM) is False


def test_verify_garbage_public_pem_returns_false():
    assert verify(_FIXED_MSG, b"\x00" * 64, "not a pem") is False


def test_load_private_pem_returns_string(tmp_path):
    p = tmp_path / "k.pem"
    p.write_text(_FIXED_PRIVATE_PEM)
    assert load_private_pem(p) == _FIXED_PRIVATE_PEM


def test_sign_is_deterministic_same_message_same_key():
    sig1 = sign(_FIXED_MSG, _FIXED_PRIVATE_PEM)
    sig2 = sign(_FIXED_MSG, _FIXED_PRIVATE_PEM)
    assert sig1 == sig2


def test_verify_with_wrong_public_key_returns_false():
    other_priv, other_pub = generate_agent_keypair()
    sig = sign(_FIXED_MSG, _FIXED_PRIVATE_PEM)
    assert verify(_FIXED_MSG, sig, other_pub) is False


def test_sign_then_verify_roundtrip_with_fresh_keypair():
    priv_pem, pub_pem = generate_agent_keypair()
    msg = b'{"content":"hello"}'
    sig = sign(msg, priv_pem)
    assert verify(msg, sig, pub_pem) is True
