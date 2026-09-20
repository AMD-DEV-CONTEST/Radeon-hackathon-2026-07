"""Unified message protocol for multi-agent communication.

All agent communication uses AgentMessage — a structured JSON message
with msg_id, session_id, payload, status, source_agent, target_agent.

Message flow:
  Orchestrator → RetrievalAgent → ReasoningAgent → RiskAgent → final decision

RiskAgent has the unique veto power: if allow_execute=false,
no trade is executed regardless of the reasoning agent's intent.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentMessage:
    """Standard message structure for inter-agent communication.

    All agents send and receive AgentMessage instances. The payload
    field carries agent-specific data (query, docs, trading intent, etc.).
    """

    payload: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"  # pending | success | reject | error
    error_msg: str = ""
    source_agent: str = ""
    target_agent: str = ""
    asset: str = ""  # e.g. "BTC-USDT"
    timeframe: str = ""  # e.g. "1h"
    session_id: str = ""
    msg_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "msg_id": self.msg_id,
            "timestamp": self.timestamp,
            "session_id": self.session_id,
            "asset": self.asset,
            "timeframe": self.timeframe,
            "payload": self.payload,
            "status": self.status,
            "error_msg": self.error_msg,
            "source_agent": self.source_agent,
            "target_agent": self.target_agent,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AgentMessage":
        return cls(
            payload=d.get("payload", {}),
            status=d.get("status", "pending"),
            error_msg=d.get("error_msg", ""),
            source_agent=d.get("source_agent", ""),
            target_agent=d.get("target_agent", ""),
            asset=d.get("asset", ""),
            timeframe=d.get("timeframe", ""),
            session_id=d.get("session_id", ""),
            msg_id=d.get("msg_id", str(uuid.uuid4())[:8]),
            timestamp=d.get("timestamp", time.time()),
        )

    def to_user_message(self) -> str:
        """Format for LLM consumption (compact text)."""
        return str(self.payload)


# ── Payload schemas (documentation + validation) ───────────────────


# RetrievalAgent → ReasoningAgent payload
RETRIEVAL_OUTPUT_SCHEMA = {
    "reference_docs": list,  # List of {title, content, score, category}
    "has_valid_docs": bool,  # If False → reasoning must output neutral
    "max_confidence_score": float,  # Best reranker score
}

# ReasoningAgent → RiskAgent payload (trading intent, NOT an order)
REASONING_OUTPUT_SCHEMA = {
    "view": str,  # "long" | "short" | "neutral"
    "confidence": float,  # [0.0, 1.0]
    "suggest_position_ratio": float,  # [0.0, 0.3]
    "entry_price": (float, type(None)),  # Suggested entry
    "stop_loss": (float, type(None)),  # Stop loss price
    "reason": str,  # Reasoning summary
}

# RiskAgent → final output payload
RISK_OUTPUT_SCHEMA = {
    "allow_execute": bool,  # Veto power
    "final_position_ratio": float,  # Possibly adjusted
    "audit_note": str,  # Explanation
    "checks_passed": list,  # List of check names
    "checks_failed": list,  # List of failed check names
}
