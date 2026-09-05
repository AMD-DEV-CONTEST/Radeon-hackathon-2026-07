use agent_core::error::AgentError;
use agent_core::event::*;
use agent_core::reducer::SideEffect;
use artifact_store::RunArtifacts;
use context_builder::{
    TaskPackageData, build_generation_messages, build_repair_messages, calculate_budget,
};
use model_vllm::chat::ChatMessage;
use model_vllm::client::VllmClient;
use model_vllm::profile::ModelProfile;
use model_vllm::tokenizer;
use std::path::{Path, PathBuf};
use tokio::sync::mpsc;
use tracing::{error, info, warn};
use validation;

/// PipelineExecutor processes SideEffects and sends RunEvents back.
/// Both TUI and headless CLI create one of these.
pub struct PipelineExecutor {
    profile: ModelProfile,
    client: VllmClient,
    event_tx: mpsc::Sender<RunEvent>,
    task: Option<TaskPackageData>,
    candidate: Option<String>, // current candidate output
    candidate_files: Vec<(String, String)>,
    artifacts: Option<RunArtifacts>,
    runs_root: PathBuf,
    run_id: String,
    /// Optional build target for code generation (e.g. "rust-lib-core")
    build_target: Option<String>,
    /// Optional patches to apply to generated Cargo.toml files
    patches: Option<std::collections::HashMap<String, String>>,
    /// Actionable errors from the most recent failed validation, fed into repair prompts.
    last_actionable_errors: Vec<String>,
}

impl PipelineExecutor {
    pub fn new(
        profile: ModelProfile,
        event_tx: mpsc::Sender<RunEvent>,
        runs_root: PathBuf,
        run_id: String,
    ) -> Self {
        let client = VllmClient::new(profile.clone());
        Self {
            profile,
            client,
            event_tx,
            task: None,
            candidate: None,
            candidate_files: Vec::new(),
            artifacts: None,
            runs_root,
            run_id,
            build_target: None,
            patches: None,
            last_actionable_errors: Vec::new(),
        }
    }

    /// Set the build target for code generation (e.g. "rust-lib-core")
    pub fn set_build_target(&mut self, target: String) {
        self.build_target = Some(target);
    }

    /// Set patches for generated Cargo.toml files
    pub fn set_patches(&mut self, patches: std::collections::HashMap<String, String>) {
        self.patches = Some(patches);
    }

    /// Process a side effect. This is the main dispatch loop.
    pub async fn handle(&mut self, effect: SideEffect) {
        match effect {
            SideEffect::RunPreflight => self.run_preflight().await,
            SideEffect::Generate { attempt } => self.generate(attempt).await,
            SideEffect::RunLocalValidation { attempt } => self.local_validate(attempt).await,
            SideEffect::RunDomainValidation { attempt } => self.domain_validate(attempt).await,
            SideEffect::RunBuildValidation { attempt } => self.build_validate(attempt).await,
            SideEffect::Repair { attempt } => self.repair(attempt).await,
            SideEffect::WriteFinalArtifact => self.write_final().await,
            SideEffect::RecordFailure { error } => self.record_failure(&error).await,
            SideEffect::LoadTask { path } => self.load_task(&path).await,
            SideEffect::RequestConsent { action, .. } => {
                // In headless mode: auto-deny
                // In TUI mode: the TUI will handle this
                self.send(RunEvent::ConsentDenied(format!(
                    "Auto-denied in headless: {action}"
                )))
                .await;
            }
            SideEffect::None => {}
        }
    }

    /// Load a task package from disk.
    pub async fn load_task_from_path(&mut self, path: &Path) {
        match TaskPackageData::load(path) {
            Ok(task) => {
                let pkg = TaskPackage {
                    name: task.name.clone(),
                    task_file: task.root.join("task.md"),
                    files: task.files(),
                    acceptance_spec: task.acceptance_spec.clone(),
                };
                self.task = Some(task);
                self.send(RunEvent::TaskLoaded(pkg)).await;
            }
            Err(e) => {
                self.send(RunEvent::TaskLoadFailed(format!(
                    "Failed to load task: {e}"
                )))
                .await;
            }
        }
    }

