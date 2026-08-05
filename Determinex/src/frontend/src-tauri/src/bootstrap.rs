use crate::hardware::DeterminexConfig;
use crate::win_process::HideConsoleExt;
/// bootstrap.rs — First-run Determinex model factory
///
/// Programmatically constructs and registers the three Ollama models required by the
/// MoA pipeline. Each model is built by writing a temporary Modelfile to the OS temp
/// directory, calling `ollama create`, then cleaning up the temp file.
///
/// Execution is sequential: Sentinel → Engineer → Observer. Each `ollama create` call
/// blocks until the model is fully built and registered in the local Ollama registry.
/// On a typical machine this takes 10–30 seconds per model (GGUF quantisation + indexing).
///
/// Uses `tokio::process::Command` throughout so the async Tauri command handler is not
/// stalled on the blocking `std::process::Command` API.
use tokio::process::Command;

/// Target model names that the Hive Mind Orchestrator (litellm_config.yaml) expects.
/// These MUST match the model_name values under determinex.roles in litellm_config.yaml.
// Corrected 2026-07-29. These were determinex-engineer-v10-dsl / -observer-v5-dsl /
// -sentinel-v3, and the first two are listed in `STALE_MODEL_IDS` in
// scripts/models/model_router.py. So first-run setup was registering exactly the tags the
// router refuses to route to: any role resolving to one of them returns
// ROUTE_BLOCKED_STALE_MODEL_ID. A fresh machine could complete setup "successfully" and then
// be unable to route work to the models it had just registered. Pinned against the router's
// CURRENT_MODEL_IDS by tests/test_windows_installer_runtime.py so the two languages cannot
// drift apart again.
const ENGINEER_TAG: &str = "determinex-engineer-v11-dsl"; // Builder:   Qwen2.5-Coder-1.5B DSL v11
const OBSERVER_TAG: &str = "determinex-observer-v6-dsl"; // Monitor:   Llama-3.2-3B DSL v6
const SENTINEL_TAG: &str = "determinex-sentinel-v5-dsl"; // Architect: Mistral-7B DSL v5

