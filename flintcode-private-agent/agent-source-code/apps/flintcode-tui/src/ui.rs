//! Ratatui rendering — pipeline observation and control UI.

use anyhow::Result;
use crossterm::{
    event::{Event, KeyCode, KeyModifiers},
    execute,
    terminal::{EnterAlternateScreen, LeaveAlternateScreen, disable_raw_mode, enable_raw_mode},
};
use futures::StreamExt;
use ratatui::{
    Frame, Terminal,
    backend::CrosstermBackend,
    layout::{Constraint, Direction, Layout, Rect},
    style::{Color, Modifier, Style},
    text::{Line, Span},
    widgets::{Block, Borders, List, ListItem, Paragraph, Wrap},
};
use std::io;
use std::path::Path;

use crate::app::{App, StageStatus, View};

/// Run the TUI event loop.
pub async fn run(app: &mut App) -> Result<()> {
    enable_raw_mode()?;
    let mut stdout = io::stdout();
    execute!(stdout, EnterAlternateScreen)?;
    let backend = CrosstermBackend::new(stdout);
    let mut terminal = Terminal::new(backend)?;

    let result = event_loop(&mut terminal, app).await;

    disable_raw_mode()?;
    execute!(terminal.backend_mut(), LeaveAlternateScreen)?;
    terminal.show_cursor()?;

    result
}

async fn event_loop(
    terminal: &mut Terminal<CrosstermBackend<io::Stdout>>,
    app: &mut App,
) -> Result<()> {
    let mut reader = crossterm::event::EventStream::new();
    loop {
        terminal.draw(|f| draw(f, app))?;

        tokio::select! {
            // 1. Terminal events
            maybe_event = reader.next() => {
                if let Some(Ok(Event::Key(key))) = maybe_event {
                    match key.code {
                        KeyCode::Char('q') => app.should_quit = true,
                        KeyCode::Char('c') if key.modifiers.contains(KeyModifiers::CONTROL) => {
                            app.should_quit = true;
                        }
                        KeyCode::Char('g') => app.view = View::Pipeline,
                        KeyCode::Char('v') => app.view = View::Diagnostics,
                        KeyCode::Char('d') => app.view = View::Candidate,
                        KeyCode::Char('t') => app.view = View::Task,
                        KeyCode::Char('p') => {
                            let _ = app.next_profile();
                        }
                        KeyCode::Tab => {
                            // Cycle subfiles in candidate view
                            if !app.candidate_files.is_empty() {
                                app.active_candidate_idx = (app.active_candidate_idx + 1) % app.candidate_files.len();
                            }
                        }
                        KeyCode::Char('?') => {
                            app.view = if app.view == View::Help { View::Pipeline } else { View::Help };
                        }
                        KeyCode::Char('j') | KeyCode::Down => {
                            app.scroll_offset = app.scroll_offset.saturating_add(1);
                        }
                        KeyCode::Char('k') | KeyCode::Up => {
                            app.scroll_offset = app.scroll_offset.saturating_sub(1);
                        }
                        // Hotkey 'r' to load bookstore 3-obj task
                        KeyCode::Char('r') => {
                            let _ = app.start_task(Path::new("benchmarks/tasks/bookstore-3obj")).await;
                        }
                        _ => {}
                    }
                }
            }

            // 2. Events from Executor (proxy)
            Some(event) = async {
                if let Some(rx) = app.proxy_event_rx.as_mut() {
                    rx.recv().await
                } else {
                    std::future::pending().await
                }
            } => {
                // Update UI from event
                match &event {
                    agent_core::event::RunEvent::ModelCompleted(res) => {
                        app.token_prompt += res.usage.prompt_tokens;
                        app.token_completion += res.usage.completion_tokens;
                        if res.elapsed_secs > 0.0 {
                            app.generation_tps = res.usage.completion_tokens as f64 / res.elapsed_secs;
                            app.prompt_tps = res.usage.prompt_tokens as f64 / (res.elapsed_secs * 0.2).max(0.1);
                        }
                        app.add_log(format!(
                            "Model response received: {} prompt tokens, {} completion tokens ({:.1} tps)",
                            res.usage.prompt_tokens, res.usage.completion_tokens, app.generation_tps
                        ));
                    }
                    agent_core::event::RunEvent::ValidationCompleted(res) => {
                        app.diagnostics = res.diagnostic.clone();
                        app.add_log(format!(
                            "Validation completed: level={}, passed={:?}, errors={}",
                            res.level_name, res.passed, res.actionable_errors.len()
                        ));
                    }
                    agent_core::event::RunEvent::TaskLoaded(task) => {
                        app.task_files = vec![task.name.clone(), format!("task_file={}", task.task_file.display())];
                        app.add_log(format!("Task loaded: {}", task.name));
                    }
                    _ => {}
                }

                if let Some(tx) = app.controller_event_tx.as_mut() {
                    let _ = tx.send(event).await;
                }
            }

            // 3. Process controller (reduces events and emits side effects)
            Some(effect) = async {
                if let Some(controller) = app.controller.as_mut() {
                    controller.process_next().await
                } else {
                    std::future::pending().await
                }
            } => {
                let candidate_files = if let Some(exec) = app.executor.as_mut() {
                    exec.handle(effect).await;
                    exec.candidate_files().to_vec()
                } else {
                    Vec::new()
                };
                if !candidate_files.is_empty() {
                    app.set_candidate_files(candidate_files);
                }
            }
        }

        if app.should_quit {
            return Ok(());
        }
    }
}

