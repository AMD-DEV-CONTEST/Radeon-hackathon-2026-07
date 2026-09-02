/// sidecar.rs — Tauri IPC bridge for the Determinex embedded Python sidecar
///
/// The sidecar is an embedded Python runtime (python-3.11-embed-amd64) that
/// runs determinex_sidecar.py as a child process. Communication happens via
/// NDJSON (newline-delimited JSON) over stdin/stdout.
///
/// This module provides:
///   - `SidecarManager`: spawns and manages the sidecar subprocess lifetime
///   - `#[tauri::command] spawn_sidecar()`: IPC command for the frontend
///   - `#[tauri::command] sidecar_infer()`: stream completions from the sidecar
///   - `#[tauri::command] sidecar_load()`: load a GGUF model into the sidecar
///   - `#[tauri::command] sidecar_status()`: health check
///
/// NDJSON Protocol (mirrors bundler/determinex_sidecar.py):
///   Request  (stdin):  {"id": "...", "action": "...", ...params}
///   Response (stdout): {"id": "...", "ok": true, "data": {...}}
///   Token    (stdout): {"id": "...", "token": "...", "done": bool}
///
/// Zero-Dependency Guarantee:
///   The sidecar runs from bundler/sidecar/python/python.exe — the embedded
///   Python distribution set up by bundler/setup_sidecar.py. The user does
///   NOT need Python installed. The Tauri installer ships the sidecar/ dir.
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::io::{BufRead, BufReader, Write};
use std::path::PathBuf;
use std::process::{Child, ChildStdin, ChildStdout, Command, Stdio};
use crate::win_process::HideConsoleExt;
use std::sync::{Arc, Mutex};
use std::time::Duration;
use tauri::{AppHandle, Manager};

// ─────────────────────────────────────────────────────────────────────────────
// TYPES
// ─────────────────────────────────────────────────────────────────────────────

/// Result of a single sidecar request (non-streaming).
#[derive(Debug, Serialize, Deserialize)]
pub struct SidecarResponse {
    pub ok: bool,
    pub data: Option<Value>,
    pub error: Option<String>,
}

/// Streamed completion token (used when token-by-token streaming is wired up).
#[allow(dead_code)]
#[derive(Debug, Serialize, Clone)]
pub struct CompletionToken {
    pub token: String,
    pub done: bool,
    pub total_tokens: Option<u32>,
}

/// State shared between Tauri commands — the live sidecar subprocess.
pub struct SidecarManager {
    child: Option<Child>,
    stdin: Option<ChildStdin>,
    stdout: Option<BufReader<ChildStdout>>,
    req_id: u64,
}

impl SidecarManager {
    pub fn new() -> Self {
        Self {
            child: None,
            stdin: None,
            stdout: None,
            req_id: 0,
        }
    }

    /// Resolve the embedded python.exe path relative to the Tauri app's
    /// resource directory. Falls back to the development path.
    pub fn sidecar_python_exe(app: &AppHandle) -> PathBuf {
        // Production: sidecar is bundled adjacent to the .exe
        if let Ok(res_dir) = app.path().resource_dir() {
            let prod = res_dir.join("bundler/sidecar/python/python.exe");
            if prod.exists() {
                return prod;
            }
        }
        // Development: relative to workspace root
        PathBuf::from("bundler/sidecar/python/python.exe")
    }

    pub fn sidecar_script(app: &AppHandle) -> PathBuf {
        if let Ok(res_dir) = app.path().resource_dir() {
            let prod = res_dir.join("bundler/sidecar/determinex_sidecar.py");
            if prod.exists() {
                return prod;
            }
        }
        PathBuf::from("bundler/sidecar/determinex_sidecar.py")
    }

