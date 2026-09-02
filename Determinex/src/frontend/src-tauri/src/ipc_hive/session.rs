use serde::Serialize;
use std::io::{BufRead, BufReader};
use std::process::Stdio;
use crate::win_process::HideConsoleExt;

use tauri::{AppHandle, Emitter, State};

use crate::ipc_envelope::Envelope;
use super::hive_command;
use super::{
    hive_script, is_oom_exit, manifest_path, project_root, sessions_dir,
    spawn_hive_subprocess, spawn_hive_subprocess_with_env, CreateSessionPayload,
    CreateSessionResult, HiveProcessMap, LogRingBuffer, RunSessionPayload, SessionIdPayload,
    SessionStatus, SpawnResult, StartSessionPayload, StepStatus,
    LOG_RING_CAPACITY,
};

/// Create a new Hive session (synchronous, instant).
///
/// Calls `determinex_hive.py new-session --spec PATH --lang LANG --budget N`.
/// Returns the session_id and workspace path. Does NOT start the build —
/// the frontend must call generate_dag() and then run_session() separately.
/// Response payloads that were inline `serde_json::json!` literals. Naming them
/// is the point: an inline literal cannot be checked against the TypeScript that
/// reads it, and `session.rs` alone wrote the `{ok,data,error}` envelope 21 times.
#[derive(Serialize)]
pub struct LogPathResponse {
    pub path: String,
    pub exists: bool,
}

#[derive(Serialize)]
pub struct StreamStartedResponse {
    pub streaming: bool,
    pub event: String,
}

#[derive(Serialize)]
pub struct SessionIdResponse {
    pub session_id: String,
}

/// `read_hive_workspace_file` puts `content` alongside `ok` rather than inside
/// `data`; api.ts reads `result.content`, so the shape is preserved exactly.
#[derive(Serialize)]
pub struct WorkspaceFileResponse {
    pub ok: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub content: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

impl WorkspaceFileResponse {
    fn ok(content: String) -> Self {
        Self { ok: true, content: Some(content), error: None }
    }
    fn err(msg: impl Into<String>) -> Self {
        Self { ok: false, content: None, error: Some(msg.into()) }
    }
}

#[tauri::command]
pub async fn create_session(
    payload: CreateSessionPayload,
) -> Result<Envelope<CreateSessionResult>, String> {
    log::info!(
        "[IPC] create_session: spec={}, lang={}, budget={}",
        payload.spec_path,
        payload.lang,
        payload.budget
    );

    let root = project_root();

    // new-session is the FIRST step of every build, and it ran
    // `python <repo>/scripts/determinex_hive.py` unconditionally -- so on an
    // installed copy with no repo checkout, nothing could be built at all. The
    // bundled engine binary was already shipped in the installer and only
    // generate-dag / run-session ever used it. Called synchronously here because
    // it is fast (it just writes the manifest).
    let (mut cmd, standalone) = hive_command("new-session")?;
    log::info!(
        "[IPC] create_session via {}",
        if standalone { "bundled engine" } else { "repo script" }
    );
    let output = cmd
        .args([
            "--spec",
            &payload.spec_path,
            "--lang",
            &payload.lang,
            "--budget",
            &payload.budget.to_string(),
        ])
        .current_dir(&root)
        .output()
        .map_err(|e| format!("Failed to spawn the hive engine (new-session): {}", e))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Ok(Envelope::err(format!("new-session failed: {}", stderr)));
    }

    // Parse session_id from stdout: "Session created: <uuid>"
    let stdout = String::from_utf8_lossy(&output.stdout);
    let session_id = stdout
        .lines()
        .find(|l| l.contains("Session created:"))
        .and_then(|l| l.split(':').nth(1))
        .map(|s| s.trim().to_string())
        .ok_or_else(|| "Could not parse session_id from new-session output".to_string())?;

