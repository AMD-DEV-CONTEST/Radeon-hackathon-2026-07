"""Approval manager - handles approval requests for risky actions."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

from app.db.database import db_session


class ApprovalManager:
    """Manages approval requests."""

    def __init__(self):
        """Initialize approval manager."""
        self.pending: Dict[int, asyncio.Future] = {}

    async def create_approval(
        self,
        command_id: int,
        risk_level: int,
        action_type: str,
        target: Optional[str],
        description: str,
        impact_summary: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Create a new approval request."""
        expires_at = datetime.now() + timedelta(minutes=5)

        async with db_session() as db:
            cursor = await db.execute(
                """
                INSERT INTO approvals (
                    command_id, risk_level, action_type, target,
                    description, impact_summary, status, expires_at
                )
                VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
                """,
                (
                    command_id,
                    risk_level,
                    action_type,
                    target,
                    description,
                    json.dumps(impact_summary) if impact_summary else None,
                    expires_at.isoformat(),
                ),
            )
            await db.commit()
            approval_id = cursor.lastrowid

        # Create future for waiting
        self.pending[approval_id] = asyncio.Future()

        return approval_id

    async def wait_for_approval(
        self, approval_id: int, timeout: int = 300
    ) -> bool:
        """Wait for approval resolution."""
        if approval_id not in self.pending:
            return False

        try:
            result = await asyncio.wait_for(
                self.pending[approval_id], timeout=timeout
            )
            return result
        except asyncio.TimeoutError:
            # Mark as expired
            await self._update_status(approval_id, "expired")
            return False

    async def resolve(
        self,
        approval_id: int,
        approved: bool,
        master_key: Optional[str] = None,
    ) -> bool:
        """Resolve an approval request."""
        # Update database
        status = "approved" if approved else "rejected"
        await self._update_status(approval_id, status)

        # Resolve future
        if approval_id in self.pending:
            future = self.pending.pop(approval_id)
            if not future.done():
                future.set_result(approved)

        return True

    async def get_pending(
        self, device_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get pending approval requests."""
        async with db_session() as db:
            cursor = await db.execute(
                """
                SELECT id, command_id, risk_level, action_type, target,
                       description, impact_summary, status, created_at,
                       resolved_at, expires_at
                FROM approvals
                WHERE status = 'pending' AND expires_at > ?
                ORDER BY created_at DESC
                """,
                (datetime.now().isoformat(),),
            )
            rows = await cursor.fetchall()

        return [dict(row) for row in rows]

    async def cancel_all_pending(self) -> None:
        """Cancel all pending approvals (emergency stop)."""
        for approval_id, future in list(self.pending.items()):
            await self._update_status(approval_id, "expired")
            if not future.done():
                future.set_result(False)
            self.pending.pop(approval_id, None)

    async def _update_status(
        self, approval_id: int, status: str
    ) -> None:
        """Update approval status."""
        async with db_session() as db:
            await db.execute(
                """
                UPDATE approvals
                SET status = ?, resolved_at = ?
                WHERE id = ?
                """,
                (status, datetime.now().isoformat(), approval_id),
            )
            await db.commit()
