//! TUI application state — thin wrapper around agent-core.

use agent_core::event::*;
use agent_core::reducer::SideEffect;
use agent_core::run_controller::RunController;
use agent_core::state::RunState;
use anyhow::Result;
use context_builder::build_chat_messages;
use model_vllm::chat::ChatMessage;
use model_vllm::{backend::ModelClient, profile::ModelProfile};
use pipeline::executor::PipelineExecutor;
use std::path::{Path, PathBuf};
use tokio::sync::mpsc;

/// Active view in the TUI
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum View {
    Main,
    Stats,
    Candidate,
    Diagnostics,
    Help,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TimelineRole {
    User,
    Agent,
    Activity,
    Success,
    Error,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TimelineEntry {
    pub role: TimelineRole,
    pub content: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ServiceHealth {
    Checking,
    Healthy,
    Unavailable(String),
}

#[derive(Debug)]
pub enum ChatEvent {
    Completed(ModelResult),
    Failed(String),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum LocalQuery {
    Model,
    Endpoint,
    Service,
    Status,
}

#[derive(Debug, Clone, PartialEq, Eq)]
enum InputIntent {
    Local(LocalQuery),
    Chat(String),
    Task(String),
}

/// Whether printable keys edit the prompt or control the dashboard.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum InputMode {
    Editing,
    Navigation,
}

/// TUI application state
pub struct App {
    pub profile: ModelProfile,
    pub controller: Option<RunController>,
    pub dummy_run: RunState,
    pub view: View,
    pub should_quit: bool,
    pub candidate: String,
    pub diagnostics: String,
    pub scroll_offset: u16,
    /// Number of rendered rows to browse backward from the latest transcript.
    pub transcript_scroll_back: u16,
    pub proxy_event_rx: Option<mpsc::Receiver<RunEvent>>,
    pub controller_event_tx: Option<mpsc::Sender<RunEvent>>,
    pub executor_effect_tx: Option<mpsc::Sender<SideEffect>>,
    executor_worker: Option<tokio::task::JoinHandle<()>>,
    chat_worker: Option<tokio::task::JoinHandle<()>>,
    pub chat_event_rx: Option<mpsc::Receiver<ChatEvent>>,
    pub chat_in_flight: bool,
    /// Whether the main surface should reserve space for the current task plan.
    pub task_surface_active: bool,
    pub input_mode: InputMode,
    pub input_buffer: String,
    /// Cursor position measured in Unicode scalar values.
    pub input_cursor: usize,
    pub input_cursor_visible: bool,
    pub plan_pulse_phase: u8,
    pub input_notice: Option<String>,
    pub timeline: Vec<TimelineEntry>,
    pub service_health: ServiceHealth,
    pub show_right_panel: bool,
    pub last_context_tokens: u64,
    pub max_context_tokens: u64,
}

impl App {
    pub fn new() -> Result<Self> {
        let profile = if let Ok(configured) = std::env::var("KLINTCODE_PROFILE") {
            ModelProfile::load(Path::new(&configured))?
        } else {
            let default_profile = PathBuf::from("profiles/local-qwen.toml");
            if default_profile.exists() {
                ModelProfile::load(&default_profile)?
            } else {
                toml::from_str(include_str!(
                    "../../../profiles/local-qwen.toml"
                ))?
            }
        };

        let max_repairs = profile.run.max_repairs;
        let run_id = format!("run-{}", chrono::Utc::now().format("%Y%m%d-%H%M%S"));
        let run = RunState::new(run_id, max_repairs);

        Ok(Self {
            profile,
            controller: None,
            dummy_run: run,
            view: View::Main,
            should_quit: false,
            candidate: String::new(),
            diagnostics: String::new(),
            scroll_offset: 0,
            transcript_scroll_back: 0,
            proxy_event_rx: None,
            controller_event_tx: None,
            executor_effect_tx: None,
            executor_worker: None,
            chat_worker: None,
            chat_event_rx: None,
            chat_in_flight: false,
            task_surface_active: true,
            input_mode: InputMode::Editing,
            input_buffer: String::new(),
            input_cursor: 0,
            input_cursor_visible: true,
            plan_pulse_phase: 2,
            input_notice: None,
            timeline: Vec::new(),
            service_health: ServiceHealth::Checking,
            show_right_panel: true,
            last_context_tokens: 0,
            max_context_tokens: 0,
        })
    }

    /// Probe the configured model backend without sending a generation request.
    pub async fn probe_model_service(profile: ModelProfile) -> ServiceHealth {
        let client = match ModelClient::from_profile(profile) {
            Ok(client) => client,
            Err(error) => return ServiceHealth::Unavailable(error.to_string()),
        };
        match client.health_check().await {
            Ok(true) => ServiceHealth::Healthy,
            Ok(false) => ServiceHealth::Unavailable("health check failed".to_string()),
            Err(error) => ServiceHealth::Unavailable(error.to_string()),
        }
    }

    pub async fn start_task(&mut self, task_path: &Path) -> Result<()> {
        self.task_surface_active = true;
        let mut executor = self.initialize_run().await?;
        executor.load_task_from_path(task_path).await;
        self.start_executor_worker(executor);
        Ok(())
    }

    async fn initialize_run(&mut self) -> Result<PipelineExecutor> {
        if let Some(worker) = self.executor_worker.take() {
            worker.abort();
        }
        self.executor_effect_tx = None;

        let max_repairs = self.profile.run.max_repairs;
        let run_id = format!("run-{}", chrono::Utc::now().format("%Y%m%d-%H%M%S"));

        let (side_effect_tx, _side_effect_rx) = mpsc::channel(32);
        let (controller, controller_event_tx) =
            RunController::new(run_id.clone(), max_repairs, side_effect_tx);

        let (proxy_event_tx, proxy_event_rx) = mpsc::channel(64);

        let runs_root = PathBuf::from("runs");
        let executor =
            PipelineExecutor::new(self.profile.clone(), proxy_event_tx, runs_root, run_id);

        self.proxy_event_rx = Some(proxy_event_rx);
        self.controller_event_tx = Some(controller_event_tx);
        self.controller = Some(controller);

        Ok(executor)
    }

    fn start_executor_worker(&mut self, mut executor: PipelineExecutor) {
        let (effect_tx, mut effect_rx) = mpsc::channel(32);
        self.executor_effect_tx = Some(effect_tx);
        self.executor_worker = Some(tokio::spawn(async move {
            while let Some(effect) = effect_rx.recv().await {
                executor.handle(effect).await;
            }
        }));
    }

    /// Submit the current composer text as a fresh in-memory task.
    pub async fn submit_input(&mut self) -> Result<()> {
        let prompt = self.input_buffer.trim().to_string();
        if prompt.is_empty() {
            self.input_notice = Some("Enter a task or question".to_string());
            return Ok(());
        }
        if prompt.starts_with('/')
            && !prompt.to_ascii_lowercase().starts_with("/task ")
            && !prompt.to_ascii_lowercase().starts_with("/ask ")
            && !prompt.to_ascii_lowercase().starts_with("/chat ")
        {
            self.execute_slash_command(&prompt);
            return Ok(());
        }
        let intent = classify_input(&prompt);
        if matches!(intent, InputIntent::Task(_) | InputIntent::Chat(_))
            && (self.run_state().state.is_active() || self.chat_in_flight)
        {
            self.input_notice =
                Some("A task is already running; press Esc, then c to cancel".to_string());
            return Ok(());
        }

        self.timeline.push(TimelineEntry {
            role: TimelineRole::User,
            content: prompt.clone(),
        });
        self.transcript_scroll_back = 0;
        match intent {
            InputIntent::Local(query) => {
                if !self.run_state().state.is_active() {
                    self.task_surface_active = false;
                }
                self.timeline.push(TimelineEntry {
                    role: TimelineRole::Agent,
                    content: self.local_answer(query),
                });
                self.clear_input("Answered locally");
            }
            InputIntent::Chat(question) => {
                self.task_surface_active = false;
                self.start_chat(question)?;
                self.clear_input("Answering");
            }
            InputIntent::Task(task) => {
                self.task_surface_active = true;
                let mut executor = self.initialize_run().await?;
                
                // Determine build target from user intent
                let lower_task = task.to_lowercase();
                if lower_task.contains("rust") {
                    executor.set_build_target("rust-lib-core".to_string());
                } else if lower_task.contains("java") {
                    executor.set_build_target("java-spring-boot-lib-core".to_string());
                }

                executor.load_task_from_text(&task).await;
                self.start_executor_worker(executor);
                self.clear_input("Task submitted");
            }
        }
        Ok(())
    }

    fn clear_input(&mut self, notice: &str) {
        self.input_buffer.clear();
        self.input_cursor = 0;
        self.input_cursor_visible = true;
        self.input_notice = Some(notice.to_string());
    }

    fn local_answer(&self, query: LocalQuery) -> String {
        match query {
            LocalQuery::Model => format!("Current model: {}", self.profile.model.name),
            LocalQuery::Endpoint => {
                format!("Current endpoint: {}", self.profile.resolve_endpoint())
            }
            LocalQuery::Service => format!(
                "Model service: {}",
                match &self.service_health {
                    ServiceHealth::Checking => "checking".to_string(),
                    ServiceHealth::Healthy => "healthy".to_string(),
                    ServiceHealth::Unavailable(detail) => format!("unavailable · {detail}"),
                }
            ),
            LocalQuery::Status => format!(
                "Model: {}\nEndpoint: {}\nService: {}",
                self.profile.model.name,
                self.profile.resolve_endpoint(),
                match &self.service_health {
                    ServiceHealth::Checking => "checking".to_string(),
                    ServiceHealth::Healthy => "healthy".to_string(),
                    ServiceHealth::Unavailable(detail) => format!("unavailable · {detail}"),
                }
            ),
        }
    }

    fn start_chat(&mut self, question: String) -> Result<()> {
        if let Some(worker) = self.chat_worker.take() {
            worker.abort();
        }
        let profile = self.profile.clone();
        let message_pairs = build_chat_messages(&question, &profile.model.name);
        let messages = message_pairs
            .into_iter()
            .map(|(role, content)| ChatMessage {
                role: role.clone(),
                content: Some(content.clone()),
                name: None,
                tool_calls: None,
                tool_call_id: None,
            })
            .collect();
        let client = ModelClient::from_profile(profile)?;
        let (event_tx, event_rx) = mpsc::channel(1);
        self.chat_event_rx = Some(event_rx);
        self.chat_in_flight = true;
        self.chat_worker = Some(tokio::spawn(async move {
            let event = match client.chat(messages, None, None).await {
                Ok(result) => ChatEvent::Completed(result),
                Err(error) => ChatEvent::Failed(error.to_string()),
            };
            let _ = event_tx.send(event).await;
        }));
        Ok(())
    }

    pub fn observe_chat_event(&mut self, event: ChatEvent) {
        self.chat_in_flight = false;
        self.chat_event_rx = None;
        self.chat_worker = None;
        match event {
            ChatEvent::Completed(result) => {
                if let Some(controller) = self.controller.as_mut() {
                    controller.state.record_model_usage(result.usage);
                } else {
                    self.dummy_run.record_model_usage(result.usage);
                }
                self.timeline.push(TimelineEntry {
                    role: TimelineRole::Agent,
                    content: result.content,
                });
                self.input_notice = Some("Answer complete".to_string());
            }
            ChatEvent::Failed(error) => {
                self.timeline.push(TimelineEntry {
                    role: TimelineRole::Error,
                    content: format!("Answer failed · {error}"),
                });
                self.input_notice = Some("Answer failed".to_string());
            }
        }
        self.transcript_scroll_back = 0;
    }

    fn execute_slash_command(&mut self, command: &str) {
        let normalized = command.trim().to_ascii_lowercase();
        let notice = match normalized.as_str() {
            "/q" | "/exit" => {
                self.should_quit = true;
                return;
            }
            "/stats" | "/plan" => {
                self.view = View::Stats;
                "Opened stats"
            }
            "/main" | "/chat" => {
                self.view = View::Main;
                "Returned to main"
            }
            "/candidate" => {
                self.view = View::Candidate;
                "Opened candidate"
            }
            "/diagnostics" => {
                self.view = View::Diagnostics;
                "Opened diagnostics"
            }
            "/help" => {
                self.view = View::Help;
                "Opened help"
            }
            "/clear" => {
                self.timeline.clear();
                self.transcript_scroll_back = 0;
                "Main timeline cleared"
            }
            "/panel" => {
                self.show_right_panel = !self.show_right_panel;
                if self.show_right_panel { "Panel opened" } else { "Panel closed" }
            }
            _ => {
                self.input_notice = Some(
                    "Unknown command; use /task … /ask … /main /stats /panel /candidate /diagnostics /help"
                        .to_string(),
                );
                return;
            }
        };
        self.input_buffer.clear();
        self.input_cursor = 0;
        self.input_cursor_visible = true;
        self.input_notice = Some(notice.to_string());
    }

    /// Add durable, compact activity to the main conversation surface.
    pub fn observe_event(&mut self, event: &RunEvent) {
        if let RunEvent::ModelCompleted(result) = event {
            self.candidate = result.content.clone();
            // Track per-call context window size
            let prompt = u64::from(result.usage.prompt_tokens);
            self.last_context_tokens = prompt;
            if prompt > self.max_context_tokens {
                self.max_context_tokens = prompt;
            }
        }
        let entry = match event {
            RunEvent::TaskLoaded(task) => {
                Some((TimelineRole::Activity, format!("Loaded task {}", task.name)))
            }
            RunEvent::ModelCompleted(result) => Some((
                TimelineRole::Agent,
                compact_candidate_message(&result.content),
            )),
            RunEvent::ModelFailed(error) | RunEvent::Failed(error) => {
                Some((TimelineRole::Error, error.to_string()))
            }
            RunEvent::ValidationCompleted(result) => {
                let status = if result.passed { "passed" } else { "failed" };
                let role = if result.passed {
                    TimelineRole::Activity
                } else {
                    TimelineRole::Error
                };
                // Main summary line
                self.timeline.push(TimelineEntry {
                    role: role.clone(),
                    content: format!(
                        "L{} {} {} · {} errors · {} warnings",
                        result.level,
                        result.level_name,
                        status,
                        result.error_count,
                        result.warning_count
                    ),
                });
                // Show actionable errors
                if !result.passed {
                    for err in result.actionable_errors.iter().take(5) {
                        self.timeline.push(TimelineEntry {
                            role: TimelineRole::Error,
                            content: format!("  ▸ {err}"),
                        });
                    }
                    // Show first part of diagnostic if present
                    if !result.diagnostic.is_empty() {
                        let diag: String = result.diagnostic.chars().take(300).collect();
                        self.timeline.push(TimelineEntry {
                            role: TimelineRole::Error,
                            content: format!("  diagnostic: {diag}"),
                        });
                    }
                }
                None
            }
            RunEvent::FinalArtifactWritten(path) => Some((
                TimelineRole::Success,
                format!("Task complete · Artifact {}", path.display()),
            )),
            RunEvent::ConsentRequired { action } => Some((
                TimelineRole::Activity,
                format!("Awaiting consent: {action}"),
            )),
            RunEvent::ToolProcessStarted { command, .. } => Some((
                TimelineRole::Activity,
                format!("$ {}", command),
            )),
            RunEvent::ToolProcessFinished { id, success, .. } => self
                .run_state()
                .tool_processes
                .iter()
                .find(|process| process.id == *id)
                .map(|process| {
                    (
                        if *success {
                            TimelineRole::Success
                        } else {
                            TimelineRole::Error
                        },
                        format!(
                            "Tool {} · $ {}",
                            if *success { "complete" } else { "failed" },
                            process.command
                        ),
                    )
                }),
            RunEvent::PreflightPassed(budget) => Some((
                TimelineRole::Activity,
                format!(
                    "Preflight passed · estimated {} / limit {}",
                    budget.estimated_prompt, budget.prompt_limit
                ),
            )),
            RunEvent::PreflightFailed(reason) => Some((
                TimelineRole::Error,
                format!("Preflight failed · {reason}"),
            )),
            RunEvent::TaskLoadFailed(reason) => Some((
                TimelineRole::Error,
                format!("Task load failed · {reason}"),
            )),
            RunEvent::ConsentDenied(reason) => Some((
                TimelineRole::Error,
                format!("Consent denied · {reason}"),
            )),
            _ => None,
        };
        if let Some((role, content)) = entry {
            self.timeline.push(TimelineEntry { role, content });
        }
    }

    pub fn insert_input_char(&mut self, character: char) {
        let byte_index = self.input_byte_index();
        self.input_buffer.insert(byte_index, character);
        self.input_cursor += 1;
        self.input_cursor_visible = true;
        self.input_notice = None;
    }

    pub fn insert_input_newline(&mut self) {
        self.insert_input_char('\n');
    }

    pub fn backspace_input(&mut self) {
        if self.input_cursor == 0 {
            return;
        }
        let end = self.input_byte_index();
        self.input_cursor -= 1;
        let start = self.input_byte_index();
        self.input_buffer.replace_range(start..end, "");
        self.input_cursor_visible = true;
        self.input_notice = None;
    }

    pub fn delete_input(&mut self) {
        if self.input_cursor >= self.input_buffer.chars().count() {
            return;
        }
        let start = self.input_byte_index();
        let end = self
            .input_buffer
            .char_indices()
            .nth(self.input_cursor + 1)
            .map(|(index, _)| index)
            .unwrap_or(self.input_buffer.len());
        self.input_buffer.replace_range(start..end, "");
        self.input_cursor_visible = true;
        self.input_notice = None;
    }

    pub fn move_input_left(&mut self) {
        self.input_cursor = self.input_cursor.saturating_sub(1);
        self.input_cursor_visible = true;
    }

    pub fn move_input_right(&mut self) {
        self.input_cursor = (self.input_cursor + 1).min(self.input_buffer.chars().count());
        self.input_cursor_visible = true;
    }

    pub fn move_input_home(&mut self) {
        self.input_cursor = 0;
        self.input_cursor_visible = true;
    }

    pub fn move_input_end(&mut self) {
        self.input_cursor = self.input_buffer.chars().count();
        self.input_cursor_visible = true;
    }

    fn input_byte_index(&self) -> usize {
        self.input_buffer
            .char_indices()
            .nth(self.input_cursor)
            .map(|(index, _)| index)
            .unwrap_or(self.input_buffer.len())
    }

    pub fn run_state(&self) -> &RunState {
        self.controller
            .as_ref()
            .map(|c| &c.state)
            .unwrap_or(&self.dummy_run)
    }

    /// Completed steps and total steps in the first-class run plan.
    pub fn plan_progress(&self) -> (usize, usize) {
        let run = self.run_state();
        let completed = run
            .plan
            .iter()
            .filter(|step| matches!(step.status, agent_core::shared::PlanStepStatus::Completed))
            .count();
        (completed, run.plan.len())
    }
}

fn compact_candidate_message(content: &str) -> String {
    const PREVIEW_LINES: usize = 6;
    let lines = content.lines().collect::<Vec<_>>();
    let mut message = format!("Generated candidate · {} lines", lines.len());
    if !lines.is_empty() {
        message.push('\n');
        message.push_str(
            &lines
                .iter()
                .take(PREVIEW_LINES)
                .copied()
                .collect::<Vec<_>>()
                .join("\n"),
        );
    }
    if lines.len() > PREVIEW_LINES {
        message.push_str(&format!(
            "\n… {} more lines · /candidate for full content",
            lines.len() - PREVIEW_LINES
        ));
    }
    message
}

impl Drop for App {
    fn drop(&mut self) {
        if let Some(worker) = self.executor_worker.take() {
            worker.abort();
        }
        if let Some(worker) = self.chat_worker.take() {
            worker.abort();
        }
    }
}

fn classify_input(prompt: &str) -> InputIntent {
    let trimmed = prompt.trim();
    let lower = trimmed.to_ascii_lowercase();
    if lower.starts_with("/task ") {
        return InputIntent::Task(trimmed["/task ".len()..].trim().to_string());
    }
    if lower.starts_with("/ask ") {
        return InputIntent::Chat(trimmed["/ask ".len()..].trim().to_string());
    }
    if lower.starts_with("/chat ") {
        return InputIntent::Chat(trimmed["/chat ".len()..].trim().to_string());
    }

    let asks_model = contains_any(
        &lower,
        &[
            "\u{4ec0}\u{4e48}\u{6a21}\u{578b}",
            "\u{54ea}\u{4e2a}\u{6a21}\u{578b}",
            "\u{5f53}\u{524d}\u{6a21}\u{578b}",
            "\u{6a21}\u{578b}\u{540d}\u{79f0}",
            "model \u{662f}",
            "model name",
            "which model",
        ],
    );
    if asks_model {
        return InputIntent::Local(LocalQuery::Model);
    }
    if contains_any(
        &lower,
        &[
            "endpoint",
            "\u{7aef}\u{70b9}",
            "\u{670d}\u{52a1}\u{5730}\u{5740}",
            "\u{63a5}\u{53e3}\u{5730}\u{5740}",
        ],
    ) {
        return InputIntent::Local(LocalQuery::Endpoint);
    }
    if contains_any(
        &lower,
        &[
            "\u{670d}\u{52a1}\u{6b63}\u{5e38}",
            "\u{670d}\u{52a1}\u{5065}\u{5eb7}",
            "\u{5065}\u{5eb7}\u{72b6}\u{6001}",
            "service healthy",
        ],
    ) {
        return InputIntent::Local(LocalQuery::Service);
    }
    if contains_any(
        &lower,
        &[
            "\u{5f53}\u{524d}\u{72b6}\u{6001}",
            "agent status",
            "\u{7cfb}\u{7edf}\u{72b6}\u{6001}",
        ],
    ) {
        return InputIntent::Local(LocalQuery::Status);
    }

    let conversational_openers = [
        "\u{5982}\u{4f55}",
        "\u{4e3a}\u{4ec0}\u{4e48}",
        "\u{600e}\u{4e48}",
        "\u{8bf7}\u{89e3}\u{91ca}",
        "\u{89e3}\u{91ca}",
        "\u{4ecb}\u{7ecd}",
        "\u{544a}\u{8bc9}\u{6211}",
        "how ",
        "why ",
        "what ",
        "explain ",
        "describe ",
    ];
    if conversational_openers
        .iter()
        .any(|opener| lower.starts_with(opener))
    {
        return InputIntent::Chat(trimmed.to_string());
    }

    let task_keywords = ["teaql", "rust", "java"];
    if contains_any(&lower, &task_keywords) {
        InputIntent::Task(trimmed.to_string())
    } else {
        InputIntent::Chat(trimmed.to_string())
    }
}

fn contains_any(content: &str, needles: &[&str]) -> bool {
    needles.iter().any(|needle| content.contains(needle))
}

#[cfg(test)]
mod tests {
    use super::*;
    use agent_core::state::PipelineState;

    #[test]
    fn composer_edits_unicode_at_character_boundaries() {
        let mut app = App::new().expect("app");
        app.insert_input_char('\u{6539}');
        app.insert_input_char('A');
        app.move_input_left();
        app.insert_input_char('\u{597d}');

        assert_eq!(app.input_buffer, "\u{6539}\u{597d}A");
        assert_eq!(app.input_cursor, 2);

        app.backspace_input();
        assert_eq!(app.input_buffer, "\u{6539}A");
        app.delete_input();
        assert_eq!(app.input_buffer, "\u{6539}");
    }

    #[test]
    fn finished_tool_is_added_to_the_main_timeline_without_exit_code() {
        let mut app = App::new().expect("app");
        app.dummy_run
            .start_tool_process(4, "cargo check".to_string());

        app.observe_event(&RunEvent::ToolProcessFinished {
            id: 4,
            success: false,
            exit_code: Some(101),
        });

        let entry = app.timeline.last().expect("tool timeline entry");
        assert_eq!(entry.role, TimelineRole::Error);
        assert_eq!(entry.content, "Tool failed · $ cargo check");
        assert!(!entry.content.contains("101"));
    }

    #[test]
    fn candidate_timeline_entry_is_bounded_and_points_to_full_view() {
        let content = (1..=20)
            .map(|line| format!("candidate-line-{line}"))
            .collect::<Vec<_>>()
            .join("\n");

        let compact = compact_candidate_message(&content);

        assert!(compact.contains("Generated candidate · 20 lines"));
        assert!(compact.contains("candidate-line-1"));
        assert!(compact.contains("candidate-line-6"));
        assert!(!compact.contains("candidate-line-7"));
        assert!(compact.contains("/candidate"));
        assert_eq!(compact.lines().count(), 8);
    }

    #[test]
    fn final_artifact_is_a_clear_success_timeline_entry() {
        let mut app = App::new().expect("app");

        app.observe_event(&RunEvent::FinalArtifactWritten(
            "runs/run-1/final-artifact".into(),
        ));

        let entry = app.timeline.last().expect("completion entry");
        assert_eq!(entry.role, TimelineRole::Success);
        assert_eq!(
            entry.content,
            "Task complete · Artifact runs/run-1/final-artifact"
        );
    }

    #[tokio::test]
    async fn active_run_rejects_a_second_submission_without_losing_draft() {
        let mut app = App::new().expect("app");
        app.input_buffer = "next task".to_string();
        app.input_cursor = app.input_buffer.chars().count();
        app.dummy_run.state = PipelineState::Generating { attempt: 1 };

        app.submit_input().await.expect("submission check");

        assert_eq!(app.input_buffer, "next task");
        assert!(
            app.input_notice
                .as_deref()
                .expect("notice")
                .contains("already running")
        );
    }

    #[test]
    fn input_router_separates_local_questions_chat_and_tasks() {
        assert_eq!(
            classify_input("which model?"),
            InputIntent::Local(LocalQuery::Model)
        );
        assert_eq!(
            classify_input("why does this need an isolated environment?"),
            InputIntent::Chat("why does this need an isolated environment?".to_string())
        );
        assert_eq!(
            classify_input("how should input routing work?"),
            InputIntent::Chat("how should input routing work?".to_string())
        );
        assert_eq!(
            classify_input("fix input routing and add tests"),
            InputIntent::Task("fix input routing and add tests".to_string())
        );
        assert_eq!(
            classify_input("/ask what is the difference between implementation and repair?"),
            InputIntent::Chat(
                "what is the difference between implementation and repair?".to_string()
            )
        );
        assert_eq!(
            classify_input("/task explain the existing code"),
            InputIntent::Task("explain the existing code".to_string())
        );

        let cjk_task = "\u{4fee}\u{590d}\u{8f93}\u{5165}\u{8def}\u{7531}";
        assert_eq!(
            classify_input(cjk_task),
            InputIntent::Task(cjk_task.to_string())
        );
    }

    #[tokio::test]
    async fn model_question_is_answered_locally_without_starting_pipeline() {
        let mut app = App::new().expect("app");
        let expected_model = app.profile.model.name.clone();
        app.input_buffer = "which model?".to_string();
        app.input_cursor = app.input_buffer.chars().count();

        app.submit_input().await.expect("local answer");

        assert!(app.controller.is_none());
        assert!(!app.chat_in_flight);
        assert!(!app.task_surface_active);
        assert_eq!(app.timeline.len(), 2);
        assert_eq!(app.timeline[1].role, TimelineRole::Agent);
        assert_eq!(
            app.timeline[1].content,
            format!("Current model: {expected_model}")
        );
    }

    #[tokio::test]
    async fn ordinary_question_uses_simulated_chat_without_starting_pipeline() {
        let mut app = App::new().expect("app");
        let mut profile: ModelProfile =
            toml::from_str(include_str!("../../../profiles/simulator.toml"))
                .expect("simulator profile");
        profile.simulator.scenario = Some(
            PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../simulator/scenarios/chat.toml"),
        );
        app.profile = profile;
        app.input_buffer = "Who are you?".to_string();
        app.input_cursor = app.input_buffer.chars().count();

        app.submit_input().await.expect("submit chat");

        assert!(app.controller.is_none());
        assert!(app.chat_in_flight);
        assert!(!app.task_surface_active);
        let event = app
            .chat_event_rx
            .as_mut()
            .expect("chat event receiver")
            .recv()
            .await
            .expect("simulated chat response");
        app.observe_chat_event(event);

        assert!(!app.chat_in_flight);
        assert_eq!(
            app.timeline.last().expect("chat answer").content,
            "I am Klint, an isolated-environment coding agent built by TeaQL."
        );
        assert_eq!(app.dummy_run.token_totals.input_tokens, 80);
        assert_eq!(app.dummy_run.token_totals.output_tokens, 18);
    }

    #[tokio::test]
    async fn submitted_text_enters_the_normal_pipeline_as_an_inline_task() {
        let mut app = App::new().expect("app");
        app.input_buffer = "add a school entity".to_string();
        app.input_cursor = app.input_buffer.chars().count();

        app.submit_input().await.expect("submit inline task");
        let event = app
            .proxy_event_rx
            .as_mut()
            .expect("executor event receiver")
            .recv()
            .await
            .expect("task-loaded event");
        app.controller_event_tx
            .as_ref()
            .expect("controller event sender")
            .send(event)
            .await
            .expect("forward task-loaded event");
        let effect = app
            .controller
            .as_mut()
            .expect("controller")
            .process_next()
            .await
            .expect("task-loaded effect");

        assert!(matches!(
            effect,
            agent_core::reducer::SideEffect::RunPreflight
        ));
        assert_eq!(
            app.run_state().task_name.as_deref(),
            Some("interactive-task")
        );
        assert!(matches!(app.run_state().state, PipelineState::Preflight));
        assert!(app.input_buffer.is_empty());
    }

    #[tokio::test]
    async fn slash_commands_switch_surfaces_without_starting_a_run() {
        let mut app = App::new().expect("app");
        app.input_buffer = "/stats".to_string();
        app.input_cursor = app.input_buffer.len();

        app.submit_input().await.expect("switch to stats");
        assert_eq!(app.view, View::Stats);
        assert!(app.controller.is_none());

        app.input_buffer = "/main".to_string();
        app.input_cursor = app.input_buffer.len();
        app.submit_input().await.expect("switch to main");
        assert_eq!(app.view, View::Main);
        assert!(app.controller.is_none());
    }

    #[tokio::test]
    async fn simulator_health_probe_validates_the_configured_scenario() {
        let mut profile: ModelProfile =
            toml::from_str(include_str!("../../../profiles/simulator.toml"))
                .expect("simulator profile");
        profile.simulator.scenario = Some(
            PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                .join("../../simulator/scenarios/happy-path.toml"),
        );

        let health = App::probe_model_service(profile).await;

        assert_eq!(health, ServiceHealth::Healthy);
    }
}