    // Read manifest to get workspace path
    let manifest_file = manifest_path(&session_id);
    let workspace = if manifest_file.exists() {
        let data: serde_json::Value = serde_json::from_str(
            &std::fs::read_to_string(&manifest_file)
                .map_err(|e| format!("Cannot read manifest: {}", e))?,
        )
        .map_err(|e| format!("Cannot parse manifest: {}", e))?;
        data["project_root"].as_str().unwrap_or("").to_string()
    } else {
        String::new()
    };

    log::info!(
        "[IPC] Session created: id={}, workspace={}",
        session_id,
        workspace
    );

    Ok(Envelope::ok(CreateSessionResult { session_id, workspace }))
}

/// Generate the DAG for a session (async, runs in background).
///
/// Spawns `determinex_hive.py generate-dag --session {id}` as a tracked subprocess.
/// This is the expensive step — it calls the Oracle + Architect APIs to decompose
/// the MD spec into a dependency-ordered step DAG. Takes 30–60 seconds.
///
/// The frontend polls `get_session_status` to detect when DAG generation finishes:
/// `steps.length` changes from 0 to N when the Architect completes.
#[tauri::command]
pub async fn generate_dag(
    payload: SessionIdPayload,
    process_map: State<'_, HiveProcessMap>,
    app: tauri::AppHandle,
) -> Result<Envelope<SpawnResult>, String> {
    log::info!("[IPC] generate_dag: session={}", payload.session_id);

    let pid = spawn_hive_subprocess("generate-dag", &payload.session_id, &process_map, &[], &app)?;

    Ok(Envelope::ok(SpawnResult { session_id: payload.session_id, pid }))
}

/// Start the DAG build loop (async, runs in background).
///
/// Spawns `determinex_hive.py run-session --session {id}` as a tracked subprocess.
/// This is the long-running build loop that executes each step: Builder → Compiler
/// Oracle → Monitor with retries and escalation. May run for minutes.
///
/// The frontend streams output via `stream_session_log` and polls `get_session_status`
/// to see step-by-step progress.
///
/// Prerequisites: generate_dag must have already populated the session's steps.
/// If steps are empty, the build loop will bail immediately.
#[tauri::command]
pub async fn run_session(
    payload: RunSessionPayload,
    process_map: State<'_, HiveProcessMap>,
    app: tauri::AppHandle,
) -> Result<Envelope<SpawnResult>, String> {
    log::info!(
        "[IPC] run_session: session={} amplify={} amplify_k={:?}",
        payload.session_id, payload.amplify, payload.amplify_k
    );

    // Pre-check: verify steps exist so we can fail fast
    let manifest_file = manifest_path(&payload.session_id);
    if manifest_file.exists() {
        if let Ok(content) = std::fs::read_to_string(&manifest_file) {
            if let Ok(data) = serde_json::from_str::<serde_json::Value>(&content) {
                let step_count = data["steps"].as_array().map(|a| a.len()).unwrap_or(0);
                if step_count == 0 {
                    return Ok(Envelope::err(
                        "Session has no steps. Run generate_dag first to populate the DAG.",
                    ));
                }
            }
        }
    }

    let mut extra_env: Vec<(&str, String)> = Vec::new();
    if payload.amplify {
        extra_env.push(("DETERMINEX_AMPLIFY", "1".to_string()));
        if let Some(k) = payload.amplify_k {
            extra_env.push(("DETERMINEX_AMPLIFY_K", k.to_string()));
        }
    }

    let pid = spawn_hive_subprocess_with_env(
        "run-session",
        &payload.session_id,
        &process_map,
        &[],
        &extra_env,
        &app,
    )?;

    Ok(Envelope::ok(SpawnResult { session_id: payload.session_id, pid }))
}

