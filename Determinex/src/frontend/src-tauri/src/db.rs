use rusqlite::Connection;
use std::path::PathBuf;
use std::sync::Mutex;

type DbResult<T> = Result<T, Box<dyn std::error::Error>>;

pub struct DbState {
    pub conn: Mutex<Connection>,
}

/// Shared app data directory path — injected at startup via `app.path().app_data_dir()`.
/// Used by any module that needs to read/write files alongside the database
/// (e.g. registry.rs for models_registry.json).
pub struct AppDataDir(pub PathBuf);

/// Apply the full Determinex schema to an open connection.
/// Called on both file and in-memory DBs so the fallback path is identical.
pub fn apply_schema(conn: &Connection) -> DbResult<()> {
    conn.execute_batch(
        "
        PRAGMA journal_mode = WAL;
        PRAGMA synchronous = NORMAL;
        PRAGMA temp_store = MEMORY;
        PRAGMA busy_timeout = 5000;
        PRAGMA wal_autocheckpoint = 1000;
        PRAGMA page_size = 4096;
        ",
    )?;

    conn.execute_batch(
        "
        CREATE TABLE IF NOT EXISTS api_keys (
            provider TEXT PRIMARY KEY,
            api_key TEXT NOT NULL,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS threads (
            thread_id TEXT PRIMARY KEY,
            title TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS ideation_todos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            thread_id TEXT NOT NULL,
            text TEXT NOT NULL,
            done BOOLEAN DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (thread_id) REFERENCES threads(thread_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS wisdom (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            metadata TEXT
        );

        -- Single-row config store for LocalModelSettingsPanel. Config only --
        -- never a trigger for a live model call (see LOCAL_MODEL_SETTINGS_PANEL_LOCK_001).
        CREATE TABLE IF NOT EXISTS local_model_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            config_json TEXT NOT NULL,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        ",
    )?;

    conn.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS vss_wisdom USING vec0(
            embedding_vector float[384]
        );",
        [],
    )?;

    conn.execute_batch(
        "
        CREATE TABLE IF NOT EXISTS knowledge_rust (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            metadata TEXT
        );

        CREATE TABLE IF NOT EXISTS knowledge_web (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            metadata TEXT
        );

        CREATE TABLE IF NOT EXISTS knowledge_security (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            metadata TEXT
        );

        CREATE TABLE IF NOT EXISTS knowledge_architecture (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            metadata TEXT
        );

        CREATE TABLE IF NOT EXISTS knowledge_companion (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            metadata TEXT
        );

        CREATE TABLE IF NOT EXISTS memory_sources (
            source_id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_path TEXT NOT NULL UNIQUE,
            source_sha256 TEXT NOT NULL,
            source_type TEXT NOT NULL,
            authority TEXT NOT NULL,
            proof_status TEXT NOT NULL,
            chunk_count INTEGER NOT NULL DEFAULT 0,
            indexed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            is_stale BOOLEAN NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS memory_chunks (
            chunk_id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id INTEGER NOT NULL,
            collection TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            chunk_sha256 TEXT NOT NULL,
            metadata TEXT NOT NULL,
            knowledge_rowid INTEGER,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(source_id) REFERENCES memory_sources(source_id) ON DELETE CASCADE,
            UNIQUE(source_id, chunk_index)
        );

        CREATE INDEX IF NOT EXISTS idx_memory_sources_type
            ON memory_sources(source_type, is_stale);

        CREATE INDEX IF NOT EXISTS idx_memory_chunks_source
            ON memory_chunks(source_id, collection);
        ",
    )?;

    conn.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS vss_code_rust USING vec0(embedding_vector float[384]);",
        [],
    )?;
    conn.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS vss_code_web USING vec0(embedding_vector float[384]);",
        [],
    )?;
    conn.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS vss_security USING vec0(embedding_vector float[384]);",
        [],
    )?;
    conn.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS vss_architecture USING vec0(embedding_vector float[384]);",
        []
    )?;
    conn.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS vss_companion USING vec0(embedding_vector float[384]);",
        [],
    )?;

    Ok(())
}

/// Refuse to continue if SQLite reports on-disk corruption.
///
/// This runs before schema migration on startup so a damaged user database does
/// not get mutated further. `VACUUM` is intentionally not run automatically:
/// it rewrites the entire database and is better reserved for explicit repair
/// or maintenance flows.
fn verify_integrity(conn: &Connection, db_path: &std::path::Path) -> DbResult<()> {
    let mut stmt = conn.prepare("PRAGMA integrity_check;")?;
    let rows = stmt.query_map([], |row| row.get::<_, String>(0))?;
    let mut problems = Vec::new();
    for row in rows {
        let value = row?;
        if value != "ok" {
            problems.push(value);
        }
    }

    if problems.is_empty() {
        Ok(())
    } else {
        let preview = problems.into_iter().take(5).collect::<Vec<_>>().join("; ");
        Err(format!(
            "SQLite integrity_check failed for {}: {}",
            db_path.display(),
            preview
        )
        .into())
    }
}

/// Initialize the SQLite database inside `data_dir`.
/// The directory is created if it doesn't exist.
pub fn initialize_database(data_dir: PathBuf) -> DbResult<Connection> {
    if !data_dir.exists() {
        std::fs::create_dir_all(&data_dir)?;
    }

    let db_path = data_dir.join("determinex.sqlite");

    // FIX #1b: sqlite-vec is compiled into the binary at link-time via the `sqlite-vec` crate.
    unsafe {
        // SAFETY: sqlite3_vec_init IS the correct C extension entry point. We transmute
        // between two C function pointer types that are ABI-compatible: the only differences
        // are (a) return void vs i32 — both are ignored by sqlite3_auto_extension, and
        // (b) const vs mut on the errmsg char** parameter — both are pointer-width identical.
        rusqlite::ffi::sqlite3_auto_extension(Some(std::mem::transmute(
            sqlite_vec::sqlite3_vec_init as *const (),
        )));
    }

    let conn = Connection::open(&db_path)?;
    verify_integrity(&conn, &db_path)?;
    apply_schema(&conn)?;
    Ok(conn)
}

/// Perform a WAL checkpoint with TRUNCATE mode.
///
/// This should be called periodically after bulk write operations (e.g., after
/// vector ingest completes) to:
///   1. Move all WAL changes into the main database file.
///   2. Truncate the WAL file back to zero bytes.
///
/// Without this, the WAL file grows monotonically on Windows (NTFS doesn't
/// support sparse files well) and can consume hundreds of MB on small SSDs.
///
/// This is safe to call while readers are active — SQLite WAL mode allows
/// concurrent reads during checkpoint. However, it will block if an active
/// write transaction is in progress.
#[allow(dead_code)]
pub fn wal_checkpoint_truncate(conn: &Connection) -> rusqlite::Result<()> {
    conn.execute_batch("PRAGMA wal_checkpoint(TRUNCATE);")?;
    Ok(())
}
