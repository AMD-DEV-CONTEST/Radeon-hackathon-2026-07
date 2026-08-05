use serde::Serialize;
/// ipc_benchmark.rs — Tauri IPC for long-running SWE-bench / benchmark runs.
///
/// Two commands:
///
///   launch_benchmark_run  — spawns `python scripts/<script> <args>` in the
///                           background, streams stdout/stderr via Tauri events,
///                           emits `complete` with resolved count when done.
///
///   stop_benchmark_run    — kills the Python process by stored PID.
///
/// Event protocol (same shape as ipc_hive stream_session_log):
///   { "line": "...", "complete": false }   — one log line
///   { "line": null, "complete": true,
///     "resolved": N, "predictions_path": "..." } — run finished
///
/// The frontend subscribes once to the event name returned by launch_benchmark_run
/// and drives the BenchmarkRunner state machine from the incoming events.
use crate::ipc_envelope::Envelope;
use std::collections::HashMap;
use std::io::{BufRead, BufReader};
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::sync::{Arc, Mutex};

use tauri::{AppHandle, Emitter, State};

use crate::ipc_hive::{project_root, resolve_python_exe};
use crate::win_process::{HideConsoleExt, HideConsoleNewGroupExt};

// ── Process registry ──────────────────────────────────────────────────────────

pub struct BenchmarkProcessMap(Arc<Mutex<HashMap<String, u32>>>);