/// Read the manifest.json for a session and return step statuses.
///
/// The frontend polls this periodically to update the DAG visualization.
/// Returns the full session status including per-step progress.
/// Also detects if the run-session process died while steps are still in_progress
/// and appends crash_tail (last 20 log lines) so the UI can surface the error.
#[tauri::command]
pub async fn get_session_status(
    payload: SessionIdPayload,
    process_map: State<'_, HiveProcessMap>,
) -> Result<Envelope<SessionStatus>, String> {
    let manifest_file = manifest_path(&payload.session_id);

    if !manifest_file.exists() {
        return Ok(Envelope::err(format!("Session not found: {}", payload.session_id)));
    }

    let content = std::fs::read_to_string(&manifest_file)
        .map_err(|e| format!("Cannot read manifest: {}", e))?;
    let data: serde_json::Value =
        serde_json::from_str(&content).map_err(|e| format!("Cannot parse manifest: {}", e))?;

    // Extract step statuses
    let steps: Vec<StepStatus> = data["steps"]
        .as_array()
        .map(|arr| {
            arr.iter()
                .map(|s| StepStatus {
                    id: s["id"].as_i64().unwrap_or(0),
                    instruction: s["instruction"].as_str().unwrap_or("").to_string(),
                    status: s["status"].as_str().unwrap_or("unknown").to_string(),
                    target_file: s["target_file"].as_str().unwrap_or("").to_string(),
                    write_mode: s["write_mode"].as_str().unwrap_or("").to_string(),
                    compiler_result: s["compiler_result"].as_str().unwrap_or("").to_string(),
                    compiler_output: s["compiler_output"].as_str().unwrap_or("").to_string(),
                    monitor_verdict: s["monitor_verdict"].as_str().unwrap_or("").to_string(),
                    adjudication_score: s["adjudication_score"].as_f64().unwrap_or(0.0),
                    retries: s["retries"].as_i64().unwrap_or(0),
                    quality: s["quality"].as_str().unwrap_or("").to_string(),
                })
                .collect()
        })
        .unwrap_or_default();

    let status = SessionStatus {
        session_id: data["session_id"].as_str().unwrap_or("").to_string(),
        lang: data["lang"].as_str().unwrap_or("").to_string(),
        project_root: data["project_root"].as_str().unwrap_or("").to_string(),
        steps,
        api_cost_usd: data["api_cost_usd"].as_f64().unwrap_or(0.0),
        session_budget_usd: data["session_budget_usd"].as_f64().unwrap_or(2.0),
        budget_exhausted: data["budget_exhausted"].as_bool().unwrap_or(false),
        scaffolding_validated: data["scaffolding_validated"].as_bool().unwrap_or(false),
        created_at: data["created_at"].as_str().unwrap_or("").to_string(),
        updated_at: data["updated_at"].as_str().unwrap_or("").to_string(),
        // Filled in by the crash detection below, when it applies.
        process_crashed: None,
        crash_tail: None,
    };

    // ── Crash detection ──────────────────────────────────────────────────────
    // If any step is still in_progress but the run-session process is no longer
    // alive, the Python worker crashed (e.g. Ollama timeout, OOM, unhandled
    // exception). Surface the last 20 lines of session.log as crash_tail so the
    // UI can show the error immediately instead of spinning indefinitely.
    let has_in_progress = status.steps.iter().any(|s| s.status == "in_progress");
    let process_alive = if has_in_progress {
        let key = format!("run-session:{}", payload.session_id);
        if let Ok(mut map) = process_map.processes.lock() {
            match map.get_mut(&key) {
                Some(child) => matches!(child.try_wait(), Ok(None)), // Ok(None) = still running
                None => false,                                       // Not tracked = not running
            }
        } else {
            true // Mutex poisoned — assume alive rather than false-crash
        }
    } else {
        true // No in_progress steps: crash check irrelevant
    };

    let mut status = status;

    if has_in_progress && !process_alive {
        let log_path = sessions_dir().join(&payload.session_id).join("session.log");
        let crash_tail = if log_path.exists() {
            std::fs::read_to_string(&log_path)
                .map(|content| {
                    let lines: Vec<&str> = content.lines().collect();
                    lines[lines.len().saturating_sub(20)..].join("\n")
                })
                .unwrap_or_else(|_| "Cannot read session log".to_string())
        } else {
            "Session log not found".to_string()
        };
        // Was `result["data"]["process_crashed"] = ...`, a double index into an
        // untyped Value that silently no-ops if either key is absent.
        status.process_crashed = Some(true);
        status.crash_tail = Some(crash_tail);
    }

    Ok(Envelope::ok(status))
}

