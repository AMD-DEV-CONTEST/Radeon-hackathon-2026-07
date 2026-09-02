use crate::db::DbState;
use bytemuck;
use fastembed::{
    EmbeddingModel, InitOptions, InitOptionsUserDefined, Pooling, TextEmbedding, TokenizerFiles,
    UserDefinedEmbeddingModel,
};
use rusqlite::params;
use serde::Serialize;
use std::{
    env, fs,
    path::{Path, PathBuf},
    sync::Mutex,
};
use tauri::State;

pub struct VectorState {
    pub model: Mutex<Option<TextEmbedding>>,
    pub init_error: Option<String>,
}

pub fn initialize_vector_engine() -> Result<TextEmbedding, String> {
    if let Ok(model_dir) = env::var("DETERMINEX_FASTEMBED_MODEL_DIR") {
        return initialize_vector_engine_from_local_dir(Path::new(&model_dir));
    }

    // Load explicitly the AllMiniLML6V2 model which outputs 384 dimensions.
    let model = TextEmbedding::try_new(InitOptions::new(EmbeddingModel::AllMiniLML6V2))
        .map_err(|e| format!("Failed to initialize fastembed model: {}", e))?;
    Ok(model)
}

pub fn initialize_vector_engine_guarded() -> Result<TextEmbedding, String> {
    match std::panic::catch_unwind(initialize_vector_engine) {
        Ok(result) => result,
        Err(payload) => Err(format!(
            "vector engine initialization panicked: {}",
            panic_payload_to_string(payload)
        )),
    }
}

fn initialize_vector_engine_from_local_dir(model_dir: &Path) -> Result<TextEmbedding, String> {
    let resolved = resolve_fastembed_model_dir(model_dir)?;
    let tokenizer_files = TokenizerFiles {
        tokenizer_file: read_fastembed_asset(&resolved, "tokenizer.json")?,
        config_file: read_fastembed_asset(&resolved, "config.json")?,
        special_tokens_map_file: read_fastembed_asset(&resolved, "special_tokens_map.json")?,
        tokenizer_config_file: read_fastembed_asset(&resolved, "tokenizer_config.json")?,
    };
    let user_defined_model = UserDefinedEmbeddingModel::new(
        read_fastembed_asset(&resolved, "model.onnx")?,
        tokenizer_files,
    )
    .with_pooling(Pooling::Mean);

    TextEmbedding::try_new_from_user_defined(user_defined_model, InitOptionsUserDefined::default())
        .map_err(|e| {
            format!(
                "Failed to initialize local fastembed model from {}: {}",
                resolved.display(),
                e
            )
        })
}

fn resolve_fastembed_model_dir(model_dir: &Path) -> Result<PathBuf, String> {
    if model_dir.join("model.onnx").is_file() {
        return Ok(model_dir.to_path_buf());
    }
    let onnx_child = model_dir.join("onnx");
    if onnx_child.join("model.onnx").is_file() {
        return Ok(onnx_child);
    }
    Err(format!(
        "DETERMINEX_FASTEMBED_MODEL_DIR does not contain model.onnx: {}",
        model_dir.display()
    ))
}

fn read_fastembed_asset(model_dir: &Path, name: &str) -> Result<Vec<u8>, String> {
    fs::read(model_dir.join(name)).map_err(|e| {
        format!(
            "Failed to read local fastembed asset {} from {}: {}",
            name,
            model_dir.display(),
            e
        )
    })
}

#[derive(Serialize)]
pub struct VectorIngestResponse {
    pub status: String,
    pub rowid: i64,
    pub dimensions: usize,
}

