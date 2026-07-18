from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import uuid4

from cortex.core.article import Provenance


class ProvenanceHelpers:
    """Static helpers for constructing/embellishing Provenance objects."""

    @staticmethod
    def _build_provenance(node) -> Provenance:
        return Provenance(
            producer_agent=node.agent_did,
            producer_org=node.org_did,
            computation_ref=None,
            source_data_hash=None,
            source_data_schema=None,
            run_id=str(uuid4()),
            timestamp=datetime.now(UTC),
        )

    @staticmethod
    def from_seed(seed_dict: dict) -> Provenance:
        """Construct a Provenance auto-filling run_id and timestamp."""
        seed = dict(seed_dict)
        seed.setdefault("run_id", str(uuid4()))
        seed.setdefault("timestamp", datetime.now(UTC))
        return Provenance(**seed)

    @staticmethod
    def with_source_hash(prov: Provenance, raw_data: bytes, schema_desc: str) -> Provenance:
        """Return a copy of `prov` with source_data_hash / source_data_schema set."""
        return Provenance(
            producer_agent=prov.producer_agent,
            producer_org=prov.producer_org,
            computation_ref=prov.computation_ref,
            source_data_hash=hashlib.sha256(raw_data).hexdigest(),
            source_data_schema=schema_desc,
            run_id=prov.run_id,
            timestamp=prov.timestamp,
        )
