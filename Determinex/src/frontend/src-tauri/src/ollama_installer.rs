use reqwest::Client;
use serde::Serialize;
/// ollama_installer.rs — Cross-platform Ollama auto-installer
///
/// Ensures Ollama is installed and running before Determinex can proceed.
/// The user never sees a terminal. The flow:
///
///   1. Check if `ollama` binary is on PATH → if yes, ensure it's serving
///   2. If not on PATH, download the platform installer:
///        - Windows: OllamaSetup.exe (silent install via /VERYSILENT)
///        - macOS:   Ollama-darwin.zip (extract to /usr/local/bin)
///        - Linux:   curl install script (piped to sh)
///   3. Start the Ollama service if not already running
///   4. Wait for http://localhost:11434 to respond (30-second timeout)
///
/// All progress is reported via the returned status enum so the frontend
/// Setup Wizard can display appropriate messaging.
use std::path::PathBuf;
use std::time::Duration;
use tokio::process::Command;
use crate::win_process::HideConsoleExt;

// ─────────────────────────────────────────────────────────────────────────────
// TYPES
// ─────────────────────────────────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize)]
pub enum OllamaSetupStatus {
    /// Ollama was already installed and is serving.
    AlreadyRunning,
    /// Ollama was installed but not serving — we started it.
    StartedExisting,
    /// Ollama was not installed — we installed and started it.
    FreshInstall,
}

#[derive(Debug, Clone, Serialize)]
pub struct OllamaSetupResult {
    pub status: OllamaSetupStatus,
    pub version: String,
}

// ─────────────────────────────────────────────────────────────────────────────
// CONSTANTS
// ─────────────────────────────────────────────────────────────────────────────

const OLLAMA_API_URL: &str = "http://localhost:11434/api/tags";
const OLLAMA_VERSION_URL: &str = "http://localhost:11434/api/version";
const API_TIMEOUT_SECS: u64 = 5;
const STARTUP_WAIT_SECS: u64 = 45;
const POLL_INTERVAL_MS: u64 = 500;

#[cfg(target_os = "windows")]
const OLLAMA_DOWNLOAD_URL: &str = "https://ollama.com/download/OllamaSetup.exe";

#[cfg(target_os = "macos")]
const OLLAMA_DOWNLOAD_URL: &str = "https://ollama.com/download/Ollama-darwin.zip";

#[cfg(target_os = "linux")]
const OLLAMA_INSTALL_SCRIPT: &str = "https://ollama.com/install.sh";

// ─────────────────────────────────────────────────────────────────────────────
// DETECTION
// ─────────────────────────────────────────────────────────────────────────────

/// Check if the Ollama API is reachable on localhost.
async fn is_ollama_serving() -> bool {
    let client = match Client::builder()
        .timeout(Duration::from_secs(API_TIMEOUT_SECS))
        .pool_max_idle_per_host(0)
        .build()
    {
        Ok(c) => c,
        Err(_) => return false,
    };

    matches!(client.get(OLLAMA_API_URL).send().await, Ok(r) if r.status().is_success())
}

/// Get the Ollama version string from the API.
async fn get_ollama_version() -> String {
    let client = match Client::builder()
        .timeout(Duration::from_secs(API_TIMEOUT_SECS))
        .pool_max_idle_per_host(0)
        .build()
    {
        Ok(c) => c,
        Err(_) => return "unknown".to_string(),
    };

    match client.get(OLLAMA_VERSION_URL).send().await {
        Ok(resp) => {
            if let Ok(body) = resp.text().await {
                if let Ok(parsed) = serde_json::from_str::<serde_json::Value>(&body) {
                    if let Some(v) = parsed["version"].as_str() {
                        return v.to_string();
                    }
                }
            }
            "unknown".to_string()
        }
        Err(_) => "unknown".to_string(),
    }
}

/// Check if `ollama` binary exists on PATH.
async fn is_ollama_on_path() -> bool {
    #[cfg(target_os = "windows")]
    let check = Command::new("where").hide_console().arg("ollama").output().await;

    #[cfg(not(target_os = "windows"))]
    let check = Command::new("which").hide_console().arg("ollama").output().await;

    matches!(check, Ok(output) if output.status.success())
}

// ─────────────────────────────────────────────────────────────────────────────
// INSTALLATION
// ─────────────────────────────────────────────────────────────────────────────

