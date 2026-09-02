// The "Passport" -- Ryan: "the claude and codex login for this right now
// sends you online to login... it pulls the session back thats what i want,
// but i want it so we decide where the information goes and what it sees."
//
// Two distinct, deliberately separate things live here:
//
// 1. NATIVE CLI LOGIN STATUS (passport_cli_login_status) -- Claude Code,
//    Codex, and Gemini CLI each already run their own browser-based OAuth
//    login and cache a session on this machine (~/.claude.json,
//    ~/.codex/auth.json, ~/.gemini/oauth_creds.json). This reads ONLY
//    whether each file exists and has the expected auth key present --
//    boolean status, exactly like get_api_key_status's existing pattern.
//    It NEVER reads, returns, or logs the actual token/session content.
//    Relocating or redirecting where these tools store their own
//    credentials is a materially riskier operation (could break a real
//    working login) that isn't attempted here.
//
// 2. CONNECTED SERVICE PROFILES (passport_connect / _list / _disconnect) --
//    a user-pasted personal access token for GitHub/HuggingFace is used
//    ONCE to fetch real profile info (avatar, display name, username) from
//    that provider's API, then both the token and the fetched profile are
//    cached in the same api_keys-backed store save_service_key already
//    uses. This is the "pulls in profile pictures" half.
//
// The "what it sees" half of the ask is handled elsewhere: agent_chat.rs's
// Cloak room already controls what each participant sees of the workspace
// (raw vs. obfuscated mirror) -- this module's job is credential VISIBILITY
// and STORAGE, not data scoping.

// Python is resolved through `ipc_hive::resolve_python_exe()`, never `Command::new("python")`.
//
// That resolver exists for a specific reason: on Windows, PATH `python` is very
// often the Microsoft Store AppExecLink stub, which does not run Python -- it opens
// the Store. It also prefers the repo venv, so the interpreter that has the
// project's dependencies is the one used. Ten call sites across six files bypassed
// it and used bare `python`, which worked only on machines where PATH happened to
// resolve to a real interpreter.

use crate::db::DbState;
use crate::win_process::HideConsoleExt;
use reqwest::Client;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::Duration;
use tauri::State;

const FETCH_TIMEOUT_SECS: u64 = 10;
const USAGE_SCRIPT: &str = "scripts/determinex_usage_ledger.py";
const SCRIPT_TIMEOUT: Duration = Duration::from_secs(15);

fn locate_repo_root() -> Option<PathBuf> {
    let cwd = std::env::current_dir().ok()?;
    let mut cur: Option<&Path> = Some(cwd.as_path());
    while let Some(c) = cur {
        if c.join(USAGE_SCRIPT).is_file() {
            return Some(c.to_path_buf());
        }
        cur = c.parent();
    }
    None
}

/// The two usage commands' shapes. `PassportPanel.tsx` has declared both all
/// along (`UsageSummary`, `CliSubscriptionStatus`) with no Rust counterpart, so
/// the contract lived only in the Python script's head.
///
/// Deserializing the script's output into these instead of forwarding it raw
/// means a change to `determinex_usage.py`'s output shape becomes an error here
/// rather than `undefined` in a panel.
#[derive(Serialize, Deserialize)]
pub struct UsageProviderSummary {
    pub calls: u64,
    pub tokens_in: u64,
    pub tokens_out: u64,
    pub est_usd: f64,
    pub models: Vec<String>,
}

#[derive(Serialize, Deserialize)]
pub struct UsageSummary {
    pub exists: bool,
    pub window_hours: Option<f64>,
    pub providers: std::collections::HashMap<String, UsageProviderSummary>,
    pub total_est_usd: f64,
    pub total_calls: u64,
}

#[derive(Serialize, Deserialize)]
pub struct CliSubscriptionEntry {
    pub available: bool,
    pub reason: String,
}

fn run_usage_script<T: serde::de::DeserializeOwned>(args: &[&str]) -> Result<T, String> {
    let root = locate_repo_root().ok_or_else(|| "could not locate repo root".to_string())?;
    // Bundled-first (see ipc_hive::helper_command): this used to build
    // `python <root>/scripts/<name>.py`, which does not exist in an installed copy.
    let (mut cmd, _bundled) = crate::ipc_hive::helper_command(USAGE_SCRIPT)?;
    for a in args {
        cmd.arg(a);
    }
    cmd.current_dir(&root);
    let output = crate::project_audit::run_with_timeout(cmd, SCRIPT_TIMEOUT)
        .map_err(|e| format!("could not run {USAGE_SCRIPT}: {e}"))?;
    let stdout = String::from_utf8_lossy(&output.stdout);
    crate::python_json::parse_python_json(&stdout, USAGE_SCRIPT).map_err(|e| {
        let stderr = String::from_utf8_lossy(&output.stderr);
        format!("{e} (args={args:?}, stderr={stderr})")
    })
}