impl BenchmarkProcessMap {
    pub fn new() -> Self {
        Self(Arc::new(Mutex::new(HashMap::new())))
    }
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/// Count non-empty lines in a predictions.jsonl file.
fn count_predictions(path: &PathBuf) -> u32 {
    std::fs::read_to_string(path)
        .map(|s| s.lines().filter(|l| !l.trim().is_empty()).count() as u32)
        .unwrap_or(0)
}

/// Find the most recently modified predictions.jsonl under logs/swebench/.
/// Returns (path, line_count) or None.
fn find_latest_predictions(root: &PathBuf) -> Option<(PathBuf, u32)> {
    let swebench_dir = root.join("logs").join("swebench");
    std::fs::read_dir(&swebench_dir)
        .ok()?
        .filter_map(|entry| {
            let entry = entry.ok()?;
            let p = entry.path().join("predictions.jsonl");
            if p.exists() {
                let meta = std::fs::metadata(&p).ok()?;
                Some((p, meta.modified().ok()?))
            } else {
                None
            }
        })
        .max_by_key(|(_, mtime)| *mtime)
        .map(|(p, _)| {
            let count = count_predictions(&p);
            (p, count)
        })
}

// ── Commands ──────────────────────────────────────────────────────────────────

/// Launch a benchmark run as a background Python process.
///
/// Returns immediately with an event name. The frontend subscribes to that
/// event to receive log lines and the final `complete` payload.
///
/// `script_name` is relative to `scripts/` (e.g. "determinex_swebench_run.py").
/// `args` are forwarded verbatim to the Python script.
#[tauri::command]
pub async fn launch_benchmark_run(
    benchmark_id: String,
    script_name: String,
    args: Vec<String>,
    process_map: State<'_, BenchmarkProcessMap>,
    app: AppHandle,
) -> Result<Envelope<BenchmarkLaunched>, String> {
    let ts = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    let run_key = format!("{}-{}", benchmark_id, ts);
    let event_name = format!("benchmark-log-{}", run_key);

    // Create a log file for this run.
    let log_dir = project_root().join("logs").join("benchmark_runs");
    std::fs::create_dir_all(&log_dir)
        .map_err(|e| format!("Cannot create benchmark log dir: {}", e))?;
    let log_path = log_dir.join(format!("{}.log", run_key));

    let log_file = std::fs::OpenOptions::new()
        .create(true)
        .write(true)
        .truncate(true)
        .open(&log_path)
        .map_err(|e| format!("Cannot create benchmark log: {}", e))?;
    let log_file2 = log_file
        .try_clone()
        .map_err(|e| format!("Cannot clone log fd: {}", e))?;

    // Resolve Python and script path.
    let python = resolve_python_exe()?;
    let script_path = project_root().join("scripts").join(&script_name);
    if !script_path.exists() {
        return Err(format!("Script not found: {}", script_path.display()));
    }

    let mut cmd = Command::new(&python);
    cmd.hide_console_new_group();
    cmd.arg(&script_path)
        .args(&args)
        .current_dir(project_root())
        .env("DETERMINEX_ROOT", project_root())
        .stdout(Stdio::from(log_file))
        .stderr(Stdio::from(log_file2));

    let child = cmd
        .spawn()
        .map_err(|e| format!("Failed to spawn benchmark Python: {}", e))?;
    let pid = child.id();

    log::info!(
        "[BENCH] Launched {} (PID {}), event={}",
        benchmark_id,
        pid,
        event_name
    );

    // Store PID for stop support.
    {
        let mut map = process_map
            .0
            .lock()
            .map_err(|e| format!("BenchmarkProcessMap mutex poisoned: {}", e))?;
        map.insert(benchmark_id.clone(), pid);
    }

    // Capture a snapshot of when we started (used to identify the "latest" predictions
    // created after this point when the run finishes).
    let run_start = std::time::SystemTime::now();
    let root_for_thread = project_root();
    let log_path_for_thread = log_path.clone();
    let event_for_thread = event_name.clone();

    // Background thread: tail the log file and emit events.
    std::thread::spawn(move || {
        // Wait up to 20 seconds for the first log write.
        let deadline = std::time::Instant::now() + std::time::Duration::from_secs(20);
        loop {
            if log_path_for_thread.exists()
                && std::fs::metadata(&log_path_for_thread)
                    .map(|m| m.len())
                    .unwrap_or(0)
                    > 0
            {
                break;
            }
            if std::time::Instant::now() > deadline {
                break;
            }
            std::thread::sleep(std::time::Duration::from_millis(200));
        }

        let file = match std::fs::File::open(&log_path_for_thread) {
            Ok(f) => f,
            Err(e) => {
                log::warn!(
                    "[BENCH] Cannot open benchmark log {:?}: {}",
                    log_path_for_thread,
                    e
                );
                let _ = app.emit(
                    &event_for_thread,
                    serde_json::json!({ "line": null, "complete": true, "resolved": 0 }),
                );
                return;
            }
        };

        let mut reader = BufReader::new(file);
        let mut line_buf = String::new();
        let mut idle_polls: u32 = 0;
        // 5-minute silence cap (3000 × 100ms). For benchmarks that take 30-90 min,
        // once all workers finish and the Python process exits, no new lines will be
        // written. We'll detect completion within 5 minutes of the last log line.
        const MAX_IDLE_POLLS: u32 = 3_000;
        let mut predictions_path: Option<PathBuf> = None;

        loop {
            line_buf.clear();
            match reader.read_line(&mut line_buf) {
                Ok(0) => {
                    idle_polls += 1;
                    if idle_polls > MAX_IDLE_POLLS {
                        log::info!(
                            "[BENCH] {} silent for 5 min — marking complete",
                            benchmark_id
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
                    if text.is_empty() {
                        continue;
                    }
                    // Parse "Predictions written → path (N instances)" to track the file.
                    if text.contains("Predictions written") {
                        if let Some(arrow_pos) = text.find('→') {
                            let rest = text[arrow_pos + 3..].trim();
                            let path_end = rest.find("  (").unwrap_or(rest.len());
                            let path_str = rest[..path_end].trim();
                            let p = if std::path::Path::new(path_str).is_absolute() {
                                PathBuf::from(path_str)
                            } else {
                                root_for_thread.join(path_str)
                            };
                            if p.exists() {
                                predictions_path = Some(p);
                            }
                        }
                    }
                    let _ = app.emit(&event_for_thread, serde_json::json!({ "line": text }));
                }
                Err(e) => {
                    log::warn!("[BENCH] Error reading benchmark log: {}", e);
                    break;
                }
            }
        }

        // Determine resolved count.
        let (final_pred_path, resolved) = match predictions_path {
            Some(ref p) if p.exists() => {
                let count = count_predictions(p);
                (p.to_string_lossy().to_string(), count)
            }
            _ => {
                // Fall back: find the most recently modified predictions.jsonl created
                // after this run started.
                match find_latest_predictions(&root_for_thread) {
                    Some((p, count)) => {
                        // Only use it if it was written after we started.
                        let is_recent = std::fs::metadata(&p)
                            .and_then(|m| m.modified())
                            .map(|mtime| mtime >= run_start)
                            .unwrap_or(false);
                        if is_recent {
                            (p.to_string_lossy().to_string(), count)
                        } else {
                            (String::new(), 0)
                        }
                    }
                    None => (String::new(), 0),
                }
            }
        };

        let _ = app.emit(
            &event_for_thread,
            serde_json::json!({
                "line": null,
                "complete": true,
                "resolved": resolved,
                "predictions_path": final_pred_path,
            }),
        );
    });

    Ok(Envelope::ok(BenchmarkLaunched {
        run_key,
        pid,
        event: event_name,
        log_path: log_path.to_string_lossy().to_string(),
    }))
}

/// Typed benchmark responses. These were three inline literals that had already
/// diverged: `stop_benchmark_run` puts `pid` at the TOP level while
/// `launch_benchmark_run` puts it inside `data`, so a caller could not read "the
/// pid" the same way from both.
#[derive(Serialize)]
pub struct BenchmarkLaunched {
    pub run_key: String,
    pub pid: u32,
    pub event: String,
    pub log_path: String,
}

/// `stop_benchmark_run`'s wire shape, preserved exactly: `pid` sits alongside
/// `ok`, not inside `data`. Changing that would be a silent breaking change for
/// whatever reads it.
#[derive(Serialize)]
pub struct BenchmarkStopped {
    pub ok: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub pid: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

/// Kill a running benchmark process by benchmark_id.
#[tauri::command]
pub async fn stop_benchmark_run(
    benchmark_id: String,
    process_map: State<'_, BenchmarkProcessMap>,
) -> Result<BenchmarkStopped, String> {
    let pid = {
        let mut map = process_map
            .0
            .lock()
            .map_err(|e| format!("BenchmarkProcessMap mutex poisoned: {}", e))?;
        map.remove(&benchmark_id)
    };

    if let Some(pid) = pid {
        log::info!("[BENCH] Stopping benchmark {} (PID {})", benchmark_id, pid);
        kill_process(pid);
        Ok(BenchmarkStopped { ok: true, pid: Some(pid), error: None })
    } else {
        Ok(BenchmarkStopped {
            ok: false,
            pid: None,
            error: Some("No running process found".to_string()),
        })
    }
}

/// Read the ProgramBench cockpit snapshot through the Python monitor contract.
///
/// This intentionally shells through `scripts/programbench_live_monitor.py`
/// instead of duplicating its SQLite/failure-family logic in Rust. The script's
/// JSON output is the stable Benchmark Lab contract; Rust only transports it.
#[tauri::command]
/// Returns the ProgramBench snapshot as the analysis script produced it.
///
/// Untyped on purpose: `api.ts`'s `ProgramBenchSnapshot` documents the fields the
/// UI reads, but the script emits a superset that changes as the campaign adds
/// metrics. A struct here would drop the new ones on the floor, silently, which is
/// exactly the failure this typing pass exists to prevent -- so the honest shape
/// is the script's own.
pub async fn get_programbench_snapshot(
    run_id: Option<String>,
    expected_total: Option<u32>,
    advise: Option<bool>,
) -> Result<serde_json::Value, String> {
    let python = resolve_python_exe()?;
    let root = project_root();
    let script = root.join("scripts").join("programbench_live_monitor.py");
    if !script.exists() {
        return Err(format!(
            "ProgramBench monitor not found: {}",
            script.display()
        ));
    }

    let mut cmd = Command::new(&python);
    cmd.hide_console();
    cmd.arg(&script)
        .arg("--json")
        .arg("--run-id")
        .arg(run_id.unwrap_or_else(|| "mass_run_v2_base".to_string()))
        .arg("--expected-total")
        .arg(expected_total.unwrap_or(115).to_string())
        .current_dir(&root)
        .env("DETERMINEX_ROOT", &root);

    if advise.unwrap_or(true) {
        cmd.arg("--advise");
    }

    let out = cmd
        .output()
        .map_err(|e| format!("Failed to run ProgramBench monitor: {}", e))?;

    if !out.status.success() {
        let stderr = String::from_utf8_lossy(&out.stderr);
        return Err(format!(
            "ProgramBench monitor exited with {}: {}",
            out.status,
            stderr.trim()
        ));
    }

    serde_json::from_slice::<serde_json::Value>(&out.stdout)
        .map_err(|e| format!("ProgramBench monitor returned invalid JSON: {}", e))
}

fn kill_process(pid: u32) {
    #[cfg(target_os = "windows")]
    {
        let _ = Command::new("taskkill")
            .hide_console()
            .args(["/F", "/PID", &pid.to_string()])
            .output();
    }
    #[cfg(not(target_os = "windows"))]
    {
        let _ = Command::new("kill").hide_console().args(["-9", &pid.to_string()]).output();
    }
}