fn draw(f: &mut Frame, app: &App) {
    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(2), // Header
            Constraint::Length(1), // Run info
            Constraint::Min(10),   // Main content
            Constraint::Length(2), // Token bar
            Constraint::Length(1), // Keybindings
        ])
        .split(f.area());

    draw_header(f, app, chunks[0]);
    draw_run_info(f, app, chunks[1]);
    draw_main(f, app, chunks[2]);
    draw_token_bar(f, app, chunks[3]);
    draw_keybindings(f, chunks[4]);
}

fn draw_header(f: &mut Frame, app: &App, area: Rect) {
    let in_flight = if app.run_state().state.is_active() {
        "1"
    } else {
        "0"
    };
    let header = Line::from(vec![
        Span::styled(
            " FlintCode TUI ",
            Style::default()
                .fg(Color::Cyan)
                .add_modifier(Modifier::BOLD),
        ),
        Span::raw(" ─ Profile: "),
        Span::styled(
            &app.profile.model.name,
            Style::default()
                .fg(Color::Green)
                .add_modifier(Modifier::BOLD),
        ),
        Span::raw(" ─ Limit: "),
        Span::styled(
            format!("{}K", app.profile.context.model_context_tokens / 1000),
            Style::default().fg(Color::Yellow),
        ),
        Span::raw(" ─ Concurrency: "),
        Span::styled(
            format!("{in_flight}/{}", app.profile.concurrency.max_in_flight),
            Style::default().fg(if in_flight == "0" {
                Color::Gray
            } else {
                Color::Cyan
            }),
        ),
        Span::raw(" ─ [p] Switch Profile"),
    ]);
    let block = Block::default().borders(Borders::TOP | Borders::LEFT | Borders::RIGHT);
    let paragraph = Paragraph::new(header).block(block);
    f.render_widget(paragraph, area);
}

fn draw_run_info(f: &mut Frame, app: &App, area: Rect) {
    let state_color = match &app.run_state().state {
        agent_core::state::PipelineState::Completed => Color::Green,
        agent_core::state::PipelineState::Failed { .. } => Color::Red,
        agent_core::state::PipelineState::Cancelled => Color::Yellow,
        _ if app.run_state().state.is_active() => Color::Cyan,
        _ => Color::Gray,
    };

    let run_name = app
        .run_state()
        .task_name
        .as_deref()
        .unwrap_or(&app.run_state().run_id);
    let elapsed = app
        .run_start_time
        .map(|t| format!("{:.1}s", t.elapsed().as_secs_f64()))
        .unwrap_or_else(|| "0.0s".to_string());

    let line = Line::from(vec![
        Span::raw(" Run: "),
        Span::styled(
            run_name,
            Style::default()
                .fg(Color::White)
                .add_modifier(Modifier::BOLD),
        ),
        Span::raw("  │  State: "),
        Span::styled(
            app.run_state().state.label(),
            Style::default()
                .fg(state_color)
                .add_modifier(Modifier::BOLD),
        ),
        Span::raw("  │  Elapsed: "),
        Span::styled(elapsed, Style::default().fg(Color::Yellow)),
    ]);
    let block = Block::default().borders(Borders::LEFT | Borders::RIGHT);
    f.render_widget(Paragraph::new(line).block(block), area);
}

