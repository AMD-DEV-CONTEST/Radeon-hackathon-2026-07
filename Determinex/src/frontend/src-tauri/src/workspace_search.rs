/// workspace_search.rs — Ripgrep-style workspace awareness for the Sentinel.
///
/// Uses the `ignore` crate (the same gitignore-aware directory walker that
/// powers ripgrep) to search the project workspace for code snippets relevant
/// to the user's current prompt. The matching lines are formatted into a
/// compact RAG block and injected into the Sentinel's system prompt, giving
/// it project-wide memory without loading a single byte into GPU VRAM.
///
/// Search strategy:
///   1. Extract the first "meaningful" keyword from the user prompt (≥4 chars).
///   2. Case-insensitive substring match on every line of every text file.
///   3. Cap at MAX_RESULTS matches to avoid context explosion.
///   4. Format as a compact multi-line block: "filename:line | content"
use ignore::WalkBuilder;
use serde::Serialize;
use std::path::Path;

const MAX_RESULTS: usize = 12;
const MAX_LINE_LEN: usize = 120;
const MIN_KEYWORD_LEN: usize = 4;
/// Hard byte budget for the entire injected RAG block.
/// Keeps the Sentinel's 2048-token context from overflowing when search hits many results.
const MAX_PROMPT_BLOCK_BYTES: usize = 600;

/// Result cap for the real "Find in Files" UI command below -- much higher
/// than MAX_RESULTS (which is tuned for RAG prompt injection, not for a
/// human scanning a results list) but still bounded so a search for a
/// one-character or extremely common substring can't return everything.
const MAX_FIND_RESULTS: usize = 500;

/// Words that are too generic to be useful search keywords.
/// These appear in virtually every source file and would fill MAX_RESULTS
/// with semantically useless noise instead of targeted matches.
const STOPWORDS: &[&str] = &[
    // Common English
    "with", "from", "this", "that", "have", "more", "some", "also", "each", "when", "what", "then",
    "them", "into", "over", "only", "just", "here", "been", "will", "used", "where", "there",
    "their", "about", "would", "could", "these", "those", "other", "after",
    // Common code tokens
    "code", "file", "func", "impl", "self", "true", "false", "none", "null", "void", "else", "case",
    "return", "const", "type", "data", "make", "todo", "test",
];

// ─────────────────────────────────────────────────────────────────────────────
// PUBLIC TYPES
// ─────────────────────────────────────────────────────────────────────────────

pub struct SearchMatch {
    pub file: String,
    pub line_number: usize,
    pub line: String,
}

// ─────────────────────────────────────────────────────────────────────────────
// PUBLIC API
// ─────────────────────────────────────────────────────────────────────────────

/// Walk `root` and return up to `max_results` lines that contain the primary
/// keyword extracted from `query`. Returns an empty Vec if the root does not
/// exist or no keyword of sufficient length can be extracted.
pub fn search(root: &Path, query: &str, max_results: usize) -> Vec<SearchMatch> {
    if !root.exists() || query.trim().is_empty() {
        return vec![];
    }

    // Extract the most specific keyword from the query.
    // Strategy: prefer the longest word that is ≥ MIN_KEYWORD_LEN and not a stopword.
    // Fallback to the first non-stopword word ≥ MIN_KEYWORD_LEN.
    // Last resort: the entire trimmed query (handles single-word queries like "reqwest").
    let query_lower = query.to_lowercase();

    let keyword: &str = {
        let words: Vec<&str> = query_lower
            .split_whitespace()
            .filter(|w| w.len() >= MIN_KEYWORD_LEN && !STOPWORDS.contains(w))
            .collect();

        if let Some(best) = words.iter().max_by_key(|w| w.len()) {
            best
        } else {
            // All words were stopwords or too short — fall back to longest word regardless
            query_lower
                .split_whitespace()
                .max_by_key(|w| w.len())
                .unwrap_or(query_lower.trim())
        }
    };

    if keyword.is_empty() {
        return vec![];
    }

    let mut matches = Vec::new();
    let cap = max_results.min(MAX_RESULTS);

    let walker = WalkBuilder::new(root)
        .hidden(true) // skip dot-files
        .git_ignore(true) // respect .gitignore
        .git_global(true)
        .git_exclude(true)
        .max_depth(Some(8))
        .build();

    'outer: for entry in walker.flatten() {
        let path = entry.path();
        if !path.is_file() {
            continue;
        }

        // ── AEGIS SECRETS BLINDFOLD ────────────────────────────────────────────
        // The RAG system MUST NOT read or index secret-bearing files.
        // This check runs before the file is opened — no content is ever loaded.
        // The blocklist is defence-in-depth on top of .gitignore: secrets files
        // are not always gitignored, and an LLM prompt containing a private key
        // or API token is an irreversible confidentiality breach.
        if is_secret_file(path) {
            log::info!(
                "[RAG] Secrets blindfold blocked (not indexed): {}",
                path.display()
            );
            continue;
        }

        let ext = path.extension().and_then(|e| e.to_str()).unwrap_or("");
        if !is_text_ext(ext) {
            continue;
        }

        let Ok(content) = std::fs::read_to_string(path) else {
            continue;
        };

        for (i, line) in content.lines().enumerate() {
            if !line.to_lowercase().contains(keyword) {
                continue;
            }

            let trimmed = line.trim();
            if trimmed.len() < 3 {
                continue; // skip blank/near-empty lines
            }

            let display_line = truncate_for_display(trimmed, MAX_LINE_LEN);

            matches.push(SearchMatch {
                file: path.to_string_lossy().to_string(),
                line_number: i + 1,
                line: display_line,
            });

            if matches.len() >= cap {
                break 'outer;
            }
        }
    }

    matches
}

