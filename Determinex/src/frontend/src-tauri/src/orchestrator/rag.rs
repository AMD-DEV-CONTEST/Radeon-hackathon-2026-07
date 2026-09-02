/// orchestrator/rag.rs — Knowledge Base RAG + telemetry emission helpers.
use serde::Serialize;

// ─────────────────────────────────────────────────────────────────────────────
// TELEMETRY
// ─────────────────────────────────────────────────────────────────────────────

/// Real-time pipeline telemetry event emitted to the frontend over the
/// `"moa-telemetry"` Tauri event channel.
#[derive(Debug, Clone, Serialize)]
pub struct TelemetryEvent {
    pub agent: String,
    pub status: String,
}

/// Fire-and-forget telemetry emit. Failures are silently discarded.
pub fn emit_telemetry(app_handle: &tauri::AppHandle, agent: &str, status: &str) {
    use tauri::Emitter;
    let _ = app_handle.emit(
        "moa-telemetry",
        TelemetryEvent {
            agent: agent.to_string(),
            status: status.to_string(),
        },
    );
}

// ─────────────────────────────────────────────────────────────────────────────
// KNOWLEDGE BASE RAG (zero-VRAM, fastembed CPU path)
// ─────────────────────────────────────────────────────────────────────────────

/// Detect the most relevant knowledge collection from the user's prompt.
/// Returns the primary collection name. Companion Skill docs are always checked
/// separately via `retrieve_companion_context` and merged into the final block.
pub fn detect_collection(prompt: &str) -> &'static str {
    let lower = prompt.to_lowercase();

    // ── Companion Skill routing (checked first — highest specificity) ─────────
    // These match the "Load when..." triggers from COMPANION_*.md frontmatter.
    let companion_keywords = [
        // cloak-safety
        "send to claude",
        "send to gpt",
        "send to gemini",
        "cloud api",
        "proprietary code",
        "identifier obfuscation",
        "cloak",
        "uncloak",
        "data leakage",
        "privacy sovereign",
        "obfuscat",
        // moa-moe
        "mixture of agents",
        "mixture of experts",
        "moe",
        "moa",
        "autogen",
        "crewai",
        "langgraph",
        "ensemble",
        "rosetta stone",
        "how is determinex different",
        "multi-agent framework",
        // flow-ai / vibe-coding
        "cognitive load",
        "flow state",
        "vibe cod",
        "build loop",
        "feedback loop latency",
        "burnout",
        "tunnel vision",
        "context switching",
        "why did you design",
        // project memory / cross-agent operating rules
        "project memory",
        "agent instruction",
        "agents.md",
        "claude.md",
        "gemini.md",
        "project.md",
        "tool-specific",
        "cross-agent",
        "handoff",
        "shared status",
        "companion memory",
        "project-specific",
    ];
    let companion_score: usize = companion_keywords
        .iter()
        .filter(|k| lower.contains(*k))
        .count();

    let rust_keywords = [
        "rust",
        " fn ",
        "cargo",
        "tokio",
        "async fn",
        "impl ",
        "struct ",
        ".rs",
        "rustc",
        "borrow checker",
        "lifetime",
        "crate",
    ];
    let web_keywords = [
        "typescript",
        "javascript",
        "react",
        "next.js",
        "nextjs",
        "css",
        "html",
        "node",
        "npm",
        "frontend",
        "component",
        ".tsx",
        ".jsx",
        "tailwind",
        "vite",
        "dom",
    ];
    let sec_keywords = [
        "security",
        "auth",
        "injection",
        "vuln",
        "xss",
        "csrf",
        "sanitize",
        "encrypt",
        "hash",
        "password",
        "token",
        "jwt",
        "cors",
        "ssl",
        "tls",
        "firewall",
        "privilege",
    ];

    let rust_score: usize = rust_keywords.iter().filter(|k| lower.contains(*k)).count();
    let web_score: usize = web_keywords.iter().filter(|k| lower.contains(*k)).count();
    let sec_score: usize = sec_keywords.iter().filter(|k| lower.contains(*k)).count();

    // Companion wins if it has any signal, unless a more specific domain also fires.
    // Cloak is a superset of security concerns — prefer companion over generic sec.
    if companion_score > 0 {
        return "companion";
    }

    if sec_score > 0 && sec_score >= rust_score && sec_score >= web_score {
        "security"
    } else if rust_score > web_score {
        "rust"
    } else if web_score > 0 {
        "web"
    } else {
        "general"
    }
}

