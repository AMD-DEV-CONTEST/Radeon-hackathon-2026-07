"""Password vault - encrypted credential storage.

Uses AES-256-GCM encryption with Argon2id key derivation.
"""

from __future__ import annotations

import os
import hashlib
from typing import Optional, Dict, Any

from app.db.database import db_session


class PasswordVault:
    """Encrypted password vault."""

    def __init__(
        self,
        kdf_memory_cost: int = 65536,
        kdf_iterations: int = 3,
        kdf_lanes: int = 4,
    ):
        """Initialize vault."""
        self.unlocked = False
        self.master_key: Optional[bytes] = None
        self.session_expiry: Optional[float] = None
        self._entry_key_cache: dict[bytes, bytes] = {}
        self.kdf_memory_cost = kdf_memory_cost
        self.kdf_iterations = kdf_iterations
        self.kdf_lanes = kdf_lanes

    def _derive_key(self, secret: bytes, salt: bytes) -> bytes:
        """Derive and cache per-salt entry keys during an unlock session."""
        if salt in self._entry_key_cache:
            return self._entry_key_cache[salt]

        try:
            from cryptography.hazmat.primitives.kdf.argon2 import Argon2id

            kdf = Argon2id(
                salt=salt,
                length=32,
                iterations=self.kdf_iterations,
                lanes=self.kdf_lanes,
                memory_cost=self.kdf_memory_cost,
            )
            key = kdf.derive(secret)
        except Exception:
            # Some Windows cryptography builds ship without a working Argon2
            # binding. Keep the local prototype usable while preserving a
            # salted, slow KDF fallback for tests and development.
            iterations = max(self.kdf_iterations * 200_000, 200_000)
            key = hashlib.pbkdf2_hmac("sha256", secret, salt, iterations, 32)
        self._entry_key_cache[salt] = key
        return key

    def unlock(self, master_password: str) -> bool:
        """Unlock vault with master password."""
        # Derive a session key once. Entry keys are cached per salt during this
        # unlock window to avoid repeated 64MB Argon2id spikes.
        salt = os.urandom(16)
        self._entry_key_cache.clear()
        self.master_key = self._derive_key(master_password.encode(), salt)
        self.unlocked = True

        # Set session expiry (5 minutes)
        import time
        self.session_expiry = time.time() + 300

        return True

    def lock(self) -> None:
        """Lock vault and wipe key from memory."""
        if self.master_key:
            # Overwrite key in memory
            self.master_key = b"\x00" * len(self.master_key)
            self.master_key = None
        for salt, key in list(self._entry_key_cache.items()):
            self._entry_key_cache[salt] = b"\x00" * len(key)
        self._entry_key_cache.clear()
        self.unlocked = False
        self.session_expiry = None

    def is_unlocked(self) -> bool:
        """Check if vault is unlocked and session valid."""
        if not self.unlocked or not self.session_expiry:
            return False

        import time
        if time.time() > self.session_expiry:
            self.lock()
            return False

        return True

    async def add_credential(
        self, site: str, username: str, password: str
    ) -> int:
        """Add encrypted credential to vault."""
        if not self.is_unlocked():
            raise PermissionError("Vault is locked")

        # Generate salt and nonce
        salt = os.urandom(16)
        nonce = os.urandom(12)

        # Derive/cached key for this entry salt.
        key = self._derive_key(self.master_key, salt)

        # Encrypt with AES-256-GCM
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        aesgcm = AESGCM(key)
        ciphertext = aesgcm.encrypt(nonce, password.encode(), None)

        # Store in database
        async with db_session() as db:
            cursor = await db.execute(
                """
                INSERT INTO vault_entries (site, username, encrypted_password, salt, nonce, tag)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(site, username) DO UPDATE SET
                    encrypted_password = excluded.encrypted_password,
                    salt = excluded.salt,
                    nonce = excluded.nonce,
                    tag = excluded.tag
                """,
                (
                    site,
                    username,
                    ciphertext[:-16],  # Ciphertext without tag
                    salt,
                    nonce,
                    ciphertext[-16:],  # Last 16 bytes is tag
                ),
            )
            await db.commit()
            entry_id = cursor.lastrowid

        return entry_id

    async def get_credential(
        self, site: str, username: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Get and decrypt credential."""
        if not self.is_unlocked():
            raise PermissionError("Vault is locked")

        async with db_session() as db:
            if username:
                cursor = await db.execute(
                    """
                    SELECT id, site, username, encrypted_password, salt, nonce, tag
                    FROM vault_entries
                    WHERE site = ? AND username = ?
                    """,
                    (site, username),
                )
            else:
                cursor = await db.execute(
                    """
                    SELECT id, site, username, encrypted_password, salt, nonce, tag
                    FROM vault_entries
                    WHERE site = ?
                    LIMIT 1
                    """,
                    (site,),
                )
            row = await cursor.fetchone()

        if not row:
            return None

        # Decrypt
        salt = row["salt"]
        nonce = row["nonce"]
        ciphertext = row["encrypted_password"] + row["tag"]

        key = self._derive_key(self.master_key, salt)

        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        aesgcm = AESGCM(key)
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)

        # Update last_used
        async with db_session() as db:
            await db.execute(
                "UPDATE vault_entries SET last_used = CURRENT_TIMESTAMP WHERE id = ?",
                (row["id"],),
            )
            await db.commit()

        return {
            "site": row["site"],
            "username": row["username"],
            "password": plaintext.decode(),
        }

    async def list_sites(self) -> list:
        """List all sites in vault (without passwords)."""
        async with db_session() as db:
            cursor = await db.execute(
                """
                SELECT id, site, username, created_at, last_used
                FROM vault_entries
                ORDER BY site, username
                LIMIT 500
                """
            )
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def delete_credential(self, entry_id: int) -> bool:
        """Delete credential from vault."""
        async with db_session() as db:
            await db.execute(
                "DELETE FROM vault_entries WHERE id = ?",
                (entry_id,),
            )
            await db.commit()
        return True
