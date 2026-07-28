-- Schema for storing past optimization attempts
CREATE TABLE IF NOT EXISTS optimization_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    codebase_fingerprint TEXT NOT NULL,
    pattern_type TEXT NOT NULL,
    hypothesis TEXT,
    diff_summary TEXT,
    measured_speedup_ratio REAL,
    outcome TEXT CHECK(outcome IN ('accepted', 'rejected', 'regressed')),
    notes TEXT
);
