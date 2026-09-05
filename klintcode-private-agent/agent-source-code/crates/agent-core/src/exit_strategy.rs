use crate::chat::ChatMessage;
use crate::loop_guard::LoopDetection;
use std::sync::atomic::{AtomicUsize, Ordering};

/// Context provided to an exit strategy when a loop is detected
pub struct LoopContext<'a> {
    pub detection: &'a LoopDetection,
    pub iteration: usize,
    pub max_iterations: usize,
    pub messages: &'a [ChatMessage],
}

/// Action that an exit strategy decides to take
#[derive(Debug, Clone)]
pub enum ExitAction {
    /// Terminate the agent loop immediately
    Abort { reason: String },
    /// Inject a hint message into the conversation to steer the model
    Intervene { message: String },
    /// Do nothing, let the loop continue
    Ignore,
}

/// Pluggable strategy for handling detected loops
pub trait ExitStrategy: Send + Sync {
    fn on_loop_detected(&self, ctx: &LoopContext) -> ExitAction;
}

// ---------------------------------------------------------------------------
// Built-in strategies
// ---------------------------------------------------------------------------

/// Immediately abort on any detected loop
pub struct AbortStrategy;

impl ExitStrategy for AbortStrategy {
    fn on_loop_detected(&self, ctx: &LoopContext) -> ExitAction {
        ExitAction::Abort {
            reason: format!(
                "Loop detected: {} at iteration {}",
                ctx.detection, ctx.iteration
            ),
        }
    }
}

/// Try to break the loop by injecting a corrective hint.
/// Falls back to abort after `max_interventions` failed attempts.
pub struct InterventionStrategy {
    max_interventions: usize,
    interventions_used: AtomicUsize,
}

impl InterventionStrategy {
    pub fn new(max_interventions: usize) -> Self {
        Self {
            max_interventions,
            interventions_used: AtomicUsize::new(0),
        }
    }
}

impl ExitStrategy for InterventionStrategy {
    fn on_loop_detected(&self, ctx: &LoopContext) -> ExitAction {
        let used = self.interventions_used.fetch_add(1, Ordering::Relaxed);
        if used >= self.max_interventions {
            return ExitAction::Abort {
                reason: format!(
                    "Loop persists after {} interventions: {} at iteration {}",
                    self.max_interventions, ctx.detection, ctx.iteration
                ),
            };
        }

        let hint = match ctx.detection {
            LoopDetection::ToolRepeat {
                tool_name,
                consecutive_count,
            } => format!(
                "[LOOP GUARD] You have called `{}` {} times consecutively with identical \
                 arguments and gotten identical results. This approach is NOT working. \
                 You MUST try a fundamentally different strategy, or call `finish_task` \
                 if the task cannot be completed.",
                tool_name, consecutive_count
            ),
            LoopDetection::PromptRepeat { consecutive_count } => format!(
                "[LOOP GUARD] The conversation state has been identical for {} consecutive \
                 iterations. You appear to be stuck in a loop. Change your approach \
                 immediately, or call `finish_task` to report what you have accomplished.",
                consecutive_count
            ),
        };

        ExitAction::Intervene { message: hint }
    }
}

// ---------------------------------------------------------------------------
// Strategy selection from config
// ---------------------------------------------------------------------------

/// Strategy kind, selectable from profile config
#[derive(Debug, Clone, PartialEq)]
pub enum ExitStrategyKind {
    Abort,
    Intervene { max_interventions: usize },
}

impl Default for ExitStrategyKind {
    fn default() -> Self {
        ExitStrategyKind::Abort
    }
}

impl ExitStrategyKind {
    /// Parse from string (for TOML config)
    pub fn from_str_config(s: &str, max_interventions: usize) -> Self {
        match s.to_lowercase().as_str() {
            "intervene" => ExitStrategyKind::Intervene { max_interventions },
            _ => ExitStrategyKind::Abort,
        }
    }

    /// Build a boxed strategy instance
    pub fn build(&self) -> Box<dyn ExitStrategy> {
        match self {
            ExitStrategyKind::Abort => Box::new(AbortStrategy),
            ExitStrategyKind::Intervene { max_interventions } => {
                Box::new(InterventionStrategy::new(*max_interventions))
            }
        }
    }
}