#[tauri::command]
pub fn passport_usage_summary(window_hours: Option<f64>) -> Result<UsageSummary, String> {
    match window_hours {
        Some(h) => run_usage_script(&["summary", "--window-hours", &h.to_string()]),
        None => run_usage_script(&["summary", "--all-time"]),
    }
}

#[tauri::command]
pub fn passport_cli_subscription_status(
) -> Result<std::collections::HashMap<String, CliSubscriptionEntry>, String> {
    run_usage_script(&["cli-status"])
}

// ---------------------------------------------------------------------------
// 1. Native CLI login status -- boolean only, never touches token content.
// ---------------------------------------------------------------------------

fn home_dir() -> Option<PathBuf> {
    std::env::var_os("USERPROFILE")
        .or_else(|| std::env::var_os("HOME"))
        .map(PathBuf::from)
}

/// True iff `path` parses as JSON and has `key` present with a non-null,
/// non-empty value. Reads the file only to check this ONE structural fact --
/// the parsed value itself is dropped immediately, never returned.
fn has_nonempty_key(path: &std::path::Path, key: &str) -> bool {
    let Ok(text) = std::fs::read_to_string(path) else { return false };
    let Ok(json) = serde_json::from_str::<serde_json::Value>(&text) else { return false };
    match json.get(key) {
        None | Some(serde_json::Value::Null) => false,
        Some(serde_json::Value::String(s)) => !s.is_empty(),
        Some(serde_json::Value::Object(o)) => !o.is_empty(),
        Some(_) => true,
    }
}

#[tauri::command]
pub fn passport_cli_login_status() -> Result<HashMap<String, bool>, String> {
    let mut status = HashMap::new();
    status.insert("claude-code".to_string(), false);
    status.insert("codex".to_string(), false);
    status.insert("gemini-cli".to_string(), false);

    if let Some(home) = home_dir() {
        status.insert(
            "claude-code".to_string(),
            has_nonempty_key(&home.join(".claude.json"), "oauthAccount"),
        );
        status.insert(
            "codex".to_string(),
            has_nonempty_key(&home.join(".codex").join("auth.json"), "tokens"),
        );
        status.insert(
            "gemini-cli".to_string(),
            has_nonempty_key(&home.join(".gemini").join("oauth_creds.json"), "access_token"),
        );
    }
    Ok(status)
}

// ---------------------------------------------------------------------------
// 2. Connected service profiles (PAT-based, no OAuth app registration
//    needed) -- real profile/avatar fetch from GitHub and HuggingFace.
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PassportProfile {
    pub provider: String,
    pub username: String,
    pub display_name: String,
    pub avatar_url: String,
    pub profile_url: String,
    pub fetched_at: String,
}

fn token_row_key(provider: &str) -> String {
    match provider.to_lowercase().as_str() {
        "github" => "GITHUB_TOKEN".to_string(),
        "huggingface" => "HUGGINGFACE_TOKEN".to_string(),
        other => format!("{}_TOKEN", other.to_uppercase()),
    }
}

fn passport_row_key(provider: &str) -> String {
    format!("__passport_{}", provider.to_lowercase())
}

fn db_set(state: &State<'_, DbState>, key: &str, value: &str) -> Result<(), String> {
    let conn = state.conn.lock().map_err(|e| format!("DbState mutex poisoned: {e}"))?;
    conn.execute(
        "INSERT INTO api_keys (provider, api_key) VALUES (?1, ?2)
         ON CONFLICT(provider) DO UPDATE SET api_key=excluded.api_key, updated_at=CURRENT_TIMESTAMP",
        (key, value),
    )
    .map_err(|e| e.to_string())?;
    Ok(())
}

async fn fetch_github_profile(token: &str) -> Result<PassportProfile, String> {
    let client = Client::builder()
        .timeout(Duration::from_secs(FETCH_TIMEOUT_SECS))
        .build()
        .map_err(|e| format!("failed to build http client: {e}"))?;
    let resp = client
        .get("https://api.github.com/user")
        .header("Authorization", format!("Bearer {token}"))
        .header("User-Agent", "Determinex-IDE")
        .header("Accept", "application/vnd.github+json")
        .send()
        .await
        .map_err(|e| format!("GitHub profile request failed: {e}"))?;
    if !resp.status().is_success() {
        return Err(format!(
            "GitHub API returned {} -- check the token is valid and has at least 'read:user' scope",
            resp.status()
        ));
    }
    let body: serde_json::Value = resp
        .json()
        .await
        .map_err(|e| format!("malformed GitHub profile response: {e}"))?;
    let login = body.get("login").and_then(|v| v.as_str()).unwrap_or("").to_string();
    Ok(PassportProfile {
        provider: "github".to_string(),
        display_name: body
            .get("name")
            .and_then(|v| v.as_str())
            .map(String::from)
            .filter(|s| !s.is_empty())
            .unwrap_or_else(|| login.clone()),
        username: login.clone(),
        avatar_url: body.get("avatar_url").and_then(|v| v.as_str()).unwrap_or("").to_string(),
        profile_url: body.get("html_url").and_then(|v| v.as_str()).unwrap_or("").to_string(),
        fetched_at: chrono::Utc::now().to_rfc3339(),
    })
}