fn draw_main(f: &mut Frame, app: &App, area: Rect) {
    let cols = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([Constraint::Percentage(35), Constraint::Percentage(65)])
        .split(area);

    let left_rows = Layout::default()
        .direction(Direction::Vertical)
        .constraints([Constraint::Percentage(60), Constraint::Percentage(40)])
        .split(cols[0]);

    draw_pipeline(f, app, left_rows[0]);
    draw_task_files(f, app, left_rows[1]);
    draw_right_panel(f, app, cols[1]);
}

fn draw_pipeline(f: &mut Frame, app: &App, area: Rect) {
    let stages = app.stage_statuses();
    let items: Vec<ListItem> = stages
        .iter()
        .map(|(name, status)| {
            let (icon, color) = match status {
                StageStatus::Done => ("✓", Color::Green),
                StageStatus::Active => ("▶", Color::Cyan),
                StageStatus::Pending => ("○", Color::DarkGray),
                StageStatus::Failed => ("✗", Color::Red),
            };

            ListItem::new(Line::from(vec![
                Span::styled(format!(" {icon} "), Style::default().fg(color)),
                Span::styled(*name, Style::default().fg(color)),
            ]))
        })
        .collect();

    let block = Block::default()
        .title(" Pipeline Stages ")
        .borders(Borders::ALL)
        .border_style(Style::default().fg(Color::DarkGray));
    let list = List::new(items).block(block);
    f.render_widget(list, area);
}

fn draw_task_files(f: &mut Frame, app: &App, area: Rect) {
    let items: Vec<ListItem> = app
        .task_files
        .iter()
        .map(|f_name| {
            ListItem::new(Line::from(vec![
                Span::styled(" ✓ ", Style::default().fg(Color::Green)),
                Span::raw(f_name),
            ]))
        })
        .collect();

    let block = Block::default()
        .title(" Loaded Task ")
        .borders(Borders::ALL)
        .border_style(Style::default().fg(Color::DarkGray));
    let list = List::new(items).block(block);
    f.render_widget(list, area);
}

fn draw_right_panel(f: &mut Frame, app: &App, area: Rect) {
    match app.view {
        View::Candidate => draw_candidate_multi_file(f, app, area),
        View::Diagnostics => draw_diagnostics_and_logs(f, app, area),
        View::Help => {
            let block = Block::default().title(" Help ").borders(Borders::ALL);
            let paragraph = Paragraph::new(HELP_TEXT).block(block);
            f.render_widget(paragraph, area);
        }
        _ => draw_diagnostics_and_logs(f, app, area),
    }
}

/// Phase 2: Multi-file Candidate Viewer
fn draw_candidate_multi_file(f: &mut Frame, app: &App, area: Rect) {
    if app.candidate_files.is_empty() {
        let block = Block::default()
            .title(" Candidate / Multi-File Preview (Tab to switch) ")
            .borders(Borders::ALL);
        let paragraph = Paragraph::new(
            "No candidate generated yet. Press 'r' to start bookstore benchmark task.",
        );
        f.render_widget(paragraph.block(block), area);
        return;
    }

    let chunks = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([Constraint::Length(24), Constraint::Min(10)])
        .split(area);

    // Left file list
    let file_items: Vec<ListItem> = app
        .candidate_files
        .iter()
        .enumerate()
        .map(|(idx, (filename, _))| {
            let is_selected = idx == app.active_candidate_idx;
            let style = if is_selected {
                Style::default()
                    .fg(Color::Yellow)
                    .add_modifier(Modifier::BOLD)
            } else {
                Style::default().fg(Color::White)
            };
            let prefix = if is_selected { "▶ " } else { "  " };
            ListItem::new(Line::from(vec![Span::styled(
                format!("{prefix}{filename}"),
                style,
            )]))
        })
        .collect();

    let list_block = Block::default()
        .title(" Subfiles (Tab) ")
        .borders(Borders::ALL);
    let list = List::new(file_items).block(list_block);
    f.render_widget(list, chunks[0]);

    // Right file content
    let (active_name, active_content) = &app.candidate_files[app.active_candidate_idx];
    let content_block = Block::default()
        .title(format!(" Content: {active_name} "))
        .borders(Borders::ALL);

    let paragraph = Paragraph::new(active_content.as_str())
        .block(content_block)
        .wrap(Wrap { trim: false })
        .scroll((app.scroll_offset, 0));

    f.render_widget(paragraph, chunks[1]);
}

