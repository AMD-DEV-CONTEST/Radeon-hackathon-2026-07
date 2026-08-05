/// hardware.rs — Multi-platform VRAM telemetry and hardware tier classification
///
/// Probes the available GPU/unified-memory budget via a three-tier fallback chain:
///
///   1. Nvidia  — `nvidia-smi` (Windows, Linux)
///   2. AMD     — `rocm-smi`   (Linux, Windows with ROCm)
///   3. Apple   — `system_profiler SPHardwareDataType` (macOS only, compile-gated)
///   4. Default — 4 000 MB conservative fallback (VMs, integrated, ARM Linux, unknown)
///
/// Overhead deductions:
///   Dedicated VRAM (Nvidia / AMD)  →  subtract 2 000 MB (driver + CUDA/ROCm context)
///   Unified memory (Apple Silicon) →  subtract 4 000 MB (macOS reserves a larger share
///                                      for the GPU command queue and IOKit buffers)
use serde::Serialize;
use std::process::Command;
use std::time::Duration;
use crate::win_process::HideConsoleExt;

// nvidia-smi / rocm-smi / system_profiler normally return in well under a
// second; 5s is generous headroom for a loaded/waking-from-sleep GPU driver
// without leaving the boot sequence hanging on a genuinely stuck probe.
const PROBE_TIMEOUT: Duration = Duration::from_secs(5);

// ─────────────────────────────────────────────────────────────────────────────
// PUBLIC TYPES
// ─────────────────────────────────────────────────────────────────────────────

/// Resolved hardware configuration for this machine's inference tier.
/// Injected into the bootstrap factory so the correct Ollama models are built.
#[derive(Debug, Clone)]
pub struct DeterminexConfig {
    /// Ollama model tag for the Engineer stage (the largest model in the pipeline).
    pub engineer_model: String,
    /// KV-cache context window, capped to fit within the available VRAM budget.
    pub num_ctx: u32,
}

#[derive(Debug, Clone, Serialize)]
pub struct HardwareProbe {
    pub total_vram_mb: Option<u64>,
    pub vram_budget_mb: u64,
    pub reserved_mb: u64,
    pub source: String,
    pub fallback: bool,
}

fn dedicated_probe(source: &str, total_mb: u64) -> HardwareProbe {
    let reserved_mb = 2000;
    HardwareProbe {
        total_vram_mb: Some(total_mb),
        vram_budget_mb: total_mb.saturating_sub(reserved_mb),
        reserved_mb,
        source: source.to_string(),
        fallback: false,
    }
}

#[cfg_attr(not(target_os = "macos"), allow(dead_code))]
fn unified_probe(source: &str, total_mb: u64) -> HardwareProbe {
    let reserved_mb = 4000;
    HardwareProbe {
        total_vram_mb: Some(total_mb),
        vram_budget_mb: total_mb.saturating_sub(reserved_mb),
        reserved_mb,
        source: source.to_string(),
        fallback: false,
    }
}