    /// Create a task from inline text (typed in TUI).
    pub async fn load_task_from_text(&mut self, text: &str) {
        let mut task = TaskPackageData::from_inline_text(text);

        // Try to load modeling skill from teaql-agent-kit
        let home = std::env::var("HOME").unwrap_or_default();
        let skill_path = Path::new(&home)
            .join("githome/teaql-agent-kit/skills/build-teaql-app/SKILL.md");
        let mut skill_content = String::new();
        if skill_path.exists() {
            if let Ok(content) = std::fs::read_to_string(&skill_path) {
                skill_content.push_str(&content);
                info!(path = %skill_path.display(), "Loaded modeling skill for inline task");
            }
        }

        let error_fix_path = Path::new(&home)
            .join("githome/teaql-agent-kit/skills/build-teaql-app/agents/ERROR-FIX.md");
        if error_fix_path.exists() {
            if let Ok(content) = std::fs::read_to_string(&error_fix_path) {
                skill_content.push_str("\n\n# Error Troubleshooting Guide\n");
                skill_content.push_str(&content);
                info!(path = %error_fix_path.display(), "Loaded ERROR-FIX.md for inline task");
            }
        }

        if !skill_content.is_empty() {
            task.modeling_skill = Some(skill_content);
        }

        let pkg = TaskPackage {
            name: task.name.clone(),
            task_file: task.root.join("task.md"),
            files: vec![],
            acceptance_spec: None,
        };
        self.task = Some(task);
        self.send(RunEvent::TaskLoaded(pkg)).await;
    }

    async fn load_task(&mut self, path: &Path) {
        self.load_task_from_path(path).await;
    }

    async fn run_preflight(&mut self) {
        let task = match &self.task {
            Some(t) => t,
            None => {
                self.send(RunEvent::PreflightFailed("No task loaded".to_string()))
                    .await;
                return;
            }
        };

        // Estimate token usage
        let messages = build_generation_messages(task);
        let estimated_prompt = tokenizer::estimate_messages_tokens(&messages);

        let budget = calculate_budget(
            self.profile.context.model_context_tokens,
            self.profile.context.max_prompt_tokens,
            self.profile.context.max_completion_tokens,
            self.profile.context.safety_tokens,
            estimated_prompt,
        );

        if !budget.admits() {
            self.send(RunEvent::PreflightFailed(format!(
                "Budget exceeded: estimated {} + completion {} + safety {} = {} > context {}",
                estimated_prompt,
                self.profile.context.max_completion_tokens,
                self.profile.context.safety_tokens,
                estimated_prompt
                    + self.profile.context.max_completion_tokens
                    + self.profile.context.safety_tokens,
                self.profile.context.model_context_tokens,
            )))
            .await;
            return;
        }

        // Create run artifacts directory
        match RunArtifacts::create(&self.runs_root, &self.run_id).await {
            Ok(artifacts) => {
                self.artifacts = Some(artifacts);
            }
            Err(e) => {
                warn!("Failed to create artifacts dir: {e}");
            }
        }

        info!(
            estimated = estimated_prompt,
            limit = self.profile.context.max_prompt_tokens,
            "Preflight passed"
        );
        self.send(RunEvent::PreflightPassed(budget)).await;
    }

    async fn generate(&mut self, attempt: u8) {
        let task = match &self.task {
            Some(t) => t,
            None => {
                self.send(RunEvent::ModelFailed(AgentError::InfrastructureError {
                    detail: "No task loaded".to_string(),
                }))
                .await;
                return;
            }
        };

        // Build messages — fresh for first attempt, repair-aware for retries
        let message_pairs = if attempt > 1 {
            let rejected = self.candidate.clone().unwrap_or_default();
            let errors = if self.last_actionable_errors.is_empty() {
                vec!["Validation failed. Please fix all errors.".to_string()]
            } else {
                self.last_actionable_errors.clone()
            };
            build_repair_messages(
                task,
                &rejected,
                &errors,
                self.profile.run.diagnostic_character_limit,
            )
        } else {
            build_generation_messages(task)
        };
        let messages: Vec<ChatMessage> = message_pairs
            .into_iter()
            .map(|(role, content)| ChatMessage {
                role,
                content: Some(content),
                ..Default::default()
            })
            .collect();

        info!(
            attempt,
            message_count = messages.len(),
            "Sending generation request"
        );

        // Save request to artifacts
        if let Some(artifacts) = &self.artifacts {
            artifacts
                .save_attempt_file(
                    attempt,
                    "request.json",
                    &serde_json::json!({
                        "attempt": attempt,
                        "message_count": messages.len(),
                        "model": self.profile.model.name,
                    }),
                )
                .await
                .ok();
        }

        let mut request_client = self.client.clone();
        if attempt > 1 {
            let mut dynamic_profile = self.profile.clone();
            let base_temp = dynamic_profile.sampling.temperature;
            let new_temp = (base_temp + (attempt as f32 - 1.0) * 0.15).min(0.8);
            dynamic_profile.sampling.temperature = new_temp;
            request_client = model_vllm::client::VllmClient::new(dynamic_profile);
            info!(attempt, temp = new_temp, "Applying dynamic temperature for repair");
        }

        match request_client.chat(messages.clone(), None, None).await {
            Ok(result) => {
                // Save candidate
                self.candidate = Some(result.content.clone());
                self.candidate_files = vec![("main.xml".to_string(), result.content.clone())];
                if let Some(artifacts) = &self.artifacts {
                    artifacts
                        .save_candidate(attempt, &result.content)
                        .await
                        .ok();
                    artifacts
                        .save_attempt_file(attempt, "response.json", &result)
                        .await
                        .ok();
                }

                // MULTI-STEP LOOP: Generate included files
                let includes = extract_includes(&result.content);
                for file in includes {
                    info!(attempt, file = %file, "Generating included file");
                    let mut sub_messages = messages.clone();
                    sub_messages.push(ChatMessage::assistant(result.content.clone()));
                    sub_messages.push(ChatMessage::user(format!("Please provide the contents of {}. Output ONLY the raw XML, nothing else. Do not use markdown blocks, just the raw XML text.", file)));

                    match self.client.chat(sub_messages, None, None).await {
                        Ok(sub_result) => {
                            let clean_content = strip_markdown_fences(&sub_result.content);
                            self.candidate_files
                                .push((file.clone(), clean_content.clone()));

                            if let Some(artifacts) = &self.artifacts {
                                artifacts
                                    .save_attempt_raw(attempt, &file, &clean_content)
                                    .await
                                    .ok();
                            }
                        }
                        Err(e) => {
                            tracing::warn!("Failed to generate included file {}: {}", file, e);
                        }
                    }
                }

                self.send(RunEvent::ModelCompleted(result)).await;
            }
            Err(err) => {
                // Save error
                if let Some(artifacts) = &self.artifacts {
                    artifacts
                        .save_attempt_file(
                            attempt,
                            "error.json",
                            &serde_json::json!({ "error": err.to_string() }),
                        )
                        .await
                        .ok();
                }
                self.send(RunEvent::ModelFailed(err)).await;
            }
        }
    }

