/// Automatic boot-time ingestion of COMPANION_*.md documents.
///
/// This seeder is intentionally manifest-based. A row-count guard can miss
/// edits to project memory forever, so each companion document is hashed and
/// compared against memory_sources before deciding to skip or reseed.
use bytemuck;
use fastembed::TextEmbedding;
use rusqlite::{params, Connection, OptionalExtension};
use sha2::{Digest, Sha256};
use std::path::{Path, PathBuf};

const CHUNK_CAP: usize = 1200;
const SOURCE_TYPE: &str = "companion_doc";
const AUTHORITY: &str = "project_companion";
const PROOF_STATUS: &str = "context_not_proof";

struct SourceManifest {
    path: PathBuf,
    source_path: String,
    source_sha256: String,
}

/// Seed companion documents when the manifest is missing or stale.
pub fn seed_if_needed(docs_dir: &Path, db_path: &Path, model: &mut TextEmbedding) {
    match run_seeding(docs_dir, db_path, model) {
        Ok(0) => eprintln!("[CompanionSeeder] Companion manifest current; skipping."),
        Ok(n) => eprintln!("[CompanionSeeder] Seeded {n} companion chunks into vector DB."),
        Err(e) => eprintln!("[CompanionSeeder] Seeding failed: {e}"),
    }
}

fn run_seeding(
    docs_dir: &Path,
    db_path: &Path,
    model: &mut TextEmbedding,
) -> Result<usize, String> {
    let conn = Connection::open(db_path).map_err(|e| format!("Cannot open DB for seeding: {e}"))?;

    let manifests = collect_companion_manifests(docs_dir)?;
    if manifests.is_empty() {
        return Err(format!("No COMPANION_*.md files found in {docs_dir:?}"));
    }

    if companion_manifest_matches(&conn, &manifests)? {
        return Ok(0);
    }

    clear_companion_memory(&conn)?;

    let mut total_inserted = 0usize;

    for manifest in &manifests {
        let text = std::fs::read_to_string(&manifest.path)
            .map_err(|e| format!("Cannot read {:?}: {e}", manifest.path))?;
        let (front, body) = strip_frontmatter(&text);
        let skill_name = front
            .iter()
            .find(|(k, _)| k == "name")
            .map(|(_, v)| v.as_str())
            .unwrap_or_else(|| {
                manifest
                    .path
                    .file_stem()
                    .and_then(|s| s.to_str())
                    .unwrap_or("unknown")
            })
            .to_string();

        let description = front
            .iter()
            .find(|(k, _)| k == "description")
            .map(|(_, v)| v.clone())
            .unwrap_or_default();

        let file_label = format!("companion | {skill_name}");
        let mut chunks: Vec<(String, String)> = Vec::new();

        if !description.is_empty() {
            let trigger = format!("Skill: {skill_name}\nRouting trigger: {description}");
            chunks.push((trigger, format!("{file_label} | routing-trigger")));
        }

        chunks.extend(chunk_by_h2(&body, &file_label));

        let source_id = record_source(&conn, manifest, chunks.len())?;
        for (chunk_index, (chunk_text, metadata)) in chunks.iter().enumerate() {
            let rowid = embed_and_insert(&conn, model, chunk_text, metadata)
                .map_err(|e| format!("Insert failed for {skill_name}: {e}"))?;
            record_chunk(&conn, source_id, chunk_index, chunk_text, metadata, rowid)?;
            total_inserted += 1;
        }

        eprintln!(
            "[CompanionSeeder] Ingested {file_label} ({} chunks)",
            chunks.len()
        );
    }

    Ok(total_inserted)
}

fn collect_companion_manifests(docs_dir: &Path) -> Result<Vec<SourceManifest>, String> {
    let mut paths: Vec<PathBuf> = std::fs::read_dir(docs_dir)
        .map_err(|e| format!("Cannot read docs dir ({docs_dir:?}): {e}"))?
        .filter_map(|entry| {
            let entry = entry.ok()?;
            let name = entry.file_name();
            let name = name.to_string_lossy();
            if name.starts_with("COMPANION_") && name.ends_with(".md") {
                Some(entry.path())
            } else {
                None
            }
        })
        .collect();
    paths.sort();

    paths
        .into_iter()
        .map(|path| {
            let text =
                std::fs::read_to_string(&path).map_err(|e| format!("Cannot read {path:?}: {e}"))?;
            Ok(SourceManifest {
                source_path: normalize_path(&path),
                source_sha256: sha256_hex(text.as_bytes()),
                path,
            })
        })
        .collect()
}