fn fallback_probe() -> HardwareProbe {
    HardwareProbe {
        total_vram_mb: None,
        vram_budget_mb: 4000,
        reserved_mb: 0,
        source: "conservative fallback".to_string(),
        fallback: true,
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// PROBE CHAIN
// ─────────────────────────────────────────────────────────────────────────────

/// **Probe 1 — Nvidia** via `nvidia-smi`.
///
/// Returns the inference budget (total − 2 000 MB overhead) on success, or `None`
/// if the binary is absent, exits non-zero, or the output cannot be parsed.
fn probe_nvidia() -> Option<HardwareProbe> {
    // Was a bare, unbounded `.output()` -- std::process::Command is blocking,
    // and poll_hardware() runs synchronously (no spawn_blocking) inside the
    // async `initialize_system` Tauri command, so a stuck/slow nvidia-smi
    // (driver waking from sleep, a stuck GPU query) starved the whole tokio
    // runtime and froze the entire app window ("Not Responding"), not just
    // this probe. Reproduced live 2026-07-19 -- boot hung at the cosmetic
    // "97%" stage after a fresh app relaunch, window title showed "(Not
    // Responding)", self-recovered a few seconds later once nvidia-smi
    // presumably returned. Same fix pattern as project_audit.rs's npm-audit
    // hang: bound every probe with the existing run_with_timeout helper.
    let mut cmd = Command::new("nvidia-smi");
    cmd.hide_console();
    cmd.args(["--query-gpu=memory.total", "--format=csv,noheader,nounits"]);
    let out = crate::project_audit::run_with_timeout(cmd, PROBE_TIMEOUT).ok()?;

    if !out.status.success() {
        return None;
    }

    let stdout = String::from_utf8_lossy(&out.stdout);
    // Multi-GPU systems return one line per GPU — take the first (primary inference device).
    let line = stdout.lines().next()?.trim().to_string();
    let total_mb: u64 = line.parse().ok()?;
    let probe = dedicated_probe("nvidia-smi", total_mb);

    log::info!(
        "[HARDWARE] Nvidia: total={}MB  overhead=2000MB  budget={}MB",
        total_mb,
        probe.vram_budget_mb
    );
    Some(probe)
}

/// **Probe 2 — AMD** via `rocm-smi --showmeminfo vram`.
///
/// Parses the text output for lines containing `"VRAM Total Memory (B):"`.
/// The value is in bytes; we convert to MB and subtract 2 000 MB overhead.
///
/// Handles both the legacy ROCm ≤ 5.x text format and newer variants that
/// still emit this field name.
fn probe_amd() -> Option<HardwareProbe> {
    // See probe_nvidia()'s comment -- same unbounded-blocking-call fix.
    let mut cmd = Command::new("rocm-smi");
    cmd.hide_console();
    cmd.args(["--showmeminfo", "vram"]);
    let out = crate::project_audit::run_with_timeout(cmd, PROBE_TIMEOUT).ok()?;

    if !out.status.success() {
        return None;
    }

    let stdout = String::from_utf8_lossy(&out.stdout);

    // Expected line format (first GPU):
    //   "GPU[0]  : VRAM Total Memory (B): 8589934592"
    for line in stdout.lines() {
        if !line.contains("VRAM Total Memory (B):") {
            continue;
        }

        // Split on the label; everything after the colon is the byte count.
        let mut parts = line.splitn(2, "VRAM Total Memory (B):");
        let _prefix = parts.next();
        let val_str = parts.next()?.trim();

        if let Ok(bytes) = val_str.parse::<u64>() {
            let total_mb = bytes / (1024 * 1024);
            let probe = dedicated_probe("rocm-smi", total_mb);
            log::info!(
                "[HARDWARE] AMD ROCm: total={}MB  overhead=2000MB  budget={}MB",
                total_mb,
                probe.vram_budget_mb
            );
            return Some(probe);
        }
    }

    // rocm-smi ran but we couldn't find the memory field — treat as absent
    None
}

/// **Probe 3 — Apple Silicon** via `system_profiler SPHardwareDataType`.
///
/// Only compiled on macOS targets. On all other platforms the stub below
/// is used, which returns `None` with zero runtime cost.
///
/// Parses lines of the form:
/// ```text
///       Memory: 32 GB
/// ```
/// Unified memory is shared between CPU and GPU; macOS reserves a larger
/// portion for GPU command queues, so the overhead is 4 000 MB rather
/// than the 2 000 MB used for dedicated VRAM.
#[cfg(target_os = "macos")]
fn probe_apple_silicon() -> Option<HardwareProbe> {
    // See probe_nvidia()'s comment -- same unbounded-blocking-call fix.
    let mut cmd = Command::new("system_profiler");
    cmd.hide_console();
    cmd.args(["SPHardwareDataType"]);
    let out = crate::project_audit::run_with_timeout(cmd, PROBE_TIMEOUT).ok()?;

    if !out.status.success() {
        return None;
    }

    let stdout = String::from_utf8_lossy(&out.stdout);

    for line in stdout.lines() {
        let trimmed = line.trim();

        // "Memory: 32 GB" — the field name includes the colon.
        if !trimmed.starts_with("Memory:") {
            continue;
        }

        let after_colon = trimmed.strip_prefix("Memory:")?.trim();
        // after_colon is e.g. "32 GB" or "16 GB"
        let mut tokens = after_colon.split_whitespace();
        let amount_str = tokens.next()?;
        let unit = tokens.next()?.to_lowercase();

        let amount: u64 = amount_str.parse().ok()?;
        let total_mb: u64 = match unit.as_str() {
            "gb" => amount * 1024,
            "mb" => amount,
            // Unexpected unit (TB would be unusual; treat as unsupported)
            _ => {
                log::warn!(
                    "[HARDWARE] system_profiler Memory field has unexpected unit: '{}'",
                    unit
                );
                return None;
            }
        };

        // Unified memory overhead is larger than dedicated VRAM overhead:
        // macOS IOKit GPU buffers, Metal command queues, and display compositor
        // together consume ~3–4 GB on a typical Apple Silicon system.
        let probe = unified_probe("Apple unified memory", total_mb);
        log::info!(
            "[HARDWARE] Apple Silicon: total={}MB  unified overhead=4000MB  budget={}MB",
            total_mb,
            probe.vram_budget_mb
        );
        return Some(probe);
    }

    // system_profiler ran but we couldn't parse the Memory field
    None
}

/// Compile-time stub for non-macOS targets — zero runtime cost.
#[cfg(not(target_os = "macos"))]
fn probe_apple_silicon() -> Option<HardwareProbe> {
    None
}

// ─────────────────────────────────────────────────────────────────────────────
// PUBLIC API
// ─────────────────────────────────────────────────────────────────────────────

/// Probe the available VRAM / unified-memory budget in MB via a platform fallback chain.
///
/// Chain order:  Nvidia → AMD → Apple Silicon → 4 000 MB default
///
/// The returned value already has the platform-specific OS overhead subtracted and
/// is ready to be passed directly to `calculate_tier`.
pub fn poll_vram_budget() -> Result<u64, String> {
    Ok(poll_hardware()?.vram_budget_mb)
}

/// Probe hardware and return both physical memory and the inference-safe budget.
pub fn poll_hardware() -> Result<HardwareProbe, String> {
    // ── Probe 1: Nvidia ───────────────────────────────────────────────────────
    if let Some(probe) = probe_nvidia() {
        return Ok(probe);
    }
    log::info!("[HARDWARE] Nvidia probe: not available. Trying AMD ROCm...");

    // ── Probe 2: AMD ──────────────────────────────────────────────────────────
    if let Some(probe) = probe_amd() {
        return Ok(probe);
    }
    log::info!("[HARDWARE] AMD probe: not available. Trying Apple Silicon...");

    // ── Probe 3: Apple Silicon (macOS compile-gate) ───────────────────────────
    if let Some(probe) = probe_apple_silicon() {
        return Ok(probe);
    }

    // ── Final fallback: conservative 4 GB ────────────────────────────────────
    // Covers: integrated graphics, VMs, ARM Linux, Apple Intel Macs without
    // discrete GPU, or any platform where none of the above probes succeeded.
    log::warn!(
        "[HARDWARE] All probes exhausted (Nvidia / AMD / Apple). \
         Using 4000MB conservative unified-memory fallback."
    );
    Ok(fallback_probe())
}

// ─────────────────────────────────────────────────────────────────────────────
// TIER CLASSIFICATION
// ─────────────────────────────────────────────────────────────────────────────

/// Map a VRAM / unified-memory budget to the appropriate `DeterminexConfig`.
///
/// | Budget (MB)   | Engineer model       | num_ctx | Notes                              |
/// |---------------|----------------------|---------|------------------------------------|
/// | < 4 000       | —                    | —       | Hard reject — minimum not met      |
/// | 4 000 - 7 999 | qwen2.5-coder:3b-instruct | 4 096 | Fits 4-6 GB. 7B models lag here. |
/// | 8 000 - 11 999| qwen2.5-coder:7b-instruct | 4 096 | Fits 8-11 GB with context growth |
/// | >= 12 000     | qwen2.5-coder:7b-instruct | 8 192 | Headroom for extended context    |
///
/// Derived from Crucible benchmark runs on 6 GB GPU (6 GB dedicated)
/// and validated against Apple M2 Pro (16 GB unified).
pub fn calculate_tier(budget_mb: u64) -> Result<DeterminexConfig, String> {
    if budget_mb < 4000 {
        return Err(format!(
            "Hardware Insufficient. Determinex requires a minimum 4 GB of available GPU memory. \
             Detected inference budget: {}MB (total minus platform overhead).",
            budget_mb
        ));
    }

    let config = if budget_mb < 8000 {
        DeterminexConfig {
            engineer_model: "qwen2.5-coder:3b-instruct".to_string(),
            num_ctx: 4096,
        }
    } else if budget_mb < 12000 {
        DeterminexConfig {
            engineer_model: "qwen2.5-coder:7b-instruct".to_string(),
            num_ctx: 4096,
        }
    } else {
        DeterminexConfig {
            engineer_model: "qwen2.5-coder:7b-instruct".to_string(),
            num_ctx: 8192,
        }
    };

    log::info!(
        "[HARDWARE] Tier resolved: engineer={}  num_ctx={}  budget={}MB",
        config.engineer_model,
        config.num_ctx,
        budget_mb
    );

    Ok(config)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn dedicated_gpu_reports_total_and_inference_budget_separately() {
        let probe = dedicated_probe("nvidia-smi", 6144);
        assert_eq!(probe.total_vram_mb, Some(6144));
        assert_eq!(probe.reserved_mb, 2000);
        assert_eq!(probe.vram_budget_mb, 4144);
        assert!(!probe.fallback);
    }

    #[test]
    fn fallback_does_not_pretend_to_detect_physical_vram() {
        let probe = fallback_probe();
        assert_eq!(probe.total_vram_mb, None);
        assert_eq!(probe.vram_budget_mb, 4000);
        assert!(probe.fallback);
    }
}
