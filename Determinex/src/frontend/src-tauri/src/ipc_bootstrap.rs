use crate::bootstrap;
use crate::hardware;
use crate::model_puller;
use crate::ollama_installer;
use crate::win_process::HideConsoleExt;
/// ipc_bootstrap.rs — Tauri IPC command for first-run system initialization
///
/// Exposes `initialize_system` as a single async Tauri command that chains
/// through the entire zero-friction setup pipeline:
///
///   0. Check Docker daemon is running (required for compiler sandboxing)
///   1. Ensure Ollama is installed and running (auto-installs if missing)
///   2. Probe available VRAM via the hardware detection chain
///   3. Resolve the hardware tier to a concrete DeterminexConfig
///   4. Pull any missing base models from the Ollama registry
///   5. Build the three Determinex model tags via `ollama create`
///
/// Safe to invoke on subsequent runs — each step is idempotent.
///
/// The frontend Setup Wizard calls this as the master "do everything" command.
/// For granular progress, it can also call the individual IPC commands:
///   - `check_docker_status`    (step 0)
///   - `ensure_ollama_installed` (step 1)
///   - `pull_required_models`   (steps 2-4)
///   - `initialize_system`      (steps 0-5)
use serde::Serialize;
use tokio::process::Command;

#[derive(Debug, Serialize)]
pub struct BootstrapResult {
    pub ollama_status: String,
    pub ollama_version: String,
    pub total_vram_mb: Option<u64>,
    pub vram_budget_mb: u64,
    pub reserved_vram_mb: u64,
    pub hardware_source: String,
    pub hardware_fallback: bool,
    pub tier: String,
    pub models_pulled: Vec<String>,
    pub models_existing: Vec<String>,
    pub models_failed: Vec<String>,
    /// True if Docker daemon is reachable. False means builds will fail at compile time.
    pub docker_ok: bool,
    pub docker_version: String,
}

/// Check whether the Docker daemon is running and reachable.
///
/// Returns (is_running, version_string).
/// Called standalone by the frontend status bar and as step 0 of initialize_system.
#[tauri::command]
pub async fn check_docker_status() -> Result<DockerStatusResponse, String> {
    let out = Command::new("docker").hide_console()
        .args(["info", "--format", "{{.ServerVersion}}"])
        .output()
        .await;

    match out {
        Ok(ref o) if o.status.success() => {
            let version = String::from_utf8_lossy(&o.stdout).trim().to_string();
            Ok(DockerStatusResponse {
                running: true,
                message: format!("Docker daemon OK (v{})", version),
                version,
            })
        }
        Ok(ref o) => {
            let stderr = String::from_utf8_lossy(&o.stderr);
            Ok(DockerStatusResponse {
                running: false,
                version: String::new(),
                message: format!(
                    "Docker is installed but not running. Start Docker Desktop, then retry.\nError: {}",
                    stderr.trim()
                ),
            })
        }
        Err(ref e) if e.kind() == std::io::ErrorKind::NotFound => Ok(DockerStatusResponse {
            running: false,
            version: String::new(),
            message: "Docker is not installed. Download Docker Desktop (free) from https://www.docker.com/products/docker-desktop".to_string(),
        }),
        Err(e) => Ok(DockerStatusResponse {
            running: false,
            version: String::new(),
            message: format!("Docker check failed: {}", e),
        }),
    }
}

/// Typed replacements for two `serde_json::Value` returns.
///
/// 36 of this app's commands returned an untyped `Value`, which made the
/// frontend's declared interface for each one an unverified assertion: nothing
/// stopped a field being renamed on one side only. `HardwareProbe` and
/// `DockerStatus` already existed as TypeScript interfaces in `src/lib/api.ts`
/// with no Rust counterpart at all, so those two shapes were pure convention.
///
/// Field names are snake_case on purpose and deliberately NOT `rename_all`'d to
/// camelCase: the TS interfaces read `vram_budget_mb`, `hardware_fallback` and so
/// on, so renaming here would silently break every consumer. The field lists are
/// pinned against each other by `src/lib/__tests__/returnShape.test.ts`.
#[derive(Serialize)]
pub struct HardwareProbeResponse {
    pub total_vram_mb: Option<u64>,
    pub vram_budget_mb: u64,
    pub reserved_vram_mb: u64,
    pub hardware_source: String,
    pub hardware_fallback: bool,
    pub recommended_tier: String,
}

#[derive(Serialize)]
pub struct DockerStatusResponse {
    pub running: bool,
    pub version: String,
    pub message: String,
}