/// Format search results as a compact block ready for LLM prompt injection.
/// Returns an empty string when there are no results (caller should skip injection).
pub fn format_for_prompt(results: &[SearchMatch], query: &str) -> String {
    if results.is_empty() {
        return String::new();
    }

    let keyword = query
        .split_whitespace()
        .find(|w| w.len() >= MIN_KEYWORD_LEN)
        .unwrap_or(query.trim());

    let mut out = format!(
        "WORKSPACE CONTEXT ({} relevant snippet(s) for '{}'):\n",
        results.len(),
        keyword
    );

    for r in results {
        // Use only the filename, not the full path, to keep the block compact.
        let short = Path::new(&r.file)
            .file_name()
            .map(|n| n.to_string_lossy().to_string())
            .unwrap_or_else(|| r.file.clone());

        let line = format!("  {}:{} | {}\n", short, r.line_number, r.line);

        // Hard byte cap: stop appending once we approach the context budget.
        if out.len() + line.len() > MAX_PROMPT_BLOCK_BYTES {
            out.push_str("  [...truncated to fit context budget]\n");
            break;
        }

        out.push_str(&line);
    }

    out
}

// ─────────────────────────────────────────────────────────────────────────────
// FIND IN FILES — real, literal-substring workspace search for the UI.
//
// This is deliberately separate from `search()` above: that function does RAG
// keyword-extraction (one best keyword from a natural-language prompt, capped
// at MAX_RESULTS=12) for prompt injection. A human using a "Find in Files"
// panel wants the opposite: an exact literal substring match against
// everything they typed, with a much higher result ceiling.
// ─────────────────────────────────────────────────────────────────────────────

#[derive(Serialize, Clone)]
pub struct FileSearchHit {
    pub file: String,
    pub line_number: usize,
    pub line: String,
}

#[derive(Serialize, Clone)]
pub struct FileSearchResponse {
    pub hits: Vec<FileSearchHit>,
    /// True when MAX_FIND_RESULTS was hit before the walk finished — the UI
    /// should tell the user to narrow their query rather than imply completeness.
    pub truncated: bool,
}

