-- Retrieval-phase events emitted by the product path.
--
-- The shape is not new. `qa/schema/retrieval_phase_trace.schema.json` froze it,
-- `qa/scripts/check_retrieval_phase.py` already enforces its ordering
-- invariants, and `capture_e2_m1_local_evidence.py` has been emitting one event
-- type since E2. What was missing is that no product operation wrote into it,
-- so the only traces that existed were built by an evidence-capture script.
--
-- Stored per asset rather than per run: the checker's invariants are about the
-- order of phases across a whole asset's life — readiness before any
-- cross-asset search, confirmation before any detail read — and a per-run table
-- could not express "before" across two runs.

CREATE TABLE IF NOT EXISTS retrieval_phase_events (
    event_id TEXT PRIMARY KEY,
    asset_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    event_type TEXT NOT NULL
        CHECK (event_type IN ('current_source_retrieval', 'current_card_changed',
                              'knowledge_card_ready', 'relation_candidate_search',
                              'relation_confirmation', 'relation_detail_retrieval',
                              'relation_no_match')),
    payload_json TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    -- Strictly increasing per asset, which is what the checker tests. A shared
    -- sequence would let two assets interleave into an order neither of them
    -- experienced.
    UNIQUE (asset_id, sequence),
    FOREIGN KEY (asset_id) REFERENCES assets(asset_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_retrieval_phase_asset
ON retrieval_phase_events(asset_id, sequence);
