/// model_puller.rs — Automated Ollama model downloader with progress tracking
///
/// Ensures all base models required by the Determinex Hive Mind are pulled into
/// the local Ollama registry before the bootstrap factory runs.
///
/// The current Determinex architecture requires these base models:
///   - qwen2.5-coder:1.5b-instruct  -> Engineer fallback (Tier 0, Builder role)
///   - qwen2.5-coder:3b-instruct    -> local/fast fallback (Oracle/Architect)
///   - qwen2.5-coder:7b-instruct    -> larger local reasoning fallback
///   - qwen2.5-coder:14b-instruct   -> Leviathan (CPU fallback, optional)
///
/// The custom fine-tuned GGUFs (determinex-engineer-v11-dsl, -observer-v6-dsl,
/// -sentinel-v5-dsl) are NOT pulled here. They are provisioned by `check_determinex_models`
/// and `install_determinex_models` further down this file, which shell to the bundled
/// sidecar's `helper setup.install_determinex_models`.
///
/// Corrected 2026-07-29 (twice, in one day). This comment first claimed they were "handled
/// separately via GitHub Releases download and `ollama create -f Modelfile`", which was false:
/// no GGUF is attached to any release. It was then rewritten to say there was no public place
/// to get them at all -- true when written, false a few hours later once the three HuggingFace
/// repos under darthceltic85 were made public and anonymously downloadable.
///
/// This mattered because roles.rs defaults a fresh install's builder and monitor to
/// determinex/engineer and determinex/observer. Until the two commands below existed, two of
/// four roles pointed at models a new user had no in-app way to obtain, and the shipped
/// Modelfiles cannot bootstrap them either (Modelfile.engineer reads
/// `FROM determinex-engineer-v11-dsl`, deriving from the model it would be creating). See
/// docs/audits/USER_FACING_AUDIT_20260729.md.
///
/// Progress is reported via Tauri events so the frontend SetupWizard can
/// render per-model progress bars.
use serde::{Deserialize, Serialize};
use tokio::process::Command;

use crate::hardware;
use crate::win_process::HideConsoleExt;

// ─────────────────────────────────────────────────────────────────────────────
// TYPES
// ─────────────────────────────────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
#[allow(dead_code)]
pub struct ModelPullStatus {
    pub model: String,
    pub status: String, // "already_exists", "pulling", "complete", "failed"
    pub progress: f32,  // 0.0 to 1.0
}

#[derive(Debug, Clone, Serialize)]
pub struct PullSummary {
    pub models_pulled: Vec<String>,
    pub models_existing: Vec<String>,
    pub models_failed: Vec<String>,
    pub tier_resolved: String,
    pub vram_budget_mb: u64,
}

// ─────────────────────────────────────────────────────────────────────────────
// MODEL RESOLUTION
// ─────────────────────────────────────────────────────────────────────────────

/// The local model Agent Chat falls back to when a session has no explicit override.
///
/// Load-bearing that this lives HERE, beside the install list, and is `pub`. `agent_chat.rs` used
/// to hardcode its own default of `qwen2.5-coder:14b-instruct-q4_K_M` -- a tag this function
/// deliberately does NOT install (see the note below about skipping the 14b). Two independent lists
/// of model tags with nothing linking them, so they drifted: on a fresh install Agent Chat asked
/// Ollama for a model that was never downloaded and every first message 404'd.
///
/// Dev boxes could not see it, because the repo `.env` sets
/// `DETERMINEX_LOCAL_BUILDER_MODEL=…14b…` and the env var still wins -- and `.env` does not ship in
/// the installer. Found 2026-07-30 while auditing "do the chat surfaces actually work".
///
/// So: whatever this is, it must be a tag `required_models_for_budget` installs unconditionally.
/// `agent_chat_default_model_is_always_installed` enforces exactly that.
pub const DEFAULT_LOCAL_CHAT_MODEL: &str = "qwen2.5-coder:3b-instruct";

