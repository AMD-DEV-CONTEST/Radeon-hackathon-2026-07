//! FlintCode TUI — Ratatui observation and control interface.

mod app;
mod input;
mod ui;

use anyhow::Result;
use clap::Parser;
use std::path::PathBuf;
use tracing_appender;
use tracing_subscriber::{EnvFilter, fmt, prelude::*};

#[derive(Parser, Debug)]
#[command(
    name = "flintcode-tui",
    about = "Interactive TUI for FlintCode AI coding agent"
)]
pub struct CliArgs {
    /// Path to model profile TOML file (e.g. profiles/qwen-3.6-coder.toml)
    #[arg(short, long)]
    pub profile: Option<PathBuf>,

    /// Path to initial task directory or task.toml to run automatically
    #[arg(short, long)]
    pub task: Option<PathBuf>,
}

#[tokio::main]
async fn main() -> Result<()> {
    let args = CliArgs::parse();

    // File-based logging (don't pollute the TUI)
    let log_dir = dirs::data_local_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join("flintcode")
        .join("logs");
    std::fs::create_dir_all(&log_dir)?;
    let file_appender = tracing_appender::rolling::daily(&log_dir, "tui.log");
    let (non_blocking, _guard) = tracing_appender::non_blocking(file_appender);

    tracing_subscriber::registry()
        .with(fmt::layer().with_writer(non_blocking).with_ansi(false))
        .with(EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info")))
        .init();

    tracing::info!(
        "FlintCode TUI starting with profile override: {:?}",
        args.profile
    );

    let mut app = app::App::new(args.profile.as_deref(), args.task.as_deref())?;

    if let Some(task_path) = args.task {
        if task_path.exists() {
            tracing::info!("Auto-starting task: {:?}", task_path);
            app.start_task(&task_path).await?;
        }
    }

    ui::run(&mut app).await?;

    tracing::info!("FlintCode TUI shutdown");
    Ok(())
}
