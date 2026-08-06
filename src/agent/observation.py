"""Minimal observation layer: record lineage, fingerprint, timing for each ModelRequest (I6 fix).

Design audit fixes:
- I6: add request-level observation contract — logical_request_id, attempt_number, prompt/schema fingerprint,
  input/output size, duration, consumer edges
- Follow observability-and-validation.md: observation is fact, not policy; it does not decide routing or retry
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ConsumerEdge:
    """An edge from an output field to its consumer."""
    field: str
    consumer: str
    validated: bool = False
    validation_error: str | None = None


@dataclass
class RequestObservation:
    """Observation record for each ModelRequest (I6).

    Follow the Observation Contract in observability-and-validation.md:
    - record lineage, fingerprint, preview, size, timing
    - do not record sensitive content (full prompt), only fingerprints
    """
    logical_request_id: str
    node_id: str
    attempt: int = 1
    timestamp: float = field(default_factory=time.time)
    prompt_fingerprint: str | None = None
    output_fingerprint: str | None = None
    input_size: int = 0
    output_size: int = 0
    duration_ms: float = 0
    status: str = "pending"  # pending / completed / failed / retried
    provider_model: str | None = None
    consumer_edges: list[ConsumerEdge] = field(default_factory=list)
    error: str | None = None

    @staticmethod
    def fingerprint(data: Any) -> str:
        """Generate a prompt/schema fingerprint, excluding sensitive content."""
        try:
            serialized = json.dumps(data, sort_keys=True, default=str, ensure_ascii=False)
            return hashlib.sha256(serialized.encode()).hexdigest()[:16]
        except Exception:
            return "fingerprint_error"

    def to_dict(self) -> dict:
        return {
            "logical_request_id": self.logical_request_id,
            "node_id": self.node_id,
            "attempt": self.attempt,
            "timestamp": self.timestamp,
            "prompt_fingerprint": self.prompt_fingerprint,
            "output_fingerprint": self.output_fingerprint,
            "input_size": self.input_size,
            "output_size": self.output_size,
            "duration_ms": round(self.duration_ms, 2),
            "status": self.status,
            "provider_model": self.provider_model,
            "consumer_edges": [
                {
                    "field": e.field,
                    "consumer": e.consumer,
                    "validated": e.validated,
                    "validation_error": e.validation_error,
                }
                for e in self.consumer_edges
            ],
            "error": self.error,
        }


class ObservationCollector:
    """Collect observation records for all ModelRequests in one pipeline run."""

    def __init__(self):
        self._observations: list[RequestObservation] = []

    def create_observation(
        self,
        node_id: str,
        attempt: int = 1,
        provider_model: str | None = None,
    ) -> RequestObservation:
        """Create and register a new observation record."""
        obs = RequestObservation(
            logical_request_id=f"{node_id}-{uuid.uuid4().hex[:8]}",
            node_id=node_id,
            attempt=attempt,
            provider_model=provider_model,
        )
        self._observations.append(obs)
        return obs

    def record_request(
        self,
        node_id: str,
        input_data: Any,
        output_data: Any,
        duration_ms: float,
        attempt: int = 1,
        status: str = "completed",
        error: str | None = None,
        provider_model: str | None = None,
        consumer_edges: list[dict] | None = None,
    ) -> RequestObservation:
        """Convenience method: record one complete ModelRequest.

        I3: consumer_edges describes the mapping from output fields to consumers, e.g.:
            [{"field": "query_type", "consumer": "host_branch"}, ...]
        """
        obs = self.create_observation(node_id, attempt, provider_model)
        obs.prompt_fingerprint = RequestObservation.fingerprint(input_data)
        obs.output_fingerprint = RequestObservation.fingerprint(output_data)
        obs.input_size = len(str(input_data))
        obs.output_size = len(str(output_data))
        obs.duration_ms = duration_ms
        obs.status = status
        obs.error = error
        if consumer_edges:
            obs.consumer_edges = [
                ConsumerEdge(
                    field=e.get("field", ""),
                    consumer=e.get("consumer", ""),
                    validated=e.get("validated", False),
                    validation_error=e.get("validation_error"),
                )
                for e in consumer_edges
            ]
        return obs

    def get_all(self) -> list[dict]:
        """Return all observation records."""
        return [obs.to_dict() for obs in self._observations]

    def get_by_node(self, node_id: str) -> list[dict]:
        """Filter observation records by node ID."""
        return [obs.to_dict() for obs in self._observations if obs.node_id == node_id]

    def summary(self) -> dict:
        """Generate an observation summary."""
        total = len(self._observations)
        completed = sum(1 for o in self._observations if o.status == "completed")
        failed = sum(1 for o in self._observations if o.status == "failed")
        retried = sum(1 for o in self._observations if o.status == "retried")
        total_duration = sum(o.duration_ms for o in self._observations)
        return {
            "total_requests": total,
            "completed": completed,
            "failed": failed,
            "retried": retried,
            "total_duration_ms": round(total_duration, 2),
            "nodes": list(set(o.node_id for o in self._observations)),
        }