/// Determine which base models need to be present for the detected hardware tier.
///
/// The tier system from hardware.rs determines the Engineer model size.
/// We always need the small models (1.5b for Builder, 3b for Observer).
/// The tier determines whether we also pull the 7b and/or 14b.
fn required_models_for_budget(budget_mb: u64) -> Vec<&'static str> {
    let mut models = vec![
        "qwen2.5-coder:1.5b-instruct",  // Builder fallback - always needed
        DEFAULT_LOCAL_CHAT_MODEL,       // local/fast + Agent Chat default - always needed
    ];

    if budget_mb >= 7000 {
        models.push("qwen2.5-coder:7b-instruct"); // larger reasoning fallback
    }

    // The 14b Leviathan runs on CPU, so it's optional but useful.
    // Only pull if the system has 16GB+ RAM (not VRAM).
    // For now, skip it to save download time. Users can add it later.

    models
}

// ─────────────────────────────────────────────────────────────────────────────
// OLLAMA INTERACTION
// ─────────────────────────────────────────────────────────────────────────────

/// Parse `ollama list` output to get currently installed model tags.
async fn get_installed_models() -> Result<Vec<String>, String> {
    let output = Command::new("ollama").hide_console()
        .arg("list")
        .output()
        .await
        .map_err(|e| format!("Failed to run `ollama list`: {}", e))?;

    if !output.status.success() {
        // If Ollama is running but has no models, it might still return success
        // with an empty list. A non-zero exit is a real error.
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(format!("`ollama list` failed: {}", stderr.trim()));
    }

    let stdout = String::from_utf8_lossy(&output.stdout);
    let tags: Vec<String> = stdout
        .lines()
        .skip(1) // Header line: "NAME   ID   SIZE   MODIFIED"
        .filter_map(|line| {
            let tag = line.split_whitespace().next()?;
            if tag.is_empty() {
                None
            } else {
                Some(tag.to_string())
            }
        })
        .collect();

    log::info!("[MODEL-PULLER] Installed models: {:?}", tags);

    Ok(tags)
}

/// Check if a model tag (e.g. "qwen2.5-coder:7b-instruct") is already installed.
/// Allows Ollama quantization suffixes while avoiding bare-tag/instruct drift.
fn model_is_installed(tag: &str, installed: &[String]) -> bool {
    installed.iter().any(|installed_tag| {
        installed_tag == tag
            || installed_tag.starts_with(&format!("{}:", tag))
    })
}