async fn fetch_huggingface_profile(token: &str) -> Result<PassportProfile, String> {
    let client = Client::builder()
        .timeout(Duration::from_secs(FETCH_TIMEOUT_SECS))
        .build()
        .map_err(|e| format!("failed to build http client: {e}"))?;
    let resp = client
        .get("https://huggingface.co/api/whoami-v2")
        .header("Authorization", format!("Bearer {token}"))
        .send()
        .await
        .map_err(|e| format!("HuggingFace profile request failed: {e}"))?;
    if !resp.status().is_success() {
        return Err(format!("HuggingFace API returned {} -- check the token is valid", resp.status()));
    }
    let body: serde_json::Value = resp
        .json()
        .await
        .map_err(|e| format!("malformed HuggingFace profile response: {e}"))?;
    let username = body.get("name").and_then(|v| v.as_str()).unwrap_or("").to_string();
    Ok(PassportProfile {
        provider: "huggingface".to_string(),
        display_name: body
            .get("fullname")
            .and_then(|v| v.as_str())
            .map(String::from)
            .filter(|s| !s.is_empty())
            .unwrap_or_else(|| username.clone()),
        avatar_url: body.get("avatarUrl").and_then(|v| v.as_str()).unwrap_or("").to_string(),
        profile_url: format!("https://huggingface.co/{username}"),
        username,
        fetched_at: chrono::Utc::now().to_rfc3339(),
    })
}

#[tauri::command]
pub async fn passport_connect(
    provider: String,
    token: String,
    state: State<'_, DbState>,
) -> Result<PassportProfile, String> {
    if token.trim().is_empty() {
        return Err("token is empty".to_string());
    }
    let profile = match provider.to_lowercase().as_str() {
        "github" => fetch_github_profile(&token).await,
        "huggingface" => fetch_huggingface_profile(&token).await,
        other => Err(format!(
            "'{other}' needs a registered OAuth app (a client ID/secret you create in that \
             provider's own developer console) -- token-only profile fetch isn't supported by \
             their API the way GitHub/HuggingFace support it."
        )),
    }?;

    db_set(&state, &token_row_key(&provider), &token)?;
    let json = serde_json::to_string(&profile).map_err(|e| e.to_string())?;
    db_set(&state, &passport_row_key(&provider), &json)?;
    Ok(profile)
}

#[tauri::command]
pub fn passport_list(state: State<'_, DbState>) -> Result<Vec<PassportProfile>, String> {
    let conn = state.conn.lock().map_err(|e| format!("DbState mutex poisoned: {e}"))?;
    let mut stmt = conn
        .prepare("SELECT api_key FROM api_keys WHERE provider LIKE '\\_\\_passport\\_%' ESCAPE '\\'")
        .map_err(|e| e.to_string())?;
    let rows = stmt
        .query_map([], |row| row.get::<_, String>(0))
        .map_err(|e| e.to_string())?;
    let mut out = Vec::new();
    for r in rows.flatten() {
        if let Ok(profile) = serde_json::from_str::<PassportProfile>(&r) {
            out.push(profile);
        }
    }
    Ok(out)
}

#[tauri::command]
pub fn passport_disconnect(provider: String, state: State<'_, DbState>) -> Result<(), String> {
    let conn = state.conn.lock().map_err(|e| format!("DbState mutex poisoned: {e}"))?;
    conn.execute("DELETE FROM api_keys WHERE provider = ?1", [token_row_key(&provider)])
        .map_err(|e| e.to_string())?;
    conn.execute("DELETE FROM api_keys WHERE provider = ?1", [passport_row_key(&provider)])
        .map_err(|e| e.to_string())?;
    Ok(())
}

