import os
import stat
from pathlib import Path

from cryptography.hazmat.primitives import serialization

from cortex.node.keys import ensure_keys


def test_ensure_keys_creates_0600(tmp_path: Path) -> None:
    p = tmp_path / "keys" / "agent_ed25519.pem"
    out = ensure_keys(p, kind="agent")
    assert out.exists()
    mode = stat.S_IMODE(os.stat(out).st_mode)
    assert mode == 0o600
    pem = out.read_bytes()
    serialization.load_pem_private_key(pem, password=None)


def test_ensure_keys_idempotent(tmp_path: Path) -> None:
    p = tmp_path / "o.pem"
    a = ensure_keys(p, kind="org")
    b = ensure_keys(p, kind="org")
    assert a.read_bytes() == b.read_bytes()