/// Pull a single model via `ollama pull <tag>`.
///
/// This blocks until the pull is complete. Ollama handles the download
/// internally with its own progress reporting to stderr.
async fn pull_model(tag: &str) -> Result<(), String> {
    log::info!("[MODEL-PULLER] Pulling model: {}", tag);

    let output = Command::new("ollama").hide_console()
        .args(["pull", tag])
        .output()
        .await
        .map_err(|e| format!("Failed to run `ollama pull {}`: {}", tag, e))?;

    if output.status.success() {
        log::info!("[MODEL-PULLER] Successfully pulled: {}", tag);
        Ok(())
    } else {
        let stderr = String::from_utf8_lossy(&output.stderr);
        let stdout = String::from_utf8_lossy(&output.stdout);
        Err(format!(
            "`ollama pull {}` failed (exit {:?}).\nstdout: {}\nstderr: {}",
            tag,
            output.status.code(),
            stdout.trim(),
            stderr.trim()
        ))
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// PUBLIC API
// ─────────────────────────────────────────────────────────────────────────────

/// Master entry point: given a pre-resolved hardware config, pull any missing base models.
///
/// Takes the already-probed budget and config from ipc_bootstrap to avoid a redundant
/// second nvidia-smi call (the double-logging problem when called after initialize_system
/// already probed hardware at steps 2-3).
pub async fn ensure_models_ready_with_config(
    budget_mb: u64,
    config: &hardware::DeterminexConfig,
) -> Result<PullSummary, String> {
    log::info!(
        "[MODEL-PULLER] VRAM budget: {}MB → tier engineer={} num_ctx={}",
        budget_mb,
        config.engineer_model,
        config.num_ctx
    );

    // 1. Determine required models
    let required = required_models_for_budget(budget_mb);

    // 3. Check what's already installed
    let installed = get_installed_models().await.unwrap_or_default();

    let mut models_pulled = Vec::new();
    let mut models_existing = Vec::new();
    let mut models_failed = Vec::new();

    // 4. Pull each missing model
    for tag in &required {
        if model_is_installed(tag, &installed) {
            log::info!("[MODEL-PULLER] Already installed: {}", tag);
            models_existing.push(tag.to_string());
            continue;
        }

        match pull_model(tag).await {
            Ok(()) => models_pulled.push(tag.to_string()),
            Err(e) => {
                log::error!("[MODEL-PULLER] Failed to pull {}: {}", tag, e);
                models_failed.push(tag.to_string());
            }
        }
    }

    let tier_desc = format!(
        "engineer={} ctx={} vram={}MB",
        config.engineer_model, config.num_ctx, budget_mb
    );

    Ok(PullSummary {
        models_pulled,
        models_existing,
        models_failed,
        tier_resolved: tier_desc,
        vram_budget_mb: budget_mb,
    })
}

/// Tauri IPC command — exposed to the frontend Setup Wizard.
/// Probes hardware itself for standalone use (outside of initialize_system).
#[tauri::command]
pub async fn pull_required_models() -> Result<PullSummary, String> {
    let budget_mb = hardware::poll_vram_budget()?;
    let config = hardware::calculate_tier(budget_mb)?;
    ensure_models_ready_with_config(budget_mb, &config).await
}

// ─────────────────────────────────────────────────────────────────────────────
// FINE-TUNED MODEL PROVISIONING
//
// Added 2026-07-29. The base qwen models above were the ONLY thing a fresh install could
// obtain, while roles.rs defaults builder and monitor to the fine-tuned determinex models --
// so two of four roles pointed at models a new user had no way to get. The Setup Wizard made
// this worse by announcing "Registering Determinex model swarm with Ollama..." over a call
// that pulled base models and registered nothing of the kind.
//
// The capability already shipped: the bundled sidecar exposes
// `helper setup.install_determinex_models`, which downloads each GGUF from its public
// HuggingFace repo, verifies the published sha256, and registers it with a generated
// Modelfile. Nothing called it. These two commands are that missing wire.
//
// Kept as two separate commands on purpose. The download is several GB, so it must be an
// explicit, informed choice rather than something first-run setup does to someone silently.
// `check` is cheap and side-effect free, which is what lets the UI ask before spending it.
// ─────────────────────────────────────────────────────────────────────────────

const MODEL_INSTALLER_SCRIPT: &str = "scripts/setup/install_determinex_models.py";

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DeterminexModelStatus {
    /// Ollama is reachable. Without it nothing can be registered, and that is worth reporting
    /// as its own condition rather than as a mysterious install failure.
    pub ollama_available: bool,
    pub missing_count: u32,
    pub total_count: u32,
    /// Raw report from the installer's --check mode, for display when something looks wrong.
    pub detail: String,
}

/// Cheap, side-effect free: how many fine-tuned models are missing?
#[tauri::command]
pub async fn check_determinex_models() -> Result<DeterminexModelStatus, String> {
    let (mut cmd, _bundled) = crate::ipc_hive::helper_command(MODEL_INSTALLER_SCRIPT)?;
    cmd.arg("--check");
    // helper_command hands back a std::process::Command, so this goes through the same
    // timeout-wrapped runner every other sidecar caller uses rather than tokio's .output().
    // --check only shells out to `ollama list`, so a minute is generous.
    let out = crate::project_audit::run_with_timeout(cmd, std::time::Duration::from_secs(60))
        .map_err(|e| format!("could not run the model installer: {}", e))?;

    let detail = format!(
        "{}{}",
        String::from_utf8_lossy(&out.stdout),
        String::from_utf8_lossy(&out.stderr)
    );

    // The installer prints "N of M missing" and exits non-zero when any are missing, so exit
    // status alone cannot distinguish "some missing" from "it failed to run". Parse the line.
    let (mut missing, mut total) = (0u32, 0u32);
    let mut parsed = false;
    for line in detail.lines() {
        if let Some((left, right)) = line.trim().split_once(" of ") {
            if let Some(rest) = right.strip_suffix(" missing") {
                if let (Ok(m), Ok(t)) = (left.trim().parse::<u32>(), rest.trim().parse::<u32>()) {
                    missing = m;
                    total = t;
                    parsed = true;
                    break;
                }
            }
        }
    }
    if !parsed {
        return Err(format!(
            "could not read the model installer's report; it said:\n{}",
            detail.trim()
        ));
    }

    Ok(DeterminexModelStatus {
        ollama_available: !detail.contains("ollama.com"),
        missing_count: missing,
        total_count: total,
        detail: detail.trim().to_string(),
    })
}

/// Download and register the fine-tuned models. Several GB; call only on explicit request.
#[tauri::command]
pub async fn install_determinex_models() -> Result<String, String> {
    let (cmd, _bundled) = crate::ipc_hive::helper_command(MODEL_INSTALLER_SCRIPT)?;
    // Several GB over a home connection. A short timeout here would kill a download that was
    // working fine and report it as a failure, which is worse than waiting.
    let out = crate::project_audit::run_with_timeout(cmd, std::time::Duration::from_secs(7200))
        .map_err(|e| format!("could not run the model installer: {}", e))?;

    let stdout = String::from_utf8_lossy(&out.stdout).to_string();
    let stderr = String::from_utf8_lossy(&out.stderr).to_string();
    if !out.status.success() {
        return Err(format!(
            "model installation did not complete:\n{}",
            format!("{}{}", stdout, stderr).trim()
        ));
    }
    Ok(stdout.trim().to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn required_models_use_configured_instruct_tags() {
        assert_eq!(
            required_models_for_budget(4000),
            vec!["qwen2.5-coder:1.5b-instruct", "qwen2.5-coder:3b-instruct"]
        );
        assert_eq!(
            required_models_for_budget(8000),
            vec![
                "qwen2.5-coder:1.5b-instruct",
                "qwen2.5-coder:3b-instruct",
                "qwen2.5-coder:7b-instruct",
            ]
        );
    }

    /// Agent Chat's fallback model must be one the installer actually downloads.
    ///
    /// The regression this pins: `agent_chat.rs` hardcoded `qwen2.5-coder:14b-instruct-q4_K_M`,
    /// which `required_models_for_budget` never installs at any budget. On a fresh install the very
    /// first chat message asked Ollama for a model that was not there. Invisible on a dev box,
    /// because the repo `.env` sets DETERMINEX_LOCAL_BUILDER_MODEL and `.env` is not shipped.
    ///
    /// Checked at the SMALLEST budget deliberately: a tag that only appears on a big machine would
    /// still leave a low-spec install broken, which is the exact case that failed.
    #[test]
    fn agent_chat_default_model_is_always_installed() {
        let minimum = required_models_for_budget(0);
        assert!(
            minimum.contains(&DEFAULT_LOCAL_CHAT_MODEL),
            "Agent Chat falls back to {DEFAULT_LOCAL_CHAT_MODEL}, but the installer only pulls \
             {minimum:?} on a minimum-spec machine — so a fresh install would 404 on its first \
             chat message. Either pull this tag unconditionally or change the default to one that \
             is."
        );
        // And at every budget the installer supports, not just the floor.
        for budget in [0_u64, 4000, 8000, 32000] {
            assert!(
                required_models_for_budget(budget).contains(&DEFAULT_LOCAL_CHAT_MODEL),
                "default chat model missing from the install set at budget {budget} MB"
            );
        }
    }

    #[test]
    fn model_install_detection_does_not_treat_bare_tag_as_instruct() {
        let installed = vec!["qwen2.5-coder:1.5b-instruct".to_string()];

        assert!(model_is_installed("qwen2.5-coder:1.5b-instruct", &installed));
        assert!(!model_is_installed("qwen2.5-coder:1.5b", &installed));
    }
}