    async fn local_validate(&mut self, attempt: u8) {
        let candidate = match &self.candidate {
            Some(c) => c.clone(),
            None => {
                self.send(RunEvent::Failed(AgentError::InfrastructureError {
                    detail: "No candidate to validate".to_string(),
                }))
                .await;
                return;
            }
        };

        // L1: XML parse validation
        let parse_result = validation::validate_xml_parse(&candidate);
        if let Some(artifacts) = &self.artifacts {
            artifacts
                .save_attempt_file(attempt, "local-validation.json", &parse_result)
                .await
                .ok();
        }

        if !parse_result.passed {
            self.send(RunEvent::ValidationCompleted(parse_result)).await;
            return;
        }

        // L2: Acceptance validation (if spec exists)
        if let Some(task) = &self.task {
            if let Some(spec) = &task.acceptance_spec {
                let acceptance_result = validation::validate_acceptance(&candidate, spec);
                if !acceptance_result.passed {
                    self.send(RunEvent::ValidationCompleted(acceptance_result))
                        .await;
                    return;
                }
            }
        }

        // All local validation passed
        self.send(RunEvent::ValidationCompleted(parse_result)).await;
    }

    async fn domain_validate(&mut self, attempt: u8) {
        let result = if let Some(artifacts) = &self.artifacts {
            // Write the candidate to a temporary model.xml in the attempt dir
            let attempt_dir = artifacts
                .create_attempt(attempt)
                .await
                .unwrap_or_else(|_| artifacts.root.clone());
            let model_path = attempt_dir.join("main.xml");
            if let Some(c) = &self.candidate {
                let mut clean = strip_markdown_fences(c);
                // Auto-repair: ensure </root> closing tag exists
                if clean.contains("<root") && !clean.contains("</root>") {
                    tracing::warn!("main.xml missing </root> — auto-appending closing tag");
                    clean.push_str("\n</root>\n");
                }
                std::fs::write(&model_path, &clean).ok();
            }

            let model_dir = attempt_dir.join("model");
            std::fs::create_dir_all(&model_dir).ok();
            if let Ok(entries) = std::fs::read_dir(&attempt_dir) {
                for entry in entries.flatten() {
                    let path = entry.path();
                    if path.is_file() {
                        if let Some(ext) = path.extension() {
                            if ext == "xml" || ext == "ksml" {
                                std::fs::copy(&path, model_dir.join(path.file_name().unwrap()))
                                    .ok();
                            }
                        }
                    }
                }
            }

            info!(attempt, path = %attempt_dir.display(), "Running domain validation");
            validation::domain::validate_domain(&model_dir)
        } else {
            // Fallback if no artifacts dir (shouldn't happen in normal runs)
            info!(attempt, "Domain validation skipped — no artifact dir");
            validation::pass(3, "domain", 0.0)
        };

        if let Some(artifacts) = &self.artifacts {
            artifacts
                .save_attempt_file(attempt, "domain-validation.json", &result)
                .await
                .ok();
        }
        self.send(RunEvent::ValidationCompleted(result)).await;
    }

