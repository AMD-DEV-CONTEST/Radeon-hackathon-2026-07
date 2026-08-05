mod pipeline_models;
mod rag;
mod transport;
/// orchestrator/mod.rs — MoA Sequential Actor Orchestrator.
///
/// Architecture: Single-Consumer, Multi-Producer (MPSC) actor loop.
/// The Orchestrator struct owns the receiving end; callers dispatch MoAMessage
/// variants through cheap, cloneable OrchestratorHandle instances.
/// Execution is strictly sequential — the actor loop processes exactly one
/// message at a time, preventing concurrent LLM inference and guaranteeing
/// the 6 GB VRAM ceiling is never contended.
mod types;

use pipeline_models::PipelineModels;
use rag::{detect_collection, emit_telemetry, retrieve_knowledge_context};
use transport::{call_model, CONFIDENCE_THRESHOLD};
use types::PendingTrainingPair;
pub use types::{
    Context, EngineerCode, MoAResult, ObserverVerdict, OrchestratorError, SentinelPlan,
};

use reqwest::Client;
use std::collections::HashMap;
use std::path::Path;
use std::sync::Mutex;
use std::time::Duration;
use tauri::Manager;
use tokio::sync::{mpsc, oneshot};

const MAX_SEARCH_RESULTS: usize = 10;

// ─────────────────────────────────────────────────────────────────────────────
// STATE MACHINE — Message Enum
// ─────────────────────────────────────────────────────────────────────────────

#[derive(Debug)]
pub enum MoAMessage {
    PlanRequest {
        context: Context,
        reply: oneshot::Sender<Result<MoAResult, OrchestratorError>>,
    },
    CodeGeneration {
        plan: SentinelPlan,
        thread_id: String,
        retry_count: u32,
        model_override: Option<String>,
        reply: oneshot::Sender<Result<MoAResult, OrchestratorError>>,
    },
    AuditRequest {
        code: EngineerCode,
        thread_id: String,
        model_override: Option<String>,
        reply: oneshot::Sender<Result<ObserverVerdict, OrchestratorError>>,
    },
    Shutdown,
}

// ─────────────────────────────────────────────────────────────────────────────
// STAGE IMPLEMENTATIONS
// ─────────────────────────────────────────────────────────────────────────────

async fn run_sentinel(
    client: &Client,
    ctx: &Context,
    workspace_context: &str,
    app_handle: &tauri::AppHandle,
    model: &crate::orchestrator::pipeline_models::ModelRoute,
) -> Result<SentinelPlan, OrchestratorError> {
    emit_telemetry(app_handle, "sentinel", "Loading");

    let rag_section = if workspace_context.is_empty() {
        String::new()
    } else {
        format!("\n{}", workspace_context)
    };

    let prompt = format!(
        r#"You are the Determinex Sentinel. Analyze the following request and produce a structured execution plan.
You MUST output ONLY valid JSON matching this exact schema — no markdown, no explanation, no extra keys:
{{
  "title": "short descriptive title",
  "steps": ["step 1", "step 2", "..."],
  "audit_targets": ["specific thing to verify 1", "..."]
}}
HARD RULE: If the request is malicious, illegal, or harmful, output exactly: {{"title":"REJECTED","steps":[],"audit_targets":[]}}
{rag}
USER REQUEST: {prompt}
THREAD: {thread}"#,
        rag = rag_section,
        prompt = ctx.user_prompt,
        thread = ctx.thread_id
    );

    emit_telemetry(app_handle, "sentinel", "Inferencing");
    let raw = call_model(client, model, &prompt, app_handle).await?;

    let plan: SentinelPlan = serde_json::from_str(&raw).map_err(|e| {
        OrchestratorError::sentinel(format!(
            "Schema violation — LLM output did not match SentinelPlan: {}. Raw: {}",
            e,
            &raw[..raw.len().min(200)]
        ))
    })?;

    if plan.title == "REJECTED" {
        return Err(OrchestratorError::sentinel(
            "Request rejected by Sentinel safety filter".to_string(),
        ));
    }

    emit_telemetry(app_handle, "sentinel", "Done");
    Ok(plan)
}