/// Tauri command backing the "Find in Files" panel. Walks `root` (gitignore-
/// aware, secrets-blocklisted, same as `search()` above) for literal
/// occurrences of `query`, case-insensitive by default.
#[tauri::command]
pub fn find_in_files(
    root: String,
    query: String,
    case_sensitive: Option<bool>,
) -> Result<FileSearchResponse, String> {
    let root_path = Path::new(&root);
    if !root_path.exists() {
        return Err(format!("Workspace root does not exist: {root}"));
    }

    let query_trimmed = query.trim();
    if query_trimmed.is_empty() {
        return Ok(FileSearchResponse { hits: vec![], truncated: false });
    }

    let case_sensitive = case_sensitive.unwrap_or(false);
    let needle = if case_sensitive {
        query_trimmed.to_string()
    } else {
        query_trimmed.to_lowercase()
    };

    let mut hits = Vec::new();
    let mut truncated = false;

    let walker = WalkBuilder::new(root_path)
        .hidden(true)
        .git_ignore(true)
        .git_global(true)
        .git_exclude(true)
        .max_depth(Some(12))
        .build();

    'outer: for entry in walker.flatten() {
        let path = entry.path();
        if !path.is_file() {
            continue;
        }

        // Same AEGIS secrets blindfold as the RAG search path above.
        if is_secret_file(path) {
            continue;
        }

        let ext = path.extension().and_then(|e| e.to_str()).unwrap_or("");
        if !is_text_ext(ext) {
            continue;
        }

        let Ok(content) = std::fs::read_to_string(path) else {
            continue;
        };

        for (i, line) in content.lines().enumerate() {
            let haystack = if case_sensitive {
                line.to_string()
            } else {
                line.to_lowercase()
            };
            if !haystack.contains(&needle) {
                continue;
            }

            hits.push(FileSearchHit {
                file: path.to_string_lossy().to_string(),
                line_number: i + 1,
                line: truncate_for_display(line.trim(), MAX_LINE_LEN * 2),
            });

            if hits.len() >= MAX_FIND_RESULTS {
                truncated = true;
                break 'outer;
            }
        }
    }

    Ok(FileSearchResponse { hits, truncated })
}

// ─────────────────────────────────────────────────────────────────────────────
// HELPERS
// ─────────────────────────────────────────────────────────────────────────────

/// Truncates `s` to at most `max_len` bytes, snapping back to the nearest
/// char boundary so multi-byte UTF-8 sequences are never split (which would
/// panic on the raw `&s[..max_len]` slice this replaces).
fn truncate_for_display(s: &str, max_len: usize) -> String {
    if s.len() <= max_len {
        return s.to_string();
    }
    let mut end = max_len;
    while end > 0 && !s.is_char_boundary(end) {
        end -= 1;
    }
    format!("{}…", &s[..end])
}

fn is_text_ext(ext: &str) -> bool {
    matches!(
        ext,
        "rs" | "ts"
            | "tsx"
            | "js"
            | "jsx"
            | "py"
            | "go"
            | "java"
            | "c"
            | "cpp"
            | "h"
            | "hpp"
            | "md"
            | "txt"
            | "toml"
            | "yaml"
            | "yml"
            | "json"
            | "html"
            | "css"
            | "scss"
    )
}

/// Returns `true` when a path matches the AEGIS secrets blocklist.
///
/// Blocklist rules (checked in order):
///   1. Extension is `.pem`, `.key`, `.pfx`, `.p12` (crypto material)
///   2. Filename is exactly `id_rsa`, `id_ed25519`, `id_ecdsa` (SSH private keys)
///   3. Filename is `secrets.json` or `credentials.json`
///   4. Filename starts with `.env` (covers `.env`, `.env.local`, `.env.production`, etc.)
///
/// The check is case-insensitive on the filename component to catch `Secrets.JSON` etc.
fn is_secret_file(path: &std::path::Path) -> bool {
    let file_name = path
        .file_name()
        .and_then(|n| n.to_str())
        .unwrap_or("")
        .to_lowercase();

    // ── Extension blocklist ────────────────────────────────────────────────────
    if let Some(ext) = path.extension().and_then(|e| e.to_str()) {
        match ext.to_lowercase().as_str() {
            "pem" | "key" | "pfx" | "p12" | "crt" | "cer" | "der" => return true,
            _ => {}
        }
    }

    // ── Exact filename blocklist ───────────────────────────────────────────────
    if matches!(
        file_name.as_str(),
        "id_rsa"
            | "id_ed25519"
            | "id_ecdsa"
            | "id_dsa"
            | "secrets.json"
            | "credentials.json"
            | "service_account.json"
            | ".netrc"
            | "vault.key" // Vanguard Vault key — must never be RAG'd
    ) {
        return true;
    }

    // ── Prefix blocklist (.env*) ───────────────────────────────────────────────
    if file_name.starts_with(".env") {
        return true;
    }

    false
}
