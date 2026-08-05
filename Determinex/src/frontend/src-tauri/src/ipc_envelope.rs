//! The one typed shape for command responses.
//!
//! 36 commands returned an untyped `serde_json::Value` built inline with
//! `serde_json::json!`. Every one of those made the frontend's declared interface
//! an unverified assertion: nothing stopped a field being renamed on one side
//! only, which is exactly how seven argument bugs shipped before `argContract`
//! existed.
//!
//! Nearly all of them share one wire shape -- `{ ok, data?, error? }` -- expressed
//! 60-odd times as separate literals. That repetition is the defect: `session.rs`
//! alone wrote it 21 times, so a typo in any single one was invisible.
//!
//! `data` and `error` are skipped when absent rather than serialised as `null`,
//! which matches what the existing TypeScript readers expect (`result.data` is
//! checked for truthiness, and `error?: string` is optional).

use serde::Serialize;

#[derive(Serialize)]
pub struct Envelope<T> {
    pub ok: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub data: Option<T>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
    /// Several hive oracle commands report whether they answered from a real
    /// model or a packaged fallback. It lives on the envelope rather than in six
    /// near-identical per-command structs, and is skipped when absent so the wire
    /// shape is unchanged for the commands that never set it.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub advisor_mode: Option<String>,
}

impl<T> Envelope<T> {
    pub fn ok(data: T) -> Self {
        Self { ok: true, data: Some(data), error: None, advisor_mode: None }
    }

    /// Mark this answer as coming from the packaged fallback rather than a model.
    pub fn advisor_mode(mut self, mode: impl Into<String>) -> Self {
        self.advisor_mode = Some(mode.into());
        self
    }

    /// A successful call with nothing to return. Still `ok: true`, so the caller's
    /// success check does not depend on whether a payload happened to exist.
    pub fn done() -> Self {
        Self { ok: true, data: None, error: None, advisor_mode: None }
    }

    pub fn err(message: impl Into<String>) -> Self {
        Self { ok: false, data: None, error: Some(message.into()), advisor_mode: None }
    }
}
