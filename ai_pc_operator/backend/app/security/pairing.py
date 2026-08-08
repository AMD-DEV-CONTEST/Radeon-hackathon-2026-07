"""Pairing manager - device pairing with codes."""

from __future__ import annotations

import secrets
import hashlib
import uuid
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from app.db.database import db_session


class PairingManager:
    """Manages device pairing."""

    def __init__(self):
        """Initialize pairing manager."""
        self.active_codes: Dict[str, datetime] = {}

    async def generate_code(self) -> str:
        """Generate a new pairing code (6 digits)."""
        # Generate 6-digit code
        code = f"{secrets.randbelow(1000000):06d}"

        # Store in database with 5-minute expiry
        expires_at = datetime.now() + timedelta(minutes=5)

        async with db_session() as db:
            await db.execute(
                """
                INSERT INTO pairing_codes (code, expires_at)
                VALUES (?, ?)
                """,
                (code, expires_at.isoformat()),
            )
            await db.commit()

        self.active_codes[code] = expires_at
        return code

    async def pair_device(
        self, code: str, device_name: str
    ) -> Optional[Dict[str, Any]]:
        """Pair a device using pairing code."""
        # Verify code
        async with db_session() as db:
            cursor = await db.execute(
                """
                SELECT code FROM pairing_codes
                WHERE code = ? AND used = 0 AND expires_at > ?
                """,
                (code, datetime.now().isoformat()),
            )
            row = await cursor.fetchone()

            if not row:
                return None

            # Mark code as used
            await db.execute(
                "UPDATE pairing_codes SET used = 1 WHERE code = ?",
                (code,),
            )

            # Generate device ID and token
            device_id = str(uuid.uuid4())
            token = secrets.token_urlsafe(32)
            token_hash = hashlib.sha256(token.encode()).hexdigest()

            # Insert device
            await db.execute(
                """
                INSERT INTO devices (id, name, token_hash, paired_at, active)
                VALUES (?, ?, ?, ?, 1)
                """,
                (device_id, device_name, token_hash, datetime.now().isoformat()),
            )
            await db.commit()

        return {
            "id": device_id,
            "name": device_name,
            "token": token,
            "paired_at": datetime.now().isoformat(),
        }

    async def verify_device(self, device_id: str, token: str = None) -> bool:
        """Verify if device is paired and active."""
        if not token:
            return False

        token_hash = hashlib.sha256(token.encode()).hexdigest()
        async with db_session() as db:
            cursor = await db.execute(
                """
                SELECT id FROM devices
                WHERE id = ? AND token_hash = ? AND active = 1
                """,
                (device_id, token_hash),
            )
            row = await cursor.fetchone()

            if not row:
                return False

            # Update last seen
            await db.execute(
                "UPDATE devices SET last_seen = ? WHERE id = ?",
                (datetime.now().isoformat(), device_id),
            )
            await db.commit()

        return True

    async def revoke_device(self, device_id: str) -> bool:
        """Revoke a paired device."""
        async with db_session() as db:
            await db.execute(
                "UPDATE devices SET active = 0 WHERE id = ?",
                (device_id,),
            )
            await db.commit()
        return True
