use anyhow::Result;
use clap::{Parser, Subcommand};
use std::path::PathBuf;
use tracing_subscriber::{EnvFilter, FmtSubscriber};
use agent_core::chat::{ChatMessage, Tool, Function};
use agent_core::agent_loop::AgentLoop;

mod executor;

#[derive(Parser)]
#[command(author, version, about = "Flint Code - Agentic Workflow V2")]
struct Cli {
    #[command(subcommand)]
    command: Commands,
}

#[derive(Subcommand)]
enum Commands {
    Health {
        #[arg(long, default_value = "profiles/default.toml")]
        profile: PathBuf,
    },
    Run {
        #[arg(long)]
        task: PathBuf,
        #[arg(long, default_value = "profiles/default.toml")]
        profile: PathBuf,
        #[arg(long, default_value = "runs")]
        output: PathBuf,
        #[arg(long)]
        skill: Option<PathBuf>,
        #[arg(long)]
        build_target: Option<String>,
    },
}

fn build_tools() -> Vec<Tool> {
    vec![
        Tool {
            r#type: "function".to_string(),
            function: Function {
                name: "read_file".to_string(),
                description: Some("Read the contents of a file".to_string()),
                parameters: Some(serde_json::json!({
                    "type": "object",
                    "properties": {
                        "path": { "type": "string", "description": "Absolute or relative path to file" }
                    },
                    "required": ["path"]
                })),
            },
        },
        Tool {
            r#type: "function".to_string(),
            function: Function {
                name: "write_file".to_string(),
                description: Some("Write content to a file".to_string()),
                parameters: Some(serde_json::json!({
                    "type": "object",
                    "properties": {
                        "path": { "type": "string", "description": "Path to file" },
                        "content": { "type": "string", "description": "Content to write" }
                    },
                    "required": ["path", "content"]
                })),
            },
        },
        Tool {
            r#type: "function".to_string(),
            function: Function {
                name: "run_command".to_string(),
                description: Some("Run a shell command (e.g. cargo check, ls, etc.)".to_string()),
                parameters: Some(serde_json::json!({
                    "type": "object",
                    "properties": {
                        "command": { "type": "string", "description": "The bash command to run" }
                    },
                    "required": ["command"]
                })),
            },
        },
        Tool {
            r#type: "function".to_string(),
            function: Function {
                name: "finish_task".to_string(),
                description: Some("Call this tool when the task is fully completed".to_string()),
                parameters: Some(serde_json::json!({
                    "type": "object",
                    "properties": {
                        "summary": { "type": "string", "description": "Summary of what was done" }
                    },
                    "required": ["summary"]
                })),
            },
        }
    ]
}

#[tokio::main]
async fn main() -> Result<()> {
    let subscriber = FmtSubscriber::builder()
        .with_env_filter(EnvFilter::from_default_env().add_directive(tracing::Level::INFO.into()))
        .with_target(true)
        .with_file(false)
        .with_line_number(false)
        .finish();

    tracing::subscriber::set_global_default(subscriber).expect("Failed to set tracing subscriber");
    let cli = Cli::parse();

    match cli.command {
        Commands::Health { profile } => {
            let model_profile = model_vllm::profile::ModelProfile::load(&profile)?;
            let _client = model_vllm::backend::ModelClient::from_profile(model_profile)?;
            eprintln!("Checking healthy... (Mock implementation for now)");
        }
        Commands::Run { task, profile, output: _, skill, build_target } => {
            tracing::info!("Agentic PoC Loop starting for task: {:?}", task);
            
            let model_profile = model_vllm::profile::ModelProfile::load(&profile)?;
            let client = model_vllm::backend::ModelClient::from_profile(model_profile.clone())?;

            let mut system_prompt = format!("You are an autonomous coding agent. Your goal is to complete the task defined in {:?}. Use tools to read files, edit code, and run terminal commands to verify your work. Once all checks pass, call finish_task.", task);
            if let Some(s) = skill {
                system_prompt.push_str(&format!("\n\nCRITICAL INSTRUCTION: You MUST strictly follow the skill guide at {:?}. Open and read it first.", s));
            }
            if let Some(bt) = build_target {
                system_prompt.push_str(&format!("\n\nYou must generate the `{}` target.", bt));
            }

            // Inject global AGENTS.md rules
            if let Ok(global_agents_md) = std::fs::read_to_string("AGENTS.md") {
                system_prompt.push_str("\n\n--- GLOBAL AGENT RULES ---\n");
                system_prompt.push_str(&global_agents_md);
            }

            let mut messages = vec![
                ChatMessage {
                    role: "system".to_string(),
                    content: Some(system_prompt),
                    name: None,
                    tool_calls: None,
                    tool_call_id: None,
                },
                ChatMessage {
                    role: "user".to_string(),
                    content: Some("Please start the task now.".to_string()),
                    name: None,
                    tool_calls: None,
                    tool_call_id: None,
                }
            ];

            let tools = build_tools();
            let executor = executor::StandardToolExecutor;
            let mut agent_config = agent_core::agent_loop::AgentConfig::default();
            agent_config.max_tokens = model_profile.context.max_prompt_tokens as usize;
            let agent = AgentLoop::with_config(client, executor, tools, agent_config);

            agent.run(messages).await?;
            
            eprintln!("✓ PoC Loop finished.");
        }
    }
    Ok(())
}
