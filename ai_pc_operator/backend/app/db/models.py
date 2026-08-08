"""Pydantic models for database entities."""

from __future__ import annotations

from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class Command(BaseModel):
    """Command model."""
    id: Optional[int] = None
    source: str
    device_id: Optional[str] = None
    input_text: str
    intent: Optional[str] = None
    risk_level: int = 0
    status: str
    result: Optional[str] = None
    error: Optional[str] = None
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class Approval(BaseModel):
    """Approval model."""
    id: Optional[int] = None
    command_id: Optional[int] = None
    risk_level: int
    action_type: str
    target: Optional[str] = None
    description: str
    impact_summary: Optional[Dict[str, Any]] = None
    status: str
    created_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None


class Action(BaseModel):
    """Action model."""
    id: Optional[int] = None
    command_id: Optional[int] = None
    approval_id: Optional[int] = None
    tool: str
    input_json: Optional[Dict[str, Any]] = None
    output_json: Optional[Dict[str, Any]] = None
    risk_level: int = 0
    status: str
    error: Optional[str] = None
    created_at: Optional[datetime] = None


class Device(BaseModel):
    """Device model."""
    id: str
    name: str
    token_hash: str
    paired_at: Optional[datetime] = None
    last_seen: Optional[datetime] = None
    active: bool = True


class VaultEntry(BaseModel):
    """Vault entry model."""
    id: Optional[int] = None
    site: str
    username: Optional[str] = None
    created_at: Optional[datetime] = None
    last_used: Optional[datetime] = None


class QuarantineEntry(BaseModel):
    """Quarantine entry model."""
    id: Optional[int] = None
    original_path: str
    quarantine_path: str
    command_id: Optional[int] = None
    file_size: Optional[int] = None
    created_at: Optional[datetime] = None
    restored_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None
