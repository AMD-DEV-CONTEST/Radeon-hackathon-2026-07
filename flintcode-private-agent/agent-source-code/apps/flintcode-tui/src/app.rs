//! TUI application state — thin wrapper around agent-core.

use agent_core::event::*;
use agent_core::run_controller::RunController;
use agent_core::state::{PipelineState, RunState};
use anyhow::Result;
use model_vllm::profile::ModelProfile;
use pipeline::executor::PipelineExecutor;
use std::path::{Path, PathBuf};
use std::time::Instant;
use tokio::sync::mpsc;

/// Active view in the TUI
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum View {
    Pipeline,
    Task,
    Candidate,
    Diagnostics,
    Config,
    Help,
}

#[derive(Debug, Clone)]
pub enum StageStatus {
    Done,
    Active,
    Pending,
    Failed,
}

/// TUI application state
pub struct App {
    pub profile: ModelProfile,
    pub available_profiles: Vec<PathBuf>,
    pub current_profile_idx: usize,
    pub controller: Option<RunController>,
    pub dummy_run: RunState,
    pub view: View,
    pub should_quit: bool,

    // Candidate multi-file support (Phase 2)
    pub candidate_files: Vec<(String, String)>, // (filename, content)
    pub active_candidate_idx: usize,

    // Diagnostics & Live ReAct Log Stream (Phase 3)
    pub diagnostics: String,
    pub react_logs: Vec<String>,

    pub task_files: Vec<String>,
    pub token_prompt: u32,
    pub token_completion: u32,
    pub scroll_offset: u16,
    pub proxy_event_rx: Option<mpsc::Receiver<RunEvent>>,
    pub controller_event_tx: Option<mpsc::Sender<RunEvent>>,
    pub executor: Option<PipelineExecutor>,

    // Telemetry (Phase 4)
    pub run_start_time: Option<Instant>,
    pub prompt_tps: f64,
    pub generation_tps: f64,
}

impl App {
    pub fn new(profile_override: Option<&Path>, _initial_task: Option<&Path>) -> Result<Self> {
        let available_profiles = Self::discover_profiles();

        let profile_path = if let Some(p) = profile_override {
            p.to_path_buf()
        } else if let Some(first) = available_profiles.first() {
            first.clone()
        } else {
            PathBuf::from("profiles/qwen-3.6-coder.toml")
        };

        let current_profile_idx = available_profiles
            .iter()
            .position(|p| p == &profile_path)
            .unwrap_or(0);

        let profile = if profile_path.exists() {
            ModelProfile::load(&profile_path)?
        } else if Path::new("profiles/qwen-3.6-coder.toml").exists() {
            ModelProfile::load(Path::new("profiles/qwen-3.6-coder.toml"))?
        } else {
            toml::from_str(include_str!("../../../profiles/qwen-3.6-coder.toml"))?
        };

        let max_repairs = profile.run.max_repairs;
        let run_id = format!("run-{}", chrono::Utc::now().format("%Y%m%d-%H%M%S"));
        let run = RunState::new(run_id, max_repairs);

        Ok(Self {
            profile,
            available_profiles,
            current_profile_idx,
            controller: None,
            dummy_run: run,
            view: View::Pipeline,
            should_quit: false,
            candidate_files: Vec::new(),
            active_candidate_idx: 0,
            diagnostics: String::new(),
            react_logs: Vec::new(),
            task_files: Vec::new(),
            token_prompt: 0,
            token_completion: 0,
            scroll_offset: 0,
            proxy_event_rx: None,
            controller_event_tx: None,
            executor: None,
            run_start_time: None,
            prompt_tps: 0.0,
            generation_tps: 0.0,
        })
    }

    /// Discover available profiles in profiles/ directory
    pub fn discover_profiles() -> Vec<PathBuf> {
        let mut profiles = Vec::new();
        if let Ok(entries) = std::fs::read_dir("profiles") {
            for entry in entries.flatten() {
                let path = entry.path();
                if path.extension().and_then(|s| s.to_str()) == Some("toml") {
                    profiles.push(path);
                }
            }
        }
        profiles.sort();
        profiles
    }

    /// Switch to next profile
    pub fn next_profile(&mut self) -> Result<()> {
        if self.available_profiles.is_empty() {
            return Ok(());
        }
        self.current_profile_idx = (self.current_profile_idx + 1) % self.available_profiles.len();
        let target_path = self.available_profiles[self.current_profile_idx].clone();
        if target_path.exists() {
            self.profile = ModelProfile::load(&target_path)?;
            self.add_log(format!(
                "Switched model profile to: {}",
                self.profile.model.name
            ));
        }
        Ok(())
    }

    /// Add a log message to the live ReAct log stream
    pub fn add_log(&mut self, message: impl Into<String>) {
        let timestamp = chrono::Local::now().format("%H:%M:%S").to_string();
        self.react_logs
            .push(format!("[{}] {}", timestamp, message.into()));
        if self.react_logs.len() > 500 {
            self.react_logs.remove(0);
        }
    }