fn companion_manifest_matches(
    conn: &Connection,
    manifests: &[SourceManifest],
) -> Result<bool, String> {
    let has_rows: Option<i64> = conn
        .query_row("SELECT 1 FROM knowledge_companion LIMIT 1", [], |row| {
            row.get(0)
        })
        .optional()
        .map_err(|e| format!("Cannot inspect companion rows: {e}"))?;
    if has_rows.is_none() {
        return Ok(false);
    }

    let stored_count: i64 = conn
        .query_row(
            "SELECT COUNT(*) FROM memory_sources WHERE source_type = ?1 AND is_stale = 0",
            params![SOURCE_TYPE],
            |row| row.get(0),
        )
        .map_err(|e| format!("Cannot inspect memory_sources: {e}"))?;
    if stored_count != manifests.len() as i64 {
        return Ok(false);
    }

    for manifest in manifests {
        let stored_hash: Option<String> = conn
            .query_row(
                "SELECT source_sha256 FROM memory_sources
                 WHERE source_type = ?1 AND source_path = ?2 AND is_stale = 0",
                params![SOURCE_TYPE, manifest.source_path],
                |row| row.get(0),
            )
            .optional()
            .map_err(|e| {
                format!(
                    "Cannot read source_sha256 for {}: {e}",
                    manifest.source_path
                )
            })?;
        if stored_hash.as_deref() != Some(manifest.source_sha256.as_str()) {
            return Ok(false);
        }
    }

    Ok(true)
}

fn clear_companion_memory(conn: &Connection) -> Result<(), String> {
    conn.execute("DELETE FROM vss_companion", [])
        .map_err(|e| format!("Cannot clear vss_companion: {e}"))?;
    conn.execute("DELETE FROM knowledge_companion", [])
        .map_err(|e| format!("Cannot clear knowledge_companion: {e}"))?;
    conn.execute(
        "DELETE FROM memory_chunks
         WHERE source_id IN (
             SELECT source_id FROM memory_sources WHERE source_type = ?1
         )",
        params![SOURCE_TYPE],
    )
    .map_err(|e| format!("Cannot clear memory_chunks: {e}"))?;
    conn.execute(
        "DELETE FROM memory_sources WHERE source_type = ?1",
        params![SOURCE_TYPE],
    )
    .map_err(|e| format!("Cannot clear memory_sources: {e}"))?;
    Ok(())
}

fn record_source(
    conn: &Connection,
    manifest: &SourceManifest,
    chunk_count: usize,
) -> Result<i64, String> {
    conn.execute(
        "INSERT INTO memory_sources
         (source_path, source_sha256, source_type, authority, proof_status, chunk_count, is_stale)
         VALUES (?1, ?2, ?3, ?4, ?5, ?6, 0)",
        params![
            manifest.source_path,
            manifest.source_sha256,
            SOURCE_TYPE,
            AUTHORITY,
            PROOF_STATUS,
            chunk_count as i64
        ],
    )
    .map_err(|e| format!("Cannot record memory source {}: {e}", manifest.source_path))?;
    Ok(conn.last_insert_rowid())
}

fn record_chunk(
    conn: &Connection,
    source_id: i64,
    chunk_index: usize,
    text: &str,
    metadata: &str,
    knowledge_rowid: i64,
) -> Result<(), String> {
    conn.execute(
        "INSERT INTO memory_chunks
         (source_id, collection, chunk_index, chunk_sha256, metadata, knowledge_rowid)
         VALUES (?1, 'companion', ?2, ?3, ?4, ?5)",
        params![
            source_id,
            chunk_index as i64,
            sha256_hex(text.as_bytes()),
            metadata,
            knowledge_rowid
        ],
    )
    .map_err(|e| format!("Cannot record memory chunk {chunk_index}: {e}"))?;
    Ok(())
}