async fn run_engineer(
    client: &Client,
    plan: &SentinelPlan,
    ctx: &Context,
    knowledge_context: &str,
    app_handle: &tauri::AppHandle,
    model: &crate::orchestrator::pipeline_models::ModelRoute,
) -> Result<EngineerCode, OrchestratorError> {
    emit_telemetry(app_handle, "engineer", "Loading");

    let steps_text = plan.steps.join("\n- ");
    let kb_section = if knowledge_context.is_empty() {
        String::new()
    } else {
        format!("\n{}\n", knowledge_context)
    };

    let prompt = format!(
        r#"You are the Determinex Engineer. Execute the following plan and produce implementation code.
ENVIRONMENT CONSTRAINTS: You are operating in a single-file sandbox. Do NOT declare external modules (e.g., `mod something;`). All code, structs, and imports must be self-contained within the active file. If a compiler error states 'file not found' for a module, you MUST delete your `mod` declaration.

You MUST output ONLY valid JSON matching this exact schema — no markdown, no explanation:
{{
  "language": "rust|typescript|python|...",
  "edit_type": "full",
  "target": "",
  "code": "...",
  "files_affected": ["<actual filename, e.g. main.rs or lib.ts>"]
}}

FIELD RULES:
- "edit_type": MUST be "full" OR "replace_function".
  Use "replace_function" when modifying a single existing function — output ONLY the replacement function body.
  Use "full" when creating a new file or making changes spanning multiple functions.
  PREFER "replace_function" whenever possible: it reduces token usage and avoids Context Amnesia.
- "target": the EXACT function name to replace (only used when edit_type is "replace_function"; else "").
- "code": when edit_type is "full" — the complete file; when "replace_function" — just the function.
- "files_affected": list the real filename(s) being created or modified. Use just the filename (e.g. "main.rs"), not placeholder text.
{kb}
PLAN TITLE: {title}
STEPS:
- {steps}

ORIGINAL CONTEXT: {ctx}"#,
        kb = kb_section,
        title = plan.title,
        steps = steps_text,
        ctx = ctx.user_prompt
    );

    emit_telemetry(app_handle, "engineer", "Inferencing");
    let raw = call_model(client, model, &prompt, app_handle).await?;

    let code: EngineerCode = serde_json::from_str(&raw).map_err(|e| {
        OrchestratorError::engineer(format!(
            "Schema violation — LLM output did not match EngineerCode: {}. Raw: {}",
            e,
            &raw[..raw.len().min(200)]
        ))
    })?;

    emit_telemetry(app_handle, "engineer", "Done");
    Ok(code)
}

