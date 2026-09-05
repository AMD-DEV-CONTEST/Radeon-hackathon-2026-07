-- E5 relation ledger: the sole persistence authority for readiness, role-graph
-- projections, discovery attempts, candidates, decisions and confirmed
-- relations.
--
-- These are sidecar aggregates in the same SQLite database, deliberately
-- separate from the immutable Experience Asset snapshot. Persisting a
-- confirmation inside the snapshot would append a new asset content version and
-- change its content hash, while GRAG-14 requires that hash identical before
-- and after a relation read. One database keeps invalidation transactional; a
-- second store would hold a copy of canonical state that must be invalidated in
-- lockstep, and any partial failure would leave the two disagreeing.
--
-- This migration adds tables only. No product behaviour reads or writes them
-- yet; tickets 02 through 09 fill them in.

PRAGMA foreign_keys = ON;

-- --------------------------------------------------------------------------
-- Parent keys for composite references
--
-- SQLite requires a UNIQUE index on the exact parent columns a composite
-- foreign key names, otherwise the reference is rejected as a mismatch. These
-- indexes add no new data; they make "this version belongs to this asset"
-- expressible as a constraint rather than as a convention nobody enforces.
-- --------------------------------------------------------------------------

CREATE UNIQUE INDEX IF NOT EXISTS idx_asset_versions_asset_identity
ON asset_versions(asset_id, version_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_m3_artifacts_asset_identity
ON m3_artifacts(asset_id, artifact_id);

-- --------------------------------------------------------------------------
-- M4 artifacts (Insight and Boundary Map)
-- --------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS m4_artifacts (
    artifact_id TEXT PRIMARY KEY,
    asset_id TEXT NOT NULL,
    parent_artifact_id TEXT,
    base_m3_artifact_id TEXT NOT NULL,
    base_canonical_version_id TEXT NOT NULL,
    content_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (asset_id) REFERENCES assets(asset_id) ON DELETE CASCADE,
    -- A parent from another asset would make this artifact's lineage cross
    -- experiences, and every version and hash derived from it would describe a
    -- history that is not this asset's.
    FOREIGN KEY (asset_id, parent_artifact_id)
        REFERENCES m4_artifacts(asset_id, artifact_id) ON DELETE CASCADE,
    -- Composite keys, not single-column ones. A single-column reference only
    -- proves the row exists somewhere; it lets an M4 artifact for asset B cite
    -- asset A's ledger and canonical version, and every readiness, hash,
    -- permission and invalidation decision downstream then rests on a version
    -- that belongs to a different experience.
    FOREIGN KEY (asset_id, base_m3_artifact_id)
        REFERENCES m3_artifacts(asset_id, artifact_id) ON DELETE CASCADE,
    FOREIGN KEY (asset_id, base_canonical_version_id)
        REFERENCES asset_versions(asset_id, version_id) ON DELETE CASCADE,
    UNIQUE (asset_id, artifact_id)
);

CREATE TABLE IF NOT EXISTS m4_current (
    asset_id TEXT PRIMARY KEY,
    artifact_id TEXT NOT NULL,
    FOREIGN KEY (asset_id) REFERENCES assets(asset_id) ON DELETE CASCADE,
    -- "Current for asset A" must point at an artifact of asset A.
    FOREIGN KEY (asset_id, artifact_id)
        REFERENCES m4_artifacts(asset_id, artifact_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_m4_artifacts_asset
ON m4_artifacts(asset_id, created_at);

-- --------------------------------------------------------------------------
-- Readiness sidecar
--
-- Keyed by asset, version and card hash rather than stored on the snapshot.
-- Readiness is created by an explicit action after a version exists, so storing
-- it inside the snapshot would require a new version, leaving the version that
-- records readiness permanently one step ahead of the version judged ready.
-- --------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS knowledge_card_readiness (
    readiness_id TEXT PRIMARY KEY,
    asset_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    m4_artifact_id TEXT NOT NULL,
    knowledge_card_hash TEXT NOT NULL,
    milestone_state TEXT NOT NULL
        CHECK (milestone_state IN ('CONFIRMED', 'COMPLETE_WITH_GAPS')),
    explicit_user_acceptance INTEGER NOT NULL DEFAULT 1
        CHECK (explicit_user_acceptance = 1),
    content_json TEXT NOT NULL,
    -- No BUILDING: readiness is minted whole by one explicit acceptance, so a
    -- half-built readiness row has no meaning and two consumers could read it
    -- as opposite answers to "is this card ready".
    lifecycle TEXT NOT NULL DEFAULT 'ACTIVE'
        CHECK (lifecycle IN ('ACTIVE', 'STALE', 'INVALIDATED')),
    accepted_at TEXT NOT NULL,
    invalidated_at TEXT,
    invalidation_reason TEXT,
    -- The lifecycle and its evidence must agree in both directions, or an
    -- ACTIVE row could carry an invalidation timestamp and no fail-closed gate
    -- could be built on it.
    CHECK (
        (lifecycle = 'ACTIVE'
            AND invalidated_at IS NULL AND invalidation_reason IS NULL)
        OR (lifecycle IN ('STALE', 'INVALIDATED')
            AND invalidated_at IS NOT NULL AND invalidation_reason IS NOT NULL)
    ),
    UNIQUE (asset_id, version_id, knowledge_card_hash),
    FOREIGN KEY (asset_id) REFERENCES assets(asset_id) ON DELETE CASCADE,
    -- Deleting an asset must be able to complete. A composite reference that
    -- blocks the delete converts a privacy request into a failure, which is
    -- fail-closed but leaves the user unable to remove their own data.
    FOREIGN KEY (asset_id, version_id)
        REFERENCES asset_versions(asset_id, version_id) ON DELETE CASCADE,
    FOREIGN KEY (asset_id, m4_artifact_id)
        REFERENCES m4_artifacts(asset_id, artifact_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_readiness_active
ON knowledge_card_readiness(asset_id, lifecycle);

-- --------------------------------------------------------------------------
-- Role-graph projections
--
-- `projection_hash` is stored so activation can require the recomputed hash to
-- match. A projection whose stored and recomputed hashes disagree has drifted
-- from its inputs and must not be compared against.
-- --------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS role_graph_projections (
    projection_id TEXT PRIMARY KEY,
    asset_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    knowledge_card_hash TEXT NOT NULL,
    projection_schema_version TEXT NOT NULL,
    projection_hash TEXT NOT NULL,
    lifecycle TEXT NOT NULL
        CHECK (lifecycle IN ('BUILDING', 'ACTIVE', 'STALE', 'INVALIDATED')),
    created_at TEXT NOT NULL,
    invalidated_at TEXT,
    invalidation_reason TEXT,
    CHECK (
        (lifecycle IN ('BUILDING', 'ACTIVE')
            AND invalidated_at IS NULL AND invalidation_reason IS NULL)
        OR (lifecycle IN ('STALE', 'INVALIDATED')
            AND invalidated_at IS NOT NULL AND invalidation_reason IS NOT NULL)
    ),
    UNIQUE (asset_id, projection_id),
    FOREIGN KEY (asset_id) REFERENCES assets(asset_id) ON DELETE CASCADE,
    FOREIGN KEY (asset_id, version_id)
        REFERENCES asset_versions(asset_id, version_id) ON DELETE CASCADE
);

-- At most one active projection per asset version and card hash. Two active
-- projections for one ready card would let discovery compare against whichever
-- the query happened to read first.
CREATE UNIQUE INDEX IF NOT EXISTS idx_projection_active_unique
ON role_graph_projections(asset_id, version_id, knowledge_card_hash)
WHERE lifecycle = 'ACTIVE';

CREATE INDEX IF NOT EXISTS idx_projection_eligibility
ON role_graph_projections(lifecycle, asset_id);

-- A projection determines the version and card hash it was built from, so
-- binding a decision to the projection is what pins the version and hash it
-- was made against. Binding version and hash to *any* readiness row of the
-- same asset is not enough: a second accepted version has its own readiness,
-- so the reference would be satisfied while the decision described a different
-- card than the candidate was computed from.
CREATE UNIQUE INDEX IF NOT EXISTS idx_projection_full_identity
ON role_graph_projections(
    projection_id, asset_id, version_id, knowledge_card_hash
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_projection_asset_version
ON role_graph_projections(projection_id, asset_id, version_id);

CREATE TABLE IF NOT EXISTS role_graph_nodes (
    projection_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    root_kind TEXT NOT NULL
        CHECK (root_kind IN ('CRITICAL_MOMENT', 'DECISION_RECORD', 'INSIGHT_RECORD')),
    canonical_record_id TEXT NOT NULL,
    is_root INTEGER NOT NULL CHECK (is_root IN (0, 1)),
    role TEXT,
    display_order INTEGER NOT NULL,
    summary_text TEXT NOT NULL,
    summary_text_hash TEXT NOT NULL,
    PRIMARY KEY (projection_id, node_id),
    CHECK ((is_root = 1 AND role IS NULL) OR (is_root = 0 AND role IS NOT NULL)),
    FOREIGN KEY (projection_id) REFERENCES role_graph_projections(projection_id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS role_graph_edges (
    projection_id TEXT NOT NULL,
    edge_id TEXT NOT NULL,
    edge_type TEXT NOT NULL,
    root_node_id TEXT NOT NULL,
    member_node_id TEXT NOT NULL,
    canonical_record_id TEXT NOT NULL,
    PRIMARY KEY (projection_id, edge_id),
    CHECK (root_node_id <> member_node_id),
    FOREIGN KEY (projection_id) REFERENCES role_graph_projections(projection_id)
        ON DELETE CASCADE,
    FOREIGN KEY (projection_id, root_node_id)
        REFERENCES role_graph_nodes(projection_id, node_id),
    FOREIGN KEY (projection_id, member_node_id)
        REFERENCES role_graph_nodes(projection_id, node_id)
);

-- At least one statement reference is required for any node that can appear in
-- a candidate: a node without one could be shown as part of an explanation
-- while resting on nothing the user can open and check.
CREATE TABLE IF NOT EXISTS role_graph_node_provenance (
    projection_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    statement_ids_json TEXT NOT NULL,
    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
    source_refs_json TEXT NOT NULL DEFAULT '[]',
    span_refs_json TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (projection_id, node_id),
    FOREIGN KEY (projection_id, node_id)
        REFERENCES role_graph_nodes(projection_id, node_id) ON DELETE CASCADE
);

-- --------------------------------------------------------------------------
-- Lexical summary index
--
-- Only active ready-card summary material is indexed. Indexing raw chat or
-- unconfirmed proposals would let material the user never confirmed become
-- cross-asset memory and reach the model on a later discovery.
--
-- Tokens are generated by the application (Latin case-folded and word
-- tokenized, CJK given character n-grams) rather than by an optional SQLite
-- tokenizer, so lexical behaviour is identical on a developer machine and in
-- the evaluation environment.
-- --------------------------------------------------------------------------

CREATE VIRTUAL TABLE IF NOT EXISTS relation_summary_fts USING fts5(
    projection_id UNINDEXED,
    asset_id UNINDEXED,
    asset_title,
    summary_text,
    lexical_tokens,
    role_signature,
    tokenize = 'unicode61 remove_diacritics 2'
);

-- Deletion protocol.
--
-- An FTS5 table is standalone storage: it holds its own copy of the indexed
-- text and nothing removes that copy when the row it came from disappears.
-- Without these triggers, deleting an asset or narrowing its privacy scope
-- would leave the summary title and body permanently searchable — the deletion
-- would look complete while the content it was meant to remove is still
-- readable through a query.
--
-- The triggers make removal a property of the schema rather than of whichever
-- application path happens to remember. A path that forgets is the normal
-- outcome: the index is invisible from the caller's point of view, so nothing
-- reminds the author it exists.

CREATE TRIGGER IF NOT EXISTS trg_relation_summary_fts_projection_deleted
AFTER DELETE ON role_graph_projections
BEGIN
    DELETE FROM relation_summary_fts
    WHERE projection_id = OLD.projection_id;
END;

-- Leaving ACTIVE removes eligibility, and an index row that outlives
-- eligibility still grants a match for canonical state that has changed.
CREATE TRIGGER IF NOT EXISTS trg_relation_summary_fts_projection_deactivated
AFTER UPDATE OF lifecycle ON role_graph_projections
WHEN OLD.lifecycle = 'ACTIVE' AND NEW.lifecycle <> 'ACTIVE'
BEGIN
    DELETE FROM relation_summary_fts
    WHERE projection_id = NEW.projection_id;
END;

-- Assets cascade to projections, but the FTS table is not a child of either, so
-- the cascade alone would leave its rows behind.
CREATE TRIGGER IF NOT EXISTS trg_relation_summary_fts_asset_deleted
AFTER DELETE ON assets
BEGIN
    DELETE FROM relation_summary_fts WHERE asset_id = OLD.asset_id;
END;

-- --------------------------------------------------------------------------
-- Discovery attempts
--
-- Reserved before inference so that a process dying mid-flight is recovered or
-- safely marked retryable rather than assumed successful. Technical failures
-- are retained for audit but never reused as a semantic result: reusing one
-- would let a brief outage permanently erase a relation that may well exist.
-- --------------------------------------------------------------------------

-- --------------------------------------------------------------------------
-- Discovery fingerprint records
--
-- The attempt stores only the digest. Without the inputs that produced it,
-- nothing can later show that a cached result corresponds to the declared
-- model, prompt and configuration — the digest would be a number nobody can
-- re-derive, and restart-time audit could not distinguish a legitimate cache
-- hit from a collision or a stale entry.
--
-- Kept in its own table rather than widened onto the attempt because many
-- attempts share one fingerprint: storing the inputs per attempt would repeat
-- them and let two attempts disagree about what the same digest meant.
-- --------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS discovery_fingerprint_records (
    discovery_fingerprint TEXT PRIMARY KEY,
    fingerprint_schema_version TEXT NOT NULL,
    current_asset_id TEXT NOT NULL,
    current_version_id TEXT NOT NULL,
    current_knowledge_card_hash TEXT NOT NULL,
    current_projection_hash TEXT NOT NULL,
    eligible_projection_hashes_json TEXT NOT NULL,
    model_identity TEXT NOT NULL,
    model_revision TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    role_contract_version TEXT NOT NULL,
    validation_contract_version TEXT NOT NULL,
    discovery_intent_version TEXT NOT NULL,
    inference_parameters_hash TEXT NOT NULL,
    prefilter_config_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (current_asset_id) REFERENCES assets(asset_id) ON DELETE CASCADE,
    FOREIGN KEY (current_asset_id, current_version_id)
        REFERENCES asset_versions(asset_id, version_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS relation_discovery_attempts (
    attempt_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    discovery_fingerprint TEXT NOT NULL,
    current_projection_id TEXT NOT NULL,
    eligible_set_hash TEXT NOT NULL,
    attempt_number INTEGER NOT NULL CHECK (attempt_number >= 1),
    outcome TEXT NOT NULL
        CHECK (outcome IN ('NOT_READY', 'RUNNING', 'CANDIDATE', 'NO_MATCH',
                           'TECHNICAL_FAILURE', 'STALE')),
    failure_class TEXT,
    candidate_id TEXT,
    lease_expires_at TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    elapsed_ms INTEGER,
    UNIQUE (discovery_fingerprint, attempt_number),
    CHECK ((outcome = 'TECHNICAL_FAILURE') = (failure_class IS NOT NULL)),
    CHECK ((outcome = 'CANDIDATE') = (candidate_id IS NOT NULL)),
    -- A RUNNING attempt with no lease is invisible to expired-reservation
    -- recovery and blocks its fingerprint forever; a settled attempt still
    -- holding one would be recovered as though it were in flight.
    CHECK (
        (outcome = 'RUNNING'
            AND lease_expires_at IS NOT NULL AND finished_at IS NULL)
        OR (outcome <> 'RUNNING'
            AND lease_expires_at IS NULL AND finished_at IS NOT NULL)
    ),
    FOREIGN KEY (asset_id) REFERENCES assets(asset_id) ON DELETE CASCADE,
    -- Every attempt names a fingerprint whose inputs are on record, so a cached
    -- result can always be traced back to the model, prompt and configuration
    -- that produced it.
    FOREIGN KEY (discovery_fingerprint)
        REFERENCES discovery_fingerprint_records(discovery_fingerprint)
        ON DELETE CASCADE,
    FOREIGN KEY (asset_id, current_projection_id)
        REFERENCES role_graph_projections(asset_id, projection_id) ON DELETE CASCADE,
    -- The attempt and its candidate must share a fingerprint. Binding the id
    -- alone lets a cached result for one discovery input point at a candidate
    -- produced by a different one, so a later identical search would return an
    -- answer computed from other inputs.
    -- Fingerprint *and* projection. Same-fingerprint alone still allows an
    -- attempt attributed to another projection of the same asset, so the cached
    -- result would be explained by a graph the candidate was not computed from.
    FOREIGN KEY (candidate_id, discovery_fingerprint, asset_id, current_projection_id)
        REFERENCES relation_candidates(
            candidate_id, discovery_fingerprint, current_asset_id, current_projection_id
        ) ON DELETE CASCADE
);

-- One durable semantic result per fingerprint. Without this, two concurrent
-- clicks could each persist a different answer to one logical question and
-- whichever committed last would silently become the answer.
CREATE UNIQUE INDEX IF NOT EXISTS idx_attempt_semantic_result_unique
ON relation_discovery_attempts(discovery_fingerprint)
WHERE outcome IN ('CANDIDATE', 'NO_MATCH');

CREATE INDEX IF NOT EXISTS idx_attempt_fingerprint
ON relation_discovery_attempts(discovery_fingerprint, started_at);

-- --------------------------------------------------------------------------
-- Validated candidates, decisions and confirmed relations
-- --------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS relation_candidates (
    candidate_id TEXT PRIMARY KEY,
    discovery_fingerprint TEXT NOT NULL,
    current_asset_id TEXT NOT NULL,
    current_projection_id TEXT NOT NULL,
    related_asset_id TEXT NOT NULL,
    historical_projection_id TEXT NOT NULL,
    relation_type TEXT NOT NULL
        CHECK (relation_type IN ('SAME_THEME', 'METHOD_REUSE', 'COUNTEREXAMPLE',
                                 'SUPPLEMENT', 'PREREQUISITE', 'FOLLOW_UP')),
    validation_contract_version TEXT NOT NULL,
    lifecycle TEXT NOT NULL
        CHECK (lifecycle IN ('PROPOSED', 'CONFIRMED', 'DECLINED', 'STALE',
                             'INVALIDATED')),
    content_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    CHECK (current_asset_id <> related_asset_id),
    -- Children bind the candidate's whole input identity, not just its id.
    -- Binding the id alone lets a decision name candidate A→B while recording
    -- a different version, hash, projection or direction — so the row would
    -- point at a real candidate while describing something the user never saw.
    UNIQUE (
        candidate_id, discovery_fingerprint, current_asset_id,
        current_projection_id, related_asset_id, historical_projection_id,
        relation_type
    ),
    -- The related asset cascades too. Without it a privacy deletion of the
    -- historical side fails outright, which turns "revoke access" into "the
    -- request cannot complete".
    FOREIGN KEY (current_asset_id) REFERENCES assets(asset_id) ON DELETE CASCADE,
    FOREIGN KEY (related_asset_id) REFERENCES assets(asset_id) ON DELETE CASCADE,
    -- Each projection must belong to the asset the candidate names for that
    -- side. Single-column references would let a candidate explain asset A
    -- using a graph built from asset C.
    FOREIGN KEY (current_asset_id, current_projection_id)
        REFERENCES role_graph_projections(asset_id, projection_id) ON DELETE CASCADE,
    FOREIGN KEY (related_asset_id, historical_projection_id)
        REFERENCES role_graph_projections(asset_id, projection_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_candidate_fingerprint
ON relation_candidates(discovery_fingerprint);

-- SQLite matches a composite foreign key to a unique index on exactly those
-- columns. Decisions bind three of them and confirmed relations bind four, so
-- both shapes need their own index; one wider index does not satisfy the
-- narrower reference.
CREATE UNIQUE INDEX IF NOT EXISTS idx_candidate_asset_pair
ON relation_candidates(candidate_id, current_asset_id, related_asset_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_candidate_fingerprint_identity
ON relation_candidates(candidate_id, discovery_fingerprint);

CREATE UNIQUE INDEX IF NOT EXISTS idx_candidate_current_projection
ON relation_candidates(candidate_id, current_asset_id, current_projection_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_candidate_fingerprint_projection
ON relation_candidates(
    candidate_id, discovery_fingerprint, current_asset_id, current_projection_id
);

-- Decisions are append-only. One settled decision per candidate: submitting the
-- opposite decision later is refused rather than overwriting, so the audit trail
-- records what the user actually decided and when.
CREATE TABLE IF NOT EXISTS relation_candidate_decisions (
    decision_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    current_asset_id TEXT NOT NULL,
    current_version_id TEXT NOT NULL,
    current_knowledge_card_hash TEXT NOT NULL,
    current_projection_id TEXT NOT NULL,
    related_asset_id TEXT NOT NULL,
    user_action TEXT NOT NULL CHECK (user_action IN ('CONFIRM', 'DECLINE')),
    decided_at TEXT NOT NULL,
    UNIQUE (candidate_id),
    UNIQUE (candidate_id, decision_id),
    -- Exposed so a confirmed relation can require the action, not merely the
    -- existence of a decision. A DECLINE is a decision too, and proving only
    -- that one exists would let a refusal produce access.
    UNIQUE (candidate_id, decision_id, user_action),
    -- The decision binds the candidate's whole input identity, and its
    -- version/hash must match an ACTIVE readiness row. Otherwise the user's
    -- answer could be recorded against a different version of the same asset —
    -- a splice no cross-asset check catches, because nothing crosses assets.
    FOREIGN KEY (candidate_id, current_asset_id, related_asset_id)
        REFERENCES relation_candidates(candidate_id, current_asset_id, related_asset_id)
        ON DELETE CASCADE,
    -- The decision uses the candidate's own projection...
    FOREIGN KEY (candidate_id, current_asset_id, current_projection_id)
        REFERENCES relation_candidates(
            candidate_id, current_asset_id, current_projection_id
        ) ON DELETE CASCADE,
    -- ...and that projection determines the version and hash recorded here.
    FOREIGN KEY (
        current_projection_id, current_asset_id, current_version_id,
        current_knowledge_card_hash
    ) REFERENCES role_graph_projections(
        projection_id, asset_id, version_id, knowledge_card_hash
    ) ON DELETE CASCADE,
    FOREIGN KEY (current_asset_id, current_version_id, current_knowledge_card_hash)
        REFERENCES knowledge_card_readiness(asset_id, version_id, knowledge_card_hash)
        ON DELETE CASCADE
);

-- A confirmed relation carries its own identifier plus the candidate it came
-- from. They are distinct identifier spaces: reusing one as the other would hide
-- which object a binding refers to.
CREATE TABLE IF NOT EXISTS confirmed_asset_relations (
    relation_id TEXT PRIMARY KEY,
    source_candidate_id TEXT NOT NULL,
    source_discovery_fingerprint TEXT NOT NULL,
    confirming_decision_id TEXT NOT NULL,
    confirming_user_action TEXT NOT NULL DEFAULT 'CONFIRM'
        CHECK (confirming_user_action = 'CONFIRM'),
    relation_type TEXT NOT NULL
        CHECK (relation_type IN ('SAME_THEME', 'METHOD_REUSE', 'COUNTEREXAMPLE',
                                 'SUPPLEMENT', 'PREREQUISITE', 'FOLLOW_UP')),
    current_asset_id TEXT NOT NULL,
    current_version_id TEXT NOT NULL,
    current_projection_id TEXT NOT NULL,
    current_knowledge_card_hash TEXT NOT NULL,
    related_asset_id TEXT NOT NULL,
    related_version_id TEXT NOT NULL,
    historical_projection_id TEXT NOT NULL,
    -- No PROPOSED or DECLINED: this row exists only because a confirmation
    -- happened and it is required to carry confirmed_at.
    lifecycle TEXT NOT NULL
        CHECK (lifecycle IN ('CONFIRMED', 'STALE', 'INVALIDATED')),
    confirmed_at TEXT NOT NULL,
    invalidated_at TEXT,
    invalidation_reason TEXT,
    UNIQUE (source_candidate_id),
    CHECK (relation_id <> source_candidate_id),
    CHECK (current_asset_id <> related_asset_id),
    CHECK (
        (lifecycle = 'CONFIRMED'
            AND invalidated_at IS NULL AND invalidation_reason IS NULL)
        OR (lifecycle IN ('STALE', 'INVALIDATED')
            AND invalidated_at IS NOT NULL AND invalidation_reason IS NOT NULL)
    ),
    -- The relation must inherit the candidate's whole identity: same assets,
    -- same direction, same relation type. Binding only the candidate id lets a
    -- confirmation assert a different relation between different assets while
    -- still pointing at a candidate the user really was shown.
    -- Same inputs as the candidate the user was shown: fingerprint, both
    -- projections, both assets, direction and relation type. Verifying only
    -- that each side's projection belongs to its own asset still allows
    -- swapping in another projection of the *same* asset.
    FOREIGN KEY (
        source_candidate_id, source_discovery_fingerprint, current_asset_id,
        current_projection_id, related_asset_id, historical_projection_id,
        relation_type
    ) REFERENCES relation_candidates(
        candidate_id, discovery_fingerprint, current_asset_id,
        current_projection_id, related_asset_id, historical_projection_id,
        relation_type
    ) ON DELETE CASCADE,
    -- A confirmed relation exists only because the user confirmed. Without
    -- this, a row could assert a confirmation that never happened.
    -- The decision must be a CONFIRM. `confirming_user_action` is pinned to
    -- 'CONFIRM' by a CHECK, so this reference cannot be satisfied by a DECLINE.
    FOREIGN KEY (source_candidate_id, confirming_decision_id, confirming_user_action)
        REFERENCES relation_candidate_decisions(candidate_id, decision_id, user_action)
        ON DELETE CASCADE,
    -- Each side's version and card hash come from its own projection. Checking
    -- them separately lets a relation claim version V2 while pointing at a
    -- projection built from V1, or carry any 64 hex characters as the card the
    -- user accepted.
    FOREIGN KEY (
        current_projection_id, current_asset_id, current_version_id,
        current_knowledge_card_hash
    ) REFERENCES role_graph_projections(
        projection_id, asset_id, version_id, knowledge_card_hash
    ) ON DELETE CASCADE,
    FOREIGN KEY (historical_projection_id, related_asset_id, related_version_id)
        REFERENCES role_graph_projections(projection_id, asset_id, version_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_confirmed_relation_current
ON confirmed_asset_relations(current_asset_id, lifecycle);
