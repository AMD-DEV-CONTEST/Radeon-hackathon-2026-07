use anyhow::Result;
use clap::{Parser, Subcommand};
use std::path::PathBuf;
use tracing_subscriber::{EnvFilter, FmtSubscriber};


mod executor;

#[derive(Parser)]
#[command(author, version, about = "Klint Code - Agentic Workflow V2")]
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
        Commands::Run { task, profile, output: _, skill: _, build_target } => {
            tracing::info!("Pipeline starting for task: {:?}", task);

            let model_profile = model_vllm::profile::ModelProfile::load(&profile)?;
            let run_id = format!("run-{}", chrono::Utc::now().format("%Y%m%d-%H%M%S"));

            let (side_effect_tx, _side_effect_rx) = tokio::sync::mpsc::channel(32);
            let (mut controller, controller_event_tx) = agent_core::run_controller::RunController::new(
                run_id.clone(),
                model_profile.run.max_repairs,
                side_effect_tx,
            );

            let (proxy_event_tx, mut proxy_event_rx) = tokio::sync::mpsc::channel(64);
            let runs_root = std::path::PathBuf::from("runs");
            let mut executor = pipeline::executor::PipelineExecutor::new(
                model_profile.clone(),
                proxy_event_tx,
                runs_root,
                run_id,
            );

            if let Some(target) = build_target {
                executor.set_build_target(target);
            }

            // Load task
            if task.exists() && task.is_dir() {
                executor.load_task_from_path(&task).await;
            } else {
                let text = task.to_string_lossy().into_owned();
                executor.load_task_from_text(&text).await;
            }

            // Start executor worker
            let (effect_tx, mut effect_rx) = tokio::sync::mpsc::channel(32);
            tokio::spawn(async move {
                while let Some(effect) = effect_rx.recv().await {
                    executor.handle(effect).await;
                }
            });

            // Main event loop
            loop {
                tokio::select! {
                    Some(event) = proxy_event_rx.recv() => {
                        // Print event
                        match &event {
                            agent_core::event::RunEvent::TaskLoaded(t) => {
                                eprintln!("✓ Task loaded: {}", t.name);
                            }
                            agent_core::event::RunEvent::PreflightPassed(b) => {
                                eprintln!("✓ Preflight passed (estimated {}, limit {})", b.estimated_prompt, b.prompt_limit);
                            }
                            agent_core::event::RunEvent::PreflightFailed(reason) => {
                                eprintln!("✗ Preflight failed: {}", reason);
                                break;
                            }
                            agent_core::event::RunEvent::TaskLoadFailed(reason) => {
                                eprintln!("✗ Task load failed: {}", reason);
                                break;
                            }
                            agent_core::event::RunEvent::ModelCompleted(_) => {
                                eprintln!("✓ Model generated response");
                            }
                            agent_core::event::RunEvent::ValidationCompleted(result) => {
                                let status = if result.passed { "passed" } else { "failed" };
                                eprintln!("{} L{} {} {} ({} errors, {} warnings)", 
                                    if result.passed { "✓" } else { "✗" },
                                    result.level, result.level_name, status, result.error_count, result.warning_count);
                                if !result.passed {
                                    for err in result.actionable_errors.iter().take(5) {
                                        eprintln!("  ▸ {}", err);
                                    }
                                }
                            }
                            agent_core::event::RunEvent::RepairScheduled { attempt } => {
                                eprintln!("↻ Scheduling repair attempt {}", attempt);
                            }
                            agent_core::event::RunEvent::FinalArtifactWritten(path) => {
                                eprintln!("✓ Task complete. Final artifact: {}", path.display());
                                break;
                            }
                            agent_core::event::RunEvent::Failed(err) | agent_core::event::RunEvent::ModelFailed(err) => {
                                eprintln!("✗ Run failed: {}", err);
                                break;
                            }
                            agent_core::event::RunEvent::ConsentRequired { action } => {
                                eprintln!("⚠ Awaiting consent: {}", action);
                            }
                            agent_core::event::RunEvent::ToolProcessFinished { id, success, .. } => {
                                eprintln!("{} Tool execution: process {}", if *success { "✓" } else { "✗" }, id);
                            }
                            _ => {}
                        }
                        
                        // Forward to controller
                        let _ = controller_event_tx.send(event).await;
                    }
                    effect = controller.process_next() => {
                        match effect {
                            Some(agent_core::reducer::SideEffect::RequestConsent { action, .. }) => {
                                eprintln!("Consent auto-granted for CLI mode: {}", action);
                                let _ = controller_event_tx.send(agent_core::event::RunEvent::ConsentGranted(
                                    agent_core::event::ExportConsent {
                                        domain: "local".to_string(),
                                        files: vec![],
                                        total_bytes: 0,
                                        purpose: "CLI auto-grant".to_string(),
                                        approved: true,
                                        approved_by: Some("cli".to_string()),
                                    }
                                )).await;
                            }
                            Some(agent_core::reducer::SideEffect::None) => {
                                // Do nothing
                            }
                            Some(eff) => {
                                let _ = effect_tx.send(eff).await;
                            }
                            None => {
                                // Controller task ended or no more effects
                                break;
                            }
                        }
                    }
                }
            }

            eprintln!("✓ Pipeline finished.");
        }
    }
    Ok(())
}
