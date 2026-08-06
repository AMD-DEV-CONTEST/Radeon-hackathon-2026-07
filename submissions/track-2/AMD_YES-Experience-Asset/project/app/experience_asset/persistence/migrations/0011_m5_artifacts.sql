-- M5 route matrix, privacy review, and approval storage.
--
-- PR #31 delivered E6 as pure policy with no persistence, which is enough to
-- prove the rules and not enough to survive a restart. Without these tables the
-- user resolves a privacy finding, closes the tab, and comes back to an asset
-- that has no memory of the decision — so the export gate re-opens and the
-- approval the product promised was "bound to exact version and hash" turns out
-- to have been bound to a process that exited.
--
-- Rows are keyed by the exact (asset, version, content hash) the policy
-- evaluated. That is deliberate: a review or approval retrieved for a different
-- version is not a stale copy to refresh, it is an answer to a different
-- question, and the read must miss rather than return it.

CREATE TABLE IF NOT EXISTS m5_privacy_reviews (
    review_id TEXT PRIMARY KEY,
    asset_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    review_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    failure_code TEXT,
    content_json TEXT NOT NULL,
    created_by_run_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    superseded_at TEXT,
    FOREIGN KEY (asset_id) REFERENCES assets(asset_id) ON DELETE CASCADE,
    FOREIGN KEY (version_id) REFERENCES asset_versions(version_id) ON DELETE CASCADE
);

-- Resolving a finding mints a successor review rather than mutating one, so the
-- history of what the user was shown when they decided stays readable. Only one
-- review per binding may be live at a time.
CREATE UNIQUE INDEX IF NOT EXISTS idx_m5_privacy_reviews_live
ON m5_privacy_reviews(asset_id, version_id, content_hash)
WHERE superseded_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_m5_privacy_reviews_binding
ON m5_privacy_reviews(asset_id, version_id, content_hash);

CREATE TABLE IF NOT EXISTS m5_route_matrices (
    matrix_id TEXT PRIMARY KEY,
    asset_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    matrix_hash TEXT NOT NULL,
    review_hash TEXT,
    content_json TEXT NOT NULL,
    created_by_run_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    superseded_at TEXT,
    FOREIGN KEY (asset_id) REFERENCES assets(asset_id) ON DELETE CASCADE,
    FOREIGN KEY (version_id) REFERENCES asset_versions(version_id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_m5_route_matrices_live
ON m5_route_matrices(asset_id, version_id, content_hash)
WHERE superseded_at IS NULL;

-- Approvals are append-only. A withdrawn or stale approval is recorded as such
-- and never deleted: deleting it would make "the user approved this and later
-- changed the card" indistinguishable from "the user never approved anything",
-- and the export audit trail depends on telling those apart.
CREATE TABLE IF NOT EXISTS m5_approvals (
    approval_id TEXT PRIMARY KEY,
    asset_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    route TEXT NOT NULL,
    language TEXT NOT NULL,
    draft_id TEXT NOT NULL,
    draft_binding_hash TEXT NOT NULL,
    review_hash TEXT NOT NULL,
    matrix_hash TEXT NOT NULL,
    content_json TEXT NOT NULL,
    created_by_run_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    stale_since TEXT,
    stale_reason TEXT,
    FOREIGN KEY (asset_id) REFERENCES assets(asset_id) ON DELETE CASCADE,
    FOREIGN KEY (version_id) REFERENCES asset_versions(version_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_m5_approvals_binding
ON m5_approvals(asset_id, version_id, content_hash);

CREATE INDEX IF NOT EXISTS idx_m5_approvals_draft
ON m5_approvals(draft_id);
