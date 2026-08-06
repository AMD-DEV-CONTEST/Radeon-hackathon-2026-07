use crate::generic_event::GenericRunEvent;
use crate::generic_reducer::{GenericSideEffect, reduce};
use crate::generic_state::{GenericPipelineState, GenericRunState};
use tokio::sync::mpsc;
use tracing::{debug, error, info};

pub struct GenericRunController {
    pub state: GenericRunState,
    pub event_rx: mpsc::UnboundedReceiver<GenericRunEvent>,
    pub side_effect_tx: mpsc::Sender<GenericSideEffect>,
}

impl GenericRunController {
    pub fn new(
        run_id: String,
        side_effect_tx: mpsc::Sender<GenericSideEffect>,
    ) -> (Self, mpsc::UnboundedSender<GenericRunEvent>) {
        let (event_tx, event_rx) = mpsc::unbounded_channel();
        let state = GenericRunState::new(run_id);
        (
            Self {
                state,
                event_rx,
                side_effect_tx,
            },
            event_tx,
        )
    }

    pub async fn run_to_completion(&mut self) {
        info!("Generic agent loop started");

        while let Some(event) = self.event_rx.recv().await {
            debug!(?event, "Received event");

            // 1. Compute state transition and side effect
            let effect = reduce(&mut self.state, event);

            // 2. Dispatch side effect to the executor
            if !matches!(effect, GenericSideEffect::None) {
                if self.side_effect_tx.send(effect).await.is_err() {
                    error!("Side effect channel closed unexpectedly; marking run as failed");
                    self.state.state = GenericPipelineState::Failed {
                        error: "Side effect channel closed".to_string(),
                    };
                    break;
                }
            }

            // 3. Terminate if we reached a final state
            if !self.state.is_active() {
                info!(state = ?self.state.state, "Agent loop reached terminal state");
                break;
            }
        }

        // If the event channel closed while we're still active, mark as failed
        if self.state.is_active() {
            error!("Event channel closed while state is still active; marking run as failed");
            self.state.state = GenericPipelineState::Failed {
                error: "Event channel closed prematurely".to_string(),
            };
        }
    }
}