    /// Spawn the sidecar process and wait for the "ready" signal on stdout.
    pub fn spawn(&mut self, app: &AppHandle) -> Result<(), String> {
        if self.child.is_some() {
            return Ok(()); // Already running
        }

        let python_exe = Self::sidecar_python_exe(app);
        let script = Self::sidecar_script(app);

        if !python_exe.exists() {
            return Err(format!(
                "Sidecar not found at {:?}. \
                 Run: python bundler/setup_sidecar.py",
                python_exe
            ));
        }

        log::info!("[Sidecar] Spawning: {:?} {:?}", python_exe, script);

        let mut child = Command::new(&python_exe).hide_console()
            .arg(&script)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit()) // Sidecar logs → Tauri console
            .spawn()
            .map_err(|e| format!("Failed to spawn sidecar: {e}"))?;

        let stdin = child.stdin.take().ok_or("Could not open sidecar stdin")?;
        let stdout = BufReader::new(child.stdout.take().ok_or("Could not open sidecar stdout")?);

        self.stdin = Some(stdin);
        self.stdout = Some(stdout);
        self.child = Some(child);

        // Wait for the {"event": "ready"} line from the sidecar
        self.wait_for_ready(Duration::from_secs(30))?;

        log::info!("[Sidecar] Ready.");
        Ok(())
    }

    fn wait_for_ready(&mut self, timeout: Duration) -> Result<(), String> {
        let start = std::time::Instant::now();
        loop {
            if start.elapsed() > timeout {
                return Err("Sidecar did not emit 'ready' within timeout".to_string());
            }
            let line = self.read_line()?;
            let val: Value = serde_json::from_str(&line)
                .map_err(|e| format!("Sidecar sent invalid JSON during startup: {e}"))?;
            if val.get("event").and_then(|v| v.as_str()) == Some("ready") {
                return Ok(());
            }
        }
    }

    fn next_id(&mut self) -> String {
        self.req_id += 1;
        self.req_id.to_string()
    }

    fn send_request(&mut self, mut req: Value) -> Result<String, String> {
        let id = self.next_id();
        req["id"] = json!(id.clone());
        let line =
            serde_json::to_string(&req).map_err(|e| format!("Serialization error: {e}"))? + "\n";

        self.stdin
            .as_mut()
            .ok_or("Sidecar stdin not available")?
            .write_all(line.as_bytes())
            .map_err(|e| format!("Failed to write to sidecar stdin: {e}"))?;

        Ok(id)
    }

    fn read_line(&mut self) -> Result<String, String> {
        let reader = self.stdout.as_mut().ok_or("Sidecar stdout not available")?;

        let mut line = String::new();
        reader
            .read_line(&mut line)
            .map_err(|e| format!("Failed to read from sidecar stdout: {e}"))?;

        Ok(line.trim_end().to_string())
    }

    /// Send a single request and read the single response line.
    pub fn request(&mut self, action: &str, params: Value) -> Result<SidecarResponse, String> {
        let mut req = params;
        req["action"] = json!(action);
        let _id = self.send_request(req)?;

        let line = self.read_line()?;
        let val: Value =
            serde_json::from_str(&line).map_err(|e| format!("Bad JSON response: {e}"))?;

        Ok(SidecarResponse {
            ok: val["ok"].as_bool().unwrap_or(false),
            data: val.get("data").cloned(),
            error: val.get("error").and_then(|v| v.as_str()).map(String::from),
        })
    }

    /// Run inference, collecting streamed tokens into a complete String.
    /// For token-by-token streaming, use `emit_infer_stream` with Tauri events.
    pub fn infer_sync(
        &mut self,
        prompt: &str,
        max_tokens: u32,
        temperature: f32,
        stop: Vec<String>,
    ) -> Result<String, String> {
        let req = json!({
            "action":      "infer",
            "prompt":      prompt,
            "max_tokens":  max_tokens,
            "temperature": temperature,
            "stop":        stop,
        });
        let _id = self.send_request(req)?;

        let mut result = String::new();
        loop {
            let line = self.read_line()?;
            let val: Value =
                serde_json::from_str(&line).map_err(|e| format!("Bad token JSON: {e}"))?;

            if val["ok"] == false {
                return Err(val["error"].as_str().unwrap_or("unknown error").to_string());
            }

            let token = val["token"].as_str().unwrap_or("").to_string();
            result.push_str(&token);

            if val["done"].as_bool().unwrap_or(false) {
                break;
            }
        }

        Ok(result)
    }

    pub fn kill(&mut self) {
        if let Some(ref mut child) = self.child {
            let _ = child.kill();
        }
        self.child = None;
        self.stdin = None;
        self.stdout = None;
    }

    pub fn is_alive(&mut self) -> bool {
        match self.child {
            None => false,
            Some(ref mut c) => matches!(c.try_wait(), Ok(None)),
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// TAURI MANAGED STATE
// ─────────────────────────────────────────────────────────────────────────────

pub type SharedSidecar = Arc<Mutex<SidecarManager>>;

pub fn new_shared_sidecar() -> SharedSidecar {
    Arc::new(Mutex::new(SidecarManager::new()))
}

// ─────────────────────────────────────────────────────────────────────────────
// TAURI IPC COMMANDS
// ─────────────────────────────────────────────────────────────────────────────

/// Spawn the sidecar subprocess. Safe to call multiple times (idempotent).
/// Call this from the frontend on app startup after setup_sidecar completes.
#[tauri::command]
pub async fn spawn_sidecar(
    sidecar: tauri::State<'_, SharedSidecar>,
    app: AppHandle,
) -> Result<String, String> {
    let mut mgr = sidecar.lock().map_err(|e| format!("Lock error: {e}"))?;
    mgr.spawn(&app)?;
    Ok("Sidecar spawned and ready.".to_string())
}

/// Load a GGUF model file into the sidecar.
#[tauri::command]
pub async fn sidecar_load(
    sidecar: tauri::State<'_, SharedSidecar>,
    model_path: String,
    n_gpu_layers: i32,
    n_ctx: u32,
) -> Result<SidecarResponse, String> {
    let mut mgr = sidecar.lock().map_err(|e| format!("Lock error: {e}"))?;
    mgr.request(
        "load",
        json!({
            "model_path":   model_path,
            "n_gpu_layers": n_gpu_layers,
            "n_ctx":        n_ctx,
        }),
    )
}

/// Run inference in the sidecar. Returns the full completion as a single string.
/// For streaming, use the Tauri event system (emit tokens to the frontend).
#[tauri::command]
pub async fn sidecar_infer(
    sidecar: tauri::State<'_, SharedSidecar>,
    prompt: String,
    max_tokens: Option<u32>,
    temperature: Option<f32>,
    stop: Option<Vec<String>>,
) -> Result<String, String> {
    let mut mgr = sidecar.lock().map_err(|e| format!("Lock error: {e}"))?;
    mgr.infer_sync(
        &prompt,
        max_tokens.unwrap_or(512),
        temperature.unwrap_or(0.1),
        stop.unwrap_or_default(),
    )
}

/// Query sidecar status (model loaded, n_ctx, etc.)
#[tauri::command]
pub async fn sidecar_status(
    sidecar: tauri::State<'_, SharedSidecar>,
) -> Result<SidecarResponse, String> {
    let mut mgr = sidecar.lock().map_err(|e| format!("Lock error: {e}"))?;
    if !mgr.is_alive() {
        return Ok(SidecarResponse {
            ok: false,
            data: None,
            error: Some("Sidecar process is not running".to_string()),
        });
    }
    mgr.request("status", json!({}))
}

/// Gracefully shut down the sidecar process.
#[tauri::command]
pub async fn shutdown_sidecar(sidecar: tauri::State<'_, SharedSidecar>) -> Result<String, String> {
    let mut mgr = sidecar.lock().map_err(|e| format!("Lock error: {e}"))?;
    if mgr.is_alive() {
        let _ = mgr.request("quit", json!({}));
    }
    mgr.kill();
    Ok("Sidecar shut down.".to_string())
}
