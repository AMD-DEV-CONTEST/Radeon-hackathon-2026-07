use crate::db::DbState;
use serde::Serialize;
use tauri::State;

#[derive(Serialize)]
pub struct ThreadRecord {
    pub id: String,
    pub title: String,
    pub updated: String,
}

#[derive(Serialize)]
pub struct ThreadsResponse {
    pub threads: Vec<ThreadRecord>,
}

#[tauri::command]
pub fn get_threads(state: State<'_, DbState>) -> Result<ThreadsResponse, String> {
    let conn = state
        .conn
        .lock()
        .map_err(|_| "Failed to lock database".to_string())?;

    let mut stmt = conn
        .prepare("SELECT thread_id, title, last_updated FROM threads ORDER BY last_updated DESC")
        .map_err(|e| e.to_string())?;

    let threads_iter = stmt
        .query_map([], |row| {
            Ok(ThreadRecord {
                id: row.get(0)?,
                title: row
                    .get::<_, Option<String>>(1)?
                    .unwrap_or_else(|| "Untitled Ideation".to_string()),
                updated: row
                    .get::<_, Option<String>>(2)?
                    .unwrap_or_else(|| "".to_string()),
            })
        })
        .map_err(|e| e.to_string())?;

    let mut threads = Vec::new();
    for thread in threads_iter {
        threads.push(thread.map_err(|e| e.to_string())?);
    }

    Ok(ThreadsResponse { threads })
}
