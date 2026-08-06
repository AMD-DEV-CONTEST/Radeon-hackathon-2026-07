//! Agentic build loop using LLM tool calling.
//!
//! Implements a ReAct (Reason-Act) loop where the LLM inspects a project,
//! runs build commands, reads/writes files, and fixes compilation errors
//! autonomously. This makes the build pipeline language-agnostic — the LLM
//! determines the appropriate build commands based on the project structure.

use std::path::Path;
use tracing::{error, info, warn};

use crate::tools::{build_tool_definitions, execute_tool};
use model_vllm::chat::{ChatMessage, FunctionCall, ToolCall};
use model_vllm::client::VllmClient;

/// Result of an agentic build loop
#[derive(Debug)]
pub enum AgentLoopResult {
    /// Agent completed successfully (returned text with no more tool calls)
    Completed {
        /// Final text summary from the agent
        summary: String,
        /// Number of LLM round-trips
        iterations: usize,
        /// Total number of tool calls executed
        total_tool_calls: usize,
    },
    /// Agent failed with an unrecoverable error
    Failed { error: String, iterations: usize },
    /// Agent hit the maximum iteration limit without completing
    MaxIterationsReached {
        iterations: usize,
        total_tool_calls: usize,
    },
}

/// Run an agentic build loop that uses tool calling to compile and fix a project.
///
/// The LLM is given tools (run_command, read_file, write_file, list_directory)
/// and a prompt describing the task. It autonomously inspects the project,
/// identifies the build system, compiles, and fixes errors until the build
/// succeeds or the iteration limit is reached.
///
/// # Arguments
/// * `client` - The vLLM client for model inference
/// * `sandbox_dir` - The project directory (all tool operations are sandboxed here)
/// * `system_prompt` - System prompt describing the agent's role
/// * `user_prompt` - Initial task description with project context
/// * `max_iterations` - Maximum number of LLM round-trips before giving up
pub async fn run_agent_loop(
    client: &VllmClient,
    sandbox_dir: &Path,
    system_prompt: &str,
    user_prompt: &str,
    max_iterations: usize,
    event_tx: Option<tokio::sync::mpsc::Sender<agent_core::RunEvent>>,
) -> AgentLoopResult {
    let tools = build_tool_definitions();

    let mut messages = vec![
        ChatMessage::system(system_prompt),
        ChatMessage::user(user_prompt),
    ];

    let mut total_tool_calls = 0usize;
    let mut iters_without_action = 0usize; // Track iterations without run_command or write_file

    for iteration in 0..max_iterations {
        info!(
            iteration,
            total_tool_calls,
            msgs = messages.len(),
            "Agent loop iteration"
        );

        // Call the model with tool definitions
        let result = client
            .chat(messages.clone(), Some(tools.clone()), None)
            .await;

        match result {
            Ok(model_result) => {
                let tool_calls = model_result.tool_calls.map(|calls| {
                    calls
                        .into_iter()
                        .map(|call| ToolCall {
                            id: call.id,
                            r#type: "function".to_string(),
                            function: FunctionCall {
                                name: call.name,
                                arguments: call.arguments,
                            },
                        })
                        .collect::<Vec<_>>()
                });

                match tool_calls {
                    Some(ref calls) if !calls.is_empty() => {
                        // Model wants to call tools — execute them
                        info!(
                            iteration,
                            num_calls = calls.len(),
                            "Agent requested tool calls"
                        );

                        // Track whether this iteration includes an "action" tool
                        let has_action = calls.iter().any(|tc| {
                            tc.function.name == "run_command" || tc.function.name == "write_file"
                        });
                        if has_action {
                            iters_without_action = 0;
                        } else {
                            iters_without_action += 1;
                        }

                        // Add the assistant's message (with tool calls) to history
                        messages.push(ChatMessage::assistant_with_tool_calls(
                            &model_result.content,
                            calls.clone(),
                        ));

                        // Execute each tool call and append results
                        for tc in calls {
                            total_tool_calls += 1;
                            info!(
                                iteration,
                                tool = %tc.function.name,
                                id = %tc.id,
                                "Executing tool call"
                            );

                            let command_str = if tc.function.name == "run_command" {
                                if let Ok(args) = serde_json::from_str::<serde_json::Value>(&tc.function.arguments) {
                                    args.get("command").and_then(|c| c.as_str()).unwrap_or(&tc.function.arguments).to_string()
                                } else {
                                    tc.function.arguments.clone()
                                }
                            } else {
                                format!("{} {}", tc.function.name, tc.function.arguments)
                            };

                            let cmd_id = total_tool_calls as u64;

                            if let Some(tx) = &event_tx {
                                tx.send(agent_core::RunEvent::ToolProcessStarted {
                                    id: cmd_id,
                                    command: command_str,
                                }).await.ok();
                            }

                            let tool_result = execute_tool(
                                &tc.function.name,
                                &tc.function.arguments,
                                sandbox_dir,
                            )
                            .await;

                            if let Some(tx) = &event_tx {
                                tx.send(agent_core::RunEvent::ToolProcessFinished {
                                    id: cmd_id,
                                    success: !tool_result.to_lowercase().contains("error"),
                                    exit_code: None,
                                }).await.ok();
                            }

                            messages.push(ChatMessage::tool_result(&tc.id, &tool_result));
                        }

                        // Nudge: if the agent has been exploring without acting, prod it
                        if iters_without_action >= 3 {
                            warn!(
                                iteration,
                                iters_without_action,
                                "Agent stuck in exploration — injecting nudge"
                            );
                            messages.push(ChatMessage::user(
                                "STOP exploring. You have read enough files. Now take action:\n\
                                 1. If there is a pom.xml, run: run_command({\"command\": \"mvn compile -f pom.xml\"})\n\
                                 2. If there is a Cargo.toml, run: run_command({\"command\": \"cargo check\"})\n\
                                 3. If business logic code is missing, use write_file to create it.\n\
                                 DO NOT call list_directory or read_file again until you have tried compiling."
                            ));
                            iters_without_action = 0; // Reset so we don't spam
                        }
                    }
                    _ => {
                        // No tool calls — agent has finished
                        info!(
                            iteration,
                            total_tool_calls, "Agent completed with text response"
                        );
                        return AgentLoopResult::Completed {
                            summary: model_result.content,
                            iterations: iteration + 1,
                            total_tool_calls,
                        };
                    }
                }
            }
            Err(e) => {
                error!(iteration, %e, "Model call failed in agent loop");
                return AgentLoopResult::Failed {
                    error: e.to_string(),
                    iterations: iteration + 1,
                };
            }
        }
    }

    warn!(
        max_iterations,
        total_tool_calls, "Agent loop reached max iterations without completing"
    );
    AgentLoopResult::MaxIterationsReached {
        iterations: max_iterations,
        total_tool_calls,
    }
}
