//! Input handling for the TUI.
//! TUI does not directly modify state — it sends RunEvents.

use agent_core::event::RunEvent;
use tokio::sync::mpsc;

/// Input handler that translates user actions into RunEvents.
pub struct InputHandler {
    event_tx: Option<mpsc::Sender<RunEvent>>,
}

impl InputHandler {
    pub fn new() -> Self {
        Self { event_tx: None }
    }

    pub fn set_event_sender(&mut self, tx: mpsc::Sender<RunEvent>) {
        self.event_tx = Some(tx);
    }

    /// Send a cancel request to the state machine.
    pub async fn cancel(&self) {
        if let Some(tx) = &self.event_tx {
            tx.send(RunEvent::CancelRequested).await.ok();
        }
    }
}
