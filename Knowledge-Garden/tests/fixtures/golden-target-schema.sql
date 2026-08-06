-- 0001_initial.sql — Learning Companion 目标 schema（规范性，见 docs/domain-contract.md §1）
-- 幂等：CREATE TABLE IF NOT EXISTS

CREATE TABLE IF NOT EXISTS skills (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT NOT NULL UNIQUE,
    description      TEXT DEFAULT '',
    growth_value     REAL NOT NULL DEFAULT 0,
    decay_rate       REAL NOT NULL DEFAULT 3.0,
    status           TEXT NOT NULL DEFAULT '萌芽',
    last_reviewed_at TEXT,
    last_decay_at    TEXT,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS materials (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_id         INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    raw_text         TEXT NOT NULL,
    normalized_text  TEXT NOT NULL,
    content_sha256   TEXT NOT NULL,
    filename         TEXT DEFAULT '',
    created_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_materials_skill ON materials(skill_id);

CREATE TABLE IF NOT EXISTS extraction_runs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    material_id      INTEGER NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
    status           TEXT NOT NULL DEFAULT 'queued',   -- queued|running|verified|failed
    model            TEXT,
    error_detail     TEXT,
    retries          INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_extraction_runs_material ON extraction_runs(material_id);

CREATE TABLE IF NOT EXISTS learning_units (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_id                INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    content                 TEXT NOT NULL,
    source_material         TEXT,
    source_start            INTEGER,
    source_end              INTEGER,
    source_quote            TEXT,
    key_points              TEXT DEFAULT '[]',          -- JSON 数组
    example                 TEXT,
    pitfall                 TEXT,
    accepted_misconceptions TEXT DEFAULT '[]',          -- JSON 数组
    status                  TEXT NOT NULL DEFAULT 'candidate',  -- preview|verified|duplicate|rejected|superseded
    created_at              TEXT NOT NULL,
    updated_at              TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_units_skill ON learning_units(skill_id);

CREATE TABLE IF NOT EXISTS learning_progress (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    unit_id           INTEGER NOT NULL UNIQUE REFERENCES learning_units(id) ON DELETE CASCADE,
    progress_status   TEXT NOT NULL DEFAULT 'unlearned', -- unlearned|learning|assessment_due|review_due|mastered
    mastery_level     INTEGER NOT NULL DEFAULT 0,
    repetitions       INTEGER NOT NULL DEFAULT 0,
    ease_factor       REAL NOT NULL DEFAULT 2.5,
    interval_days     REAL NOT NULL DEFAULT 0,
    next_review_at    TEXT,
    progress_version  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_progress_due ON learning_progress(next_review_at) WHERE next_review_at IS NOT NULL;

CREATE TABLE IF NOT EXISTS study_sessions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_id        INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    session_type    TEXT NOT NULL,                    -- learn|assessment|review
    status          TEXT NOT NULL DEFAULT 'active',   -- active|completed|abandoned
    idempotency_key TEXT,
    created_at      TEXT NOT NULL,
    completed_at    TEXT,
    UNIQUE(skill_id, session_type, idempotency_key)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_session_active
    ON study_sessions(skill_id, session_type) WHERE status = 'active';

CREATE TABLE IF NOT EXISTS assessment_attempts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      INTEGER NOT NULL REFERENCES study_sessions(id) ON DELETE CASCADE,
    unit_id         INTEGER NOT NULL REFERENCES learning_units(id) ON DELETE CASCADE,
    idempotency_key TEXT NOT NULL,
    payload_hash    TEXT NOT NULL,
    recall_text     TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'judged',   -- judged|failed
    score           INTEGER,
    mastery_level   INTEGER,
    needs_retry     INTEGER,
    created_at      TEXT NOT NULL,
    UNIQUE(session_id, idempotency_key, payload_hash)
);
CREATE INDEX IF NOT EXISTS idx_attempts_unit ON assessment_attempts(unit_id);