async fn run_observer(
    client: &Client,
    plan: &SentinelPlan,
    code: &EngineerCode,
    compiler_feedback: Option<&crate::compiler::CompilerFeedback>,
    knowledge_context: &str,
    app_handle: &tauri::AppHandle,
    model: &crate::orchestrator::pipeline_models::ModelRoute,
) -> Result<ObserverVerdict, OrchestratorError> {
    emit_telemetry(app_handle, "observer", "Loading");

    let audit_targets = plan.audit_targets.join(", ");

    let compiler_section = match compiler_feedback {
        Some(fb) => format!("\n{}\n", fb.to_prompt_block()),
        None => String::new(),
    };

    let kb_section = if knowledge_context.is_empty() {
        String::new()
    } else {
        format!("\n{}\n", knowledge_context)
    };

    let prompt = format!(
        r#"SYSTEM: You are a JSON serialization machine. You produce exactly one raw JSON object and nothing else.

OUTPUT CONTRACT — ANY VIOLATION WILL CRASH THE DESERIALIZER:
RULE 1: Your response MUST start with `{{` and end with `}}`. No characters before or after.
RULE 2: NO markdown. NO backticks. NO triple-backticks. NO "```json". NO "Here is your result:". NO explanations.
RULE 3: Output MUST exactly match this schema — no extra keys, no missing keys, no reordering:

EXACT REQUIRED SCHEMA:
{{
  "verdict": "CLEAN",
  "issues": [],
  "confidence": 0.95,
  "review_notes": null
}}

FIELD CONSTRAINTS:
- "verdict": string — MUST be exactly one of: "CLEAN", "HALLUCINATION", or "PARTIAL"
- "issues": array of strings — MUST be [] when verdict is "CLEAN"; list specific issues otherwise
- "confidence": float — MUST be a number between 0.0 and 1.0 (e.g. 0.87)

LOGIC REVIEW PROTOCOL: If the compiler succeeds but unit tests fail, do NOT just output the error. You must add a 'review_notes' string explaining EXACTLY why the logic failed (e.g., 'You are returning a 0-indexed array, but the test expects 1-indexed. Adjust the loop.').
{kb}
{compiler}
AUDIT TASK: Review the code below against the plan. Audit specifically for: {audit_targets}

CODE TO AUDIT (language: {lang}):
{code}

ORIGINAL PLAN STEPS:
{steps}

RESPOND WITH THE JSON OBJECT ONLY. YOUR FIRST CHARACTER MUST BE `{{`. YOUR LAST CHARACTER MUST BE `}}`."#,
        kb = kb_section,
        compiler = compiler_section,
        audit_targets = audit_targets,
        lang = code.language,
        code = code.code,
        steps = plan.steps.join("\n")
    );

    emit_telemetry(app_handle, "observer", "Evaluating");
    let raw = call_model(client, model, &prompt, app_handle).await?;

    let verdict: ObserverVerdict = match serde_json::from_str(&raw) {
        Ok(v) => v,
        Err(e) => {
            log::error!(
                "[OBSERVER] Deserialization failed: {}\n[OBSERVER] Full raw output ({} bytes):\n---\n{}\n---",
                e, raw.len(), raw
            );
            log::warn!("[OBSERVER] Attempting regex structural salvage due to JSON truncation.");
            let re_verdict = regex::Regex::new(r#""verdict"\s*:\s*"([^"]+)""#).unwrap();
            let re_conf = regex::Regex::new(r#""confidence"\s*:\s*([0-9]*\.?[0-9]+)"#).unwrap();
            if let Some(caps) = re_verdict.captures(&raw) {
                let salvaged_verdict = caps.get(1).unwrap().as_str().to_string();
                let salvaged_confidence = re_conf
                    .captures(&raw)
                    .and_then(|c| c.get(1))
                    .and_then(|m| m.as_str().parse::<f32>().ok())
                    .filter(|&v| (0.0..=1.0).contains(&v))
                    .unwrap_or(CONFIDENCE_THRESHOLD);
                log::info!(
                    "[OBSERVER] Salvaged verdict: {} (confidence: {:.2})",
                    salvaged_verdict,
                    salvaged_confidence
                );
                ObserverVerdict {
                    verdict: salvaged_verdict,
                    issues: vec!["JSON truncation — salvaged via regex".to_string()],
                    confidence: salvaged_confidence,
                    review_notes: None,
                }
            } else {
                return Err(OrchestratorError::observer(format!(
                    "Schema violation — Observer output did not match ObserverVerdict and salvage failed: {}", e
                )));
            }
        }
    };

    if verdict.confidence < 0.0 || verdict.confidence > 1.0 {
        return Err(OrchestratorError::observer(
            "Observer produced out-of-bounds confidence score".to_string(),
        ));
    }

    emit_telemetry(app_handle, "observer", "Done");
    Ok(verdict)
}

// ─────────────────────────────────────────────────────────────────────────────
// AST EDIT RESOLVER
// ─────────────────────────────────────────────────────────────────────────────

fn apply_ast_edit(
    workspace_root: &Path,
    code: &EngineerCode,
) -> Result<EngineerCode, OrchestratorError> {
    if code.edit_type != "replace_function" || code.target.is_empty() {
        return Ok(code.clone());
    }

    let target_file = code.files_affected.first().ok_or_else(|| {
        OrchestratorError::system("files_affected is empty for replace_function edit".to_string())
    })?;

    let basename = std::path::Path::new(target_file)
        .file_name()
        .unwrap_or_else(|| std::ffi::OsStr::new(target_file));
    let existing_path = workspace_root.join("sandbox").join(basename);

    if !existing_path.exists() {
        log::info!(
            "[AST] '{}' not in sandbox — treating replace_function as full write",
            target_file
        );
        let mut resolved = code.clone();
        resolved.edit_type = "full".to_string();
        return Ok(resolved);
    }

    let source = std::fs::read_to_string(&existing_path).map_err(|e| {
        OrchestratorError::system(format!("Failed to read '{}': {}", target_file, e))
    })?;

    let modified =
        crate::ast_editor::replace_function(&source, &code.language, &code.target, &code.code)
            .map_err(|e| OrchestratorError::system(format!("AST splice failed: {}", e)))?;

    Ok(EngineerCode {
        language: code.language.clone(),
        code: modified,
        files_affected: code.files_affected.clone(),
        edit_type: "full".to_string(),
        target: String::new(),
    })
}

// ─────────────────────────────────────────────────────────────────────────────
// ORCHESTRATOR ACTOR
// ─────────────────────────────────────────────────────────────────────────────

pub struct Orchestrator {
    rx: mpsc::Receiver<MoAMessage>,
    client: Client,
    app_handle: tauri::AppHandle,
    retry_cache: Mutex<HashMap<String, PendingTrainingPair>>,
}

impl Orchestrator {
    fn new(rx: mpsc::Receiver<MoAMessage>, app_handle: tauri::AppHandle) -> Self {
        let client = Client::builder()
            .timeout(Duration::from_secs(transport::OLLAMA_TIMEOUT_SECS))
            .build()
            .expect("Failed to build HTTP client for Ollama transport");
        Self {
            rx,
            client,
            app_handle,
            retry_cache: Mutex::new(HashMap::new()),
        }
    }

    /// Load the config-assigned role models, then apply the request's
    /// model_override (if any) on top -- shared by all three pipeline entry
    /// points (full run, the plan-skip retry path, and the standalone audit
    /// path) so a route picked in the UI takes effect the same way regardless
    /// of which one a request hits.
    fn resolve_models(model_override: Option<&str>) -> PipelineModels {
        let models = PipelineModels::load();
        match PipelineModels::read_config_text() {
            Some(config_text) => models.with_override(&config_text, model_override),
            None => models,
        }
    }

    pub async fn run(mut self) {
        log::info!("[ORCHESTRATOR] Actor loop online. Awaiting MoA dispatch.");

        while let Some(message) = self.rx.recv().await {
            match message {
                MoAMessage::PlanRequest { context, reply } => {
                    log::info!(
                        "[ORCHESTRATOR] PlanRequest received for thread: {}",
                        context.thread_id
                    );
                    let result = self.execute_full_pipeline(context).await;
                    if reply.send(result).is_err() {
                        log::warn!("[ORCHESTRATOR] PlanRequest caller dropped receiver before result arrived.");
                    }
                }

                MoAMessage::CodeGeneration {
                    plan,
                    thread_id,
                    retry_count,
                    model_override,
                    reply,
                } => {
                    log::info!(
                        "[ORCHESTRATOR] CodeGeneration (plan-skip) for thread: {}",
                        thread_id
                    );
                    let ctx = Context {
                        user_prompt: plan.title.clone(),
                        thread_id: thread_id.clone(),
                        retry_count,
                        model_override,
                    };
                    let result = self.execute_from_engineer(plan, ctx).await;
                    if reply.send(result).is_err() {
                        log::warn!("[ORCHESTRATOR] CodeGeneration caller dropped receiver.");
                    }
                }

                MoAMessage::AuditRequest {
                    code,
                    thread_id,
                    model_override,
                    reply,
                } => {
                    log::info!(
                        "[ORCHESTRATOR] AuditRequest (observer-only) for thread: {}",
                        thread_id
                    );
                    let synthetic_plan = SentinelPlan {
                        title: format!("Isolated audit for thread {}", thread_id),
                        steps: vec![],
                        audit_targets: vec![
                            "general correctness".into(),
                            "no hallucinated APIs".into(),
                        ],
                    };
                    let models = Self::resolve_models(model_override.as_deref());
                    let result = run_observer(
                        &self.client,
                        &synthetic_plan,
                        &code,
                        None,
                        "",
                        &self.app_handle,
                        &models.observer,
                    )
                    .await;
                    if reply.send(result).is_err() {
                        log::warn!("[ORCHESTRATOR] AuditRequest caller dropped receiver.");
                    }
                }

                MoAMessage::Shutdown => {
                    log::info!("[ORCHESTRATOR] Shutdown signal received. Draining and halting.");
                    self.rx.close();
                    while self.rx.recv().await.is_some() {}
                    break;
                }
            }
        }

        log::info!("[ORCHESTRATOR] Actor loop terminated.");
    }

    async fn execute_full_pipeline(
        &self,
        context: Context,
    ) -> Result<MoAResult, OrchestratorError> {
        let thread_id = context.thread_id.clone();
        let models = Self::resolve_models(context.model_override.as_deref());

        if context.retry_count > 3 {
            return Err(OrchestratorError::max_retries_exceeded(
                "Max retries exceeded (circuit breaker active). Pipeline bound broken.".to_string(),
            ));
        }

        const VRAM_FLUSH_SECS: u64 = 8;

        let workspace = self.app_handle.state::<crate::fs::WorkspaceRoot>();

        // Workspace RAG
        let rag_results = crate::workspace_search::search(
            &workspace.0.join("sandbox"),
            &context.user_prompt,
            MAX_SEARCH_RESULTS,
        );
        let workspace_context =
            crate::workspace_search::format_for_prompt(&rag_results, &context.user_prompt);
        if !workspace_context.is_empty() {
            log::info!(
                "[WORKSPACE-RAG] Injecting {} snippet(s) into Sentinel context",
                rag_results.len()
            );
            emit_telemetry(
                &self.app_handle,
                "system",
                &format!("RAG|{}", rag_results.len()),
            );
        }

        // Knowledge Base RAG for Sentinel
        let db_state = self.app_handle.state::<crate::db::DbState>();
        let vec_state = self.app_handle.state::<crate::vector_engine::VectorState>();
        let arch_context = retrieve_knowledge_context(
            &context.user_prompt,
            "architecture",
            3,
            db_state.inner(),
            vec_state.inner(),
            Some(&self.app_handle),
        );
        let sentinel_context = if arch_context.is_empty() {
            workspace_context.clone()
        } else {
            format!("{}\n{}", workspace_context, arch_context)
        };
        if !arch_context.is_empty() {
            log::info!("[KNOWLEDGE-RAG] Injected architecture context for Sentinel");
        }

        // STAGE 1: Sentinel
        log::info!(
            "[SENTINEL] Invoking {} for thread {}",
            models.sentinel,
            thread_id
        );
        let plan = run_sentinel(
            &self.client,
            &context,
            &sentinel_context,
            &self.app_handle,
            &models.sentinel,
        )
        .await?;
        log::info!(
            "[SENTINEL] Plan committed: '{}' ({} steps)",
            plan.title,
            plan.steps.len()
        );

        emit_telemetry(&self.app_handle, "system", "FlushingVRAM");
        log::info!(
            "[ORCHESTRATOR] VRAM flush pause {}s (Sentinel eviction window)",
            VRAM_FLUSH_SECS
        );
        tokio::time::sleep(Duration::from_secs(VRAM_FLUSH_SECS)).await;

        // Knowledge Base RAG for Engineer
        let eng_collection = detect_collection(&context.user_prompt);
        let eng_context = retrieve_knowledge_context(
            &context.user_prompt,
            eng_collection,
            3,
            db_state.inner(),
            vec_state.inner(),
            Some(&self.app_handle),
        );
        if !eng_context.is_empty() {
            log::info!(
                "[KNOWLEDGE-RAG] Injected {} collection context for Engineer",
                eng_collection
            );
        }

        // STAGE 2: Engineer
        log::info!(
            "[ENGINEER] Invoking {} for thread {}",
            models.engineer,
            thread_id
        );
        let raw_code = run_engineer(
            &self.client,
            &plan,
            &context,
            &eng_context,
            &self.app_handle,
            &models.engineer,
        )
        .await?;
        log::info!(
            "[ENGINEER] Code produced: {} ({}) edit_type={}",
            raw_code.language,
            raw_code.files_affected.join(", "),
            raw_code.edit_type
        );

        // AST Edit Resolution
        let code = if raw_code.edit_type == "replace_function" {
            log::info!(
                "[AST] Resolving replace_function for target '{}'",
                raw_code.target
            );
            match apply_ast_edit(&workspace.0, &raw_code) {
                Ok(resolved) => resolved,
                Err(e) => {
                    log::warn!(
                        "[AST] Splice failed — degrading to full write: {}",
                        e.message
                    );
                    emit_telemetry(
                        &self.app_handle,
                        "system",
                        &format!("AST|Fallback|{}", &e.message),
                    );
                    let mut fallback = raw_code.clone();
                    fallback.edit_type = "full".to_string();
                    fallback
                }
            }
        } else {
            raw_code
        };

        // Compiler Check
        let primary_file = code
            .files_affected
            .first()
            .map(String::as_str)
            .unwrap_or("output.txt");
        let compiler_feedback = crate::compiler::check(&code.language, primary_file, &code.code);
        if let Some(ref fb) = compiler_feedback {
            log::info!(
                "[COMPILER] {} {} — {} bytes output",
                fb.tool,
                if fb.success { "PASS" } else { "FAIL" },
                fb.output.len()
            );
            emit_telemetry(
                &self.app_handle,
                "system",
                &format!("CompilerCheck|{}", if fb.success { "PASS" } else { "FAIL" }),
            );
        }

        let target_file = code
            .files_affected
            .first()
            .cloned()
            .unwrap_or_else(|| "output.txt".to_string());

        // AEGIS FS JAIL
        let candidate_path = workspace.0.join("sandbox").join(&target_file);
        if !crate::fs::is_safe_path(&workspace.0, &candidate_path) {
            log::error!(
                "[SECURITY] Path traversal attempt blocked! AI requested write to: '{}'",
                candidate_path.display()
            );
            emit_telemetry(
                &self.app_handle,
                "system",
                "SecurityPanic|PathTraversalBlocked",
            );
            return Err(OrchestratorError::security_panic("Path Traversal Blocked"));
        }

        let staging_result =
            crate::fs::stage_files(&workspace, &[(target_file.clone(), code.code.clone())]);
        if let Err(e) = &staging_result {
            log::error!("[ORCHESTRATOR] File staging failed: {}", e);
            return Err(OrchestratorError::system(format!(
                "Failed to stage generated files: {}",
                e
            )));
        }
        let staging_dir = staging_result.unwrap();

        emit_telemetry(&self.app_handle, "system", "FlushingVRAM");
        log::info!(
            "[ORCHESTRATOR] VRAM flush pause {}s (Engineer eviction window)",
            VRAM_FLUSH_SECS
        );
        tokio::time::sleep(Duration::from_secs(VRAM_FLUSH_SECS)).await;

        // Knowledge Base RAG for Observer
        let obs_context = retrieve_knowledge_context(
            &context.user_prompt,
            "architecture",
            2,
            db_state.inner(),
            vec_state.inner(),
            Some(&self.app_handle),
        );
        if !obs_context.is_empty() {
            log::info!("[KNOWLEDGE-RAG] Injected architecture context for Observer");
        }

        // STAGE 3: Observer
        log::info!(
            "[OBSERVER] Invoking {} for thread {}",
            models.observer,
            thread_id
        );
        let audit = run_observer(
            &self.client,
            &plan,
            &code,
            compiler_feedback.as_ref(),
            &obs_context,
            &self.app_handle,
            &models.observer,
        )
        .await?;
        log::info!(
            "[OBSERVER] Verdict: {} (confidence: {:.2})",
            audit.verdict,
            audit.confidence
        );

        let accepted = audit.verdict == "CLEAN" && audit.confidence >= CONFIDENCE_THRESHOLD;

        if accepted {
            if let Err(e) = crate::fs::commit_staged_files(&workspace, &staging_dir) {
                return Err(OrchestratorError::system(format!(
                    "Failed to commit staged files: {}",
                    e
                )));
            }
            log::info!(
                "[ORCHESTRATOR] Successfully committed generated files to active workspace."
            );
            emit_telemetry(
                &self.app_handle,
                "system",
                &format!("FileCommitted|{}|{}", thread_id, target_file),
            );

            // DPO Flywheel
            let pending = self.retry_cache.lock().unwrap().remove(&thread_id);
            if let Some(pair) = pending {
                let workspace_path = workspace.0.clone();
                let good_code = code.code.clone();
                let thread_id_log = thread_id.clone();
                tokio::spawn(async move {
                    let result = tokio::task::spawn_blocking(move || {
                        crate::telemetry_logger::log_training_pair(
                            &workspace_path,
                            &pair.system_prompt,
                            &pair.failed_code,
                            &pair.compiler_error,
                            &good_code,
                        )
                    })
                    .await;
                    match result {
                        Ok(Ok(_)) => log::info!(
                            "[TELEMETRY] DPO training pair logged for thread {}",
                            thread_id_log
                        ),
                        Ok(Err(e)) => log::warn!("[TELEMETRY] Failed to log training pair: {}", e),
                        Err(e) => log::warn!("[TELEMETRY] spawn_blocking panic: {:?}", e),
                    }
                });
            }
        } else {
            crate::fs::clear_staged_files(&workspace);
            log::warn!(
                "[ORCHESTRATOR] Pipeline for thread {} rejected: verdict={}, confidence={:.2}, issues={:?}",
                thread_id, audit.verdict, audit.confidence, audit.issues
            );

            let compiler_passed = compiler_feedback
                .as_ref()
                .map(|fb| fb.success)
                .unwrap_or(true);
            if let Some(ref fb) = compiler_feedback {
                if !fb.success {
                    let system_prompt = format!(
                        "You are the Determinex Engineer. Fix the compiler errors in the code below.\n\
                         Plan: {}\nSteps:\n- {}",
                        plan.title, plan.steps.join("\n- ")
                    );
                    self.retry_cache.lock().unwrap().insert(
                        thread_id.clone(),
                        PendingTrainingPair {
                            system_prompt,
                            failed_code: code.code.clone(),
                            compiler_error: fb.output.clone(),
                        },
                    );
                    log::info!(
                        "[TELEMETRY] Cached compiler failure for thread {} (DPO candidate)",
                        thread_id
                    );
                }
            }
            // Observer rejection of compiler-passing code is also a valuable training signal.
            if compiler_passed {
                let obs_feedback = format!(
                    "Observer verdict: {} (confidence={:.2}). Issues: {}",
                    audit.verdict,
                    audit.confidence,
                    if audit.issues.is_empty() {
                        "none specified".to_string()
                    } else {
                        audit.issues.join("; ")
                    }
                );
                let system_prompt = format!(
                    "You are the Determinex Engineer. Fix the code below to satisfy the Observer's review.\n\
                     Plan: {}\nSteps:\n- {}",
                    plan.title, plan.steps.join("\n- ")
                );
                self.retry_cache.lock().unwrap().insert(
                    thread_id.clone(),
                    PendingTrainingPair {
                        system_prompt,
                        failed_code: code.code.clone(),
                        compiler_error: obs_feedback,
                    },
                );
                log::info!(
                    "[TELEMETRY] Cached Observer rejection for thread {} (DPO candidate)",
                    thread_id
                );
            }

            let issues_str = if audit.issues.is_empty() {
                "no specific issues noted".to_string()
            } else {
                audit.issues.join(";")
            };
            emit_telemetry(
                &self.app_handle,
                "observer",
                &format!(
                    "Rejected|{}|{:.2}|{}",
                    audit.verdict, audit.confidence, issues_str
                ),
            );
        }

        Ok(MoAResult {
            thread_id,
            plan,
            code,
            audit,
            accepted,
        })
    }

    async fn execute_from_engineer(
        &self,
        plan: SentinelPlan,
        context: Context,
    ) -> Result<MoAResult, OrchestratorError> {
        let thread_id = context.thread_id.clone();
        let models = Self::resolve_models(context.model_override.as_deref());

        if context.retry_count > 3 {
            return Err(OrchestratorError::max_retries_exceeded(
                "Max retries exceeded (circuit breaker active). Pipeline bound broken.".to_string(),
            ));
        }

        log::info!(
            "[ENGINEER] Invoking {} for thread {} (plan-skip mode)",
            models.engineer,
            thread_id
        );
        let raw_code = run_engineer(
            &self.client,
            &plan,
            &context,
            "",
            &self.app_handle,
            &models.engineer,
        )
        .await?;

        let workspace = self.app_handle.state::<crate::fs::WorkspaceRoot>();

        let code = if raw_code.edit_type == "replace_function" {
            log::info!(
                "[AST] Resolving replace_function for target '{}' (plan-skip)",
                raw_code.target
            );
            match apply_ast_edit(&workspace.0, &raw_code) {
                Ok(resolved) => resolved,
                Err(e) => {
                    log::warn!(
                        "[AST] Splice failed (plan-skip) — degrading to full write: {}",
                        e.message
                    );
                    emit_telemetry(
                        &self.app_handle,
                        "system",
                        &format!("AST|Fallback|{}", &e.message),
                    );
                    let mut fallback = raw_code.clone();
                    fallback.edit_type = "full".to_string();
                    fallback
                }
            }
        } else {
            raw_code
        };

        let primary_file = code
            .files_affected
            .first()
            .map(String::as_str)
            .unwrap_or("output.txt");
        let compiler_feedback = crate::compiler::check(&code.language, primary_file, &code.code);
        if let Some(ref fb) = compiler_feedback {
            log::info!(
                "[COMPILER] {} {} — {} bytes (plan-skip)",
                fb.tool,
                if fb.success { "PASS" } else { "FAIL" },
                fb.output.len()
            );
            emit_telemetry(
                &self.app_handle,
                "system",
                &format!("CompilerCheck|{}", if fb.success { "PASS" } else { "FAIL" }),
            );
        }

        let target_file = code
            .files_affected
            .first()
            .cloned()
            .unwrap_or_else(|| "output.txt".to_string());

        let candidate_path = workspace.0.join("sandbox").join(&target_file);
        if !crate::fs::is_safe_path(&workspace.0, &candidate_path) {
            log::error!(
                "[SECURITY] Path traversal attempt blocked (plan-skip)! AI requested: '{}'",
                candidate_path.display()
            );
            emit_telemetry(
                &self.app_handle,
                "system",
                "SecurityPanic|PathTraversalBlocked",
            );
            return Err(OrchestratorError::security_panic("Path Traversal Blocked"));
        }

        let staging_result =
            crate::fs::stage_files(&workspace, &[(target_file, code.code.clone())]);
        if let Err(e) = &staging_result {
            log::error!("[ORCHESTRATOR] File staging failed: {}", e);
            return Err(OrchestratorError::system(format!(
                "Failed to stage generated files: {}",
                e
            )));
        }
        let staging_dir = staging_result.unwrap();

        emit_telemetry(&self.app_handle, "system", "FlushingVRAM");
        tokio::time::sleep(Duration::from_secs(8)).await;

        log::info!(
            "[OBSERVER] Invoking {} for thread {} (plan-skip mode)",
            models.observer,
            thread_id
        );
        let audit = run_observer(
            &self.client,
            &plan,
            &code,
            compiler_feedback.as_ref(),
            "",
            &self.app_handle,
            &models.observer,
        )
        .await?;

        let accepted = audit.verdict == "CLEAN" && audit.confidence >= CONFIDENCE_THRESHOLD;

        if accepted {
            if let Err(e) = crate::fs::commit_staged_files(&workspace, &staging_dir) {
                return Err(OrchestratorError::system(format!(
                    "Failed to commit staged files: {}",
                    e
                )));
            }
            log::info!(
                "[ORCHESTRATOR] Successfully committed generated files to active workspace."
            );

            let vanguard = self
                .app_handle
                .state::<crate::vanguard_state::VanguardState>();
            if vanguard.is_enabled() {
                let pending = self.retry_cache.lock().unwrap().remove(&thread_id);
                if let Some(pair) = pending {
                    let workspace_path = workspace.0.clone();
                    let good_code = code.code.clone();
                    let thread_id_log = thread_id.clone();
                    tokio::spawn(async move {
                        let result = tokio::task::spawn_blocking(move || {
                            crate::telemetry_logger::log_training_pair(
                                &workspace_path,
                                &pair.system_prompt,
                                &pair.failed_code,
                                &pair.compiler_error,
                                &good_code,
                            )
                        })
                        .await;
                        match result {
                            Ok(Ok(_)) => log::info!(
                                "[TELEMETRY] DPO training pair logged for thread {}",
                                thread_id_log
                            ),
                            Ok(Err(e)) => {
                                log::warn!("[TELEMETRY] Failed to log training pair: {}", e)
                            }
                            Err(e) => log::warn!("[TELEMETRY] spawn_blocking panic: {:?}", e),
                        }
                    });
                }
            } else {
                self.retry_cache.lock().unwrap().remove(&thread_id);
                log::debug!(
                    "[TELEMETRY] Vanguard opt-in is OFF — training pair discarded for thread {}",
                    thread_id
                );
            }
        } else {
            crate::fs::clear_staged_files(&workspace);

            if let Some(ref fb) = compiler_feedback {
                if !fb.success {
                    let system_prompt = format!(
                        "You are the Determinex Engineer. Fix the compiler errors in the code below.\n\
                         Plan: {}\nSteps:\n- {}",
                        plan.title, plan.steps.join("\n- ")
                    );
                    self.retry_cache.lock().unwrap().insert(
                        thread_id.clone(),
                        PendingTrainingPair {
                            system_prompt,
                            failed_code: code.code.clone(),
                            compiler_error: fb.output.clone(),
                        },
                    );
                    log::info!("[TELEMETRY] Cached compiler failure for thread {} (plan-skip DPO candidate)", thread_id);
                }
            }

            let issues_str = if audit.issues.is_empty() {
                "no specific issues noted".to_string()
            } else {
                audit.issues.join(";")
            };
            emit_telemetry(
                &self.app_handle,
                "observer",
                &format!(
                    "Rejected|{}|{:.2}|{}",
                    audit.verdict, audit.confidence, issues_str
                ),
            );
        }

        Ok(MoAResult {
            thread_id,
            plan,
            code,
            audit,
            accepted,
        })
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// PUBLIC HANDLE
// ─────────────────────────────────────────────────────────────────────────────

#[derive(Clone)]
pub struct OrchestratorHandle {
    tx: mpsc::Sender<MoAMessage>,
}

impl OrchestratorHandle {
    pub fn spawn(buffer_size: usize, app_handle: tauri::AppHandle) -> Self {
        let (tx, rx) = mpsc::channel::<MoAMessage>(buffer_size);
        let orchestrator = Orchestrator::new(rx, app_handle);
        tauri::async_runtime::spawn(async move {
            orchestrator.run().await;
        });
        Self { tx }
    }

    pub async fn plan_request(&self, context: Context) -> Result<MoAResult, OrchestratorError> {
        let (reply_tx, reply_rx) = oneshot::channel();
        self.tx
            .send(MoAMessage::PlanRequest {
                context,
                reply: reply_tx,
            })
            .await
            .map_err(|_| OrchestratorError::transport("Orchestrator channel closed".to_string()))?;
        reply_rx.await.map_err(|_| {
            OrchestratorError::transport("Orchestrator dropped reply before responding".to_string())
        })?
    }

    pub async fn code_generation(
        &self,
        plan: SentinelPlan,
        thread_id: String,
        retry_count: u32,
        model_override: Option<String>,
    ) -> Result<MoAResult, OrchestratorError> {
        let (reply_tx, reply_rx) = oneshot::channel();
        self.tx
            .send(MoAMessage::CodeGeneration {
                plan,
                thread_id,
                retry_count,
                model_override,
                reply: reply_tx,
            })
            .await
            .map_err(|_| OrchestratorError::transport("Orchestrator channel closed".to_string()))?;
        reply_rx.await.map_err(|_| {
            OrchestratorError::transport("Orchestrator dropped reply before responding".to_string())
        })?
    }

    pub async fn audit_request(
        &self,
        code: EngineerCode,
        thread_id: String,
        model_override: Option<String>,
    ) -> Result<ObserverVerdict, OrchestratorError> {
        let (reply_tx, reply_rx) = oneshot::channel();
        self.tx
            .send(MoAMessage::AuditRequest {
                code,
                thread_id,
                model_override,
                reply: reply_tx,
            })
            .await
            .map_err(|_| OrchestratorError::transport("Orchestrator channel closed".to_string()))?;
        reply_rx.await.map_err(|_| {
            OrchestratorError::transport("Orchestrator dropped reply before responding".to_string())
        })?
    }

    pub async fn shutdown(&self) {
        let _ = self.tx.send(MoAMessage::Shutdown).await;
    }
}