/// Return the path to the session's log file.
///
/// The frontend uses this to know where to tail for log streaming.
/// Log file: sessions/{session_id}/session.log
#[tauri::command]
pub async fn get_session_log_path(
    payload: SessionIdPayload,
) -> Result<Envelope<LogPathResponse>, String> {
    let log_path = sessions_dir().join(&payload.session_id).join("session.log");

    Ok(Envelope::ok(LogPathResponse {
        exists: log_path.exists(),
        path: log_path.to_string_lossy().to_string(),
    }))
}

/// Read a file from a session's workspace directory.
///
/// Safe: validates the resolved path is inside the session's project_root before reading.
/// Returns { ok, content } or { ok: false, error }.
#[tauri::command]
pub async fn read_hive_workspace_file(
    payload: SessionIdPayload,
    relative_path: String,
) -> Result<WorkspaceFileResponse, String> {
    let manifest_file = manifest_path(&payload.session_id);
    if !manifest_file.exists() {
        return Ok(WorkspaceFileResponse::err("Session not found"));
    }

    let content = std::fs::read_to_string(&manifest_file)
        .map_err(|e| format!("Cannot read manifest: {}", e))?;
    let data: serde_json::Value =
        serde_json::from_str(&content).map_err(|e| format!("Cannot parse manifest: {}", e))?;

    let project_root = data["project_root"].as_str().unwrap_or("").to_string();
    if project_root.is_empty() {
        return Ok(WorkspaceFileResponse::err("No project_root in manifest"));
    }

    let root = std::path::Path::new(&project_root);
    let target = root.join(&relative_path);

    // Security: ensure resolved path stays inside the session workspace
    let canonical_root = match std::fs::canonicalize(root) {
        Ok(p) => p,
        Err(_) => return Ok(WorkspaceFileResponse::err("Workspace not found")),
    };
    let canonical_target = match std::fs::canonicalize(&target) {
        Ok(p) => p,
        Err(_) => return Ok(WorkspaceFileResponse::err("File not found")),
    };
    if !canonical_target.starts_with(&canonical_root) {
        return Ok(WorkspaceFileResponse::err("Path traversal blocked"));
    }
    if !canonical_target.is_file() {
        return Ok(WorkspaceFileResponse::err("Not a file"));
    }

    match std::fs::read_to_string(&canonical_target) {
        Ok(text) => Ok(WorkspaceFileResponse::ok(text)),
        Err(e) => Ok(WorkspaceFileResponse::err(e.to_string())),
    }
}