    /// Scan candidate directory for generated multi-file XML / source files
    pub fn refresh_candidate_files(&mut self, candidate_dir: &Path) {
        let mut files = Vec::new();
        if candidate_dir.is_file() {
            if let Ok(content) = std::fs::read_to_string(candidate_dir) {
                let fname = candidate_dir
                    .file_name()
                    .unwrap_or_default()
                    .to_string_lossy()
                    .to_string();
                files.push((fname, content));
            }
        } else if candidate_dir.is_dir() {
            if let Ok(entries) = std::fs::read_dir(candidate_dir) {
                for entry in entries.flatten() {
                    let path = entry.path();
                    if path.is_file() {
                        if let Ok(content) = std::fs::read_to_string(&path) {
                            let fname = path
                                .file_name()
                                .unwrap_or_default()
                                .to_string_lossy()
                                .to_string();
                            files.push((fname, content));
                        }
                    }
                }
            }
        }
        files.sort_by(|a, b| a.0.cmp(&b.0));
        self.candidate_files = files;
        if self.active_candidate_idx >= self.candidate_files.len() {
            self.active_candidate_idx = 0;
        }
    }

    pub fn set_candidate_files(&mut self, files: Vec<(String, String)>) {
        self.candidate_files = files;
        if self.active_candidate_idx >= self.candidate_files.len() {
            self.active_candidate_idx = 0;
        }
    }

    pub async fn start_task(&mut self, task_path: &Path) -> Result<()> {
        let max_repairs = self.profile.run.max_repairs;
        let run_id = format!("run-{}", chrono::Utc::now().format("%Y%m%d-%H%M%S"));

        let (side_effect_tx, _side_effect_rx) = mpsc::channel(32);
        let (controller, controller_event_tx) =
            RunController::new(run_id.clone(), max_repairs, side_effect_tx);

        let (proxy_event_tx, proxy_event_rx) = mpsc::channel(64);

        let runs_root = PathBuf::from("runs");
        let mut executor =
            PipelineExecutor::new(self.profile.clone(), proxy_event_tx, runs_root, run_id);
        executor.load_task_from_path(task_path).await;

        self.proxy_event_rx = Some(proxy_event_rx);
        self.controller_event_tx = Some(controller_event_tx);
        self.controller = Some(controller);
        self.executor = Some(executor);
        self.run_start_time = Some(Instant::now());
        self.add_log(format!("Task started from: {:?}", task_path));

        Ok(())
    }

    pub fn run_state(&self) -> &RunState {
        self.controller
            .as_ref()
            .map(|c| &c.state)
            .unwrap_or(&self.dummy_run)
    }

    pub fn stage_statuses(&self) -> Vec<(&'static str, StageStatus)> {
        let run = self.run_state();
        let current_state = &run.state;

        let stages = [
            (
                "Task Loaded",
                matches!(
                    current_state,
                    PipelineState::LoadingTask
                        | PipelineState::Preflight
                        | PipelineState::Generating { .. }
                        | PipelineState::LocalValidation { .. }
                        | PipelineState::DomainValidation { .. }
                        | PipelineState::BuildValidation { .. }
                        | PipelineState::Finalizing
                        | PipelineState::Completed
                ),
            ),
            (
                "LLM Generation",
                matches!(
                    current_state,
                    PipelineState::Generating { .. }
                        | PipelineState::LocalValidation { .. }
                        | PipelineState::DomainValidation { .. }
                        | PipelineState::BuildValidation { .. }
                        | PipelineState::Finalizing
                        | PipelineState::Completed
                ),
            ),
            (
                "Local Validation",
                matches!(
                    current_state,
                    PipelineState::LocalValidation { .. }
                        | PipelineState::DomainValidation { .. }
                        | PipelineState::BuildValidation { .. }
                        | PipelineState::Finalizing
                        | PipelineState::Completed
                ),
            ),
            (
                "Domain Validation",
                matches!(
                    current_state,
                    PipelineState::DomainValidation { .. }
                        | PipelineState::BuildValidation { .. }
                        | PipelineState::Finalizing
                        | PipelineState::Completed
                ),
            ),
            (
                "Build Validation",
                matches!(
                    current_state,
                    PipelineState::BuildValidation { .. }
                        | PipelineState::Finalizing
                        | PipelineState::Completed
                ),
            ),
        ];

        stages
            .iter()
            .map(|(name, is_done)| {
                let status = if *is_done {
                    if matches!(current_state, PipelineState::Completed) {
                        StageStatus::Done
                    } else if matches!(current_state, PipelineState::Failed { .. }) {
                        StageStatus::Failed
                    } else {
                        StageStatus::Done
                    }
                } else if run.state.is_active() {
                    StageStatus::Active
                } else {
                    StageStatus::Pending
                };
                (*name, status)
            })
            .collect()
    }
}