/// Query the per-persona knowledge base and format results as a prompt block.
/// Runs entirely on CPU (fastembed ONNX) — zero VRAM cost.
pub fn retrieve_knowledge_context(
    query: &str,
    collection: &str,
    limit: usize,
    db_state: &crate::db::DbState,
    vec_state: &crate::vector_engine::VectorState,
    app_handle: Option<&tauri::AppHandle>,
) -> String {
    use rusqlite::params;

    let (rel_table, vss_table) = match crate::vector_engine::resolve_tables(collection) {
        Ok(t) => t,
        Err(e) => {
            eprintln!("[RAG] resolve_tables({collection}) failed: {e}");
            return String::new();
        }
    };

    let query_bytes: Vec<u8> = {
        let mut model_lock = match vec_state.model.lock() {
            Ok(l) => l,
            Err(e) => {
                eprintln!("[RAG] vector model mutex poisoned: {e}");
                return String::new();
            }
        };
        let model = match model_lock.as_mut() {
            Some(model) => model,
            None => {
                let detail = vec_state
                    .init_error
                    .as_deref()
                    .unwrap_or("model was not initialized");
                eprintln!("[RAG] vector engine unavailable: {detail}");
                return String::new();
            }
        };
        let embeddings = match model.embed(vec![query.to_string()], None) {
            Ok(e) => e,
            Err(e) => {
                eprintln!("[RAG] embed failed: {e}");
                return String::new();
            }
        };
        if embeddings.is_empty() || embeddings[0].len() != 384 {
            eprintln!(
                "[RAG] unexpected embedding shape: got {} vecs",
                embeddings.len()
            );
            return String::new();
        }
        bytemuck::cast_slice::<f32, u8>(&embeddings[0]).to_vec()
    };

    let conn = match db_state.conn.lock() {
        Ok(c) => c,
        Err(e) => {
            eprintln!("[RAG] db mutex poisoned: {e}");
            return String::new();
        }
    };

    let table_exists: bool = conn
        .query_row(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?1",
            rusqlite::params![rel_table],
            |row| row.get::<_, i64>(0),
        )
        .unwrap_or(0)
        > 0;
    if !table_exists {
        return String::new();
    }

    let sql = format!(
        "SELECT r.content, r.metadata, v.distance
         FROM {} v
         JOIN {} r ON r.id = v.rowid
         WHERE v.embedding_vector MATCH ?1
         ORDER BY v.distance
         LIMIT ?2",
        vss_table, rel_table,
    );

    let mut stmt = match conn.prepare(&sql) {
        Ok(s) => s,
        Err(e) => {
            eprintln!("[RAG] prepare({collection}) failed: {e}");
            return String::new();
        }
    };

    let limit_i64 = limit as i64;
    let rows: Vec<(String, Option<String>, f32)> =
        match stmt.query_map(params![query_bytes, limit_i64], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, Option<String>>(1)?,
                row.get::<_, f32>(2)?,
            ))
        }) {
            Ok(mapped) => mapped.filter_map(|r| r.ok()).collect(),
            Err(e) => {
                eprintln!("[RAG] query({collection}) failed: {e}");
                return String::new();
            }
        };

    if rows.is_empty() {
        return String::new();
    }

    let mut block = String::from("[KNOWLEDGE BASE]\n");
    for (i, (content, metadata, dist)) in rows.iter().enumerate() {
        block.push_str(&format!(
            "--- KB entry {} (distance: {:.3}) ---\n{}\n\n",
            i + 1,
            dist,
            content
        ));

        if collection == "companion" {
            if let Some(app) = app_handle {
                let meta_label = metadata.as_deref().unwrap_or("unknown_skill");
                emit_telemetry(
                    app,
                    "system",
                    &format!("RoutingPrecision|{}|{:.3}", meta_label, dist),
                );
                emit_telemetry(app, "system", &format!("SkillLoaded|{}", meta_label));
            }
        }
    }
    block
}