/// Full zero-friction bootstrap: check Docker → install Ollama → detect hardware → pull models → build tags.
///
/// This single command takes a machine from zero to fully operational Determinex.
/// Returns a structured result the Setup Wizard can display.
#[tauri::command]
pub async fn initialize_system() -> Result<BootstrapResult, String> {
    // ── Step 0: Check Docker daemon (optional — sidecar mode uses local compiler) ──
    // Docker is NOT required for sidecar-mode Determinex. The Compiler Oracle
    // invokes rustc/go/python directly from the determinex-hive sidecar binary.
    // We still probe it so the frontend can surface a status indicator, but
    // we no longer abort if it's absent or not running.
    // Now that check_docker_status returns a real struct, both fallbacks build one
    // too and the fields are read directly. The previous version indexed into a
    // Value with `["running"].as_bool().unwrap_or(false)` — which silently reports
    // "Docker not running" for a renamed or missing key just as it does for a
    // genuinely stopped daemon, the same shape of indistinguishable failure this
    // typing pass exists to remove.
    let docker_result = tokio::time::timeout(
        std::time::Duration::from_secs(5),
        check_docker_status(),
    )
    .await
    .unwrap_or_else(|_| {
        Ok(DockerStatusResponse {
            running: false,
            version: String::new(),
            message: "Docker check timed out (daemon not running)".to_string(),
        })
    })
    .unwrap_or_else(|_| DockerStatusResponse {
        running: false,
        version: String::new(),
        message: "Docker check failed".to_string(),
    });
    let docker_ok = docker_result.running;
    let docker_version = docker_result.version.clone();

    // ── Step 1: Ensure Ollama ────────────────────────────────────────────────
    let ollama = ollama_installer::ensure_ollama().await?;
    let ollama_status = format!("{:?}", ollama.status);

    // ── Step 2: Probe VRAM ──────────────────────────────────────────────────
    // spawn_blocking: poll_hardware() shells out to nvidia-smi/rocm-smi/
    // system_profiler synchronously. Even bounded by a timeout (see
    // hardware.rs), that's still up to several seconds of blocking work: run
    // it off the async runtime's worker threads so a slow probe can't stall
    // other in-flight commands or the window's own responsiveness while it
    // waits.
    let hardware_probe = tokio::task::spawn_blocking(hardware::poll_hardware)
        .await
        .map_err(|e| format!("hardware probe task panicked: {e}"))??;
    let budget_mb = hardware_probe.vram_budget_mb;

    // ── Step 3: Resolve tier ────────────────────────────────────────────────
    let config = hardware::calculate_tier(budget_mb)?;

    // ── Step 4: Pull base models (pass already-probed config — no second nvidia-smi) ──
    let pull_summary = model_puller::ensure_models_ready_with_config(budget_mb, &config).await?;

    // ── Step 5: Build Determinex model tags ─────────────────────────────────────
    // bootstrap::run_first_setup now also checks Docker again internally as a
    // belt-and-suspenders guard for headless / CLI invocations.
    bootstrap::run_first_setup(&config).await?;

    let tier_desc = format!(
        "engineer={} | num_ctx={} | vram={}MB",
        config.engineer_model, config.num_ctx, budget_mb
    );

    Ok(BootstrapResult {
        ollama_status,
        ollama_version: ollama.version,
        total_vram_mb: hardware_probe.total_vram_mb,
        vram_budget_mb: budget_mb,
        reserved_vram_mb: hardware_probe.reserved_mb,
        hardware_source: hardware_probe.source,
        hardware_fallback: hardware_probe.fallback,
        tier: tier_desc,
        models_pulled: pull_summary.models_pulled,
        models_existing: pull_summary.models_existing,
        models_failed: pull_summary.models_failed,
        docker_ok,
        docker_version,
    })
}

/// Probes the system hardware and returns the VRAM budget and recommended tier without installing anything.
/// Used by the interactive Setup Wizard to display recommendations before proceeding.
#[tauri::command]
pub async fn probe_hardware() -> Result<HardwareProbeResponse, String> {
    // See initialize_system's Step 2 comment -- same spawn_blocking rationale.
    let hardware_probe = tokio::task::spawn_blocking(hardware::poll_hardware)
        .await
        .map_err(|e| format!("hardware probe task panicked: {e}"))??;
    let budget_mb = hardware_probe.vram_budget_mb;
    let config = hardware::calculate_tier(budget_mb)?;

    Ok(HardwareProbeResponse {
        total_vram_mb: hardware_probe.total_vram_mb,
        vram_budget_mb: budget_mb,
        reserved_vram_mb: hardware_probe.reserved_mb,
        hardware_source: hardware_probe.source,
        hardware_fallback: hardware_probe.fallback,
        recommended_tier: format!(
            "engineer={} | num_ctx={}",
            config.engineer_model, config.num_ctx
        ),
    })
}