#[tauri::command]
pub fn generate_and_store_embedding(
    text: String,
    metadata: String,
    db_state: State<'_, DbState>,
    vec_state: State<'_, VectorState>,
) -> Result<VectorIngestResponse, String> {
    // FIX #3 + #4: Acquire the model lock, generate the embedding, then EXPLICITLY DROP the
    // guard before acquiring the DB lock. This prevents holding two mutexes simultaneously,
    // which is the necessary precondition for deadlock under concurrent execution.
    let embedding_bytes: Vec<u8> = {
        let mut model_lock = vec_state
            .model
            .lock()
            .map_err(|e| format!("VectorState mutex poisoned: {}", e))?; // FIX #6: log poison

        let model = model_lock
            .as_mut()
            .ok_or_else(|| vector_engine_unavailable_error(vec_state.init_error.as_deref()))?;

        let embeddings = model
            .embed(vec![text.clone()], None)
            .map_err(|e| format!("Embedding failure: {}", e))?;

        if embeddings.is_empty() {
            return Err("No embedding generated".to_string());
        }

        let embedding_vector: &[f32] = &embeddings[0];
        let dimensions = embedding_vector.len();

        if dimensions != 384 {
            return Err(format!(
                "Incorrect embedding dimension: {} (expected 384)",
                dimensions
            ));
        }

        // FIX #3: Replace unsafe from_raw_parts aliasing cast with bytemuck::cast_slice.
        // bytemuck enforces at compile time that f32 is Pod (Plain Old Data), making this
        // cast sound under Rust's aliasing rules — no unsafe block required.
        bytemuck::cast_slice::<f32, u8>(embedding_vector).to_vec()

        // ← model_lock MutexGuard is DROPPED here as the block exits.
        // The Mutex is fully released before any DB lock is acquired below.
    };

    let dimensions = embedding_bytes.len() / std::mem::size_of::<f32>();

    // FIX #4: DB lock acquired only AFTER model lock has been released above.
    // FIX #6: Log poison error instead of discarding it with |_|.
    let mut conn = db_state
        .conn
        .lock()
        .map_err(|e| format!("DbState mutex poisoned: {}", e))?;

    let tx = conn.transaction().map_err(|e| e.to_string())?;

    // Insert relational plain-text record
    tx.execute(
        "INSERT INTO wisdom (content, metadata) VALUES (?1, ?2)",
        params![text, metadata],
    )
    .map_err(|e| e.to_string())?;

    let rowid = tx.last_insert_rowid();

    // Insert binary vector blob, bound to the same rowid as the relational record
    tx.execute(
        "INSERT INTO vss_wisdom (rowid, embedding_vector) VALUES (?1, ?2)",
        params![rowid, embedding_bytes],
    )
    .map_err(|e| e.to_string())?;

    tx.commit().map_err(|e| e.to_string())?;

    Ok(VectorIngestResponse {
        status: "success".to_string(),
        rowid,
        dimensions,
    })
}

// ─────────────────────────────────────────────────────────────────────────────
// PER-PERSONA KNOWLEDGE QUERY + STORE
// ─────────────────────────────────────────────────────────────────────────────

#[derive(Serialize)]
pub struct KnowledgeResult {
    pub content: String,
    pub metadata: String,
    pub distance: f32,
}

/// Resolves a collection name to its (relational_table, vss_table) pair.
/// Returns an error for unknown collection names.
pub fn resolve_tables(collection: &str) -> Result<(&'static str, &'static str), String> {
    match collection {
        "rust"         => Ok(("knowledge_rust",         "vss_code_rust")),
        "web"          => Ok(("knowledge_web",          "vss_code_web")),
        "security"     => Ok(("knowledge_security",     "vss_security")),
        "architecture" => Ok(("knowledge_architecture", "vss_architecture")),
        "companion"    => Ok(("knowledge_companion",    "vss_companion")),
        "general"      => Ok(("wisdom",                 "vss_wisdom")),
        _ => Err(format!("Unknown collection: '{}'. Valid: rust, web, security, architecture, companion, general", collection)),
    }
}

