import os
import stat
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from cortex.node.keys import ensure_keys, load_keys


def _write_key(tmp_path: Path, mode: int) -> Path:
    k = Ed25519PrivateKey.generate()
    pem = k.private_bytes(encoding=serialization.Encoding.PEM,
                          format=serialization.PrivateFormat.PKCS8,
                          encryption_algorithm=serialization.NoEncryption())
    p = tmp_path / "k.pem"
    p.write_bytes(pem)
    try:
        p.chmod(mode)
    except PermissionError:
        pytest.skip(f"cannot set mode {oct(mode)} on this FS")
    return p


def test_load_keys_accepts_owner_only(tmp_path: Path) -> None:
    p = _write_key(tmp_path, 0o600)
    assert load_keys(p, p)[0] == p.read_text(encoding="utf-8")


def test_load_keys_refuses_group_readable(tmp_path: Path) -> None:
    p = _write_key(tmp_path, 0o640)
    with pytest.raises(PermissionError):
        load_keys(p, p)


def test_load_keys_refuses_world_writable(tmp_path: Path) -> None:
    p = _write_key(tmp_path, 0o622)
    with pytest.raises(PermissionError):
        load_keys(p, p)


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
