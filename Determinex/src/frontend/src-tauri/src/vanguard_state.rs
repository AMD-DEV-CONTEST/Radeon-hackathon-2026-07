/// vanguard_state.rs — Vanguard Telemetry Opt-In Gate
///
/// Manages the user's consent state for local encrypted telemetry logging.
/// Default: OFF. The user must explicitly enable it from the UI.
///
/// The `VanguardState` is registered as a Tauri managed state on startup.
/// The `toggle_vanguard_telemetry` IPC command flips the flag atomically.
/// The orchestrator reads `is_vanguard_enabled` before writing any training pair.
use std::sync::atomic::{AtomicBool, Ordering};
use tauri::State;

/// Global opt-in gate for Vanguard encrypted telemetry logging.
///
/// Uses `AtomicBool` (not `Mutex<bool>`) because the toggle is a single-word
/// write that needs no exclusive critical section — atomics are faster and
/// can never deadlock.
pub struct VanguardState {
    pub enabled: AtomicBool,
}

impl VanguardState {
    /// Construct with logging disabled by default.
    pub fn new() -> Self {
        Self {
            enabled: AtomicBool::new(false),
        }
    }

    /// Check whether Vanguard logging is currently opted in.
    #[inline]
    pub fn is_enabled(&self) -> bool {
        self.enabled.load(Ordering::Acquire)
    }
}

impl Default for VanguardState {
    fn default() -> Self {
        Self::new()
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// IPC COMMAND
// ─────────────────────────────────────────────────────────────────────────────

/// Toggle Vanguard telemetry from the frontend.
///
/// When `enabled` is `true`, the orchestrator will encrypt and archive every
/// successful code-generation recovery pair in the local outbox. No data
/// leaves the device — the encryption key is stored at
/// `.determinex_staging/vault/vault.key` and only the user has access to it.
///
/// When `enabled` is `false` (the default), the logger is a complete no-op:
/// no files are written, no keys are accessed, no VRAM budget is touched.
#[tauri::command]
pub fn toggle_vanguard_telemetry(
    enabled: bool,
    state: State<'_, VanguardState>,
) -> Result<bool, String> {
    state.enabled.store(enabled, Ordering::Release);
    let new_state = state.is_enabled();
    log::info!(
        "[VANGUARD] Telemetry logging toggled: {}",
        if new_state { "ENABLED" } else { "DISABLED" }
    );
    Ok(new_state)
}