    /// Run build validation: code generation via `cargo teaql` + `cargo check`.
    ///
    /// When `build_target` is set (e.g. "rust-lib-core"), this method:
    /// 1. Runs `cargo teaql --input <attempt_dir> <target>` to generate code
    /// 2. Patches the known rusqlite dependency conflict in the generated Cargo.toml
    /// 3. Runs `cargo check` on the generated crate
    /// 4. Parses compiler output into a ValidationResult
    async fn build_validate(&mut self, attempt: u8) {
        let build_target = match &self.build_target {
            Some(t) => t.clone(),
            None => {
                info!(
                    attempt,
                    "Build validation — no build target configured, passing"
                );
                let result = validation::pass(5, "build", 0.0);
                if let Some(artifacts) = &self.artifacts {
                    artifacts
                        .save_attempt_file(attempt, "build-validation.json", &result)
                        .await
                        .ok();
                }
                self.send(RunEvent::ValidationCompleted(result)).await;
                return;
            }
        };

        let attempt_dir = match &self.artifacts {
            Some(a) => match a.create_attempt(attempt).await {
                Ok(dir) => dir,
                Err(e) => {
                    error!(attempt, %e, "Failed to create attempt directory");
                    let result = ValidationResult {
                        level: 5,
                        level_name: "build".to_string(),
                        passed: false,
                        error_count: 1,
                        warning_count: 0,
                        suggestion_count: 0,
                        actionable_errors: vec![format!("Failed to create attempt dir: {}", e)],
                        structured_errors: vec![],
                        diagnostic: e.to_string(),
                        elapsed_secs: 0.0,
                    };
                    self.send(RunEvent::ValidationCompleted(result)).await;
                    return;
                }
            },
            None => {
                error!(attempt, "No artifact directory for build validation");
                let result = ValidationResult {
                    level: 5,
                    level_name: "build".to_string(),
                    passed: false,
                    error_count: 1,
                    warning_count: 0,
                    suggestion_count: 0,
                    actionable_errors: vec!["No artifact directory available".to_string()],
                    structured_errors: vec![],
                    diagnostic: "Internal error: no artifact store".to_string(),
                    elapsed_secs: 0.0,
                };
                self.send(RunEvent::ValidationCompleted(result)).await;
                return;
            }
        };

        let start = std::time::Instant::now();

        // Step 1: Run cargo teaql to generate code
        info!(attempt, target = %build_target, dir = %attempt_dir.display(), "Running code generation");
        let gen_result = tokio::process::Command::new("cargo")
            .args(["teaql", "--input", "model", &build_target])
            .current_dir(&attempt_dir)
            .output()
            .await;

        match &gen_result {
            Ok(output) if !output.status.success() => {
                let stderr = String::from_utf8_lossy(&output.stderr);
                let stdout = String::from_utf8_lossy(&output.stdout);
                let diagnostic = format!("Code generation failed:\n{}\n{}", stdout, stderr);
                warn!(attempt, "Code generation failed");
                let result = ValidationResult {
                    level: 5,
                    level_name: "build".to_string(),
                    passed: false,
                    error_count: 1,
                    warning_count: 0,
                    suggestion_count: 0,
                    actionable_errors: vec![format!("cargo teaql {} failed", build_target)],
                    structured_errors: vec![],
                    diagnostic,
                    elapsed_secs: start.elapsed().as_secs_f64(),
                };
                if let Some(artifacts) = &self.artifacts {
                    artifacts
                        .save_attempt_file(attempt, "build-validation.json", &result)
                        .await
                        .ok();
                }
                self.send(RunEvent::ValidationCompleted(result)).await;
                return;
            }
            Err(e) => {
                error!(attempt, %e, "Failed to run cargo teaql");
                let result = ValidationResult {
                    level: 5,
                    level_name: "build".to_string(),
                    passed: false,
                    error_count: 1,
                    warning_count: 0,
                    suggestion_count: 0,
                    actionable_errors: vec![format!("Failed to execute cargo teaql: {}", e)],
                    structured_errors: vec![],
                    diagnostic: e.to_string(),
                    elapsed_secs: start.elapsed().as_secs_f64(),
                };
                if let Some(artifacts) = &self.artifacts {
                    artifacts
                        .save_attempt_file(attempt, "build-validation.json", &result)
                        .await
                        .ok();
                }
                self.send(RunEvent::ValidationCompleted(result)).await;
                return;
            }
            _ => {
                info!(attempt, "Code generation succeeded");
            }
        }

        // ── Step 2: Run additional generation targets ──
        // Derive the app target from the build target (e.g. rust-lib-core → rust-app-console)
        let app_target = if build_target.contains("-lib-core") {
            let app = if build_target.starts_with("java") {
                build_target.replace("-lib-core", "-web-spring-boot")
            } else {
                build_target.replace("-lib-core", "-app-console")
            };
            info!(attempt, target = %app, "Generating app target");
            let app_gen = tokio::process::Command::new("cargo")
                .args(["teaql", "--input", "model", &app])
                .current_dir(&attempt_dir)
                .output()
                .await;

            match &app_gen {
                Ok(output) if !output.status.success() => {
                    let stderr = String::from_utf8_lossy(&output.stderr);
                    warn!(attempt, "App target generation failed: {}", stderr);
                    if let Some(artifacts) = &self.artifacts {
                        artifacts
                            .save_attempt_raw(attempt, "app-gen-error.txt", &stderr)
                            .await
                            .ok();
                    }
                }
                Err(e) => warn!(attempt, %e, "Failed to run app target generation"),
                _ => info!(attempt, target = %app, "App target generated successfully"),
            }
            Some(app)
        } else {
            None
        };

        // ── Step 3: Apply patches to generated files ──
        let build_dir = attempt_dir.join("build");
        if let Some(patches) = &self.patches {
            // Apply patches to any Cargo.toml or pom.xml files found
            for entry in walkdir_toml_xml(&build_dir) {
                if let Ok(content) = std::fs::read_to_string(&entry) {
                    let mut fixed = content.clone();
                    for (find, replace) in patches {
                        fixed = fixed.replace(find, replace);
                    }
                    if fixed != content {
                        info!(attempt, file = %entry.display(), "Applied patches");
                        std::fs::write(&entry, &fixed).ok();
                    }
                }
            }
        }

        // Fix app-console dependency path if applicable
        if let Some(ref _app) = app_target {
            let app_cargo_toml = build_dir.join("Cargo.toml");
            if app_cargo_toml.exists() {
                if let Ok(content) = std::fs::read_to_string(&app_cargo_toml) {
                    let old_path = format!(r#"path = "../{}/lib""#, build_target);
                    let fixed = content.replace(&old_path, r#"path = "./lib""#);
                    if fixed != content {
                        info!(attempt, "Fixed app dependency path");
                        std::fs::write(&app_cargo_toml, &fixed).ok();
                    }
                }
            }
        }

        // ── Step 4: Run assist queries for API reference context ──
        let agents_md_path = build_dir.join("AGENTS.md");
        let agents_md = if agents_md_path.exists() {
            std::fs::read_to_string(&agents_md_path).unwrap_or_default()
        } else {
            String::new()
        };

        let entity_names = parse_entity_names_from_agents_md(&agents_md);

        // Limit assist queries to avoid context overflow
        const MAX_ASSIST_ENTITIES: usize = 8;
        let assist_entities: Vec<&String> = if entity_names.len() > MAX_ASSIST_ENTITIES {
            let step = entity_names.len() as f64 / MAX_ASSIST_ENTITIES as f64;
            (0..MAX_ASSIST_ENTITIES)
                .map(|i| &entity_names[(i as f64 * step) as usize])
                .collect()
        } else {
            entity_names.iter().collect()
        };

        info!(
            attempt,
            total = entity_names.len(),
            sampled = assist_entities.len(),
            "Running assist commands"
        );

        let assist_target_base = build_target.replace("-lib-core", "-assist-query");
        let mut assist_outputs = String::new();
        for entity in &assist_entities {
            let assist_target = format!("{}/{}", assist_target_base, entity);
            let assist_result = tokio::process::Command::new("cargo")
                .args(["teaql", "--input", "model", &assist_target])
                .current_dir(&attempt_dir)
                .output()
                .await;

            if let Ok(output) = &assist_result {
                let stdout = String::from_utf8_lossy(&output.stdout);
                let truncated = if stdout.len() > 1200 {
                    let mut boundary = 1200;
                    while boundary > 0 && !stdout.is_char_boundary(boundary) {
                        boundary -= 1;
                    }
                    format!("{}...\n[truncated]", &stdout[..boundary])
                } else {
                    stdout.to_string()
                };
                assist_outputs.push_str(&format!(
                    "### Assist: query/{}\n\n{}\n\n",
                    entity, truncated
                ));
            }
        }

        // List remaining entities so LLM knows the full set
        if entity_names.len() > MAX_ASSIST_ENTITIES {
            assist_outputs.push_str(&format!(
                "### All entity names ({})\n{}\n\n",
                entity_names.len(),
                entity_names.join(", ")
            ));
        }

        if !assist_outputs.is_empty() {
            if let Some(artifacts) = &self.artifacts {
                artifacts
                    .save_attempt_raw(attempt, "assist-output.md", &assist_outputs)
                    .await
                    .ok();
            }
        }

        // ── Step 5: Launch agentic build loop ──
        // Instead of hardcoding cargo check / mvn compile, we let the LLM
        // autonomously inspect, compile, and fix the project using tools.
        if !entity_names.is_empty() && !assist_outputs.is_empty() {
            info!(attempt, "Launching agentic build loop");

            let system_prompt = std::fs::read_to_string("prompts/agentic-build.txt")
                .unwrap_or_else(|_| include_str!("../../../prompts/agentic-build.txt").to_string())
                .replace("{{project_dir}}", &build_dir.display().to_string())
                .replace("{{#if assist_outputs}}", "")
                .replace("{{/if}}", "")
                .replace("{{assist_outputs}}", &assist_outputs);

            // Give the agent specific first-step instructions based on detected build system
            let compile_hint = if build_target.starts_with("java") {
                "This is a Java/Maven project. Your FIRST action must be: run_command({\"command\": \"mvn compile -f pom.xml 2>&1 | tail -30\"})"
            } else {
                "This is a Rust/Cargo project. Your FIRST action must be: run_command({\"command\": \"cargo check 2>&1 | tail -30\"})"
            };

            let user_prompt = format!(
                "The project is at `{dir}`. {hint}\n\n\
                 After seeing the compile output:\n\
                 - If it succeeds, respond with a summary (no more tool calls).\n\
                 - If it fails, read the relevant source files, fix the errors using write_file, and recompile.\n\
                 - Write business logic code (one query function per entity) if the src/ files are empty stubs.\n\n\
                 Do NOT spend time exploring the directory tree. Compile first, fix errors after.",
                dir = build_dir.display(),
                hint = compile_hint
            );

            let max_iterations = 20; // Enough for explore → compile → fix → recompile cycles

            let loop_result = crate::agent_loop::run_agent_loop(
                &self.client,
                &build_dir,
                &system_prompt,
                &user_prompt,
                max_iterations,
                Some(self.event_tx.clone()),
            )
            .await;

            match &loop_result {
                crate::agent_loop::AgentLoopResult::Completed {
                    summary,
                    iterations,
                    total_tool_calls,
                } => {
                    let total_elapsed = start.elapsed().as_secs_f64();
                    if let Err(diagnostic) = verify_generated_build(&build_dir, &build_target).await
                    {
                        let result = validation::fail(
                            5,
                            "build",
                            vec!["Deterministic build verification failed".to_string()],
                            diagnostic,
                            total_elapsed,
                        );
                        self.send(RunEvent::ValidationCompleted(result)).await;
                        return;
                    }
                    info!(
                        attempt,
                        iterations,
                        total_tool_calls,
                        total_elapsed,
                        "Agentic build loop completed successfully"
                    );
                    let mut r = validation::pass(5, "build", total_elapsed);
                    r.diagnostic = format!(
                        "Agentic build: ✓ ({} iterations, {} tool calls)\n\nAgent summary: {}",
                        iterations, total_tool_calls, summary
                    );
                    if let Some(artifacts) = &self.artifacts {
                        artifacts
                            .save_attempt_file(attempt, "build-validation.json", &r)
                            .await
                            .ok();
                        artifacts
                            .save_attempt_raw(attempt, "agent-summary.txt", summary)
                            .await
                            .ok();
                    }
                    self.send(RunEvent::ValidationCompleted(r)).await;
                    return;
                }
                crate::agent_loop::AgentLoopResult::Failed { error, iterations } => {
                    let total_elapsed = start.elapsed().as_secs_f64();
                    warn!(attempt, iterations, %error, "Agentic build loop failed");
                    let result = ValidationResult {
                        level: 5,
                        level_name: "build".to_string(),
                        passed: false,
                        error_count: 1,
                        warning_count: 0,
                        suggestion_count: 0,
                        actionable_errors: vec![format!("Agent loop failed: {}", error)],
                        structured_errors: vec![],
                        diagnostic: format!(
                            "Agentic build failed after {} iterations: {}",
                            iterations, error
                        ),
                        elapsed_secs: total_elapsed,
                    };
                    if let Some(artifacts) = &self.artifacts {
                        artifacts
                            .save_attempt_file(attempt, "build-validation.json", &result)
                            .await
                            .ok();
                    }
                    self.send(RunEvent::ValidationCompleted(result)).await;
                    return;
                }
                crate::agent_loop::AgentLoopResult::MaxIterationsReached {
                    iterations,
                    total_tool_calls,
                } => {
                    let total_elapsed = start.elapsed().as_secs_f64();
                    warn!(
                        attempt,
                        iterations, total_tool_calls, "Agentic build loop hit max iterations"
                    );
                    let result = ValidationResult {
                        level: 5,
                        level_name: "build".to_string(),
                        passed: false,
                        error_count: 1,
                        warning_count: 0,
                        suggestion_count: 0,
                        actionable_errors: vec![format!(
                            "Agent loop exhausted {} iterations",
                            iterations
                        )],
                        structured_errors: vec![],
                        diagnostic: format!(
                            "Agentic build did not complete within {} iterations ({} tool calls)",
                            iterations, total_tool_calls
                        ),
                        elapsed_secs: total_elapsed,
                    };
                    if let Some(artifacts) = &self.artifacts {
                        artifacts
                            .save_attempt_file(attempt, "build-validation.json", &result)
                            .await
                            .ok();
                    }
                    self.send(RunEvent::ValidationCompleted(result)).await;
                    return;
                }
            }
        }

        // Fallback: no entities found, verify the generated project directly.
        let total_elapsed = start.elapsed().as_secs_f64();
        info!(
            attempt,
            total_elapsed, "No entities for agentic build; lib-only validation"
        );
        let r = match verify_generated_build(&build_dir, &build_target).await {
            Ok(diagnostic) => {
                let mut result = validation::pass(5, "build", total_elapsed);
                result.diagnostic = diagnostic;
                result
            }
            Err(diagnostic) => validation::fail(
                5,
                "build",
                vec!["Generated project failed deterministic build verification".to_string()],
                diagnostic,
                total_elapsed,
            ),
        };
        if let Some(artifacts) = &self.artifacts {
            artifacts
                .save_attempt_file(attempt, "build-validation.json", &r)
                .await
                .ok();
        }
        self.send(RunEvent::ValidationCompleted(r)).await;
    }

    async fn repair(&mut self, attempt: u8) {
        let task = match &self.task {
            Some(t) => t,
            None => {
                self.send(RunEvent::Failed(AgentError::InfrastructureError {
                    detail: "No task for repair".to_string(),
                }))
                .await;
                return;
            }
        };

        let rejected = match &self.candidate {
            Some(c) => c.clone(),
            None => {
                self.send(RunEvent::Failed(AgentError::InfrastructureError {
                    detail: "No candidate to repair".to_string(),
                }))
                .await;
                return;
            }
        };

        // Build repair messages — fresh, stateless
        // We need the actionable errors from the last validation.
        // For now, use a generic message since we don't store them in executor state.
        let message_pairs = build_repair_messages(
            task,
            &rejected,
            &["See diagnostic output for errors".to_string()],
            self.profile.run.diagnostic_character_limit,
        );

        let _messages: Vec<ChatMessage> = message_pairs
            .into_iter()
            .map(|(role, content)| ChatMessage {
                role,
                content: Some(content),
                ..Default::default()
            })
            .collect();

        info!(attempt, "Sending repair request");

        // Signal that repair is scheduled, which will transition to Generating
        self.send(RunEvent::RepairScheduled { attempt }).await;
    }

    async fn write_final(&mut self) {
        if let Some(candidate) = &self.candidate {
            if let Some(artifacts) = &self.artifacts {
                match artifacts.save_final_artifact(candidate).await {
                    Ok(path) => {
                        info!(path = %path.display(), "Final artifact saved");
                        self.send(RunEvent::FinalArtifactWritten(path)).await;
                    }
                    Err(e) => {
                        self.send(RunEvent::Failed(AgentError::InfrastructureError {
                            detail: format!("Failed to write final artifact: {e}"),
                        }))
                        .await;
                    }
                }
            } else {
                // No artifact store, just report success with a fake path
                self.send(RunEvent::FinalArtifactWritten(PathBuf::from(
                    "<no-artifact-store>",
                )))
                .await;
            }
        } else {
            self.send(RunEvent::Failed(AgentError::InfrastructureError {
                detail: "No candidate to finalize".to_string(),
            }))
            .await;
        }
    }

    async fn record_failure(&mut self, error: &str) {
        error!(%error, "Recording failure");
        if let Some(artifacts) = &self.artifacts {
            artifacts
                .save_summary(&serde_json::json!({
                    "status": "failed",
                    "error": error,
                }))
                .await
                .ok();
        }
    }

    async fn send(&mut self, event: RunEvent) {
        // Capture validation errors for repair prompts
        if let RunEvent::ValidationCompleted(ref result) = event {
            if !result.passed {
                self.last_actionable_errors = result.actionable_errors.clone();
            }
        }
        if self.event_tx.send(event).await.is_err() {
            error!("Failed to send event — channel closed");
        }
    }

    /// Get the VllmClient reference for health checks
    pub fn client(&self) -> &VllmClient {
        &self.client
    }

    /// Get the profile
    pub fn profile(&self) -> &ModelProfile {
        &self.profile
    }

    /// Get current candidate
    pub fn candidate(&self) -> Option<&str> {
        self.candidate.as_deref()
    }

    /// Get all generated candidate files for interactive previews.
    pub fn candidate_files(&self) -> &[(String, String)] {
        &self.candidate_files
    }

    /// Store actionable errors for repair context
    pub fn set_last_errors(&mut self, _errors: Vec<String>) {
        // Will be used when building repair messages
        // For now this is a placeholder for richer repair context
    }
}

async fn verify_generated_build(build_dir: &Path, build_target: &str) -> Result<String, String> {
    let mut command = if build_target.starts_with("java") {
        let mut command = tokio::process::Command::new("mvn");
        command.args(["compile", "-f", "pom.xml"]);
        command
    } else {
        let mut command = tokio::process::Command::new("cargo");
        command.arg("check");
        command
    };

    let output = command
        .current_dir(build_dir)
        .env("PAGER", "cat")
        .output()
        .await
        .map_err(|error| format!("Failed to start deterministic build verification: {error}"))?;

    let diagnostic = format!(
        "Exit status: {}\nSTDOUT:\n{}\nSTDERR:\n{}",
        output.status,
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );

    if output.status.success() {
        Ok(diagnostic)
    } else {
        Err(diagnostic)
    }
}

fn extract_includes(content: &str) -> Vec<String> {
    let mut includes = Vec::new();
    let mut start = 0;
    while let Some(idx) = content[start..].find("<_include file=\"") {
        let open_quote = start + idx + 16;
        if let Some(close_quote) = content[open_quote..].find('"') {
            includes.push(content[open_quote..open_quote + close_quote].to_string());
            start = open_quote + close_quote + 1;
        } else {
            break;
        }
    }
    // Also handle single quotes just in case
    start = 0;
    while let Some(idx) = content[start..].find("<_include file='") {
        let open_quote = start + idx + 16;
        if let Some(close_quote) = content[open_quote..].find('\'') {
            includes.push(content[open_quote..open_quote + close_quote].to_string());
            start = open_quote + close_quote + 1;
        } else {
            break;
        }
    }
    includes
}

/// Parse entity names from the generated AGENTS.md.
///
/// The generated AGENTS.md contains a markdown table like:
/// ```text
/// | entity-name | display-name |
/// |-------------|--------------|
/// | school | School |
/// | teacher | Teacher |
/// ```
/// We extract the entity-name column values.
fn parse_entity_names_from_agents_md(content: &str) -> Vec<String> {
    let mut entities = Vec::new();
    let mut in_entity_table = false;
    let mut header_seen = false;

    for line in content.lines() {
        let trimmed = line.trim();
        // Detect the entity table header
        if trimmed.contains("entity-name") && trimmed.contains("display-name") {
            in_entity_table = true;
            header_seen = false;
            continue;
        }
        if in_entity_table {
            // Skip the separator line (|---|---|)
            if trimmed.starts_with("|") && trimmed.contains("---") {
                header_seen = true;
                continue;
            }
            // Parse data rows
            if header_seen && trimmed.starts_with('|') {
                let parts: Vec<&str> = trimmed.split('|').collect();
                if parts.len() >= 3 {
                    let entity = parts[1].trim();
                    if !entity.is_empty() && !entity.contains("---") {
                        entities.push(entity.to_string());
                    }
                }
            } else if header_seen && !trimmed.starts_with('|') {
                // End of table
                break;
            }
        }
    }
    entities
}

/// Recursively find Cargo.toml and pom.xml files for patching
fn walkdir_toml_xml(dir: &Path) -> Vec<PathBuf> {
    let mut results = Vec::new();
    if let Ok(entries) = std::fs::read_dir(dir) {
        for entry in entries.flatten() {
            let path = entry.path();
            if path.is_dir() {
                results.extend(walkdir_toml_xml(&path));
            } else {
                let name = path.file_name().and_then(|n| n.to_str()).unwrap_or("");
                if name == "Cargo.toml" || name == "pom.xml" || name == "build.gradle" {
                    results.push(path);
                }
            }
        }
    }
    results
}

/// Strip markdown code fences from LLM output (e.g. ```xml ... ```)
fn strip_markdown_fences(content: &str) -> String {
    let trimmed = content.trim();
    
    // Find the first occurrence of ```
    if let Some(start_idx) = trimmed.find("```") {
        let after_start = &trimmed[start_idx + 3..];
        
        // Skip the optional language identifier (e.g., xml or ksml)
        let content_start = if after_start.to_lowercase().starts_with("xml") {
            after_start[3..].trim_start()
        } else if after_start.to_lowercase().starts_with("ksml") {
            after_start[4..].trim_start()
        } else {
            // Just skip to the next newline if there's any text on the same line
            if let Some(newline_idx) = after_start.find('\n') {
                &after_start[newline_idx + 1..]
            } else {
                after_start
            }
        };
        
        // Find the matching end fence
        if let Some(end_idx) = content_start.rfind("```") {
            return content_start[..end_idx].trim().to_string();
        }
    }
    
    // If no markdown fences are found, return the trimmed content
    trimmed.to_string()
}
