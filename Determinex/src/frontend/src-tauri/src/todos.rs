use crate::db::DbState;
use serde::Serialize;
use tauri::State;

#[derive(Serialize)]
pub struct TodoItem {
    pub id: i64,
    pub text: String,
    pub done: bool,
}

#[derive(Serialize)]
pub struct TodosResponse {
    pub todos: Vec<TodoItem>,
}

#[derive(Serialize)]
pub struct SuccessResponse {
    pub success: bool,
}

#[tauri::command]
pub fn fetch_todos(thread_id: String, state: State<'_, DbState>) -> Result<TodosResponse, String> {
    let conn = state
        .conn
        .lock()
        .map_err(|e| format!("DbState mutex poisoned: {}", e))?;

    let mut stmt = conn
        .prepare("SELECT id, text, done FROM ideation_todos WHERE thread_id = ? ORDER BY id ASC")
        .map_err(|e| e.to_string())?;

    let iter = stmt
        .query_map([thread_id], |row| {
            Ok(TodoItem {
                id: row.get(0)?,
                text: row.get(1)?,
                done: row.get(2)?,
            })
        })
        .map_err(|e| e.to_string())?;

    let mut todos = Vec::new();
    for todo in iter {
        todos.push(todo.map_err(|e| e.to_string())?);
    }

    Ok(TodosResponse { todos })
}

#[tauri::command]
pub fn create_todo(
    thread_id: String,
    text: String,
    state: State<'_, DbState>,
) -> Result<TodoItem, String> {
    let conn = state
        .conn
        .lock()
        .map_err(|e| format!("DbState mutex poisoned: {}", e))?;

    conn.execute(
        "INSERT INTO ideation_todos (thread_id, text, done) VALUES (?1, ?2, 0)",
        (&thread_id, &text),
    )
    .map_err(|e| e.to_string())?;

    let id = conn.last_insert_rowid();

    Ok(TodoItem {
        id,
        text,
        done: false,
    })
}

#[tauri::command]
pub fn toggle_todo(id: i64, done: bool, state: State<'_, DbState>) -> Result<TodoItem, String> {
    let conn = state
        .conn
        .lock()
        .map_err(|e| format!("DbState mutex poisoned: {}", e))?;

    conn.execute(
        "UPDATE ideation_todos SET done = ?1 WHERE id = ?2",
        (done, id),
    )
    .map_err(|e| e.to_string())?;

    // fetch the text to return the full item because frontend expects it, or at least it doesn't hurt
    let text: String = conn
        .query_row(
            "SELECT text FROM ideation_todos WHERE id = ?1",
            [id],
            |row| row.get(0),
        )
        .unwrap_or_default();

    Ok(TodoItem { id, text, done })
}

#[tauri::command]
pub fn delete_todo(id: i64, state: State<'_, DbState>) -> Result<SuccessResponse, String> {
    let conn = state
        .conn
        .lock()
        .map_err(|e| format!("DbState mutex poisoned: {}", e))?;

    conn.execute("DELETE FROM ideation_todos WHERE id = ?1", [id])
        .map_err(|e| e.to_string())?;

    Ok(SuccessResponse { success: true })
}