/// Tail the session log file and stream lines to the frontend via Tauri events.
///
/// The frontend invokes this once and receives a stream of `hive-log-{session_id}` events.
/// Each event payload is a single log line. The command runs until the session
/// process exits or the frontend disconnects.
///
/// Log file location: sessions/{session_id}/session.log (written by determinex_hive.py
/// via Python logging to stdout, captured by the subprocess).
#[tauri::command]
pub async fn stream_session_log(
    payload: SessionIdPayload,
    app: AppHandle,
) -> Result<Envelope<StreamStartedResponse>, String> {
    let session_dir = sessions_dir().join(&payload.session_id);
    let log_path = session_dir.join("session.log");

    // If the log file doesn't exist yet, try the manifest to find workspace
    // and check if the process is writing to stdout instead
    if !log_path.exists() {
        // Create the log file so we can watch it
        let _ = std::fs::create_dir_all(&session_dir);
        let _ = std::fs::write(&log_path, "");
    }

    let session_id = payload.session_id.clone();
    let event_name = format!("hive-log-{}", session_id);

    // Spawn a background thread to poll-tail the log through a ring buffer.
    // #ipc_ring: Caps in-memory lines at LOG_RING_CAPACITY to prevent OOM when
    // a verbose 50-step DAG generates 100K+ log lines.
    //
    // Poll-tail design: read_line returns Ok(0) at EOF; we sleep 100ms and retry.
    // When the Python process appends new lines the OS refills the read buffer.
    // This is the same mechanism as `tail -f` — no inotify/kqueue dependency.
    std::thread::spawn(move || {
        // Wait up to 15 seconds for the log file to receive its first write.
        let deadline = std::time::Instant::now() + std::time::Duration::from_secs(15);
        loop {
            if log_path.exists() && std::fs::metadata(&log_path).map(|m| m.len()).unwrap_or(0) > 0 {
                break;
            }
            if std::time::Instant::now() > deadline {
                log::warn!("[IPC] Timed out waiting for session log: {:?}", log_path);
                break;
            }
            std::thread::sleep(std::time::Duration::from_millis(200));
        }

        let mut ring = LogRingBuffer::new(LOG_RING_CAPACITY);

        let file = match std::fs::File::open(&log_path) {
            Ok(f) => f,
            Err(e) => {
                log::warn!("[IPC] Cannot open hive log at {:?}: {}", log_path, e);
                let _ = app.emit(
                    &event_name,
                    serde_json::json!({ "line": null, "complete": true }),
                );
                return;
            }
        };

        let mut reader = BufReader::new(file);
        let mut line_buf = String::new();
        // idle_polls counts consecutive Ok(0) returns. At 100ms/poll, 3000 = 5 min silence.
        // After 5 min of silence, also check the manifest — the session may have finished
        // without writing a final log line (e.g. Python crash before the last flush).
        let mut idle_polls: u32 = 0;
        const MAX_IDLE_POLLS: u32 = 3_000; // 300s silence cap
        const MANIFEST_CHECK_INTERVAL: u32 = 100; // check manifest every 10s of silence

        loop {
            line_buf.clear();
            match reader.read_line(&mut line_buf) {
                Ok(0) => {
                    idle_polls += 1;

                    // Every 10 seconds of silence: check the manifest for completion.
                    if idle_polls % MANIFEST_CHECK_INTERVAL == 0 {
                        let manifest = sessions_dir().join(&session_id).join("manifest.json");
                        if let Ok(content) = std::fs::read_to_string(&manifest) {
                            if let Ok(data) = serde_json::from_str::<serde_json::Value>(&content) {
                                if let Some(steps) = data["steps"].as_array() {
                                    if !steps.is_empty()
                                        && steps.iter().all(|s| {
                                            matches!(
                                                s["status"].as_str(),
                                                Some("complete") | Some("failed")
                                            )
                                        })
                                    {
                                        log::info!(
                                            "[IPC] Session {} manifest complete — ending log stream",
                                            session_id
                                        );
                                        break;
                                    }
                                }
                            }
                        }
                    }

                    if idle_polls > MAX_IDLE_POLLS {
                        log::info!(
                            "[IPC] stream_session_log: session {} silent for 5 min — closing stream",
                            session_id
                        );
                        break;
                    }
                    std::thread::sleep(std::time::Duration::from_millis(100));
                }
                Ok(_) => {
                    idle_polls = 0;
                    let text = line_buf
                        .trim_end_matches('\n')
                        .trim_end_matches('\r')
                        .to_string();
                    if !text.is_empty() {
                        ring.push(text.clone());
                        // Emit truncation marker if the ring just dropped lines.
                        if let Some(marker) = ring.drain_marker() {
                            let _ = app.emit(&event_name, serde_json::json!({ "line": marker }));
                        }
                        let _ = app.emit(&event_name, serde_json::json!({ "line": text }));
                    }
                }
                Err(e) => {
                    log::warn!("[IPC] Error reading session log for {}: {}", session_id, e);
                    break;
                }
            }
        }

        let total = ring.total_received();
        if total > LOG_RING_CAPACITY as u64 {
            log::info!(
                "[IPC] #ipc_ring: Session {} streamed {} lines (ring capped at {})",
                session_id,
                total,
                LOG_RING_CAPACITY
            );
        }

        let _ = app.emit(
            &event_name,
            serde_json::json!({ "line": null, "complete": true }),
        );
    });

    Ok(Envelope::ok(StreamStartedResponse {
        streaming: true,
        event: format!("hive-log-{}", payload.session_id),
    }))
}