/// Download a file from `url` to `dest`, returning the path on success.
async fn download_file(url: &str, dest: &PathBuf) -> Result<(), String> {
    log::info!("[OLLAMA-INSTALLER] Downloading {} → {:?}", url, dest);

    let client = Client::builder()
        .timeout(Duration::from_secs(300)) // 5 min timeout for large downloads
        .build()
        .map_err(|e| format!("Failed to create HTTP client: {}", e))?;

    let response = client
        .get(url)
        .send()
        .await
        .map_err(|e| format!("Download request failed: {}", e))?;

    if !response.status().is_success() {
        return Err(format!(
            "Download failed with HTTP {}: {}",
            response.status(),
            url
        ));
    }

    let bytes = response
        .bytes()
        .await
        .map_err(|e| format!("Failed to read download body: {}", e))?;

    // Ensure parent directory exists
    if let Some(parent) = dest.parent() {
        std::fs::create_dir_all(parent)
            .map_err(|e| format!("Failed to create directory {:?}: {}", parent, e))?;
    }

    std::fs::write(dest, &bytes).map_err(|e| format!("Failed to write {:?}: {}", dest, e))?;

    log::info!(
        "[OLLAMA-INSTALLER] Downloaded {} bytes to {:?}",
        bytes.len(),
        dest
    );
    Ok(())
}

/// Install Ollama on Windows via silent installer.
#[cfg(target_os = "windows")]
async fn install_ollama() -> Result<(), String> {
    let temp_dir = std::env::temp_dir();
    let installer_path = temp_dir.join("OllamaSetup.exe");

    download_file(OLLAMA_DOWNLOAD_URL, &installer_path).await?;

    log::info!("[OLLAMA-INSTALLER] Running silent install...");

    let output = Command::new(&installer_path).hide_console()
        .args(["/VERYSILENT", "/NORESTART", "/SUPPRESSMSGBOXES"])
        .output()
        .await
        .map_err(|e| format!("Failed to run OllamaSetup.exe: {}", e))?;

    // Clean up installer
    let _ = std::fs::remove_file(&installer_path);

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(format!(
            "Ollama installer exited with {:?}. stderr: {}",
            output.status.code(),
            stderr.trim()
        ));
    }

    log::info!("[OLLAMA-INSTALLER] Silent install completed successfully.");
    Ok(())
}

/// Install Ollama on macOS via zip download.
#[cfg(target_os = "macos")]
async fn install_ollama() -> Result<(), String> {
    let temp_dir = std::env::temp_dir();
    let zip_path = temp_dir.join("Ollama-darwin.zip");

    download_file(OLLAMA_DOWNLOAD_URL, &zip_path).await?;

    log::info!("[OLLAMA-INSTALLER] Extracting Ollama for macOS...");

    // Extract to /Applications (standard macOS location)
    let output = Command::new("unzip").hide_console()
        .args(["-o", zip_path.to_str().unwrap_or(""), "-d", "/Applications"])
        .output()
        .await
        .map_err(|e| format!("Failed to unzip Ollama: {}", e))?;

    let _ = std::fs::remove_file(&zip_path);

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(format!("Ollama extraction failed: {}", stderr.trim()));
    }

    // Symlink the CLI binary
    let _ = Command::new("ln").hide_console()
        .args([
            "-sf",
            "/Applications/Ollama.app/Contents/Resources/ollama",
            "/usr/local/bin/ollama",
        ])
        .output()
        .await;

    log::info!("[OLLAMA-INSTALLER] macOS install completed.");
    Ok(())
}

/// Install Ollama on Linux via the official install script.
#[cfg(target_os = "linux")]
async fn install_ollama() -> Result<(), String> {
    log::info!("[OLLAMA-INSTALLER] Running Linux install script...");

    let output = Command::new("sh").hide_console()
        .args(["-c", &format!("curl -fsSL {} | sh", OLLAMA_INSTALL_SCRIPT)])
        .output()
        .await
        .map_err(|e| format!("Failed to run install script: {}", e))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(format!("Linux install script failed: {}", stderr.trim()));
    }

    log::info!("[OLLAMA-INSTALLER] Linux install completed.");
    Ok(())
}

// ─────────────────────────────────────────────────────────────────────────────
// SERVICE START
// ─────────────────────────────────────────────────────────────────────────────

