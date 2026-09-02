// Real persistence for LocalModelSettingsPanel.tsx. Config storage only --
// per LOCAL_MODEL_SETTINGS_PANEL_LOCK_001, saving this config must never
// trigger a live model call.
use crate::db::DbState;
use serde::{Deserialize, Serialize};
use tauri::State;

#[derive(Debug, Serialize, Deserialize, Default)]
pub struct LocalModelConfig {
    pub provider: String,
    pub model_id: String,
    pub digest: String,
    pub capabilities: String,
    pub task_classes: String,
    pub dry_run_default: bool,
}

#[derive(Serialize)]
pub struct SuccessResponse {
    pub status: String,
}

#[tauri::command]
pub fn save_local_model_config(
    config: LocalModelConfig,
    state: State<'_, DbState>,
) -> Result<SuccessResponse, String> {
    let conn = state
        .conn
        .lock()
        .map_err(|e| format!("DbState mutex poisoned: {}", e))?;
    let json = serde_json::to_string(&config).map_err(|e| e.to_string())?;
    conn.execute(
        "INSERT INTO local_model_settings (id, config_json) VALUES (1, ?1)
         ON CONFLICT(id) DO UPDATE SET config_json=excluded.config_json, updated_at=CURRENT_TIMESTAMP",
        [&json],
    )
    .map_err(|e| e.to_string())?;
    Ok(SuccessResponse {
        status: "success".to_string(),
    })
}

#[tauri::command]
pub fn get_local_model_config(state: State<'_, DbState>) -> Result<Option<LocalModelConfig>, String> {
    let conn = state
        .conn
        .lock()
        .map_err(|e| format!("DbState mutex poisoned: {}", e))?;
    let result: Result<String, _> = conn.query_row(
        "SELECT config_json FROM local_model_settings WHERE id = 1",
        [],
        |row| row.get(0),
    );
    match result {
        Ok(json) => Ok(serde_json::from_str(&json).ok()),
        Err(rusqlite::Error::QueryReturnedNoRows) => Ok(None),
        Err(e) => Err(e.to_string()),
    }
}