/// Kill any running hive processes (generate-dag, run-session) for a session.
///
/// Stops background builds cleanly. The kill() method also reaps the child
/// process to prevent zombies.
///
/// start_session spawns children in a background thread that cannot register
/// them in process_map (ownership constraints). We fall back to a OS-level
/// kill by session ID in the command line as a reliable catch-all.
#[tauri::command]
pub async fn kill_session(
    payload: SessionIdPayload,
    process_map: State<'_, HiveProcessMap>,
) -> Result<Envelope<()>, String> {
    // Path 1: process_map (populated by generate_dag / run_session commands)
    for key in &[
        format!("generate-dag:{}", payload.session_id),
        format!("run-session:{}", payload.session_id),
    ] {
        process_map.kill(key);
    }

    // Path 2: OS-level fallback for start_session background-thread processes.
    // Session ID is always passed as --session <id>, making it unique per process.
    #[cfg(target_os = "windows")]
    {
        let filter = format!("COMMANDLINE like %{}%", payload.session_id);
        let _ = tokio::process::Command::new("taskkill").hide_console()
            .args(["/F", "/FI", &filter])
            .output()
            .await;
        log::info!("[IPC] kill_session: taskkill /FI \"{}\"", filter);
    }
    #[cfg(not(target_os = "windows"))]
    {
        // On Linux/macOS: pkill by session ID in command args
        let _ = tokio::process::Command::new("pkill").hide_console()
            .args(["-f", &payload.session_id])
            .output()
            .await;
    }

    log::info!("[IPC] kill_session: session={}", payload.session_id);
    Ok(Envelope::done())
}

