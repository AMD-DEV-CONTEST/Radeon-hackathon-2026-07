/// ipc_hive — Tauri IPC Bridge for the Hive Mind DAG Orchestrator
///
/// Organized into four domain submodules:
///   session   — create_session, generate_dag, run_session, get_session_status, ...
///   oracle    — generate_spec, discover_idea, converse_idea, refine_spec
///   workspace — explore_workspace, diagnose_workspace, fix_workspace
///   roles     — list_hive_sessions, get_role_assignments, set_role_assignments, reveal_session_output
///
/// All submodule commands are re-exported here so lib.rs can reference them as
/// `ipc_hive::create_session` without any path changes.
use std::collections::VecDeque;
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::sync::Mutex;

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter, Manager};

use crate::win_process::{HideConsoleExt, HideConsoleNewGroupExt};

pub mod onboarding;
pub mod oracle;
pub mod roles;
pub mod session;
pub mod workspace;

// Re-export everything from submodules so lib.rs can use `ipc_hive::cmd_name`.
// Wildcard re-exports are necessary here: Tauri's generate_handler! macro resolves
// commands via a companion `__cmd__cmd_name` struct generated alongside each
// `#[tauri::command]` fn. Named re-exports would bring the fn but not the struct;
// `pub use submod::*` re-exports both.
pub use onboarding::*;
pub use oracle::*;
pub use roles::*;
pub use session::*;
pub use workspace::*;

// ─────────────────────────────────────────────────────────────────────────────
// IPC RING BUFFER (#ipc_ring)
// ─────────────────────────────────────────────────────────────────────────────

/// Maximum number of log lines held in the ring buffer per session.
/// At ~120 bytes/line average (compiler output), 10K lines ≈ 1.2 MB of RAM.
/// Without this cap, a verbose 50-step DAG can generate 100K+ lines and OOM
/// the Tauri WebView process (Chromium has a per-renderer ~2GB limit on Windows).
pub const LOG_RING_CAPACITY: usize = 10_000;

/// Bounded FIFO ring buffer for session log lines.
/// Drops oldest lines when capacity is exceeded. Thread-safe via external Mutex.
pub struct LogRingBuffer {
    buf: VecDeque<String>,
    capacity: usize,
    /// Total lines received (including dropped). Used for telemetry.
    total_received: u64,
    /// Lines dropped from the front since the last read; injected as a marker on next read.
    dropped: u64,
}

impl LogRingBuffer {
    pub fn new(capacity: usize) -> Self {
        Self {
            buf: VecDeque::with_capacity(capacity.min(LOG_RING_CAPACITY)),
            capacity,
            total_received: 0,
            dropped: 0,
        }
    }

    /// Push a line. If at capacity, drops the oldest line and increments the dropped counter.
    pub fn push(&mut self, line: String) {
        self.total_received += 1;
        if self.buf.len() >= self.capacity {
            self.buf.pop_front();
            self.dropped += 1;
        }
        self.buf.push_back(line);
    }

    /// Prepend a truncation marker if any lines were dropped since the last read.
    fn drain_marker(&mut self) -> Option<String> {
        if self.dropped > 0 {
            let marker = format!(
                "[LOG TRUNCATED — {} lines dropped from ring buffer]",
                self.dropped
            );
            self.dropped = 0;
            Some(marker)
        } else {
            None
        }
    }

