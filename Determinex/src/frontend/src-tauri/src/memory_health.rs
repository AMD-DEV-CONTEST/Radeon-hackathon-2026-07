use crate::db::DbState;
use crate::vector_engine::VectorState;
use rusqlite::Connection;
use serde::Serialize;
use tauri::State;

#[derive(Serialize)]
pub struct MemoryHealth {
    pub vector_enabled: bool,
    pub vector_init_error: Option<String>,
    pub knowledge_companion_rows: i64,
    pub vss_companion_rows: i64,
    pub memory_sources: i64,
    pub memory_chunks: i64,
    pub stale_sources: i64,
    pub source_paths: Vec<String>,
}

#[tauri::command]
pub fn get_memory_health(
    db_state: State<'_, DbState>,
    vec_state: State<'_, VectorState>,
) -> Result<MemoryHealth, String> {
    let vector_enabled = vec_state
        .model
        .lock()
        .map_err(|e| format!("VectorState mutex poisoned: {e}"))?
        .is_some();

    let conn = db_state
        .conn
        .lock()
        .map_err(|e| format!("DbState mutex poisoned: {e}"))?;

    Ok(MemoryHealth {
        vector_enabled,
        vector_init_error: vec_state.init_error.clone(),
        knowledge_companion_rows: count_rows(&conn, "knowledge_companion"),
        vss_companion_rows: count_rows(&conn, "vss_companion"),
        memory_sources: count_rows(&conn, "memory_sources"),
        memory_chunks: count_rows(&conn, "memory_chunks"),
        stale_sources: count_stale_sources(&conn),
        source_paths: companion_source_paths(&conn),
    })
}

fn count_rows(conn: &Connection, table: &str) -> i64 {
    let sql = match table {
        "knowledge_companion" => "SELECT COUNT(*) FROM knowledge_companion",
        "vss_companion" => "SELECT COUNT(*) FROM vss_companion",
        "memory_sources" => "SELECT COUNT(*) FROM memory_sources",
        "memory_chunks" => "SELECT COUNT(*) FROM memory_chunks",
        _ => return 0,
    };
    conn.query_row(sql, [], |row| row.get(0)).unwrap_or(0)
}

fn count_stale_sources(conn: &Connection) -> i64 {
    conn.query_row(
        "SELECT COUNT(*) FROM memory_sources WHERE is_stale = 1",
        [],
        |row| row.get(0),
    )
    .unwrap_or(0)
}

fn companion_source_paths(conn: &Connection) -> Vec<String> {
    let Ok(mut stmt) = conn.prepare(
        "SELECT source_path FROM memory_sources
         WHERE source_type = 'companion_doc'
         ORDER BY source_path",
    ) else {
        return Vec::new();
    };

    let Ok(rows) = stmt.query_map([], |row| row.get::<_, String>(0)) else {
        return Vec::new();
    };

    rows.filter_map(Result::ok).collect()
}