/// Start the Ollama service in the background.
async fn start_ollama_service() -> Result<(), String> {
    log::info!("[OLLAMA-INSTALLER] Starting Ollama service...");

    #[cfg(target_os = "windows")]
    {
        // On Windows, Ollama installs as a user service and auto-starts.
        // But if the user just installed, the service might not be running yet.
        // Try to find and launch the Ollama app.
        let local_appdata = std::env::var("LOCALAPPDATA").unwrap_or_default();
        let ollama_app = PathBuf::from(&local_appdata)
            .join("Programs")
            .join("Ollama")
            .join("ollama app.exe");

        if ollama_app.exists() {
            // Launch the Ollama app (which starts the server)
            let _ = Command::new(&ollama_app).hide_console().spawn();
        } else {
            // Fallback: try `ollama serve` in the background
            let _ = Command::new("ollama").hide_console().arg("serve").spawn();
        }
    }

    #[cfg(target_os = "macos")]
    {
        // On macOS, launch the app which starts the server
        let _ = Command::new("open").hide_console().args(["-a", "Ollama"]).output().await;
    }

    #[cfg(target_os = "linux")]
    {
        // On Linux, start via systemd or direct
        let systemd = Command::new("systemctl").hide_console()
            .args(["start", "ollama"])
            .output()
            .await;

        if !matches!(systemd, Ok(ref o) if o.status.success()) {
            // Fallback: direct launch
            let _ = Command::new("ollama").hide_console().arg("serve").spawn();
        }
    }

    Ok(())
}

/// Poll the Ollama API until it responds or we time out.
async fn wait_for_ollama_api() -> Result<(), String> {
    log::info!("[OLLAMA-INSTALLER] Waiting for Ollama API to become reachable...");

    let deadline = std::time::Instant::now() + Duration::from_secs(STARTUP_WAIT_SECS);

    while std::time::Instant::now() < deadline {
        if is_ollama_serving().await {
            log::info!("[OLLAMA-INSTALLER] Ollama API is reachable.");
            return Ok(());
        }
        tokio::time::sleep(Duration::from_millis(POLL_INTERVAL_MS)).await;
    }

    Err(format!(
        "Ollama API did not become reachable within {} seconds. \
         Please start Ollama manually and retry.",
        STARTUP_WAIT_SECS
    ))
}

// ─────────────────────────────────────────────────────────────────────────────
// PUBLIC API
// ─────────────────────────────────────────────────────────────────────────────

/// Master entry point: ensure Ollama is installed, running, and reachable.
///
/// This is the single function the Setup Wizard calls. It handles every
/// possible state transparently:
///   - Already running → instant return
///   - Installed but not running → start and wait
///   - Not installed → download, install, start, wait
pub async fn ensure_ollama() -> Result<OllamaSetupResult, String> {
    // ── Fast path: already serving ────────────────────────────────────────
    if is_ollama_serving().await {
        let version = get_ollama_version().await;
        log::info!("[OLLAMA-INSTALLER] Already running (v{}).", version);
        return Ok(OllamaSetupResult {
            status: OllamaSetupStatus::AlreadyRunning,
            version,
        });
    }

    // ── Medium path: installed but not serving ────────────────────────────
    if is_ollama_on_path().await {
        log::info!("[OLLAMA-INSTALLER] Found on PATH but not serving. Starting...");
        start_ollama_service().await?;
        wait_for_ollama_api().await?;
        let version = get_ollama_version().await;
        return Ok(OllamaSetupResult {
            status: OllamaSetupStatus::StartedExisting,
            version,
        });
    }

    // ── Slow path: full install ──────────────────────────────────────────
    log::info!("[OLLAMA-INSTALLER] Not found. Performing fresh install...");
    install_ollama().await?;

    // After install, the binary should be on PATH (installer adds it)
    // Give the system a moment to register the new PATH entry
    tokio::time::sleep(Duration::from_secs(2)).await;

    start_ollama_service().await?;
    wait_for_ollama_api().await?;

    let version = get_ollama_version().await;
    log::info!(
        "[OLLAMA-INSTALLER] Fresh install completed. Ollama v{} is serving.",
        version
    );

    Ok(OllamaSetupResult {
        status: OllamaSetupStatus::FreshInstall,
        version,
    })
}

/// Tauri IPC command — exposed to the frontend Setup Wizard.
#[tauri::command]
pub async fn ensure_ollama_installed() -> Result<OllamaSetupResult, String> {
    ensure_ollama().await
}