/// Phase 3: Diagnostics & Live ReAct Log Stream
fn draw_diagnostics_and_logs(f: &mut Frame, app: &App, area: Rect) {
    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([Constraint::Percentage(40), Constraint::Percentage(60)])
        .split(area);

    // Diagnostics report top box
    let diag_block = Block::default()
        .title(" TeaQL Domain Diagnostics ")
        .borders(Borders::ALL);
    let diag_text = if app.diagnostics.is_empty() {
        "No domain validation report yet."
    } else {
        &app.diagnostics
    };
    let diag_paragraph = Paragraph::new(diag_text)
        .block(diag_block)
        .wrap(Wrap { trim: false });
    f.render_widget(diag_paragraph, chunks[0]);

    // Live ReAct log stream bottom box
    let log_items: Vec<ListItem> = app
        .react_logs
        .iter()
        .map(|log| {
            ListItem::new(Line::from(vec![Span::styled(
                log,
                Style::default().fg(Color::Green),
            )]))
        })
        .collect();

    let logs_block = Block::default()
        .title(" Agentic ReAct Live Log Stream ")
        .borders(Borders::ALL);
    let logs_list = List::new(log_items).block(logs_block);
    f.render_widget(logs_list, chunks[1]);
}

/// Phase 4: Token Bar & Telemetry Metrics
fn draw_token_bar(f: &mut Frame, app: &App, area: Rect) {
    let prompt_limit = app.profile.context.max_prompt_tokens;
    let completion_limit = app.profile.context.max_completion_tokens;
    let safety = app.profile.context.safety_tokens;

    let line = Line::from(vec![
        Span::raw(" Prompt Tokens: "),
        Span::styled(
            format!("{:>6}", app.token_prompt),
            Style::default().fg(Color::Cyan),
        ),
        Span::styled(
            format!(" / {prompt_limit:>5}"),
            Style::default().fg(Color::DarkGray),
        ),
        Span::raw(" │ Completion: "),
        Span::styled(
            format!("{:>5}", app.token_completion),
            Style::default().fg(Color::Green),
        ),
        Span::styled(
            format!(" / {completion_limit:>4}"),
            Style::default().fg(Color::DarkGray),
        ),
        Span::raw(" │ Output Speed: "),
        Span::styled(
            format!("{:.1} t/s", app.generation_tps),
            Style::default()
                .fg(Color::Yellow)
                .add_modifier(Modifier::BOLD),
        ),
        Span::raw(" │ Reserve: "),
        Span::styled(format!("{safety:>5}"), Style::default().fg(Color::DarkGray)),
    ]);

    let block = Block::default()
        .borders(Borders::ALL)
        .title(" Real-time LLM Telemetry ")
        .border_style(Style::default().fg(Color::DarkGray));
    f.render_widget(Paragraph::new(line).block(block), area);
}

fn draw_keybindings(f: &mut Frame, area: Rect) {
    let line = Line::from(vec![
        Span::styled(" [g]", Style::default().fg(Color::Cyan)),
        Span::raw(" Pipeline  "),
        Span::styled("[v]", Style::default().fg(Color::Cyan)),
        Span::raw(" Logs  "),
        Span::styled("[d]", Style::default().fg(Color::Cyan)),
        Span::raw(" Subfiles  "),
        Span::styled("[p]", Style::default().fg(Color::Yellow)),
        Span::raw(" Switch Profile  "),
        Span::styled("[Tab]", Style::default().fg(Color::Cyan)),
        Span::raw(" Next File  "),
        Span::styled("[r]", Style::default().fg(Color::Green)),
        Span::raw(" Run Task  "),
        Span::styled("[?]", Style::default().fg(Color::Cyan)),
        Span::raw(" Help  "),
        Span::styled("[q]", Style::default().fg(Color::Red)),
        Span::raw(" Quit"),
    ]);
    f.render_widget(Paragraph::new(line), area);
}

const HELP_TEXT: &str = r#"FlintCode TUI — Keyboard Shortcuts

  g     Pipeline view
  v     Validation & Live ReAct Logs stream
  d     Multi-file Candidate viewer (Tab to switch files)
  p     Switch Model Profile (Qwen3.6-Coder / MiMo / Nemotron)
  r     Start benchmark evaluation task
  Tab   Cycle through generated subfiles (main.xml, operations.xml, etc.)
  j/k   Scroll content down/up
  ?     Toggle help screen
  q     Quit TUI"#;
