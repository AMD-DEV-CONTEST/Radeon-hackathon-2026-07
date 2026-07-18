from __future__ import annotations

import os
import stat
from pathlib import Path

from cortex.core.crypto import generate_agent_keypair, generate_org_keypair, load_private_pem


def load_keys(org_path: Path, agent_path: Path) -> tuple[str, str]:
    for p in (org_path, agent_path):
        if not Path(p).exists():
            raise FileNotFoundError(f"key file missing: {p}")
        mode = stat.S_IMODE(os.stat(p).st_mode)
        if mode & 0o044:
            raise PermissionError(f"key file is world-readable: {p} (mode {oct(mode)})")
    org_pem = Path(org_path).read_text(encoding="utf-8")
    agent_pem = Path(agent_path).read_text(encoding="utf-8")
    load_private_pem(org_path)
    load_private_pem(agent_path)
    return org_pem, agent_pem


def ensure_keys(path: Path, kind: str = "org") -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        if kind == "org":
            pem, _ = generate_org_keypair()
        else:
            pem, _ = generate_agent_keypair()
        p.write_bytes(pem.encode("utf-8"))
        p.chmod(0o600)
    return p