    /// Number of lines dropped so far (total_received - current len - already drained).
    pub fn total_received(&self) -> u64 {
        self.total_received
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// OOM DETECTION (#oom_hook)
// ─────────────────────────────────────────────────────────────────────────────

/// Exit codes that indicate the process was killed by the OS OOM killer.
/// Linux: SIGKILL = exit code 137 (128 + 9).
/// Windows NTSTATUS codes cast to i32:
///   STATUS_ACCESS_VIOLATION  = 0xC0000005 → -1073741819 (NULL deref from failed alloc)
///   STATUS_NO_MEMORY         = 0xC0000017 → -1073741801 (explicit out-of-memory)
///   STATUS_STACK_OVERFLOW    = 0xC00000FD → -1073740791 (stack exhaustion, not true OOM but surfaced the same way)
const OOM_EXIT_CODES: &[i32] = &[
    137,         // Linux OOM kill (SIGKILL)
    -1073741819, // Windows STATUS_ACCESS_VIOLATION (0xC0000005)
    -1073741801, // Windows STATUS_NO_MEMORY (0xC0000017)
    -1073740791, // Windows STATUS_STACK_OVERFLOW (0xC00000FD)
];

/// Check if a process exit code indicates an OOM kill.
pub(crate) fn is_oom_exit(code: i32) -> bool {
    OOM_EXIT_CODES.contains(&code)
}

// ─────────────────────────────────────────────────────────────────────────────
// SHARED STATE — tracks spawned hive session processes
// ─────────────────────────────────────────────────────────────────────────────

/// Tracks spawned hive session child processes so we can kill entire process trees.
pub struct HiveProcessMap {
    pub processes: Mutex<std::collections::HashMap<String, std::process::Child>>,
}

impl HiveProcessMap {
    pub fn new() -> Self {
        Self {
            processes: Mutex::new(std::collections::HashMap::new()),
        }
    }

    /// Kill a tracked process and reap it to prevent zombies.
    pub fn kill(&self, key: &str) {
        if let Ok(mut map) = self.processes.lock() {
            if let Some(mut child) = map.remove(key) {
                let _ = child.kill();
                let _ = child.wait(); // reap so no zombie
            }
        }
    }

    /// Kill and reap all tracked processes (e.g., during application shutdown).
    pub fn abort_all(&self) {
        if let Ok(mut map) = self.processes.lock() {
            for (_, child) in map.iter_mut() {
                let _ = child.kill();
                let _ = child.wait();
            }
            map.clear();
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// IPC PAYLOADS
// ─────────────────────────────────────────────────────────────────────────────

#[derive(Deserialize)]
pub struct GenerateSpecPayload {
    pub idea: String,
}

#[derive(Deserialize)]
pub struct RefineSpecPayload {
    pub spec: String,
    pub request: String,
}

#[derive(Deserialize, Serialize)]
pub struct AttachmentPayload {
    pub name: String,
    pub mime_type: String,
    pub data: String, // base64-encoded bytes
}

#[derive(Deserialize, Serialize)]
pub struct DiscoverIdeaPayload {
    pub idea: String,
    pub attachments: Option<Vec<AttachmentPayload>>,
}

#[derive(Deserialize, Serialize)]
pub struct ConversationMessage {
    pub role: String,
    pub text: String,
}

/// "Do we know enough to build this yet?" — answered by whether a SOUND ORACLE can be
/// synthesized from the answers gathered so far, not by counting questions.
///
/// This command exists because the Python side of the feature shipped without it. The
/// Concept Lab prefers Tauri IPC and only falls back to the HTTP bridge, so an endpoint
/// added to the bridge alone was unreachable in the desktop app: the frontend's
/// `invokeSafe` failed, the caller's `if (!res.ok) buildSpec()` fallback fired, and the
/// interview quietly stopped at the old four questions while every test passed.
#[derive(Deserialize, Serialize)]
pub struct AssessIdeaContextPayload {
    pub idea: String,
    pub answers: Vec<String>,
    pub asked: Vec<String>,
    pub previous_satisfied: Option<Vec<String>>,
}

#[derive(Deserialize, Serialize)]
pub struct ConverseIdeaPayload {
    pub idea: String,
    pub messages: Vec<ConversationMessage>,
    pub user_message: String,
    pub attachments: Option<Vec<AttachmentPayload>>,
}

#[derive(Deserialize)]
pub struct StartSessionPayload {
    pub spec_path: String,
    pub lang: String,
    #[serde(default = "default_budget")]
    pub budget: f64,
}

#[derive(Deserialize)]
pub struct CreateSessionPayload {
    pub spec_path: String,
    pub lang: String,
    #[serde(default = "default_budget")]
    pub budget: f64,
}

pub fn default_budget() -> f64 {
    2.0
}

#[derive(Deserialize)]
pub struct SessionIdPayload {
    pub session_id: String,
}

#[derive(Deserialize)]
pub struct RunSessionPayload {
    pub session_id: String,
    /// Opt-in Correctness Amplifier (best-of-K verified search against the same
    /// Compiler Oracle, per hive/amplifier_bridge.py). Off unless explicitly set.
    #[serde(default)]
    pub amplify: bool,
    /// Candidate count K. Frontend should default this to a hardware-recommended
    /// value (see probe_hardware's vram_budget_mb) before the user overrides it.
    #[serde(default)]
    pub amplify_k: Option<u32>,
}

// ─────────────────────────────────────────────────────────────────────────────
// RESPONSE TYPES
// ─────────────────────────────────────────────────────────────────────────────

#[derive(Serialize)]
pub struct CreateSessionResult {
    pub session_id: String,
    pub workspace: String,
}

#[derive(Serialize)]
pub struct SpawnResult {
    pub session_id: String,
    pub pid: u32,
}

#[derive(Serialize)]
pub struct SessionStatus {
    pub session_id: String,
    pub lang: String,
    pub project_root: String,
    pub steps: Vec<StepStatus>,
    pub api_cost_usd: f64,
    pub session_budget_usd: f64,
    pub budget_exhausted: bool,
    pub scaffolding_validated: bool,
    pub created_at: String,
    pub updated_at: String,

    /// Set when the manifest still says a step is in progress but no process is
    /// alive. Previously injected into the serialized envelope with
    /// `result["data"]["process_crashed"] = ...`, a double index into an untyped
    /// Value that silently no-ops if either key is missing -- so a crash could
    /// have gone unreported with nothing to show it had.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub process_crashed: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub crash_tail: Option<String>,
}

#[derive(Serialize)]
pub struct StepStatus {
    pub id: i64,
    pub instruction: String,
    pub status: String,
    pub target_file: String,
    pub write_mode: String,
    pub compiler_result: String,
    pub compiler_output: String,
    pub monitor_verdict: String,
    pub adjudication_score: f64,
    pub retries: i64,
    pub quality: String,
}

// ─────────────────────────────────────────────────────────────────────────────
// HELPERS
// ─────────────────────────────────────────────────────────────────────────────

/// Resolve the project root at runtime.
///
/// Resolution order:
///   1. `DETERMINEX_ROOT` env var — explicit override for non-standard checkout paths
///   2. Walk up from `current_exe()` looking for `scripts/determinex_hive.py` (dev + packaged)
///   3. Current working directory fallback
pub(crate) fn project_root() -> PathBuf {
    if let Ok(root) = std::env::var("DETERMINEX_ROOT") {
        return PathBuf::from(root);
    }
    // Walk up from the executable to find the repo root at runtime.
    // In dev mode (tauri dev): exe is in target/debug/, so we walk up ~3 levels.
    // In production: user should set DETERMINEX_ROOT; this is the best-effort fallback.
    // Walk up from exe (works when target is on same drive as repo)
    if let Ok(exe) = std::env::current_exe() {
        let mut candidate = exe.parent().map(|p| p.to_path_buf()).unwrap_or_default();
        for _ in 0..8 {
            if candidate.join("scripts").join("determinex_hive.py").exists() {
                return candidate;
            }
            match candidate.parent() {
                Some(p) => candidate = p.to_path_buf(),
                None => break,
            }
        }
    }
    // Walk up from cwd — handles the case where CARGO_TARGET_DIR redirects the
    // exe to a different drive (e.g. T:\determinex-target) so the exe walk misses.
    if let Ok(cwd) = std::env::current_dir() {
        let mut candidate = cwd;
        for _ in 0..8 {
            if candidate.join("scripts").join("determinex_hive.py").exists() {
                return candidate;
            }
            match candidate.parent() {
                Some(p) => candidate = p.to_path_buf(),
                None => break,
            }
        }
    }
    eprintln!("[Determinex] project_root() fell back to '.' — set DETERMINEX_ROOT to the repo root to suppress this warning");
    PathBuf::from(".")
}

/// Resolve the Python interpreter, bypassing Windows Store AppExecLink stubs.
///
/// The Windows Store ships a fake `python.exe` AppExecLink in
/// `%LOCALAPPDATA%\Microsoft\WindowsApps\` that silently opens the Store
/// (or exits with code 9009) instead of running Python. `Command::new("python")`
/// will hit this stub whenever Python is not installed on the system PATH —
/// and the spawn succeeds (no error) while the process silently dies.
///
/// Priority order:
///   1. `DETERMINEX_PYTHON` env var — explicit override, highest priority
///   2. `<project_root>/venv/Scripts/python.exe` (Windows venv, standard layout)
///   3. `<project_root>/.venv/Scripts/python.exe` (alternative naming)
///   4. `<project_root>/venv/bin/python` (Linux / macOS)
///   5. `where python` output (Windows) — validated: WindowsApps paths rejected
///   6. `python3` literal (Linux / macOS fallback)
pub(crate) fn resolve_python_exe() -> Result<PathBuf, String> {
    // 1. Explicit override
    if let Ok(explicit) = std::env::var("DETERMINEX_PYTHON") {
        let p = PathBuf::from(&explicit);
        if p.exists() {
            log::info!("[IPC] Python resolved via DETERMINEX_PYTHON: {:?}", p);
            return Ok(p);
        }
        log::warn!(
            "[IPC] DETERMINEX_PYTHON={:?} not found — falling through to auto-detection",
            p
        );
    }

    let root = project_root();

    // 2. venv/Scripts/python.exe (Windows virtualenv)
    let venv_win = root.join("venv").join("Scripts").join("python.exe");
    if venv_win.exists() {
        log::info!("[IPC] Python resolved via venv: {:?}", venv_win);
        return Ok(venv_win);
    }

    // 3. .venv/Scripts/python.exe (alternative naming)
    let dot_venv_win = root.join(".venv").join("Scripts").join("python.exe");
    if dot_venv_win.exists() {
        log::info!("[IPC] Python resolved via .venv: {:?}", dot_venv_win);
        return Ok(dot_venv_win);
    }

    // 4. venv/bin/python (Linux / macOS)
    let venv_unix = root.join("venv").join("bin").join("python");
    if venv_unix.exists() {
        log::info!("[IPC] Python resolved via venv/bin: {:?}", venv_unix);
        return Ok(venv_unix);
    }

    // 5. PATH resolution — reject Windows Store stubs
    #[cfg(target_os = "windows")]
    {
        if let Ok(out) = std::process::Command::new("where").hide_console().arg("python").output() {
            if out.status.success() {
                for candidate in String::from_utf8_lossy(&out.stdout).lines() {
                    let candidate = candidate.trim();
                    if candidate.is_empty() {
                        continue;
                    }
                    // Reject Windows Store AppExecLink stubs — they live under
                    // either %LOCALAPPDATA%\Microsoft\WindowsApps\ or
                    // %WINDIR%\System32\WindowsApps\
                    let lower = candidate.to_lowercase();
                    if lower.contains("windowsapps") {
                        log::warn!("[IPC] Skipping Windows Store Python stub: {}", candidate);
                        continue;
                    }
                    let p = PathBuf::from(candidate);
                    if p.exists() {
                        log::info!("[IPC] Python resolved via PATH (where): {:?}", p);
                        return Ok(p);
                    }
                }
            }
        }
        // All candidates exhausted
        return Err("Cannot find a valid Python interpreter. \
             Set the DETERMINEX_PYTHON environment variable to the full path of python.exe, \
             or create a virtualenv at <project_root>/venv/."
            .to_string());
    }

    // 6. Last resort on Unix: "python3"
    #[cfg(not(target_os = "windows"))]
    Ok(PathBuf::from("python3"))
}

/// Path to the sessions directory.
pub(crate) fn sessions_dir() -> PathBuf {
    project_root().join("sessions")
}

/// Path to a session's manifest.json.
pub(crate) fn manifest_path(session_id: &str) -> PathBuf {
    sessions_dir().join(session_id).join("manifest.json")
}

/// Path to the determinex_hive.py script.
pub(crate) fn hive_script() -> PathBuf {
    project_root().join("scripts").join("determinex_hive.py")
}

/// Resolve the bundled `determinex-hive` engine binary, if present.
///
/// Extracted from `spawn_hive_subprocess_with_env`, where this walk was inline and
/// therefore unavailable to every OTHER command. That is why `create_session`,
/// `explore_workspace`, `diagnose_workspace` and `fix_workspace` all shelled to
/// `python <repo>/scripts/determinex_hive.py` instead: the standalone path existed
/// and only one call site could reach it. On a machine with no repo checkout those
/// commands could not work at all, which made the shipped app dependent on the
/// development tree.
///
/// Search order: dev layout, then packaged layouts (bin/ beside or above the exe).
pub(crate) fn resolve_hive_binary() -> Option<PathBuf> {
    let suffix = if cfg!(target_os = "windows") { ".exe" } else { "" };
    let triple_name = format!("determinex-hive-{}{}", target_triple(), suffix);
    let plain_name = format!("determinex-hive{}", suffix);
    let candidates = [triple_name.as_str(), plain_name.as_str()];

    // Dev layout: <project_root>/frontend/src-tauri/bin/
    let dev_bin_dir = project_root().join("frontend").join("src-tauri").join("bin");
    if let Some(found) = candidates
        .iter()
        .map(|name| dev_bin_dir.join(name))
        .find(|path| path.exists())
    {
        return Some(found);
    }

    // Packaged layout: bin/<name> at or above the exe, or beside the exe.
    let exe = std::env::current_exe().ok()?;
    let mut dir = exe.parent()?.to_path_buf();
    for _ in 0..6 {
        for name in candidates {
            let in_bin = dir.join("bin").join(name);
            if in_bin.exists() {
                return Some(in_bin);
            }
            let beside = dir.join(name);
            if beside.exists() {
                return Some(beside);
            }
        }
        match dir.parent() {
            Some(parent) => dir = parent.to_path_buf(),
            None => break,
        }
    }
    None
}

/// Should the repo's Python be used instead of the bundled sidecar?
///
/// True when the script exists and is NEWER than the binary built from it — i.e. someone is
/// editing source in a dev checkout. `resolve_hive_binary` looks in
/// `frontend/src-tauri/bin/` before anywhere else, so without this check a dev tree runs
/// whatever sidecar happens to be sitting there and every Python edit is silently ignored.
/// That is not hypothetical: the app was answering `list_coding_agents` from a sidecar built
/// three days earlier, so a freshly added field was simply absent, the picker fell back to its
/// free-text branch, and nothing anywhere said which copy of the code had run. The comment on
/// the branch below called itself a "dev fallback", which reads as "source wins in a dev tree"
/// and means the opposite: it only fires when the sidecar is missing entirely.
///
/// In a packaged install there is no `scripts/` directory, so this is always false and the
/// sidecar is used unconditionally. `DETERMINEX_HELPER_FROM_SOURCE` forces either answer.
fn prefer_source(script: &std::path::Path, binary: &std::path::Path) -> bool {
    match std::env::var("DETERMINEX_HELPER_FROM_SOURCE").ok().as_deref() {
        Some("1") | Some("true") => return script.exists(),
        Some("0") | Some("false") => return false,
        _ => {}
    }
    if !script.exists() {
        return false;
    }
    let newer = |a: &std::path::Path, b: &std::path::Path| -> Option<bool> {
        Some(a.metadata().ok()?.modified().ok()? > b.metadata().ok()?.modified().ok()?)
    };
    // Unreadable timestamps mean we cannot tell, and the sidecar stays authoritative --
    // guessing "use source" would change behaviour in a packaged install on a filesystem
    // that does not report mtimes.
    newer(script, binary).unwrap_or(false)
}

/// A `Command` that runs a hive subcommand, preferring the bundled engine binary
/// and falling back to `python scripts/determinex_hive.py` for a dev checkout.
///
/// Returns the command plus whether it is the standalone binary, so callers can
/// log which path they took rather than guessing.
pub(crate) fn hive_command(subcommand: &str) -> Result<(Command, bool), String> {
    if let Some(binary) = resolve_hive_binary().filter(|b| !prefer_source(&hive_script(), b)) {
        let mut cmd = Command::new(binary);
        cmd.hide_console();
        cmd.arg(subcommand);
        return Ok((cmd, true));
    }
    // Dev fallback: the repo's script through a resolved interpreter.
    let script = hive_script();
    if !script.exists() {
        return Err(format!(
            "Neither the bundled determinex-hive binary nor {} was found.              Build the engine with: python bundler/build_hive_sidecar.py",
            script.display()
        ));
    }
    let python = resolve_python_exe()?;
    let mut cmd = Command::new(python);
    cmd.hide_console();
    cmd.arg(script).arg(subcommand);
    Ok((cmd, false))
}

/// A `Command` that runs one of the bundled HELPER scripts (agent chat, agent
/// registry, usage ledger, toolchain installer, model bench, corpus API), preferring
/// the bundled engine and falling back to `python scripts/<name>.py` in a dev tree.
///
/// WHY THIS EXISTS
/// `hive_command` above has been bundled-first for a while, but every non-hive script
/// the desktop backend needs was invoked through a SECOND path that shells out to
/// `scripts/<name>.py` by path. That path does not exist in an installed copy, so the
/// agent chat room and friends were dev-checkout-only while the hive itself shipped
/// fine. Two invocation paths, one bundled, and new callers reached for whichever was
/// nearest.
///
/// `script` is the repo-relative path the old callers already use
/// (e.g. "scripts/determinex_agents.py"); the module name handed to the sidecar's
/// `helper` subcommand is derived from it, so call sites do not have to change shape.
pub(crate) fn helper_command(script: &str) -> Result<(Command, bool), String> {
    // "scripts/determinex_agents.py"     -> "determinex_agents"
    // "scripts/ide/_tauri_driver.py"      -> "ide._tauri_driver"
    // file_stem() alone was wrong for the nested case: it yields "_tauri_driver",
    // which is not importable and is not what the sidecar's allowlist names.
    let module = script
        .trim_start_matches("./")
        .strip_prefix("scripts/")
        .unwrap_or(script)
        .strip_suffix(".py")
        .unwrap_or(script)
        .replace(['/', '\\'], ".");

    let path = project_root().join(script);
    if let Some(binary) = resolve_hive_binary().filter(|b| !prefer_source(&path, b)) {
        let mut cmd = Command::new(binary);
        cmd.hide_console();
        cmd.arg("helper").arg(&module);
        return Ok((cmd, true));
    }
    // The repo's script through a resolved interpreter: either no sidecar exists, or this
    // script is newer than the one that was built (see `prefer_source`).
    if !path.exists() {
        return Err(format!(
            "Neither the bundled determinex-hive binary nor {} was found.              Build the engine with: python bundler/build_hive_sidecar.py",
            path.display()
        ));
    }
    let python = resolve_python_exe()?;
    let mut cmd = Command::new(python);
    cmd.hide_console();
    cmd.arg(path);
    Ok((cmd, false))
}

/// Spawn the Determinex Hive sidecar binary for a subcommand.
///
/// This is the VS Code pattern: Tauri bundles the pre-compiled determinex-hive
/// binary inside the installer. We resolve the binary path by walking up from
/// the current executable — this works in both dev (src-tauri/bin/) and
/// production (app bundle resources).
///
/// Stdout + stderr are redirected to session.log so stream_session_log can tail them.
/// On Windows, CREATE_NEW_PROCESS_GROUP ensures killing the sidecar also kills
/// child compiler processes (rustc, go build) — same zombie prevention as before.
pub(crate) fn spawn_hive_subprocess(
    subcommand: &str,
    session_id: &str,
    process_map: &HiveProcessMap,
    extra_args: &[&str],
    _app: &tauri::AppHandle,
) -> Result<u32, String> {
    spawn_hive_subprocess_with_env(subcommand, session_id, process_map, extra_args, &[], _app)
}

/// Same as `spawn_hive_subprocess`, plus caller-supplied environment variables
/// (e.g. DETERMINEX_AMPLIFY / DETERMINEX_AMPLIFY_K for the opt-in Correctness
/// Amplifier — see `hive/amplifier_bridge.py`).
pub(crate) fn spawn_hive_subprocess_with_env(
    subcommand: &str,
    session_id: &str,
    process_map: &HiveProcessMap,
    extra_args: &[&str],
    extra_env: &[(&str, String)],
    _app: &tauri::AppHandle,
) -> Result<u32, String> {
    // Redirect stdout + stderr to the session log
    let session_log_path = sessions_dir().join(session_id).join("session.log");
    let _ = std::fs::create_dir_all(
        session_log_path
            .parent()
            .unwrap_or_else(|| std::path::Path::new(".")),
    );
    let log_file = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&session_log_path)
        .map_err(|e| {
            format!(
                "Cannot open session log '{}': {}",
                session_log_path.display(),
                e
            )
        })?;
    let log_file2 = log_file
        .try_clone()
        .map_err(|e| format!("Cannot clone session log fd: {}", e))?;

    // Build arg list: subcommand --session <id> [extra...]
    let mut args: Vec<String> = vec![
        subcommand.to_string(),
        "--session".to_string(),
        session_id.to_string(),
    ];
    for a in extra_args {
        args.push(a.to_string());
    }

    // Resolve the sidecar binary path.
    // Search order:
    //   1. <project_root>/frontend/src-tauri/bin/ — dev layout
    //   2. Walk up from current exe looking for bin/<name> — packaged layout
    //   3. Same directory as the current executable — Tauri bundled layout
    let binary_name = format!(
        "determinex-hive-{}{}",
        target_triple(),
        if cfg!(target_os = "windows") {
            ".exe"
        } else {
            ""
        }
    );
    let legacy_binary_name = format!(
        "determinex-hive-{}{}",
        target_triple(),
        if cfg!(target_os = "windows") {
            ".exe"
        } else {
            ""
        }
    );
    let packaged_binary_name = if cfg!(target_os = "windows") {
        "determinex-hive.exe"
    } else {
        "determinex-hive"
    };
    let legacy_packaged_binary_name = if cfg!(target_os = "windows") {
        "determinex-hive.exe"
    } else {
        "determinex-hive"
    };
    let candidate_names = [
        binary_name.as_str(),
        legacy_binary_name.as_str(),
        packaged_binary_name,
        legacy_packaged_binary_name,
    ];

    let sidecar_path = {
        // Dev path: <project_root>/frontend/src-tauri/bin/
        let dev_bin_dir = project_root()
            .join("frontend")
            .join("src-tauri")
            .join("bin");
        if let Some(dev_path) = candidate_names
            .iter()
            .map(|name| dev_bin_dir.join(name))
            .find(|path| path.exists())
        {
            dev_path
        } else {
            // Production path: walk up from exe to find bin/
            let mut found = None;
            if let Ok(exe) = std::env::current_exe() {
                let mut p = exe.parent().map(|x| x.to_path_buf()).unwrap_or_default();
                for _ in 0..6 {
                    for name in candidate_names {
                        let candidate = p.join("bin").join(name);
                        if candidate.exists() {
                            found = Some(candidate);
                            break;
                        }
                        // Also check same dir as exe (Tauri bundles sidecars next to the exe)
                        let beside_exe = p.join(name);
                        if beside_exe.exists() {
                            found = Some(beside_exe);
                            break;
                        }
                    }
                    if found.is_some() {
                        break;
                    }
                    match p.parent() {
                        Some(pp) => p = pp.to_path_buf(),
                        None => break,
                    }
                }
            }
            found.ok_or_else(|| {
                format!(
                    "Determinex Hive sidecar not found (looked for '{}'). \
                 Run: python bundler/build_hive_sidecar.py",
                    binary_name
                )
            })?
        }
    };

    log::info!("[IPC] Using sidecar: {}", sidecar_path.display());

    let mut cmd = Command::new(&sidecar_path);
    cmd.hide_console_new_group();

    let policy = _app
        .try_state::<crate::NetworkPolicyState>()
        .and_then(|state| state.0.lock().ok().map(|p| p.clone()))
        .and_then(|policy| crate::normalize_network_policy(&policy).ok())
        .unwrap_or_else(|| crate::DEFAULT_NETWORK_POLICY.to_string());

    cmd.args(&args)
        .current_dir(project_root())
        .env("DETERMINEX_ROOT", project_root())
        .env("DETERMINEX_NETWORK_POLICY", policy)
        .envs(extra_env.iter().map(|(k, v)| (k.to_string(), v.clone())))
        .stdout(Stdio::from(log_file))
        .stderr(Stdio::from(log_file2));

    let child = cmd
        .spawn()
        .map_err(|e| format!("Failed to spawn Determinex Hive {}: {}", subcommand, e))?;

    let pid = child.id();
    let key = format!("{}:{}", subcommand, session_id);
    if let Ok(mut map) = process_map.processes.lock() {
        map.insert(key.clone(), child);
    }

    log::info!(
        "[IPC] Spawned Determinex Hive {} --session {} → pid={} log={}",
        subcommand,
        session_id,
        pid,
        session_log_path.display()
    );

    // Spawn a watcher thread that waits for the child to exit and checks for OOM.
    let app_clone = _app.clone();
    let key_clone = key.clone();
    std::thread::spawn(move || {
        check_child_exit_for_oom(&key_clone, &app_clone.state::<HiveProcessMap>(), &app_clone);
    });

    Ok(pid)
}

/// Return the current Rust target triple at runtime.
pub(crate) fn target_triple() -> &'static str {
    #[cfg(all(target_os = "windows", target_arch = "x86_64"))]
    return "x86_64-pc-windows-msvc";
    #[cfg(all(target_os = "macos", target_arch = "aarch64"))]
    return "aarch64-apple-darwin";
    #[cfg(all(target_os = "macos", target_arch = "x86_64"))]
    return "x86_64-apple-darwin";
    #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
    return "x86_64-unknown-linux-gnu";
    #[cfg(all(target_os = "linux", target_arch = "aarch64"))]
    return "aarch64-unknown-linux-gnu";
    #[allow(unreachable_code)]
    "unknown-unknown-unknown"
}

/// Wait for a tracked child process to exit and check for OOM.
/// Emits a `hive-oom` Tauri event if the exit code indicates OOM kill.
pub(crate) fn check_child_exit_for_oom(key: &str, process_map: &HiveProcessMap, app: &AppHandle) {
    if let Ok(mut map) = process_map.processes.lock() {
        if let Some(mut child) = map.remove(key) {
            match child.wait() {
                Ok(status) => {
                    if let Some(code) = status.code() {
                        if is_oom_exit(code) {
                            log::error!(
                                "[IPC] #oom_hook: Process '{}' killed by OOM (exit code {}). \
                                 The host ran out of memory — reduce model size or close other apps.",
                                key, code
                            );
                            let _ = app.emit(
                                "hive-oom",
                                serde_json::json!({
                                    "process": key,
                                    "exit_code": code,
                                    "message": format!(
                                        "Process '{}' was killed by the OS (exit code {}). \
                                         This usually means the system ran out of memory. \
                                         Try reducing model size (num_gpu_layers) or closing \
                                         other applications.",
                                        key, code
                                    ),
                                }),
                            );
                        } else if !status.success() {
                            log::warn!("[IPC] Process '{}' exited with code {}", key, code);
                        }
                    }
                }
                Err(e) => {
                    log::warn!("[IPC] Failed to wait on process '{}': {}", key, e);
                }
            }
        }
    }
}