fn normalize_path(path: &Path) -> String {
    path.to_string_lossy().replace('\\', "/")
}

fn sha256_hex(bytes: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(bytes);
    let digest = hasher.finalize();
    digest.iter().map(|b| format!("{b:02x}")).collect()
}

fn strip_frontmatter(text: &str) -> (Vec<(String, String)>, String) {
    if !text.starts_with("---\n") {
        return (vec![], text.to_string());
    }

    let rest = &text[4..];
    let end_pos = match rest.find("\n---\n") {
        Some(p) => p,
        None => return (vec![], text.to_string()),
    };

    let front_block = &rest[..end_pos];
    let body = rest[end_pos + 5..].to_string();

    let mut pairs: Vec<(String, String)> = Vec::new();
    let mut current_key: Option<String> = None;
    let mut current_lines: Vec<String> = Vec::new();

    for line in front_block.lines() {
        if let Some(colon_pos) = line.find(':') {
            let key_part = &line[..colon_pos];
            let val_part = line[colon_pos + 1..].trim();

            if !line.starts_with(' ') && !line.starts_with('\t') {
                if let Some(k) = current_key.take() {
                    pairs.push((k, current_lines.join(" ").trim().to_string()));
                    current_lines.clear();
                }

                let key = key_part.trim().to_string();
                if val_part.is_empty() || val_part == "|" {
                    current_key = Some(key);
                } else {
                    pairs.push((key, val_part.to_string()));
                }
                continue;
            }
        }

        if current_key.is_some() {
            current_lines.push(line.trim().to_string());
        }
    }

    if let Some(k) = current_key {
        pairs.push((k, current_lines.join(" ").trim().to_string()));
    }

    (pairs, body)
}

fn chunk_by_h2(text: &str, file_label: &str) -> Vec<(String, String)> {
    let mut sections: Vec<(String, String)> = Vec::new();
    let parts: Vec<&str> = text.split("\n## ").collect();

    for (i, part) in parts.iter().enumerate() {
        let part = if i == 0 {
            part.trim().to_string()
        } else {
            format!("## {}", part.trim())
        };

        if part.is_empty() {
            continue;
        }

        let header = part.lines().next().unwrap_or(file_label).trim().to_string();
        let meta = format!("{file_label} | {header}");

        if part.len() <= CHUNK_CAP {
            sections.push((part, meta));
        } else {
            let paragraphs: Vec<&str> = part.split("\n\n").collect();
            let mut current = String::new();

            for para in paragraphs {
                if !current.is_empty() && current.len() + para.len() + 2 > CHUNK_CAP {
                    sections.push((current.trim().to_string(), meta.clone()));
                    current = para.to_string();
                } else if current.is_empty() {
                    current = para.to_string();
                } else {
                    current.push_str("\n\n");
                    current.push_str(para);
                }
            }
            if !current.trim().is_empty() {
                sections.push((current.trim().to_string(), meta));
            }
        }
    }

    sections
}

fn embed_and_insert(
    conn: &Connection,
    model: &mut TextEmbedding,
    text: &str,
    metadata: &str,
) -> Result<i64, String> {
    let embeddings = model
        .embed(vec![text.to_string()], None)
        .map_err(|e| format!("Embedding error: {e}"))?;

    let vec = embeddings
        .first()
        .ok_or_else(|| "No embedding returned".to_string())?;

    if vec.len() != 384 {
        return Err(format!(
            "Unexpected embedding dim: {} (expected 384)",
            vec.len()
        ));
    }

    let embedding_bytes: Vec<u8> = bytemuck::cast_slice::<f32, u8>(vec.as_slice()).to_vec();

    conn.execute(
        "INSERT INTO knowledge_companion (content, metadata) VALUES (?1, ?2)",
        params![text, metadata],
    )
    .map_err(|e| format!("Relational insert error: {e}"))?;

    let rowid = conn.last_insert_rowid();

    conn.execute(
        "INSERT INTO vss_companion (rowid, embedding_vector) VALUES (?1, ?2)",
        params![rowid, embedding_bytes],
    )
    .map_err(|e| format!("VSS insert error: {e}"))?;

    Ok(rowid)
}
