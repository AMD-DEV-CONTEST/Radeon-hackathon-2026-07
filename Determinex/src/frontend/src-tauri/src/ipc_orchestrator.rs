use crate::ipc_envelope::Envelope;
use crate::orchestrator::{
    Context, EngineerCode, MoAResult, ObserverVerdict, OrchestratorError, OrchestratorHandle,
    SentinelPlan,
};
use serde::{Deserialize, Serialize};
/// ipc_orchestrator.rs — Tauri IPC Bridge for the MoA Orchestrator
///
/// These are the thin async command handlers that sit between the React frontend
/// and the internal OrchestratorHandle. Each handler:
///   1. Deserializes the IPC payload from the Tauri invoke call
///   2. Dispatches to the actor via OrchestratorHandle (non-blocking through the MPSC channel)
///   3. Awaits the oneshot reply and serializes the result back to the frontend
///
/// The Tauri runtime calls these on a managed thread pool. The `.await` inside
/// each command suspends that handler without blocking any Tauri threads — the
/// sequential guarantee lives entirely inside the actor loop, not here.
use tauri::State;

// ─────────────────────────────────────────────────────────────────────────────
// IPC PAYLOADS (Deserialize from JS invoke arguments)
// ─────────────────────────────────────────────────────────────────────────────

#[derive(Deserialize)]
pub struct PlanRequestPayload {
    pub user_prompt: String,
    pub thread_id: String,
    #[serde(default)]
    pub retry_count: u32,
    #[serde(default)]
    pub model_override: Option<String>,
}

#[derive(Deserialize)]
pub struct CodeGenPayload {
    pub plan: SentinelPlan,
    pub thread_id: String,
    #[serde(default)]
    pub retry_count: u32,
    #[serde(default)]
    pub model_override: Option<String>,
}

#[derive(Deserialize)]
pub struct AuditPayload {
    pub code: EngineerCode,
    pub thread_id: String,
    #[serde(default)]
    pub model_override: Option<String>,
}

// ─────────────────────────────────────────────────────────────────────────────
// IPC RESPONSE WRAPPERS
// These wrap the inner result so the frontend always gets a consistent
// { "ok": true, "data": ... } | { "ok": false, "error": ... } envelope.
// ─────────────────────────────────────────────────────────────────────────────

/// Converts any Result<T, OrchestratorError> into the uniform envelope.
/// Frontend discriminates on `result.ok` — true for success, false for failure.
///
/// This was already generic over `T` and then erased that type by building a
/// `serde_json::json!` literal, so all three orchestrate commands returned an
/// untyped Value despite the payload type being known right here. Returning
/// `Envelope<T>` keeps it.
fn to_ipc_result<T: Serialize>(
    result: Result<T, OrchestratorError>,
) -> Result<Envelope<T>, String> {
    match result {
        Ok(data) => Ok(Envelope::ok(data)),
        Err(e) => Ok(Envelope::err(e.to_string())),
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// IPC COMMANDS
// ─────────────────────────────────────────────────────────────────────────────

/// Trigger a full 3-stage MoA pipeline: Sentinel → Engineer → Observer.
/// The call will block until the Observer completes (up to ~15 min for large tasks).
/// The sequential execution guarantee inside the actor means only ONE LLM runs at a time.
#[tauri::command]
pub async fn orchestrate_plan(
    payload: PlanRequestPayload,
    handle: State<'_, OrchestratorHandle>,
) -> Result<Envelope<MoAResult>, String> {
    log::info!(
        "[IPC] orchestrate_plan invoked for thread: {}",
        payload.thread_id
    );

    let context = Context {
        user_prompt: payload.user_prompt,
        thread_id: payload.thread_id,
        retry_count: payload.retry_count,
        model_override: payload.model_override,
    };

    let result: Result<MoAResult, OrchestratorError> = handle.plan_request(context).await;

    if let Ok(ref r) = result {
        log::info!(
            "[IPC] orchestrate_plan complete: thread={}, accepted={}, verdict={}",
            r.thread_id,
            r.accepted,
            r.audit.verdict
        );
    }

    to_ipc_result(result)
}

/// Skip the Sentinel and drive the Engineer + Observer directly with a pre-built plan.
/// Used by the frontend retry flow when the plan is valid but the generated code failed audit.
#[tauri::command]
pub async fn orchestrate_codegen(
    payload: CodeGenPayload,
    handle: State<'_, OrchestratorHandle>,
) -> Result<Envelope<MoAResult>, String> {
    log::info!(
        "[IPC] orchestrate_codegen (plan-skip) for thread: {}",
        payload.thread_id
    );

    let result = handle
        .code_generation(
            payload.plan,
            payload.thread_id,
            payload.retry_count,
            payload.model_override,
        )
        .await;
    to_ipc_result(result)
}

/// Submit existing code directly to the Observer for a standalone audit.
/// Does not modify any database state — pure inspection.
#[tauri::command]
pub async fn orchestrate_audit(
    payload: AuditPayload,
    handle: State<'_, OrchestratorHandle>,
) -> Result<Envelope<ObserverVerdict>, String> {
    log::info!(
        "[IPC] orchestrate_audit (observer-only) for thread: {}",
        payload.thread_id
    );

    let result: Result<ObserverVerdict, OrchestratorError> = handle
        .audit_request(payload.code, payload.thread_id, payload.model_override)
        .await;
    to_ipc_result(result)
}

/// Gracefully shut down the orchestrator's actor loop.
/// Call this from the frontend's `onUnmount` or app close handler.
#[tauri::command]
pub async fn orchestrator_shutdown(handle: State<'_, OrchestratorHandle>) -> Result<(), String> {
    log::info!("[IPC] orchestrator_shutdown invoked.");
    handle.shutdown().await;
    Ok(())
}