/// Registers the three Determinex DSL model tags in Ollama.
///
/// Model tags MUST match litellm_config.yaml role assignments and
/// `scripts/models/model_router.py::CURRENT_MODEL_IDS`:
///   engineer → determinex-engineer-v11-dsl (Qwen2.5-Coder-1.5B, DSL v11, 57/70 = 81.4%)
///   observer → determinex-observer-v6-dsl  (Llama-3.2-3B, DSL v6, 53/70 = 75.7%)
///   sentinel → determinex-sentinel-v5-dsl  (Mistral-7B, DSL v5, no eval artifact on disk)
///
/// The per-model figures above are the 70-probe results and are LOWER than the 45-probe
/// v10/v5 numbers this comment used to quote as "+2pp" and "+4pp" improvements. Those
/// deltas compared different probe sets and were credited to models that had not been
/// evaluated; see the correction note in CLAUDE.md.
///
/// The Modelfiles live in <repo>/modelfiles/ and reference GGUFs from DETERMINEX_MODELS_DIR.
/// If the GGUFs are not yet present (pre-RunPod training run), this step is skipped
/// gracefully with a warning — the model pre-flight check in executor.py will surface
/// the gap when the user tries to run a session.
pub async fn run_first_setup(_config: &DeterminexConfig) -> Result<(), String> {
    // ── Step 0: Check if models are already registered (fast path) ────────────
    // Idempotent: if all three tags exist, return immediately — no Docker check,
    // no GGUF scan, nothing. This is the common case on subsequent boots.
    let output = Command::new("ollama").hide_console()
        .arg("list")
        .output()
        .await
        .map_err(|e| format!("ollama list failed: {}", e))?;
    let installed = String::from_utf8_lossy(&output.stdout).to_string();

    let has_all_tags = installed.contains(ENGINEER_TAG)
        && installed.contains(OBSERVER_TAG)
        && installed.contains(SENTINEL_TAG);

    if has_all_tags {
        log::info!(
            "[BOOTSTRAP] All DSL-versioned models already registered ({}, {}, {}) — skipping.",
            ENGINEER_TAG,
            OBSERVER_TAG,
            SENTINEL_TAG
        );
        return Ok(());
    }

    // ── Step 1: Docker daemon check (optional — sidecar uses local compiler) ──
    // Docker is no longer required for sidecar-mode Determinex. Log a warning if
    // it's absent but do not abort — the build loop uses local rustc/go/python.
    let docker_check = tokio::time::timeout(
        std::time::Duration::from_secs(5),
        Command::new("docker").hide_console()
            .args(["info", "--format", "{{.ServerVersion}}"])
            .output(),
    )
    .await;
    match docker_check {
        Ok(Ok(ref out)) if out.status.success() => {
            let ver = String::from_utf8_lossy(&out.stdout);
            log::info!("[BOOTSTRAP] Docker daemon OK (version {})", ver.trim());
        }
        _ => {
            log::warn!(
                "[BOOTSTRAP] Docker not available — sidecar mode uses local compiler, continuing."
            );
        }
    }

    // ── Step 2: Locate the DETERMINEX_MODELS_DIR ─────────────────────────────────
    // Reads DETERMINEX_MODELS_DIR from the environment (set in .env or system env).
    // Falls back to ~/determinex-models so the system degrades gracefully.
    let models_dir = std::env::var("DETERMINEX_MODELS_DIR").unwrap_or_else(|_| {
        let home = std::env::var("USERPROFILE")
            .or_else(|_| std::env::var("HOME"))
            .unwrap_or_else(|_| ".".to_string());
        format!("{}/determinex-models", home)
    });
    let models_path = std::path::PathBuf::from(&models_dir);

    log::info!("[BOOTSTRAP] DETERMINEX_MODELS_DIR = {:?}", models_path);

    // ── Step 3: Build each missing model from its versioned GGUF ──────────────
    // Model version → relative path from DETERMINEX_MODELS_DIR
    let model_specs: &[(&str, &str, &str)] = &[
        // (ollama_tag, relative_gguf_path, num_ctx)
        (
            ENGINEER_TAG,
            "versions/engineer/v11-dsl/determinex-engineer-v11-dsl.gguf",
            "4096",
        ),
        (
            OBSERVER_TAG,
            "versions/observer/v6-dsl/determinex-observer-v6-dsl.gguf",
            "4096",
        ),
        (
            SENTINEL_TAG,
            "versions/sentinel/v5-dsl/determinex-sentinel-v5-dsl.gguf",
            "4096",
        ),
    ];

    for (tag, relative_path, num_ctx) in model_specs {
        if installed.contains(tag) {
            log::info!("[BOOTSTRAP] {} already registered — skipping.", tag);
            continue;
        }

        let gguf_path = models_path.join(relative_path);

        if !gguf_path.exists() {
            log::warn!(
                "[BOOTSTRAP] GGUF not found for {} at {:?}. \
                 Skipping — run the RunPod training pipeline first, \
                 then re-run the Setup Wizard to register the model.",
                tag,
                gguf_path
            );
            continue;
        }

        let gguf_str = gguf_path.to_string_lossy();
        let modelfile_content = format!(
            "FROM {}\nPARAMETER num_ctx {}\nPARAMETER temperature 0\n",
            gguf_str, num_ctx
        );

        let safe_name = tag.replace(':', "_").replace('/', "_");
        let temp_path = std::env::temp_dir().join(format!("determinex_modelfile_{}.txt", safe_name));

        std::fs::write(&temp_path, &modelfile_content)
            .map_err(|e| format!("Failed to write Modelfile for {}: {}", tag, e))?;

        log::info!("[BOOTSTRAP] Registering {} FROM {:?}", tag, gguf_path);

        let out = Command::new("ollama").hide_console()
            .args(["create", tag, "-f", temp_path.to_str().unwrap_or("")])
            .output()
            .await
            .map_err(|e| format!("Failed to spawn `ollama create {}`: {}", tag, e));

        let _ = std::fs::remove_file(&temp_path);
        let out = out?;

        if out.status.success() {
            log::info!("[BOOTSTRAP] Successfully registered: {}", tag);
        } else {
            let stderr = String::from_utf8_lossy(&out.stderr);
            log::warn!(
                "[BOOTSTRAP] `ollama create {}` failed: {} — continuing to next model.",
                tag,
                stderr.trim()
            );
        }
    }

    Ok(())
}
