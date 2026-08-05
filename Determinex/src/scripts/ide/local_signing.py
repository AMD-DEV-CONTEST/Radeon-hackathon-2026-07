"""Local HMAC signing for real human approvals.

CLAUDE-AUTH-008 remediation: previously approval signatures were
just 64-char hex strings — any random value passed the shape check.
Now `signature_kind == "real_local_hmac"` means the signature is an
HMAC-SHA256 over a canonical payload using a per-host local secret.

The secret is stored at:

    ~/.determinex/local_signing_secret

If absent, it is created with 32 random bytes (0600 permissions on
POSIX). This is *local* signing, not a CA-rooted identity. The
upgrade path to asymmetric crypto (e.g. ed25519 with a stored
public key registry) is left for a future lock.

Canonical payload format (LF-separated string), then UTF-8 bytes:

    v1
    trace_id=<trace_id>
    canonical_patch_body_hash=<hex>
    diff_hash=<hex>
    verifier_status=<status>
    rollback_snapshot_ref=<ref>
    workspace_identity_hash=<sha256-hex>
    operator_identity=<identity>
    stale_after=<isoformat>

Empty fields are still present (e.g. ``verifier_status=``) so the
canonical bytes are deterministic and tamper-evident.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from pathlib import Path

SIGNATURE_KIND_HMAC = "real_local_hmac"
SIGNATURE_KIND_LEGACY = "real_local_signed"


def _secret_path() -> Path:
    """Resolve the per-host signing secret file path."""
    home = Path.home()
    return home / ".determinex" / "local_signing_secret"


def _load_or_create_secret(path: Path | None = None) -> bytes:
    """Load the per-host secret, creating one with 32 random bytes
    on first run. POSIX 0600 perms when creating."""
    p = Path(path) if path else _secret_path()
    if p.exists():
        return p.read_bytes()
    p.parent.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_bytes(32)
    # Best-effort restrictive perms; on Windows this is a no-op for
    # the value, but we still write the file.
    p.write_bytes(secret)
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass
    return secret


def canonical_payload(
    *,
    trace_id: str,
    canonical_patch_body_hash: str,
    diff_hash: str,
    verifier_status: str,
    rollback_snapshot_ref: str,
    workspace_identity: str,
    operator_identity: str,
    stale_after: str,
) -> bytes:
    """Build the canonical payload bytes the signature binds to.

    ``workspace_identity`` is hashed inside (so the raw value never
    appears in payload or signature inputs).
    """
    ws_hash = hashlib.sha256(
        (workspace_identity or "").encode("utf-8", errors="replace")
    ).hexdigest()
    lines = [
        "v1",
        f"trace_id={trace_id}",
        f"canonical_patch_body_hash={canonical_patch_body_hash}",
        f"diff_hash={diff_hash}",
        f"verifier_status={verifier_status}",
        f"rollback_snapshot_ref={rollback_snapshot_ref}",
        f"workspace_identity_hash={ws_hash}",
        f"operator_identity={operator_identity}",
        f"stale_after={stale_after}",
    ]
    return "\n".join(lines).encode("utf-8")


def sign(
    payload: bytes,
    *,
    secret: bytes | None = None,
    secret_path: Path | None = None,
) -> str:
    """Return the hex HMAC-SHA256 of payload."""
    sec = secret if secret is not None else _load_or_create_secret(secret_path)
    return hmac.new(sec, payload, hashlib.sha256).hexdigest()


def verify(
    payload: bytes,
    signature_hex: str,
    *,
    secret: bytes | None = None,
    secret_path: Path | None = None,
) -> bool:
    """Constant-time HMAC verify."""
    if not signature_hex or len(signature_hex) != 64:
        return False
    sec = secret if secret is not None else _load_or_create_secret(secret_path)
    expected = hmac.new(sec, payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_hex)


__all__ = [
    "SIGNATURE_KIND_HMAC",
    "SIGNATURE_KIND_LEGACY",
    "canonical_payload",
    "sign",
    "verify",
]
