use crate::chat::{ChatMessage, FunctionCall, Tool, ToolCall};
use crate::context::ContextManager;
use crate::error::AgentError;
use crate::event::ModelResult;
use crate::exit_strategy::{ExitAction, ExitStrategyKind, LoopContext};
use crate::loop_guard::LoopGuard;
use std::future::Future;
use std::sync::Arc;
use tokio::sync::Mutex;

pub trait ModelBackend {
    fn chat(
        &self,
        messages: Vec<ChatMessage>,
        tools: Option<Vec<Tool>>,
    ) -> impl Future<Output = Result<ModelResult, AgentError>> + Send;
}

pub trait ToolExecutor {
    fn execute(
        &self,
        name: &str,
        arguments: &str,
    ) -> impl Future<Output = Result<String, AgentError>> + Send;
}

pub struct AgentConfig {
    pub max_iterations: usize,
    pub max_tokens: usize,
    pub trim_ratio: f32,
    /// Number of consecutive identical calls/prompts before loop detection triggers
    pub loop_threshold: usize,
    /// Strategy to use when a loop is detected
    pub exit_strategy: ExitStrategyKind,
    /// Maximum total tokens (prompt + completion) across the entire run.
    /// 0 means unlimited.
    pub max_total_tokens: u64,
}

impl Default for AgentConfig {
    fn default() -> Self {
        Self {
            max_iterations: 1000,
            max_tokens: 32000,
            trim_ratio: 0.25,
            loop_threshold: 10,
            exit_strategy: ExitStrategyKind::default(),
            max_total_tokens: 0,
        }
    }
}

pub struct AgentLoop<M, E> {
    model: M,
    executor: E,
    tools: Vec<Tool>,
    config: AgentConfig,
}

impl<M: ModelBackend, E: ToolExecutor> AgentLoop<M, E> {
    pub fn new(model: M, executor: E, tools: Vec<Tool>) -> Self {
        Self::with_config(model, executor, tools, AgentConfig::default())
    }

    pub fn with_config(model: M, executor: E, tools: Vec<Tool>, config: AgentConfig) -> Self {
        Self {
            model,
            executor,
            tools,
            config,
        }
    }

    /// Helper to trim context while avoiding orphaning tool messages
    fn trim_messages(messages: &mut Vec<ChatMessage>, trim_ratio: f32) {
        let preserve_count = if messages.len() > 1 && messages[1].role == "user" {
            2
        } else {
            1
        };
        if messages.len() <= preserve_count + 1 {
            return;
        }
        let target_drop = ((messages.len() as f32) * trim_ratio) as usize;
        if target_drop == 0 {
            return;
        }

        let mut drop_end = preserve_count + target_drop;
        while drop_end < messages.len() {
            if messages[drop_end].role != "tool" {
                break;
            }
            drop_end += 1;
        }

        if drop_end < messages.len() {
            messages.drain(preserve_count..drop_end);
        }
    }