/// The credential-delivery half for agent_chat.rs: connected passport
/// tokens (GitHub/HuggingFace, whatever the user has explicitly linked),
/// returned as an env-var map for injection into ONE agent subprocess's
/// spawn env only -- never into the built prompt or chat transcript.
///
/// claude-code and codex authenticate through their own OAuth session files and
/// need nothing injected (verified live). gemini-cli is the exception: it
/// requires GEMINI_API_KEY (or an explicit Google OAuth/Vertex mode), so the
/// model-provider keys saved in the app's own dialog are injected too.
/// The env var an `api_keys` row should be injected as, or None to never inject it.
///
/// An explicit allowlist, not a transformation: the same table also holds
/// `__passport_*` profile JSON and the Ollama base-URL row, and neither belongs
/// in a child process's environment. Anything unrecognised is skipped.
///
/// Two naming conventions live in this table because two dialogs write to it --
/// `passport_connect` stores env-var names (`GITHUB_TOKEN`) while
/// `save_api_keys` stores bare provider names (`gemini`) -- so both are mapped.
fn spawn_env_var(row: &str) -> Option<&'static str> {
    match row {
        // passport_connect rows (already env-var shaped)
        "GITHUB_TOKEN" => Some("GITHUB_TOKEN"),
        "HUGGINGFACE_TOKEN" => Some("HUGGINGFACE_TOKEN"),
        // save_api_keys rows (bare provider names)
        "gemini" => Some("GEMINI_API_KEY"),
        "openai" => Some("OPENAI_API_KEY"),
        "anthropic" => Some("ANTHROPIC_API_KEY"),
        "openrouter" => Some("OPENROUTER_API_KEY"),
        "deepseek" => Some("DEEPSEEK_API_KEY"),
        "groq" => Some("GROQ_API_KEY"),
        "mistral" => Some("MISTRAL_API_KEY"),
        "kimi" => Some("MOONSHOT_API_KEY"),
        _ => None,
    }
}

pub fn env_credentials(state: &DbState) -> HashMap<String, String> {
    let mut out = HashMap::new();
    let Ok(conn) = state.conn.lock() else { return out };
    // Read every row and filter through the allowlist, rather than naming rows
    // in the SQL. The previous version selected only GITHUB_TOKEN and
    // HUGGINGFACE_TOKEN on the belief -- stated in the doc comment above -- that
    // claude-code/codex/gemini-cli "already read their own session files and need
    // nothing injected". Two thirds right: claude-code and codex do authenticate
    // via their own OAuth sessions (verified live 2026-07-28, both reached the
    // API with nothing injected). gemini-cli does NOT -- it fails with "Please
    // set an Auth method ... GEMINI_API_KEY" unless a key or a Google OAuth mode
    // is configured. So a user who saved their Gemini key in Determinex's own
    // keys dialog got it stored, and then never passed to the gemini-cli
    // Determinex itself spawned.
    let Ok(mut stmt) = conn.prepare("SELECT provider, api_key FROM api_keys") else {
        return out;
    };
    let Ok(rows) = stmt.query_map([], |row| Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?))) else {
        return out;
    };
    for (row_key, v) in rows.flatten() {
        if v.trim().is_empty() {
            continue;
        }
        if let Some(var) = spawn_env_var(&row_key) {
            out.insert(var.to_string(), v);
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::spawn_env_var;

    /// The gap this closes: the app's keys dialog stores a Gemini key as the row
    /// `gemini`, and gemini-cli requires GEMINI_API_KEY. Before this mapping the
    /// key was saved and then never passed to the CLI Determinex itself spawned.
    #[test]
    fn model_provider_rows_map_to_the_env_var_their_cli_actually_reads() {
        assert_eq!(spawn_env_var("gemini"), Some("GEMINI_API_KEY"));
        assert_eq!(spawn_env_var("anthropic"), Some("ANTHROPIC_API_KEY"));
        assert_eq!(spawn_env_var("openai"), Some("OPENAI_API_KEY"));
        assert_eq!(spawn_env_var("openrouter"), Some("OPENROUTER_API_KEY"));
    }

    #[test]
    fn passport_rows_keep_their_existing_names() {
        assert_eq!(spawn_env_var("GITHUB_TOKEN"), Some("GITHUB_TOKEN"));
        assert_eq!(spawn_env_var("HUGGINGFACE_TOKEN"), Some("HUGGINGFACE_TOKEN"));
    }

    /// env_credentials now reads the WHOLE api_keys table instead of naming rows
    /// in SQL, so the allowlist is the only thing keeping non-credential rows out
    /// of a child process's environment. These rows share that table.
    #[test]
    fn non_credential_rows_are_never_injected() {
        assert_eq!(spawn_env_var("__passport_github"), None);
        assert_eq!(spawn_env_var("__passport_huggingface"), None);
        assert_eq!(spawn_env_var("OLLAMA_BASE_URL"), None);
        assert_eq!(spawn_env_var("ollama_base_url"), None);
        assert_eq!(spawn_env_var(""), None);
        assert_eq!(spawn_env_var("anything_else"), None);
    }
}