/// Start an entire session (new-session -> generate-dag -> run-session)
/// Returns immediately with the session_id, runs the rest in a background tokio thread.
#[tauri::command]
pub async fn start_session(
    payload: StartSessionPayload,
    _process_map: State<'_, HiveProcessMap>,
    app: AppHandle,
) -> Result<Envelope<SessionIdResponse>, String> {
    log::info!(
        "[IPC] start_session: spec={}, lang={}",
        payload.spec_path,
        payload.lang
    );

    let root = project_root();

    // 1. new-session (sync), through the bundled engine when present.
    let (mut cmd, standalone) = hive_command("new-session")?;
    log::info!(
        "[IPC] start_session via {}",
        if standalone { "bundled engine" } else { "repo script" }
    );
    let output = cmd
        .args([
            "--spec",
            &payload.spec_path,
            "--lang",
            &payload.lang,
            "--budget",
            &payload.budget.to_string(),
        ])
        .current_dir(&root)
        .output()
        .map_err(|e| format!("Failed to spawn the hive engine (new-session): {}", e))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Ok(Envelope::err(format!("new-session failed: {}", stderr)));
    }

    let stdout = String::from_utf8_lossy(&output.stdout);
    let session_id = stdout
        .lines()
        .find(|l| l.contains("Session created:"))
        .and_then(|l| l.split(':').nth(1))
        .map(|s| s.trim().to_string())
        .ok_or_else(|| "Could not parse session_id from new-session output".to_string())?;

    // 2. Spawn a thread to run generate-dag, wait for it, then run-session.
    //    #oom_hook: After each subprocess exits, check for OOM exit codes.
    let sid_clone = session_id.clone();
    let root_clone = root.clone();

    std::thread::spawn(move || {
        // Open the session log once — both subcommands append to the same file
        // so stream_session_log can tail all output continuously.
        let session_log_path = sessions_dir().join(&sid_clone).join("session.log");
        let _ = std::fs::create_dir_all(
            session_log_path
                .parent()
                .unwrap_or_else(|| std::path::Path::new(".")),
        );

        log::info!(
            "[IPC] start_session background: generate-dag for {}",
            sid_clone
        );
        // GAP-3: Replace .expect() with match so errors emit a "hive-error" event
        // instead of silently panicking the spawned thread (leaving the UI hung).
        let stdout_file1 = match std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&session_log_path)
        {
            Ok(f) => f,
            Err(e) => {
                log::error!("[IPC] Cannot open session log for generate-dag: {}", e);
                let _ = app.emit(
                    "hive-error",
                    serde_json::json!({
                        "session_id": &sid_clone,
                        "message": format!("Cannot open session log: {}", e),
                    }),
                );
                return;
            }
        };
        let stderr_file1 = match stdout_file1.try_clone() {
            Ok(f) => f,
            Err(e) => {
                log::error!("[IPC] Cannot clone session log fd: {}", e);
                let _ = app.emit(
                    "hive-error",
                    serde_json::json!({
                        "session_id": &sid_clone,
                        "message": format!("Cannot clone session log fd: {}", e),
                    }),
                );
                return;
            }
        };
        // Same preference inside the thread: bundled engine first, repo script only
        // as a dev fallback. `hive_command` cannot fail here in a way worth
        // aborting for -- if it does, the spawn below reports it into session.log
        // like any other launch failure.
        let (mut thread_cmd, _) = match hive_command("generate-dag") {
            Ok(pair) => pair,
            Err(e) => {
                log::error!("[IPC] start_session: no hive engine available: {}", e);
                return;
            }
        };
        let mut child1 = match thread_cmd
            .args(["--session", &sid_clone])
            .current_dir(&root_clone)
            .stdout(Stdio::from(stdout_file1))
            .stderr(Stdio::from(stderr_file1))
            .spawn()
        {
            Ok(c) => c,
            Err(e) => {
                log::error!("[IPC] Failed to start generate-dag: {}", e);
                let _ = app.emit(
                    "hive-error",
                    serde_json::json!({
                        "session_id": &sid_clone,
                        "message": format!(
                            "Failed to start generate-dag. Python binary not found or inaccessible: {}",
                            e
                        ),
                    }),
                );
                return;
            }
        };

        let status1 = child1.wait();

        // Check generate-dag exit status before proceeding to run-session.
        match &status1 {
            Ok(status) if !status.success() => {
                let code = status.code().unwrap_or(-1);
                if is_oom_exit(code) {
                    log::error!(
                        "[IPC] #oom_hook: generate-dag for {} killed by OOM (exit code {})",
                        sid_clone,
                        code
                    );
                    let _ = app.emit(
                        "hive-oom",
                        serde_json::json!({
                            "process": format!("generate-dag:{}", sid_clone),
                            "exit_code": code,
                            "message": format!(
                                "DAG generation was killed by the OS (exit code {}). \
                                 The system ran out of memory. Try closing other applications \
                                 or reducing model size.",
                                code
                            ),
                        }),
                    );
                } else {
                    log::error!(
                        "[IPC] generate-dag for {} failed (exit code {})",
                        sid_clone,
                        code
                    );
                    let _ = app.emit(
                        "hive-error",
                        serde_json::json!({
                            "session_id": &sid_clone,
                            "message": format!(
                                "DAG generation failed (exit code {}). Check the session log for details.",
                                code
                            ),
                        }),
                    );
                }
                return; // Do not proceed to run-session on any generate-dag failure
            }
            Err(e) => {
                log::error!("[IPC] generate-dag wait error for {}: {}", sid_clone, e);
                let _ = app.emit(
                    "hive-error",
                    serde_json::json!({
                        "session_id": &sid_clone,
                        "message": format!("Failed to wait for generate-dag: {}", e),
                    }),
                );
                return;
            }
            Ok(_) => {} // success — fall through to run-session
        }

        log::info!(
            "[IPC] start_session background: run-session for {}",
            sid_clone
        );
        // GAP-3: Same pattern — match instead of expect so errors surface to the UI.
        let stdout_file2 = match std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&session_log_path)
        {
            Ok(f) => f,
            Err(e) => {
                log::error!("[IPC] Cannot open session log for run-session: {}", e);
                let _ = app.emit(
                    "hive-error",
                    serde_json::json!({
                        "session_id": &sid_clone,
                        "message": format!("Cannot open session log for run-session: {}", e),
                    }),
                );
                return;
            }
        };
        let stderr_file2 = match stdout_file2.try_clone() {
            Ok(f) => f,
            Err(e) => {
                log::error!("[IPC] Cannot clone session log fd for run-session: {}", e);
                let _ = app.emit(
                    "hive-error",
                    serde_json::json!({
                        "session_id": &sid_clone,
                        "message": format!("Cannot clone session log fd: {}", e),
                    }),
                );
                return;
            }
        };
        let (mut thread_cmd2, _) = match hive_command("run-session") {
            Ok(pair) => pair,
            Err(e) => {
                log::error!("[IPC] start_session: no hive engine for run-session: {}", e);
                return;
            }
        };
        let mut child2 = match thread_cmd2
            .args(["--session", &sid_clone])
            .current_dir(&root_clone)
            .stdout(Stdio::from(stdout_file2))
            .stderr(Stdio::from(stderr_file2))
            .spawn()
        {
            Ok(c) => c,
            Err(e) => {
                log::error!("[IPC] Failed to start run-session: {}", e);
                let _ = app.emit(
                    "hive-error",
                    serde_json::json!({
                        "session_id": &sid_clone,
                        "message": format!(
                            "Failed to start run-session. Python binary not found or inaccessible: {}",
                            e
                        ),
                    }),
                );
                return;
            }
        };

        let status2 = child2.wait();

        // #oom_hook: Check if run-session was OOM killed
        if let Ok(status) = &status2 {
            if let Some(code) = status.code() {
                if is_oom_exit(code) {
                    log::error!(
                        "[IPC] #oom_hook: run-session for {} killed by OOM (exit code {})",
                        sid_clone,
                        code
                    );
                    let _ = app.emit(
                        "hive-oom",
                        serde_json::json!({
                            "process": format!("run-session:{}", sid_clone),
                            "exit_code": code,
                            "message": format!(
                                "Build session was killed by the OS (exit code {}). \
                                 The system ran out of memory. Try reducing model size \
                                 (num_gpu_layers) or closing other applications.",
                                code
                            ),
                        }),
                    );
                }
            }
        }
    });

    Ok(Envelope::ok(SessionIdResponse { session_id }))
}

#[tauri::command]
pub async fn pause_session(payload: SessionIdPayload) -> Result<Envelope<()>, String> {
    log::info!("[IPC] pause_session: session={}", payload.session_id);
    Err("Pause session is not implemented in native backend yet".to_string())
}

#[tauri::command]
pub async fn resume_session(payload: SessionIdPayload) -> Result<Envelope<()>, String> {
    log::info!("[IPC] resume_session: session={}", payload.session_id);
    Err("Resume session is not implemented in native backend yet".to_string())
}

#[tauri::command]
pub async fn cancel_session(
    payload: SessionIdPayload,
    process_map: State<'_, HiveProcessMap>,
) -> Result<Envelope<()>, String> {
    log::info!("[IPC] cancel_session: session={}", payload.session_id);
    kill_session(payload, process_map).await
}

#[tauri::command]
pub async fn replay_session(payload: SessionIdPayload) -> Result<Envelope<()>, String> {
    log::info!("[IPC] replay_session: session={}", payload.session_id);
    Err("Replay session is not implemented in native backend yet".to_string())
}