    pub async fn run(&self, mut messages: Vec<ChatMessage>) -> Result<(), AgentError> {
        let mut iterations = 0;
        let mut total_tokens_used: u64 = 0;
        let mut guard = LoopGuard::new(self.config.loop_threshold);
        let strategy = self.config.exit_strategy.build();

        let context = Arc::new(Mutex::new(ContextManager::new()));

        // Parse initial system prompt if present
        if !messages.is_empty() && messages[0].role == "system" {
            if let Some(ref content) = messages[0].content {
                context.lock().await.load_from_str("system", content);
                messages[0].content = Some(context.lock().await.render_active_prompt());
            }
        }

        crate::context::start_debug_server(context.clone());

        loop {
            iterations += 1;
            if iterations > self.config.max_iterations {
                tracing::error!(
                    "Agent Loop exceeded max iterations ({})",
                    self.config.max_iterations
                );
                break;
            }

            // --- Ephemeral Cleanup (阅后即焚) ---
            let safe_byte_limit = self.config.max_tokens * 3; // roughly 3 bytes per token
            let last_assistant_idx = messages
                .iter()
                .rposition(|m| m.role == "assistant")
                .unwrap_or(0);

            // 1. Explicitly marked ephemeral tools are always truncated
            for i in 0..last_assistant_idx {
                if messages[i].role == "tool" {
                    if let Some(ref content) = messages[i].content {
                        if content.contains("<!-- ephemeral -->") {
                            messages[i].content = Some(format!(
                                "[EPHEMERAL: Output omitted explicitly (Original size: {} bytes)]",
                                content.len()
                            ));
                        }
                    }
                }
            }

            // 2. Dynamically truncate historical tool outputs if we are over budget
            loop {
                let current_bytes: usize = messages
                    .iter()
                    .map(|m| {
                        let mut size = m.content.as_ref().map(|c| c.len()).unwrap_or(0);
                        if let Some(calls) = &m.tool_calls {
                            for c in calls {
                                size += c.function.name.len();
                                size += c.function.arguments.len();
                            }
                        }
                        size
                    })
                    .sum();
                if current_bytes <= safe_byte_limit {
                    break;
                }

                let mut largest_idx = None;
                let mut max_len = 1000;

                for i in 0..last_assistant_idx {
                    if messages[i].role == "tool" {
                        if let Some(ref content) = messages[i].content {
                            if content.len() > max_len && !content.starts_with("[EPHEMERAL:") {
                                max_len = content.len();
                                largest_idx = Some(i);
                            }
                        }
                    }
                }

                if let Some(idx) = largest_idx {
                    let original_size = messages[idx].content.as_ref().unwrap().len();
                    tracing::info!(
                        "Dynamic Ephemeral: Truncating tool output at idx {} (size: {}) to save context",
                        idx,
                        original_size
                    );
                    messages[idx].content = Some(format!(
                        "[EPHEMERAL: Output omitted dynamically for context limits (Original size: {} bytes)]",
                        original_size
                    ));
                } else {
                    break;
                }
            }

            // --- Explicit Skill Block Discarding ---
            let mut blocks_to_discard = std::collections::HashSet::new();
            for m in &messages {
                if let Some(ref content) = m.content {
                    let mut idx = 0;
                    while let Some(start) = content[idx..].find("<!-- DISCARD_BLOCK: ") {
                        let actual_start = idx + start + "<!-- DISCARD_BLOCK: ".len();
                        if let Some(end) = content[actual_start..].find(" -->") {
                            let block_id = content[actual_start..actual_start + end].trim();
                            blocks_to_discard.insert(block_id.to_string());
                            idx = actual_start + end + " -->".len();
                        } else {
                            break;
                        }
                    }
                }
            }

            if !blocks_to_discard.is_empty() {
                let mut ctx = context.lock().await;
                let mut changed = false;
                for id in &blocks_to_discard {
                    if ctx.discard_block(id) {
                        tracing::info!("Discarding explicit skill block: {}", id);
                        changed = true;
                    }
                }
                if changed && !messages.is_empty() && messages[0].role == "system" {
                    messages[0].content = Some(ctx.render_active_prompt());
                }
            }
            // ------------------------------------

            // --- Prompt Repeat Detection ---
            if let Some(detection) = guard.record_prompt(&messages) {
                let ctx = LoopContext {
                    detection: &detection,
                    iteration: iterations,
                    max_iterations: self.config.max_iterations,
                    messages: &messages,
                };
                match strategy.on_loop_detected(&ctx) {
                    ExitAction::Abort { reason } => {
                        tracing::error!("Loop guard abort (prompt): {}", reason);
                        return Err(AgentError::LoopDetected {
                            pattern: detection.to_string(),
                            iterations,
                        });
                    }
                    ExitAction::Intervene { message } => {
                        tracing::warn!("Loop guard intervention (prompt): {}", message);
                        messages.push(ChatMessage {
                            role: "user".to_string(),
                            content: Some(message),
                            name: None,
                            tool_calls: None,
                            tool_call_id: None,
                        });
                        guard.reset();
                    }
                    ExitAction::Ignore => {}
                }
            }

            tracing::info!("Querying LLM (Messages: {})...", messages.len());

            let result = self
                .model
                .chat(messages.clone(), Some(self.tools.clone()))
                .await?;

            // --- Token Budget Tracking ---
            total_tokens_used += result.usage.total_tokens as u64;
            if self.config.max_total_tokens > 0 && total_tokens_used > self.config.max_total_tokens
            {
                tracing::error!(
                    "Token budget exhausted: used {} > limit {}",
                    total_tokens_used,
                    self.config.max_total_tokens
                );
                return Err(AgentError::BudgetExceeded {
                    estimated: total_tokens_used as u32,
                    limit: self.config.max_total_tokens as u32,
                });
            }
            tracing::debug!(
                "Token usage: iteration={}, this_call={}, cumulative={}{}",
                iterations,
                result.usage.total_tokens,
                total_tokens_used,
                if self.config.max_total_tokens > 0 {
                    format!("/{}", self.config.max_total_tokens)
                } else {
                    String::new()
                }
            );

            if result.usage.prompt_tokens > self.config.max_tokens as u32 {
                tracing::warn!(
                    "Context size {} exceeds max tokens {}. Trimming context...",
                    result.usage.prompt_tokens,
                    self.config.max_tokens
                );
                Self::trim_messages(&mut messages, self.config.trim_ratio);
            }

            // Add the assistant's message to the conversation
            messages.push(ChatMessage {
                role: "assistant".to_string(),
                content: if result.content.is_empty() {
                    None
                } else {
                    Some(result.content.clone())
                },
                name: None,
                tool_calls: result.tool_calls.as_ref().map(|calls| {
                    calls
                        .iter()
                        .map(|c| ToolCall {
                            id: c.id.clone(),
                            r#type: "function".to_string(),
                            function: FunctionCall {
                                name: c.name.clone(),
                                arguments: c.arguments.clone(),
                            },
                        })
                        .collect()
                }),
                tool_call_id: None,
            });

            if let Some(calls) = result.tool_calls {
                let mut finished = false;
                for call in calls {
                    tracing::info!(
                        "Executing Tool: {} with arguments: {}",
                        call.name,
                        call.arguments
                    );

                    let mut tool_output =
                        match self.executor.execute(&call.name, &call.arguments).await {
                            Ok(output) => {
                                if call.name == "finish_task" {
                                    tracing::info!("Task finished by Agent: {}", call.arguments);
                                    finished = true;
                                }
                                output
                            }
                            Err(e) => format!("Error executing tool: {}", e),
                        };

                    // --- Tool Repeat Detection ---
                    if let Some(detection) =
                        guard.record_tool_call(&call.name, &call.arguments, &tool_output)
                    {
                        let ctx = LoopContext {
                            detection: &detection,
                            iteration: iterations,
                            max_iterations: self.config.max_iterations,
                            messages: &messages,
                        };
                        match strategy.on_loop_detected(&ctx) {
                            ExitAction::Abort { reason } => {
                                tracing::error!("Loop guard abort (tool): {}", reason);
                                return Err(AgentError::LoopDetected {
                                    pattern: detection.to_string(),
                                    iterations,
                                });
                            }
                            ExitAction::Intervene { message } => {
                                tracing::warn!("Loop guard intervention (tool): {}", message);
                                tool_output = format!("{}\n\n{}", tool_output, message);
                                guard.reset();
                            }
                            ExitAction::Ignore => {}
                        }
                    }

                    // --- Dynamic Tool Output Truncation ---
                    let current_bytes: usize = messages
                        .iter()
                        .map(|m| {
                            let mut size = m.content.as_ref().map(|c| c.len()).unwrap_or(0);
                            if let Some(calls) = &m.tool_calls {
                                for c in calls {
                                    size += c.function.name.len();
                                    size += c.function.arguments.len();
                                }
                            }
                            size
                        })
                        .sum();
                    let safe_byte_limit = self.config.max_tokens * 3;
                    // Cap the maximum tool output so it doesn't eat up the LLM's budget
                    let mut allowed_bytes = safe_byte_limit
                        .saturating_sub(current_bytes)
                        .saturating_sub(4000);
                    allowed_bytes = allowed_bytes.min(16000).max(2000);

                    if tool_output.len() > allowed_bytes {
                        tracing::warn!(
                            "Tool output too large ({}), applying head/tail truncation",
                            tool_output.len()
                        );
                        let lines: Vec<&str> = tool_output.lines().collect();
                        if lines.len() > 40 {
                            let head_10 = lines[..10].join("\n");
                            let tail_10 = lines[lines.len() - 10..].join("\n");

                            let mut final_head = head_10.clone();
                            let mut final_tail = tail_10.clone();

                            if head_10.len() + tail_10.len() < 1000 {
                                let head_20 = lines[..20].join("\n");
                                let tail_20 = lines[lines.len() - 20..].join("\n");
                                if head_20.len() + tail_20.len() <= 2000 {
                                    final_head = head_20;
                                    final_tail = tail_20;
                                }
                            }

                            let truncated_msg = format!(
                                "\n\n...[TRUNCATED: Middle omitted. Original size: {} bytes, {} lines]...\n\n",
                                tool_output.len(),
                                lines.len()
                            );
                            tool_output = format!("{}{}{}", final_head, truncated_msg, final_tail);

                            // Last resort fallback if individual lines are massively long
                            if tool_output.len() > allowed_bytes {
                                let mut boundary =
                                    allowed_bytes.saturating_sub(truncated_msg.len());
                                while boundary > 0 && !tool_output.is_char_boundary(boundary) {
                                    boundary -= 1;
                                }
                                tool_output.truncate(boundary);
                                tool_output.push_str(&truncated_msg);
                            }
                        } else {
                            let truncated_msg = format!(
                                "\n...[TRUNCATED: Original size: {} bytes]",
                                tool_output.len()
                            );
                            let mut boundary = allowed_bytes.saturating_sub(truncated_msg.len());
                            while boundary > 0 && !tool_output.is_char_boundary(boundary) {
                                boundary -= 1;
                            }
                            tool_output.truncate(boundary);
                            tool_output.push_str(&truncated_msg);
                        }
                    }

                    messages.push(ChatMessage {
                        role: "tool".to_string(),
                        content: Some(tool_output),
                        name: Some(call.name),
                        tool_calls: None,
                        tool_call_id: Some(call.id),
                    });
                }

                if finished {
                    break;
                }
            } else if result.finish_reason == "stop" {
                tracing::warn!(
                    "Agent stopped without calling finish_task. Content: {}",
                    result.content
                );
                break;
            }
        }

        Ok(())
    }
}
