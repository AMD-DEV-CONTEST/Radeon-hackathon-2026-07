use crate::event::RunEvent;
use crate::reducer::{SideEffect, reduce};
use crate::state::RunState;
use tokio::sync::mpsc;
use tracing::info;

/// The run controller owns the RunState and processes events.
/// Both TUI and headless CLI use this same controller.
pub struct RunController {
    pub state: RunState,
    event_rx: mpsc::Receiver<RunEvent>,
    event_tx: mpsc::Sender<RunEvent>,
    side_effect_tx: mpsc::Sender<SideEffect>,
}

impl RunController {
    /// Create a new run controller.
    /// Returns the controller and a sender for submitting events.
    pub fn new(
        run_id: String,
        max_repairs: u8,
        side_effect_tx: mpsc::Sender<SideEffect>,
    ) -> (Self, mpsc::Sender<RunEvent>) {
        let (event_tx, event_rx) = mpsc::channel(64);
        let controller = Self {
            state: RunState::new(run_id, max_repairs),
            event_rx,
            event_tx: event_tx.clone(),
            side_effect_tx,
        };
        (controller, event_tx)
    }

    /// Get a clone of the event sender for external use
    pub fn event_sender(&self) -> mpsc::Sender<RunEvent> {
        self.event_tx.clone()
    }

    /// Process the next event from the channel.
    /// Returns the side effect produced, or None if the channel closed.
    pub async fn process_next(&mut self) -> Option<SideEffect> {
        let event = self.event_rx.recv().await?;
        let effect = reduce(&mut self.state, event);

        // Forward the side effect
        if !matches!(effect, SideEffect::None) {
            self.side_effect_tx.send(effect.clone()).await.ok();
        }

        Some(effect)
    }

    /// Run the event loop until a terminal state is reached.
    pub async fn run_to_completion(&mut self) {
        while !self.state.state.is_terminal() {
            match self.process_next().await {
                Some(_) => {}
                None => {
                    info!("Event channel closed");
                    break;
                }
            }
        }
        info!(state = %self.state.state, "Run completed");
    }

    /// Get current pipeline state
    pub fn pipeline_state(&self) -> &crate::state::PipelineState {
        &self.state.state
    }
}
