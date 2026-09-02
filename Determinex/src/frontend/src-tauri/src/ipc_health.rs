/// ipc_health.rs — Tauri IPC command for system health telemetry
///
/// Replaces the Python FastAPI `/api/health` endpoint with a native Rust
/// equivalent that runs inside the Tauri desktop shell.
///
/// Returns a JSON object matching the shape the frontend expects:
///   { status, ollama_up, vanguard_enabled, pack_task_active, api_keys_active, vector_wisdom_nodes }
use serde::Serialize;
use tauri::State;

use crate::db::DbState;
use crate::ipc_hive::HiveProcessMap;
use crate::vanguard_state::VanguardState;

// ─────────────────────────────────────────────────────────────────────────────
// RESPONSE SHAPE
// ─────────────────────────────────────────────────────────────────────────────

#[derive(Serialize)]
pub struct HealthTelemetry {
    pub status: String,
    pub ollama_up: bool,
    pub vanguard_enabled: bool,
    pub pack_task_active: bool,
    pub api_keys_active: Vec<String>,
    pub vector_wisdom_nodes: i32,
}

// ─────────────────────────────────────────────────────────────────────────────
// IPC COMMAND
// ─────────────────────────────────────────────────────────────────────────────

/// Return a snapshot of the system's operational health.
///
/// This is polled every 15 seconds by the frontend telemetry gauge.
/// The Ollama probe is inlined here to avoid a second IPC round-trip.
#[tauri::command]
pub async fn get_health_telemetry(
    vanguard: State<'_, VanguardState>,
    hive_processes: State<'_, HiveProcessMap>,
    db: State<'_, DbState>,
) -> Result<HealthTelemetry, String> {
    // Quick Ollama reachability check (2-second timeout).
    let ollama_up = match reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(2))
        .pool_max_idle_per_host(0)
        .build()
    {
        Ok(client) => client
            .get("http://localhost:11434/api/tags")
            .send()
            .await
            .map(|r| r.status().is_success())
            .unwrap_or(false),
        Err(_) => false,
    };

    let status = if ollama_up { "online" } else { "degraded" };

    Ok(HealthTelemetry {
        status: status.to_string(),
        ollama_up,
        vanguard_enabled: vanguard.is_enabled(),
        // Any live hive subprocess (generate-dag or run-session) = pipeline active
        pack_task_active: hive_processes
            .processes
            .lock()
            .map(|m| !m.is_empty())
            .unwrap_or(false),
        api_keys_active: vec![],
        // Count rows in the wisdom knowledge table; -1 on error (db locked, table missing)
        vector_wisdom_nodes: db
            .conn
            .lock()
            .ok()
            .and_then(|conn| {
                conn.query_row("SELECT COUNT(*) FROM wisdom", [], |r| r.get::<_, i32>(0))
                    .ok()
            })
            .unwrap_or(-1),
    })
}