/// Query the knowledge base for the top-k most similar entries in a collection.
/// Returns results ordered by cosine distance (lowest = most similar).
#[tauri::command]
pub fn query_knowledge(
    query: String,
    collection: String,
    limit: usize,
    db_state: State<'_, DbState>,
    vec_state: State<'_, VectorState>,
) -> Result<Vec<KnowledgeResult>, String> {
    let (rel_table, vss_table) = resolve_tables(&collection)?;

    // Generate embedding for the query text
    let query_bytes: Vec<u8> = {
        let mut model_lock = vec_state
            .model
            .lock()
            .map_err(|e| format!("VectorState mutex poisoned: {}", e))?;

        let model = model_lock
            .as_mut()
            .ok_or_else(|| vector_engine_unavailable_error(vec_state.init_error.as_deref()))?;

        let embeddings = model
            .embed(vec![query.clone()], None)
            .map_err(|e| format!("Query embedding failure: {}", e))?;

        if embeddings.is_empty() {
            return Err("No embedding generated for query".to_string());
        }

        let vec: &[f32] = &embeddings[0];
        if vec.len() != 384 {
            return Err(format!(
                "Query embedding dimension mismatch: {} (expected 384)",
                vec.len()
            ));
        }

        bytemuck::cast_slice::<f32, u8>(vec).to_vec()
    };

    let conn = db_state
        .conn
        .lock()
        .map_err(|e| format!("DbState mutex poisoned: {}", e))?;

    // vec0 query: SELECT rowid, distance FROM vss_table WHERE embedding_vector MATCH ?1 ORDER BY distance LIMIT ?2
    // Then join against the relational table for content + metadata.
    let sql = format!(
        "SELECT r.content, COALESCE(r.metadata, '') as metadata, v.distance
         FROM {vss} v
         JOIN {rel} r ON r.id = v.rowid
         WHERE v.embedding_vector MATCH ?1
         ORDER BY v.distance
         LIMIT ?2",
        vss = vss_table,
        rel = rel_table,
    );

    let mut stmt = conn
        .prepare(&sql)
        .map_err(|e| format!("Query prepare error: {}", e))?;

    let limit_i64 = limit as i64;
    let results: Vec<KnowledgeResult> = stmt
        .query_map(params![query_bytes, limit_i64], |row| {
            Ok(KnowledgeResult {
                content: row.get(0)?,
                metadata: row.get(1)?,
                distance: row.get(2)?,
            })
        })
        .map_err(|e| format!("Query execution error: {}", e))?
        .filter_map(|r| r.ok())
        .collect();

    Ok(results)
}

/// Store a knowledge entry into a specific per-persona collection.
/// Embeds the text and inserts into both the relational and vss tables.
#[tauri::command]
pub fn store_to_collection(
    text: String,
    metadata: String,
    collection: String,
    db_state: State<'_, DbState>,
    vec_state: State<'_, VectorState>,
) -> Result<VectorIngestResponse, String> {
    let (rel_table, vss_table) = resolve_tables(&collection)?;

    // Generate embedding
    let embedding_bytes: Vec<u8> = {
        let mut model_lock = vec_state
            .model
            .lock()
            .map_err(|e| format!("VectorState mutex poisoned: {}", e))?;

        let model = model_lock
            .as_mut()
            .ok_or_else(|| vector_engine_unavailable_error(vec_state.init_error.as_deref()))?;

        let embeddings = model
            .embed(vec![text.clone()], None)
            .map_err(|e| format!("Embedding failure: {}", e))?;

        if embeddings.is_empty() {
            return Err("No embedding generated".to_string());
        }

        let vec: &[f32] = &embeddings[0];
        if vec.len() != 384 {
            return Err(format!(
                "Embedding dimension mismatch: {} (expected 384)",
                vec.len()
            ));
        }

        bytemuck::cast_slice::<f32, u8>(vec).to_vec()
    };

    let dimensions = embedding_bytes.len() / std::mem::size_of::<f32>();

    let mut conn = db_state
        .conn
        .lock()
        .map_err(|e| format!("DbState mutex poisoned: {}", e))?;

    let tx = conn.transaction().map_err(|e| e.to_string())?;

    let insert_rel = format!(
        "INSERT INTO {} (content, metadata) VALUES (?1, ?2)",
        rel_table
    );
    tx.execute(&insert_rel, params![text, metadata])
        .map_err(|e| e.to_string())?;

    let rowid = tx.last_insert_rowid();

    let insert_vss = format!(
        "INSERT INTO {} (rowid, embedding_vector) VALUES (?1, ?2)",
        vss_table
    );
    tx.execute(&insert_vss, params![rowid, embedding_bytes])
        .map_err(|e| e.to_string())?;

    tx.commit().map_err(|e| e.to_string())?;

    Ok(VectorIngestResponse {
        status: "success".to_string(),
        rowid,
        dimensions,
    })
}

fn vector_engine_unavailable_error(init_error: Option<&str>) -> String {
    match init_error {
        Some(error) => format!("Vector engine unavailable: {}", error),
        None => "Vector engine unavailable: model was not initialized".to_string(),
    }
}

fn panic_payload_to_string(payload: Box<dyn std::any::Any + Send>) -> String {
    if let Some(message) = payload.downcast_ref::<&str>() {
        return (*message).to_string();
    }
    if let Some(message) = payload.downcast_ref::<String>() {
        return message.clone();
    }
    "unknown panic payload".to_string()
}
