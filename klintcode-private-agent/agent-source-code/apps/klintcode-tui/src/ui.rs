//! Ratatui rendering — pipeline observation and control UI.

use anyhow::Result;
use crossterm::{
    event::{Event, KeyCode, KeyModifiers, EnableBracketedPaste, DisableBracketedPaste, EnableMouseCapture, DisableMouseCapture},
    execute,
    terminal::{EnterAlternateScreen, LeaveAlternateScreen, disable_raw_mode, enable_raw_mode},
};
use ratatui::{
    Frame, Terminal,
    backend::CrosstermBackend,
    layout::{Alignment, Constraint, Direction, Layout, Rect},
    style::{Color, Modifier, Style},
    text::{Line, Span, Text},
    widgets::{Block, Borders, Clear, List, ListItem, Padding, Paragraph, Wrap},
};
use std::io;
use std::time::Duration;

use agent_core::event::ExportConsent;
use agent_core::state::PipelineState;
use agent_core::shared::{PlanStepStatus, ToolProcessStatus};

use crate::app::{App, InputMode, ServiceHealth, TimelineRole, View};

const KLINT_TEXT_MARK: [&str; 3] = [
    " █▄▀ █   █ █▄ █ ▀█▀",
    " █▀▄ █   █ █ ▀█  █ ",
    " ▀ ▀ ▀▀▀ ▀ ▀  ▀  ▀ ",
];
const KLINT_SLOGAN: &str = "Built for coding where networks can't reach.";

/// Run the TUI event loop.
pub async fn run(app: &mut App) -> Result<()> {
    enable_raw_mode()?;
    let mut stdout = io::stdout();
    execute!(stdout, EnterAlternateScreen, EnableBracketedPaste)?;
    let backend = CrosstermBackend::new(stdout);
    let mut terminal = Terminal::new(backend)?;

    let result = event_loop(&mut terminal, app).await;

    disable_raw_mode()?;
    execute!(terminal.backend_mut(), LeaveAlternateScreen, DisableBracketedPaste)?;
    terminal.show_cursor()?;

    result
}

use futures::StreamExt;

async fn event_loop(
    terminal: &mut Terminal<CrosstermBackend<io::Stdout>>,
    app: &mut App,
) -> Result<()> {
    let (input_tx, mut input_rx) = tokio::sync::mpsc::channel(32);
    tokio::spawn(async move {
        let mut reader = crossterm::event::EventStream::new();
        while let Some(Ok(event)) = reader.next().await {
            if input_tx.send(event).await.is_err() {
                break;
            }
        }
    });

    let mut cursor_blink = tokio::time::interval(Duration::from_millis(500));
    cursor_blink.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
    let mut plan_pulse = tokio::time::interval(Duration::from_millis(850));
    plan_pulse.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
    let health_profile = app.profile.clone();
    let health_probe = App::probe_model_service(health_profile);
    tokio::pin!(health_probe);
    let mut health_probe_complete = false;
    loop {
        terminal.draw(|f| draw(f, app))?;

        tokio::select! {
            // 1. Terminal events
            maybe_event = input_rx.recv() => {
                if let Some(event) = maybe_event {
                  match event {
                    Event::Paste(text) => {
                        if app.input_mode != InputMode::Editing {
                            app.input_mode = InputMode::Editing;
                            app.input_cursor_visible = true;
                            app.input_notice = None;
                        }
                        for ch in text.chars() {
                            app.insert_input_char(ch);
                        }
                    }
                    Event::Key(key) => {
                    if key.code == KeyCode::Char('c')
                        && key.modifiers.contains(KeyModifiers::CONTROL)
                    {
                        app.should_quit = true;
                    } else if matches!(
                        &app.run_state().state,
                        PipelineState::AwaitingConsent { .. }
                    ) && matches!(key.code, KeyCode::Char('y') | KeyCode::Char('n'))
                    {
                        if let Some(tx) = app.controller_event_tx.as_ref() {
                            match key.code {
                                KeyCode::Char('y') => {
                                    let consent = ExportConsent {
                                        domain: "local".to_string(),
                                        files: Vec::new(),
                                        total_bytes: 0,
                                        purpose: "TUI approval".to_string(),
                                        approved: true,
                                        approved_by: Some("tui-user".to_string()),
                                    };
                                    let _ = tx
                                        .send(agent_core::event::RunEvent::ConsentGranted(consent))
                                        .await;
                                }
                                KeyCode::Char('n') => {
                                    let _ = tx
                                        .send(agent_core::event::RunEvent::ConsentDenied(
                                            "User denied the requested action".to_string(),
                                        ))
                                        .await;
                                }
                                _ => {}
                            }
                        }
                    } else if app.input_mode == InputMode::Editing {
                        match key.code {
                            KeyCode::Esc => {
                                app.input_mode = InputMode::Navigation;
                                app.input_cursor_visible = false;
                            }
                            KeyCode::Enter
                                if key.modifiers.intersects(
                                    KeyModifiers::SHIFT | KeyModifiers::ALT,
                                ) =>
                            {
                                app.insert_input_newline();
                            }
                            KeyCode::Enter => {
                                app.submit_input().await?;
                            }
                            KeyCode::Backspace => app.backspace_input(),
                            KeyCode::Delete => app.delete_input(),
                            KeyCode::Left => app.move_input_left(),
                            KeyCode::Right => app.move_input_right(),
                            KeyCode::Home => app.move_input_home(),
                            KeyCode::End => app.move_input_end(),
                            KeyCode::Char(character)
                                if !key.modifiers.contains(KeyModifiers::CONTROL) =>
                            {
                                app.insert_input_char(character);
                            }
                            _ => {}
                        }
                    } else {
                        match key.code {
                            KeyCode::Char('i') => {
                                app.input_mode = InputMode::Editing;
                                app.input_cursor_visible = true;
                                app.input_notice = None;
                            }
                            KeyCode::Char('q') => app.should_quit = true,
                            KeyCode::Char('c') => {
                                if let Some(tx) = app.controller_event_tx.as_ref() {
                                    let _ = tx.send(agent_core::event::RunEvent::CancelRequested).await;
                                }
                            }
                            KeyCode::Char('g') => app.view = View::Main,
                            KeyCode::Char('v') => app.view = View::Stats,
                            KeyCode::Char('d') => app.view = View::Candidate,

                        KeyCode::Char('?') => {
                                app.view = if app.view == View::Help { View::Main } else { View::Help };
                        }
                        KeyCode::Char('j') | KeyCode::Down => {
                            if app.view == View::Main {
                                app.transcript_scroll_back =
                                    app.transcript_scroll_back.saturating_sub(1);
                            } else {
                                app.scroll_offset = app.scroll_offset.saturating_add(1);
                            }
                        }
                        KeyCode::Char('k') | KeyCode::Up => {
                            if app.view == View::Main {
                                app.transcript_scroll_back =
                                    app.transcript_scroll_back.saturating_add(1);
                            } else {
                                app.scroll_offset = app.scroll_offset.saturating_sub(1);
                            }
                        }
                        _ => {}
                        }
                    }
                    }
                    Event::Mouse(mouse) => {
                        match mouse.kind {
                            crossterm::event::MouseEventKind::ScrollUp => {
                                if app.view == View::Main {
                                    app.transcript_scroll_back =
                                        app.transcript_scroll_back.saturating_add(3);
                                } else {
                                    app.scroll_offset = app.scroll_offset.saturating_sub(3);
                                }
                            }
                            crossterm::event::MouseEventKind::ScrollDown => {
                                if app.view == View::Main {
                                    app.transcript_scroll_back =
                                        app.transcript_scroll_back.saturating_sub(3);
                                } else {
                                    app.scroll_offset = app.scroll_offset.saturating_add(3);
                                }
                            }
                            _ => {}
                        }
                    }
                    _ => {}
                  }
                }
            }

            // 2. Events from Executor (proxy)
            proxy_res = async {
                if let Some(rx) = app.proxy_event_rx.as_mut() {
                    rx.recv().await
                } else {
                    std::future::pending().await
                }
            } => {
                match proxy_res {
                    Some(event) => {
                        // Update UI from event
                        match &event {
                            agent_core::event::RunEvent::ValidationCompleted(res) => {
                                app.diagnostics = res.diagnostic.clone();
                            }
                            _ => {}
                        }
                        app.observe_event(&event);

                        if let Some(tx) = app.controller_event_tx.as_mut() {
                            let _ = tx.send(event).await;
                        }
                    }
                    None => {
                        app.proxy_event_rx = None;
                    }
                }
            }

            // 3. Process controller (reduces events and emits side effects)
            ctrl_res = async {
                if let Some(controller) = app.controller.as_mut() {
                    controller.process_next().await
                } else {
                    std::future::pending().await
                }
            } => {
                match ctrl_res {
                    Some(effect) => {
                        // Show dispatched effects in timeline for debugging
                        let effect_label = match &effect {
                            agent_core::reducer::SideEffect::RunPreflight => Some("→ RunPreflight"),
                            agent_core::reducer::SideEffect::Generate { attempt } => Some(if *attempt == 1 { "→ Generate" } else { "→ Repair/Generate" }),
                            agent_core::reducer::SideEffect::RunLocalValidation { .. } => Some("→ LocalValidation"),
                            agent_core::reducer::SideEffect::RunDomainValidation { .. } => Some("→ DomainValidation"),
                            agent_core::reducer::SideEffect::RunBuildValidation { .. } => Some("→ BuildValidation"),
                            agent_core::reducer::SideEffect::Repair { .. } => Some("→ Repair"),
                            agent_core::reducer::SideEffect::WriteFinalArtifact => Some("→ WriteFinalArtifact"),
                            agent_core::reducer::SideEffect::RecordFailure { error } => {
                                app.timeline.push(crate::app::TimelineEntry {
                                    role: crate::app::TimelineRole::Error,
                                    content: format!("→ RecordFailure: {error}"),
                                });
                                None
                            }
                            _ => None,
                        };
                        if let Some(label) = effect_label {
                            app.timeline.push(crate::app::TimelineEntry {
                                role: crate::app::TimelineRole::Activity,
                                content: label.to_string(),
                            });
                        }

                        match effect {
                            agent_core::reducer::SideEffect::RequestConsent { action, .. } => {
                                if let Some(tx) = app.controller_event_tx.as_ref() {
                                    let _ = tx
                                        .send(agent_core::event::RunEvent::ConsentRequired { action })
                                        .await;
                                }
                            }
                            effect => {
                                if let Some(tx) = app.executor_effect_tx.as_ref() {
                                    let _ = tx.send(effect).await;
                                }
                            }
                        }
                    }
                    None => {
                        app.controller = None;
                    }
                }
            }

            // 4. Lightweight conversational responses bypass the task pipeline.
            chat_res = async {
                if let Some(rx) = app.chat_event_rx.as_mut() {
                    rx.recv().await
                } else {
                    std::future::pending().await
                }
            } => {
                match chat_res {
                    Some(event) => app.observe_chat_event(event),
                    None => app.chat_event_rx = None,
                }
            }

            // 5. Blink only while the prompt owns keyboard focus.
            _ = cursor_blink.tick() => {
                if app.input_mode == InputMode::Editing {
                    app.input_cursor_visible = !app.input_cursor_visible;
                } else {
                    app.input_cursor_visible = false;
                }
            }

            // 6. Pulse the current plan step independently from input focus.
            _ = plan_pulse.tick() => {
                app.plan_pulse_phase = (app.plan_pulse_phase + 1) % 4;
            }

            // 7. Probe once after the interface is visible.
            health = &mut health_probe, if !health_probe_complete => {
                app.service_health = health;
                health_probe_complete = true;
            }
        }

        if app.should_quit {
            return Ok(());
        }
    }
}

fn draw(f: &mut Frame, app: &App) {
    let composer_lines = visible_composer_lines(app);
    let composer_height = composer_lines + 2;
    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Min(8),
            Constraint::Length(composer_height),
            Constraint::Length(1),
        ])
        .split(f.area());

    match app.view {
        View::Stats => draw_stats_screen(f, app, chunks[0]),
        View::Candidate => draw_plain_screen(f, "Candidate", &app.candidate, chunks[0]),
        View::Diagnostics => draw_plain_screen(f, "Diagnostics", &app.diagnostics, chunks[0]),
        View::Help => draw_plain_screen(f, "Help", HELP_TEXT, chunks[0]),
        _ => draw_main_surface(f, app, chunks[0]),
    }


    draw_composer(f, app, chunks[1]);
    draw_bottom_hint(f, app, chunks[2]);
}

fn draw_main_surface(f: &mut Frame, app: &App, area: Rect) {
    if app.show_right_panel {
        let columns = Layout::default()
            .direction(Direction::Horizontal)
            .constraints([Constraint::Percentage(75), Constraint::Percentage(25)])
            .split(area);
        draw_transcript(f, app, columns[0]);
        
        let running_count = app
            .run_state()
            .tool_processes
            .iter()
            .filter(|p| p.status == ToolProcessStatus::Running)
            .count();
        let tools_height = if running_count > 0 { (running_count.min(6) + 2) as u16 } else { 0 };

        if app.task_surface_active {
            let status_rows = Layout::default()
                .direction(Direction::Vertical)
                .constraints([
                    Constraint::Length(5),
                    Constraint::Length(3),
                    Constraint::Length(3),
                    Constraint::Length(tools_height),
                    Constraint::Length(status_panel_height(app) + 1),
                    Constraint::Min(0),
                ])
                .split(columns[1]);
            draw_system_status(f, app, status_rows[0]);
            draw_context_metrics(f, app, status_rows[1]);
            draw_context_size(f, app, status_rows[2]);
            draw_tool_commands(f, app, status_rows[3]);
            draw_compact_status(f, app, status_rows[4]);
        } else {
            let status_rows = Layout::default()
                .direction(Direction::Vertical)
                .constraints([
                    Constraint::Length(5),
                    Constraint::Length(3),
                    Constraint::Length(3),
                    Constraint::Length(tools_height),
                    Constraint::Min(0),
                ])
                .split(columns[1]);
            draw_system_status(f, app, status_rows[0]);
            draw_context_metrics(f, app, status_rows[1]);
            draw_context_size(f, app, status_rows[2]);
            draw_tool_commands(f, app, status_rows[3]);
        }
    } else {
        draw_transcript(f, app, area);
    }
}

fn draw_system_status(f: &mut Frame, app: &App, area: Rect) {
    let cwd = std::env::current_dir()
        .map(|path| path.display().to_string())
        .unwrap_or_else(|_| ".".to_string());

    let (health_icon, health_label, health_color) = match &app.service_health {
        ServiceHealth::Checking => ("●", "checking".to_string(), Color::Yellow),
        ServiceHealth::Healthy => ("✓", "healthy".to_string(), Color::Green),
        ServiceHealth::Unavailable(detail) => ("✗", format!("unavailable: {detail}"), Color::Red),
    };

    let text = vec![
        Line::from(vec![
            Span::styled(" dir:      ", Style::default().fg(Color::DarkGray)),
            Span::styled(cwd, Style::default().fg(Color::DarkGray)),
        ]),
        Line::from(vec![
            Span::styled(" endpoint: ", Style::default().fg(Color::DarkGray)),
            Span::styled(app.profile.resolve_endpoint(), Style::default().fg(Color::DarkGray)),
        ]),
        Line::from(vec![
            Span::styled(" service:  ", Style::default().fg(Color::DarkGray)),
            Span::styled(format!("{health_icon} {health_label}"), Style::default().fg(health_color)),
        ]),
    ];
    let block = Block::default()
        .title(Span::styled(" System ", Style::default().fg(Color::DarkGray)))
        .title_alignment(Alignment::Center)
        .borders(Borders::TOP)
        .border_style(Style::default().fg(Color::DarkGray))
        .padding(ratatui::widgets::Padding::horizontal(1));
    f.render_widget(Paragraph::new(text).block(block).alignment(Alignment::Left), area);
}

fn draw_context_metrics(f: &mut Frame, app: &App, area: Rect) {
    let input = app.run_state().token_totals.input_tokens;
    let output = app.run_state().token_totals.output_tokens;
    let total = input + output;
    
    let format_k = |v: u64| {
        if v >= 1000 {
            format!("{:.1}K", v as f64 / 1000.0)
        } else {
            v.to_string()
        }
    };
    
    let reqs = app.run_state().token_totals.model_calls;
    
    let text = vec![
        Line::from(vec![
            Span::styled(" ↑", Style::default().fg(Color::Green)),
            Span::styled(format_k(input), Style::default().fg(Color::Green)),
            Span::styled(" + ", Style::default().fg(Color::DarkGray)),
            Span::styled("↓", Style::default().fg(Color::Yellow)),
            Span::styled(format_k(output), Style::default().fg(Color::Yellow)),
            Span::styled(" = ", Style::default().fg(Color::DarkGray)),
            Span::styled(format_k(total), Style::default().fg(Color::Cyan).add_modifier(Modifier::BOLD)),
            Span::styled(" (", Style::default().fg(Color::DarkGray)),
            Span::styled(format!("{} reqs", reqs), Style::default().fg(Color::White)),
            Span::styled(")", Style::default().fg(Color::DarkGray)),
        ]),
    ];
    let block = Block::default()
        .title(Span::styled(" Tokens ", Style::default().fg(Color::DarkGray)))
        .title_alignment(Alignment::Center)
        .borders(Borders::TOP)
        .border_style(Style::default().fg(Color::DarkGray))
        .padding(ratatui::widgets::Padding::horizontal(1));
    f.render_widget(Paragraph::new(text).block(block), area);
}

fn draw_context_size(f: &mut Frame, app: &App, area: Rect) {
    let current = app.last_context_tokens;
    let peak = app.max_context_tokens;
    
    let format_k = |v: u64| {
        if v >= 1000 {
            format!("{:.1}K", v as f64 / 1000.0)
        } else {
            v.to_string()
        }
    };
    
    let text = vec![
        Line::from(vec![
            Span::styled(" now: ", Style::default().fg(Color::DarkGray)),
            Span::styled(format_k(current), Style::default().fg(Color::Cyan)),
            Span::styled("  peak: ", Style::default().fg(Color::DarkGray)),
            Span::styled(format_k(peak), Style::default().fg(Color::Magenta).add_modifier(Modifier::BOLD)),
        ]),
    ];
    let block = Block::default()
        .title(Span::styled(" Context ", Style::default().fg(Color::DarkGray)))
        .title_alignment(Alignment::Center)
        .borders(Borders::TOP)
        .border_style(Style::default().fg(Color::DarkGray))
        .padding(ratatui::widgets::Padding::horizontal(1));
    f.render_widget(Paragraph::new(text).block(block), area);
}

fn draw_transcript(f: &mut Frame, app: &App, area: Rect) {
    let mut lines = if app.timeline.is_empty() {
        let mut header = KLINT_TEXT_MARK
            .iter()
            .map(|line| {
                Line::from(Span::styled(
                    *line,
                    Style::default()
                        .fg(Color::Cyan)
                        .add_modifier(Modifier::BOLD),
                ))
            })
            .collect::<Vec<_>>();
        header.extend([
            Line::from(vec![
                Span::styled(" klint", Style::default().fg(Color::Cyan)),
                Span::styled("  coding agent", Style::default().fg(Color::DarkGray)),
            ]),
            Line::from(Span::styled(
                format!(" {KLINT_SLOGAN}"),
                Style::default()
                    .fg(Color::Yellow)
                    .add_modifier(Modifier::ITALIC),
            )),
            Line::from(Span::styled(
                " Built by TeaQL",
                Style::default().fg(Color::DarkGray),
            )),
            Line::from(""),
        ]);
        header
    } else {
        vec![]
    };

    if app.timeline.is_empty() {
        lines.push(Line::from(Span::styled(
            "  Describe a task and I will inspect the project and begin.",
            Style::default().fg(Color::DarkGray),
        )));
        lines.push(Line::from(Span::styled(
            "  Use /stats to inspect the plan, validation, and tokens.",
            Style::default().fg(Color::DarkGray),
        )));
    } else {
        for (i, entry) in app.timeline.iter().enumerate() {
            if i > 0 {
                match entry.role {
                    TimelineRole::User | TimelineRole::Agent => {
                        lines.push(Line::from(""));
                    }
                    _ => {}
                }
            }
            let (marker, color) = match entry.role {
                TimelineRole::User => ("❯", Color::White),
                TimelineRole::Agent => ("●", Color::Cyan),
                TimelineRole::Activity => ("⎿", Color::DarkGray),
                TimelineRole::Success => ("✓", Color::Green),
                TimelineRole::Error => ("✗", Color::Red),
            };
            let content_lines: Vec<&str> = entry.content.lines().collect();
            let mut display_lines = content_lines.clone();
            let mut truncated = false;
            
            match entry.role {
                TimelineRole::Activity | TimelineRole::Success | TimelineRole::Error => {
                    if display_lines.len() > 3 {
                        display_lines.truncate(3);
                        truncated = true;
                    }
                }
                _ => {}
            }

            for (index, content_line) in display_lines.iter().enumerate() {
                lines.push(Line::from(vec![
                    Span::styled(
                        if index == 0 {
                            match entry.role {
                                TimelineRole::Activity | TimelineRole::Success | TimelineRole::Error => {
                                    format!("   {marker} ")
                                }
                                _ => format!(" {marker} ")
                            }
                        } else {
                            match entry.role {
                                TimelineRole::Activity | TimelineRole::Success | TimelineRole::Error => {
                                    "     ".to_string()
                                }
                                _ => "   ".to_string()
                            }
                        },
                        Style::default().fg(color).add_modifier(if index == 0 {
                            Modifier::BOLD
                        } else {
                            Modifier::empty()
                        }),
                    ),
                    Span::styled(content_line.to_string(), Style::default().fg(color)),
                ]));
            }
            
            if truncated {
                lines.push(Line::from(vec![
                    Span::styled("     ", Style::default().fg(color)),
                    Span::styled("...", Style::default().fg(color).add_modifier(Modifier::DIM)),
                ]));
            }
        }
    }

    let run = app.run_state();
    if app.chat_in_flight {
        lines.push(Line::from(vec![
            Span::styled(" ● ", Style::default().fg(Color::Cyan)),
            Span::styled("Answering", Style::default().fg(Color::Cyan)),
        ]));
    }
    if run.state.is_active() {
        let (state_icon, label, color) = state_presentation(&run.state);
        let action = run
            .current_plan_step()
            .and_then(|(_, step)| step.detail.as_deref())
            .unwrap_or_else(|| run.state.label());
        lines.push(Line::from(vec![
            Span::styled(format!(" {state_icon} "), Style::default().fg(color)),
            Span::styled(format!("{label} · {action}"), Style::default().fg(color)),
        ]));
        if matches!(run.state, PipelineState::AwaitingConsent { .. }) {
            lines.push(Line::from(vec![
                Span::styled("   [y]", Style::default().fg(Color::Green)),
                Span::raw(" Allow  "),
                Span::styled("[n]", Style::default().fg(Color::Red)),
                Span::raw(" Deny"),
            ]));
        }
    }

    let transcript_area = area;

    let rendered_line_count = wrapped_line_count(&lines, transcript_area.width);
    let paragraph = Paragraph::new(lines).wrap(Wrap { trim: false });
    let max_scroll = rendered_line_count
        .saturating_sub(usize::from(transcript_area.height))
        .min(usize::from(u16::MAX)) as u16;
    let browse_back = app.transcript_scroll_back.min(max_scroll);
    let scroll = max_scroll.saturating_sub(browse_back);
    f.render_widget(paragraph.scroll((scroll, 0)), transcript_area);

    if browse_back > 0 && transcript_area.height > 0 {
        let indicator_width = transcript_area.width.min(30);
        let indicator_area = Rect::new(
            transcript_area.right().saturating_sub(indicator_width),
            transcript_area.bottom().saturating_sub(1),
            indicator_width,
            1,
        );
        f.render_widget(Clear, indicator_area);
        f.render_widget(
            Paragraph::new(Line::from(Span::styled(
                format!("↓ Latest · j · {browse_back} lines above"),
                Style::default()
                    .fg(Color::Cyan)
                    .add_modifier(Modifier::BOLD),
            )))
            .alignment(Alignment::Right),
            indicator_area,
        );
    }
}

fn wrapped_line_count(lines: &[Line<'_>], width: u16) -> usize {
    let width = usize::from(width.max(1));
    lines
        .iter()
        .map(|line| line.width().max(1).div_ceil(width))
        .sum()
}

fn endpoint_line(app: &App) -> Line<'static> {
    Line::from(vec![
        Span::styled(" endpoint · ", Style::default().fg(Color::DarkGray)),
        Span::styled(
            app.profile.resolve_endpoint(),
            Style::default().fg(Color::DarkGray),
        ),
    ])
}

fn service_health_line(health: &ServiceHealth) -> Line<'static> {
    let (icon, label, color) = match health {
        ServiceHealth::Checking => ("●", "checking model service".to_string(), Color::Yellow),
        ServiceHealth::Healthy => ("✓", "model service healthy".to_string(), Color::Green),
        ServiceHealth::Unavailable(detail) => (
            "✗",
            format!("model service unavailable · {detail}"),
            Color::Red,
        ),
    };
    Line::from(vec![
        Span::styled(" service  · ", Style::default().fg(Color::DarkGray)),
        Span::styled(format!("{icon} {label}"), Style::default().fg(color)),
    ])
}

fn draw_compact_status(f: &mut Frame, app: &App, area: Rect) {
    let run = app.run_state();
    let (completed, total) = app.plan_progress();
    let content = run.plan.iter().enumerate().map(|(index, step)| {
        let (step_icon, step_style) = plan_step_style(step.status, app.plan_pulse_phase);
        Line::from(vec![
            Span::styled(format!("{step_icon} "), step_style),
            Span::styled(format!("{}. {}", index + 1, step.title), step_style),
        ])
    });
    f.render_widget(
        Paragraph::new(content.collect::<Vec<_>>())
            .block(
                Block::default()
                    .title(format!(" Plan {completed}/{total} "))
                    .title_alignment(Alignment::Center)
                    .borders(Borders::TOP)
                    .padding(Padding::horizontal(1))
                    .border_style(Style::default().fg(Color::DarkGray)),
            )
            .wrap(Wrap { trim: true }),
        area,
    );
}

fn status_panel_height(app: &App) -> u16 {
    (app.run_state().plan.len() as u16 + 1).clamp(4, 10)
}

fn plan_step_style(status: PlanStepStatus, pulse_phase: u8) -> (&'static str, Style) {
    match status {
        PlanStepStatus::Completed => ("✓", Style::default().fg(Color::Green)),
        PlanStepStatus::InProgress | PlanStepStatus::WaitingUser => {
            let (color, modifier) = match pulse_phase % 4 {
                0 => (Color::DarkGray, Modifier::empty()),
                2 => (Color::LightCyan, Modifier::BOLD),
                _ => (Color::Cyan, Modifier::empty()),
            };
            ("●", Style::default().fg(color).add_modifier(modifier))
        }
        PlanStepStatus::Pending
        | PlanStepStatus::Blocked
        | PlanStepStatus::Failed
        | PlanStepStatus::Skipped
        | PlanStepStatus::Cancelled => ("○", Style::default().fg(Color::DarkGray)),
    }
}

fn draw_stats_screen(f: &mut Frame, app: &App, area: Rect) {
    let run = app.run_state();
    let (completed, total) = app.plan_progress();
    let mut lines = Vec::new();

    // Header
    lines.push(Line::from(vec![
        Span::styled(
            " Statistics",
            Style::default().fg(Color::Cyan).add_modifier(Modifier::BOLD),
        ),
        Span::styled("  Esc back", Style::default().fg(Color::DarkGray)),
    ]));
    lines.push(Line::from(""));

    // Plan
    lines.push(Line::from(Span::styled(
        format!(" Plan {completed}/{total}"),
        Style::default().fg(Color::White).add_modifier(Modifier::BOLD),
    )));
    for (index, step) in run.plan.iter().enumerate() {
        let (icon, style) = plan_step_style(step.status, app.plan_pulse_phase);
        lines.push(Line::from(vec![
            Span::styled(format!("   {icon} "), style),
            Span::styled(format!("{}. {}", index + 1, step.title), style),
        ]));
    }
    lines.push(Line::from(""));

    // Validation history
    lines.push(Line::from(Span::styled(
        " Validation",
        Style::default().fg(Color::White).add_modifier(Modifier::BOLD),
    )));
    if run.validation_history.is_empty() {
        lines.push(Line::from(Span::styled(
            "   ○ waiting",
            Style::default().fg(Color::DarkGray),
        )));
    } else {
        for (index, result) in run.validation_history.iter().enumerate() {
            let (icon, color) = if result.passed {
                ("✓", Color::Green)
            } else {
                ("✗", Color::Red)
            };
            lines.push(Line::from(vec![
                Span::styled(format!("   {icon} "), Style::default().fg(color)),
                Span::styled(
                    format!(
                        "L{} {} · check {} · {:.1}s · {} err · {} warn",
                        result.level, result.level_name, index + 1,
                        result.elapsed_secs, result.error_count, result.warning_count
                    ),
                    Style::default().fg(Color::DarkGray),
                ),
            ]));
        }
    }
    lines.push(Line::from(""));

    // Tokens
    let totals = &run.token_totals;
    lines.push(Line::from(Span::styled(
        " Tokens",
        Style::default().fg(Color::White).add_modifier(Modifier::BOLD),
    )));
    lines.push(Line::from(vec![
        Span::styled("   ↑", Style::default().fg(Color::Green)),
        Span::styled(
            format_tokens(totals.input_tokens),
            Style::default().fg(Color::Green),
        ),
        Span::styled(" + ", Style::default().fg(Color::DarkGray)),
        Span::styled("↓", Style::default().fg(Color::Yellow)),
        Span::styled(
            format_tokens(totals.output_tokens),
            Style::default().fg(Color::Yellow),
        ),
        Span::styled(" = ", Style::default().fg(Color::DarkGray)),
        Span::styled(
            format_tokens(totals.input_tokens + totals.output_tokens),
            Style::default().fg(Color::Cyan).add_modifier(Modifier::BOLD),
        ),
        Span::styled(" (", Style::default().fg(Color::DarkGray)),
        Span::styled(format!("{} reqs", totals.model_calls), Style::default().fg(Color::White)),
        Span::styled(")", Style::default().fg(Color::DarkGray)),
    ]));
    lines.push(Line::from(""));

    // Tool processes
    let processes = &run.tool_processes;
    if !processes.is_empty() {
        lines.push(Line::from(Span::styled(
            " Tools",
            Style::default().fg(Color::White).add_modifier(Modifier::BOLD),
        )));
        for process in processes.iter().rev().take(10) {
            let (icon, color) = match process.status {
                ToolProcessStatus::Running => ("●", Color::Cyan),
                ToolProcessStatus::Succeeded => ("✓", Color::Green),
                ToolProcessStatus::Failed => ("✗", Color::Red),
            };
            lines.push(Line::from(vec![
                Span::styled(format!("   {icon} "), Style::default().fg(color)),
                Span::styled(
                    format!("$ {}", process.command),
                    Style::default().fg(Color::DarkGray),
                ),
            ]));
        }
    }

    f.render_widget(
        Paragraph::new(lines)
            .wrap(Wrap { trim: false })
            .scroll((app.scroll_offset, 0)),
        area,
    );
}

fn draw_stats_dashboard(f: &mut Frame, app: &App, area: Rect) {
    if area.width < 100 {
        let rows = Layout::default()
            .direction(Direction::Vertical)
            .constraints([
                Constraint::Percentage(45),
                Constraint::Percentage(30),
                Constraint::Percentage(25),
            ])
            .split(area);
        draw_plan(f, app, rows[0]);
        if matches!(
            &app.run_state().state,
            PipelineState::AwaitingConsent { .. }
        ) {
            draw_waiting_panel(f, app, rows[1]);
        } else {
            draw_right_panel(f, app, rows[1]);
        }
        draw_tool_history(f, app, rows[2]);
        return;
    }

    let cols = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([
            Constraint::Percentage(64),
            Constraint::Length(3),
            Constraint::Min(24),
        ])
        .split(area);
    let left_rows = if matches!(
        &app.run_state().state,
        PipelineState::AwaitingConsent { .. }
    ) {
        Layout::default()
            .direction(Direction::Vertical)
            .constraints([
                Constraint::Length(8),
                Constraint::Percentage(38),
                Constraint::Percentage(62),
            ])
            .split(cols[0])
    } else {
        Layout::default()
            .direction(Direction::Vertical)
            .constraints([
                Constraint::Length(0),
                Constraint::Percentage(42),
                Constraint::Percentage(58),
            ])
            .split(cols[0])
    };
    let right_rows = Layout::default()
        .direction(Direction::Vertical)
        .constraints([Constraint::Percentage(72), Constraint::Percentage(28)])
        .split(cols[2]);

    if left_rows[0].height > 0 {
        draw_waiting_panel(f, app, left_rows[0]);
    }
    draw_validation_history(f, app, left_rows[1]);
    draw_right_panel(f, app, left_rows[2]);
    draw_plan(f, app, right_rows[0]);
    draw_tool_history(f, app, right_rows[1]);
}

fn draw_plain_screen(f: &mut Frame, title: &str, content: &str, area: Rect) {
    let lines = vec![
        Line::from(vec![
            Span::styled(
                format!(" {title}"),
                Style::default()
                    .fg(Color::Cyan)
                    .add_modifier(Modifier::BOLD),
            ),
            Span::styled(
                " · /main back · /stats",
                Style::default().fg(Color::DarkGray),
            ),
        ]),
        Line::from(""),
        Line::from(content.to_string()),
    ];
    f.render_widget(Paragraph::new(lines).wrap(Wrap { trim: false }), area);
}

fn draw_plan(f: &mut Frame, app: &App, area: Rect) {
    let run = app.run_state();
    let (completed, total) = app.plan_progress();
    let items: Vec<ListItem> = run
        .plan
        .iter()
        .enumerate()
        .map(|(index, step)| {
            let (icon, style) = plan_step_style(step.status, app.plan_pulse_phase);
            let mut lines = vec![Line::from(vec![
                Span::styled(format!(" {icon} "), style),
                Span::styled(format!("{}. {}", index + 1, step.title), style),
            ])];
            if let Some(detail) = &step.detail {
                lines.push(Line::from(vec![
                    Span::raw("     "),
                    Span::styled(detail, style),
                ]));
            }
            ListItem::new(lines)
        })
        .collect();

    let block = Block::default()
        .title(format!(" Plan {completed}/{total} "))
        .borders(Borders::BOTTOM)
        .padding(Padding::horizontal(1))
        .border_style(Style::default().fg(
            if matches!(&run.state, PipelineState::AwaitingConsent { .. }) {
                Color::Yellow
            } else {
                Color::DarkGray
            },
        ));
    let list = List::new(items).block(block);
    f.render_widget(list, area);
}

fn draw_validation_history(f: &mut Frame, app: &App, area: Rect) {
    let run = app.run_state();
    let items: Vec<ListItem> = if run.validation_history.is_empty() {
        vec![ListItem::new(Line::from(vec![
            Span::styled(" ○ ", Style::default().fg(Color::DarkGray)),
            Span::styled(
                "Waiting for validation",
                Style::default().fg(Color::DarkGray),
            ),
        ]))]
    } else {
        run.validation_history
            .iter()
            .enumerate()
            .map(|(index, result)| {
                let (icon, color) = if result.passed {
                    ("✓", Color::Green)
                } else {
                    ("✗", Color::Red)
                };
                ListItem::new(Line::from(vec![
                    Span::styled(format!(" {icon} "), Style::default().fg(color)),
                    Span::styled(
                        format!("L{} {}", result.level, result.level_name),
                        Style::default().fg(color).add_modifier(Modifier::BOLD),
                    ),
                    Span::styled(
                        format!(
                            "  check {} · {:.1}s · {} errors · {} warnings",
                            index + 1,
                            result.elapsed_secs,
                            result.error_count,
                            result.warning_count
                        ),
                        Style::default().fg(Color::DarkGray),
                    ),
                ]))
            })
            .collect()
    };
    let block = Block::default()
        .title(" Validation Timeline ")
        .borders(Borders::BOTTOM)
        .padding(Padding::horizontal(1))
        .border_style(Style::default().fg(Color::DarkGray));
    f.render_widget(List::new(items).block(block), area);
}

fn draw_tool_history(f: &mut Frame, app: &App, area: Rect) {
    let processes = &app.run_state().tool_processes;
    let visible_rows = usize::from(area.height.saturating_sub(1));
    let start = processes.len().saturating_sub(visible_rows);
    let items = if processes.is_empty() {
        vec![ListItem::new(Line::from(Span::styled(
            " ○ No running tools",
            Style::default().fg(Color::DarkGray),
        )))]
    } else {
        processes[start..]
            .iter()
            .map(|process| {
                let (icon, label, color) = match process.status {
                    ToolProcessStatus::Running => ("●", "running", Color::Cyan),
                    ToolProcessStatus::Succeeded => ("✓", "completed", Color::Green),
                    ToolProcessStatus::Failed => ("✗", "failed", Color::Red),
                };
                ListItem::new(Line::from(vec![
                    Span::styled(format!(" {icon} "), Style::default().fg(color)),
                    Span::styled(format!("{label} · "), Style::default().fg(Color::DarkGray)),
                    Span::styled(
                        format!("$ {}", process.command),
                        Style::default().fg(Color::White),
                    ),
                ]))
            })
            .collect()
    };
    f.render_widget(
        List::new(items).block(
            Block::default()
                .title(" Tool History ")
                .borders(Borders::BOTTOM)
                .padding(Padding::horizontal(1))
                .border_style(Style::default().fg(Color::DarkGray)),
        ),
        area,
    );
}

fn draw_waiting_panel(f: &mut Frame, app: &App, area: Rect) {
    let action = match &app.run_state().state {
        PipelineState::AwaitingConsent { action } => action.as_str(),
        _ => "Your input is required to continue",
    };
    let content = vec![
        Line::from(Span::styled(
            "◆ Waiting for your response",
            Style::default()
                .fg(Color::Yellow)
                .add_modifier(Modifier::BOLD),
        )),
        Line::from(""),
        Line::from(action),
        Line::from(""),
        Line::from(vec![
            Span::styled("[y]", Style::default().fg(Color::Green)),
            Span::raw(" Allow  "),
            Span::styled("[n]", Style::default().fg(Color::Red)),
            Span::raw(" Deny"),
        ]),
    ];
    let block = Block::default()
        .title(" USER INPUT REQUIRED ")
        .borders(Borders::BOTTOM)
        .padding(Padding::horizontal(1))
        .border_style(Style::default().fg(Color::Yellow));
    f.render_widget(Paragraph::new(content).block(block), area);
}

fn draw_right_panel(f: &mut Frame, app: &App, area: Rect) {
    let (title, content) = match app.view {
        View::Candidate => (" Candidate / Diff ", app.candidate.as_str()),
        View::Diagnostics => (" Diagnostics ", app.diagnostics.as_str()),
        View::Help => (" Help ", HELP_TEXT),
        _ => (" Diagnostics ", app.diagnostics.as_str()),
    };

    let block = Block::default()
        .title(title)
        .borders(Borders::BOTTOM)
        .padding(Padding::horizontal(1))
        .border_style(Style::default().fg(Color::DarkGray));
    let paragraph = Paragraph::new(content)
        .block(block)
        .wrap(Wrap { trim: false })
        .scroll((app.scroll_offset, 0));
    f.render_widget(paragraph, area);
}

fn draw_token_bar(f: &mut Frame, app: &App, area: Rect) {
    let run = app.run_state();
    let prompt_limit = run
        .context_budget
        .as_ref()
        .map(|budget| budget.prompt_limit)
        .unwrap_or(app.profile.context.max_prompt_tokens);
    let model_in_flight = matches!(
        run.state,
        PipelineState::Generating { .. } | PipelineState::Repairing { .. }
    );
    let context_tokens = if model_in_flight {
        None
    } else {
        run.current_context_tokens()
    };
    let context_ratio = context_tokens.map(|tokens| {
        if prompt_limit == 0 {
            0.0
        } else {
            f64::from(tokens) / f64::from(prompt_limit)
        }
    });
    let context_color = match context_ratio {
        Some(ratio) if ratio >= 0.9 => Color::Red,
        Some(ratio) if ratio >= 0.8 => Color::LightRed,
        Some(ratio) if ratio >= 0.6 => Color::Yellow,
        Some(_) => Color::Green,
        None => Color::DarkGray,
    };
    let (completed, total) = app.plan_progress();

    let mut spans = vec![Span::raw(" Context ")];
    match (context_tokens, context_ratio) {
        (Some(tokens), Some(ratio)) => {
            spans.push(Span::styled(
                format!(
                    "{} / {} · {:.0}% · reported",
                    format_tokens(u64::from(tokens)),
                    format_tokens(u64::from(prompt_limit)),
                    ratio * 100.0
                ),
                Style::default()
                    .fg(context_color)
                    .add_modifier(Modifier::BOLD),
            ));
        }
        _ if model_in_flight => {
            spans.push(Span::styled(
                "waiting for model usage",
                Style::default().fg(Color::Cyan),
            ));
        }
        _ => {
            spans.push(Span::styled(
                "reported after response",
                Style::default().fg(Color::DarkGray),
            ));
        }
    }
    spans.push(Span::raw("    Session "));
    if run.token_totals.model_calls == 0 {
        spans.push(Span::styled(
            "reported after response",
            Style::default().fg(Color::DarkGray),
        ));
    } else {
        spans.push(Span::styled(
            format!("↑{}", format_tokens(run.token_totals.input_tokens)),
            Style::default().fg(Color::Cyan),
        ));
        spans.push(Span::raw(" "));
        spans.push(Span::styled(
            format!("↓{}", format_tokens(run.token_totals.output_tokens)),
            Style::default().fg(Color::Green),
        ));
        spans.push(Span::styled(
            format!(" · {} calls", run.token_totals.model_calls),
            Style::default().fg(Color::DarkGray),
        ));
    }
    spans.push(Span::raw("    Plan "));
    spans.push(Span::styled(
        format!("{completed}/{total}"),
        Style::default().fg(Color::White),
    ));
    let line = Line::from(spans);

    let block = Block::default()
        .borders(Borders::TOP | Borders::BOTTOM)
        .title(" Context & Tokens ")
        .padding(Padding::horizontal(1))
        .border_style(Style::default().fg(context_color));
    f.render_widget(Paragraph::new(line).block(block), area);
}

fn state_presentation(state: &PipelineState) -> (&'static str, &'static str, Color) {
    match state {
        PipelineState::Idle => ("○", "IDLE", Color::Gray),
        PipelineState::LoadingTask | PipelineState::Preflight => ("●", "PREFLIGHT", Color::Cyan),
        PipelineState::AwaitingConsent { .. } => ("◆", "WAITING FOR YOU", Color::Yellow),
        PipelineState::Generating { .. } => ("●", "GENERATING", Color::Cyan),
        PipelineState::LocalValidation { .. }
        | PipelineState::DomainValidation { .. }
        | PipelineState::BuildValidation { .. } => ("●", "VALIDATING", Color::Cyan),
        PipelineState::Repairing { .. } => ("↻", "REPAIRING", Color::Yellow),
        PipelineState::Finalizing => ("●", "FINALIZING", Color::Cyan),
        PipelineState::Completed => ("✓", "COMPLETED", Color::Green),
        PipelineState::Failed { .. } => ("✗", "FAILED", Color::Red),
        PipelineState::Cancelled => ("–", "CANCELLED", Color::Yellow),
        PipelineState::SkippedByPolicy { .. } => ("■", "BLOCKED BY POLICY", Color::Red),
    }
}

fn format_tokens(tokens: u64) -> String {
    if tokens >= 1_000_000 {
        format!("{:.1}M", tokens as f64 / 1_000_000.0)
    } else if tokens >= 1_000 {
        format!("{:.1}K", tokens as f64 / 1_000.0)
    } else {
        tokens.to_string()
    }
}

fn draw_composer(f: &mut Frame, app: &App, area: Rect) {
    let editing = app.input_mode == InputMode::Editing;
    let content = composer_text(app);
    let color = if editing {
        Color::Cyan
    } else {
        Color::DarkGray
    };
    let paragraph = Paragraph::new(content)
        .block(
            Block::default()
                .borders(Borders::TOP | Borders::BOTTOM)
                .padding(Padding::horizontal(1))
                .border_style(Style::default().fg(color)),
        )
        .scroll((composer_scroll(app), 0));
    f.render_widget(paragraph, area);
}

fn draw_tool_commands(f: &mut Frame, app: &App, area: Rect) {
    if area.height == 0 {
        return;
    }
    let running: Vec<_> = app
        .run_state()
        .tool_processes
        .iter()
        .filter(|process| process.status == ToolProcessStatus::Running)
        .rev()
        .collect();

    let count = running.len();
    let display_count = count.min(5);
    
    let mut lines = running
        .into_iter()
        .take(display_count)
        .map(|process| {
            Line::from(vec![
                Span::styled(" ● ", Style::default().fg(Color::Cyan)),
                Span::styled(process.command.clone(), Style::default().fg(Color::White)),
            ])
        })
        .collect::<Vec<_>>();

    if count > 5 {
        lines.push(Line::from(vec![
            Span::styled(format!("   ... and {} more", count - 5), Style::default().fg(Color::DarkGray)),
        ]));
    }

    let block = Block::default()
        .title(Span::styled(" Active Tools ", Style::default().fg(Color::DarkGray)))
        .title_alignment(Alignment::Center)
        .borders(Borders::TOP)
        .border_style(Style::default().fg(Color::DarkGray))
        .padding(ratatui::widgets::Padding::horizontal(1));

    f.render_widget(Paragraph::new(lines).block(block), area);
}

fn visible_composer_lines(app: &App) -> u16 {
    app.input_buffer
        .split('\n')
        .count()
        .clamp(1, 8)
        .try_into()
        .unwrap_or(8)
}

fn composer_scroll(app: &App) -> u16 {
    app.input_buffer
        .split('\n')
        .count()
        .saturating_sub(8)
        .try_into()
        .unwrap_or(u16::MAX)
}

fn composer_text(app: &App) -> Text<'static> {
    if app.input_mode != InputMode::Editing {
        return if app.input_buffer.is_empty() {
            Text::styled(
                "Describe a task for the coding agent…",
                Style::default().fg(Color::DarkGray),
            )
        } else {
            Text::styled(app.input_buffer.clone(), Style::default().fg(Color::White))
        };
    }

    let cursor = if app.input_cursor_visible { "█" } else { " " };
    let cursor_style = Style::default()
        .fg(Color::Cyan)
        .add_modifier(Modifier::BOLD);
    if app.input_buffer.is_empty() {
        return Text::from(Line::from(vec![
            Span::styled(cursor, cursor_style),
            Span::styled(
                " Describe a task for the coding agent…",
                Style::default().fg(Color::DarkGray),
            ),
        ]));
    }

    let byte_index = app
        .input_buffer
        .char_indices()
        .nth(app.input_cursor)
        .map(|(index, _)| index)
        .unwrap_or(app.input_buffer.len());
    let before = &app.input_buffer[..byte_index];
    let after = &app.input_buffer[byte_index..];
    let mut before_lines = before.split('\n').map(str::to_string).collect::<Vec<_>>();
    let mut after_lines = after.split('\n').map(str::to_string).collect::<Vec<_>>();
    let current_before = before_lines.pop().unwrap_or_default();
    let current_after = after_lines.first().cloned().unwrap_or_default();
    if !after_lines.is_empty() {
        after_lines.remove(0);
    }

    let mut lines = before_lines
        .into_iter()
        .map(|line| Line::styled(line, Style::default().fg(Color::White)))
        .collect::<Vec<_>>();
    lines.push(Line::from(vec![
        Span::styled(current_before, Style::default().fg(Color::White)),
        Span::styled(cursor, cursor_style),
        Span::styled(current_after, Style::default().fg(Color::White)),
    ]));
    lines.extend(
        after_lines
            .into_iter()
            .map(|line| Line::styled(line, Style::default().fg(Color::White))),
    );
    Text::from(lines)
}

fn draw_bottom_hint(f: &mut Frame, app: &App, area: Rect) {
    let mut spans = vec![Span::raw("  ")];
    if let Some(notice) = &app.input_notice {
        spans.push(Span::styled(
            notice.clone(),
            Style::default().fg(Color::Yellow),
        ));
        spans.push(Span::styled(" · ", Style::default().fg(Color::DarkGray)));
    }
    if app.input_mode == InputMode::Editing {
        spans.extend([
            Span::styled("Enter", Style::default().fg(Color::Green)),
            Span::styled(" send · ", Style::default().fg(Color::DarkGray)),
            Span::styled("Shift+Enter", Style::default().fg(Color::Cyan)),
            Span::styled(" newline · ", Style::default().fg(Color::DarkGray)),
            Span::styled("/stats", Style::default().fg(Color::Cyan)),
            Span::styled(" stats · ", Style::default().fg(Color::DarkGray)),
            Span::styled("/main", Style::default().fg(Color::Cyan)),
            Span::styled(" main · ? shortcuts", Style::default().fg(Color::DarkGray)),
        ]);
    } else {
        spans.extend([
            Span::styled("i", Style::default().fg(Color::Green)),
            Span::styled(" input · ", Style::default().fg(Color::DarkGray)),
            Span::styled("j/k", Style::default().fg(Color::Cyan)),
            Span::styled(" scroll · ", Style::default().fg(Color::DarkGray)),
            Span::styled("c", Style::default().fg(Color::Yellow)),
            Span::styled(" cancel · ", Style::default().fg(Color::DarkGray)),
            Span::styled("q", Style::default().fg(Color::Red)),
            Span::styled(" quit", Style::default().fg(Color::DarkGray)),
        ]);
    }
    f.render_widget(Paragraph::new(Line::from(spans)), area);
}

const HELP_TEXT: &str = r#"KlintCode TUI — Keyboard Shortcuts

  g     Main conversation
  v     Statistics
  d     Candidate / diff view
  ?     Toggle help
  j/k   Scroll down/up
  c     Cancel current operation
  i     Focus interactive prompt
  q     Quit

While editing the prompt:
  Enter             Route and submit input
  Shift/Alt+Enter   Insert a new line
  Esc               Return to dashboard shortcuts

Slash commands:
  /task <request>    Force the development task pipeline
  /ask <question>    Force lightweight conversation
  /main              Main conversation
  /stats             Plan, validation, context, and Token usage
  /candidate         Generated candidate
  /diagnostics       Latest diagnostics
  /clear             Clear the main conversation

The TUI observes the pipeline state machine.
All execution is driven by the agent-core reducer."#;

#[cfg(test)]
mod tests {
    use super::*;
    use ratatui::backend::TestBackend;

    fn rendered_screen(app: &App, width: u16, height: u16) -> String {
        let backend = TestBackend::new(width, height);
        let mut terminal = Terminal::new(backend).expect("test terminal");
        terminal
            .draw(|frame| draw(frame, app))
            .expect("render screen");
        let buffer = terminal.backend().buffer();
        let mut rendered = String::new();
        for y in 0..height {
            for x in 0..width {
                rendered.push_str(buffer[(x, y)].symbol());
            }
            rendered.push('\n');
        }
        rendered
    }

    #[test]
    fn dashboard_keeps_plan_context_and_usage_visible() {
        let mut app = App::new().expect("app");
        app.view = View::Stats;
        app.dummy_run.context_budget = Some(agent_core::event::ContextBudget {
            model_context: 65_536,
            prompt_limit: 48_000,
            completion_limit: 8_000,
            safety_reserve: 8_000,
            estimated_prompt: 31_800,
        });
        app.dummy_run.token_totals.input_tokens = 84_000;
        app.dummy_run.token_totals.output_tokens = 7_200;
        app.dummy_run.token_totals.model_calls = 3;
        app.dummy_run.last_model_usage = Some(agent_core::event::TokenUsage {
            prompt_tokens: 31_800,
            completion_tokens: 2_100,
            total_tokens: 33_900,
        });

        let screen = rendered_screen(&app, 120, 36);

        assert!(screen.contains("Plan 0/6"));
        assert!(screen.contains("Context & Tokens"));
        assert!(screen.contains("31.8K / 48.0K"));
        assert!(screen.contains("↑84.0K"));
        assert!(screen.contains("↓7.2K"));
    }

    #[test]
    fn preflight_estimate_is_not_exposed_as_token_usage() {
        let mut app = App::new().expect("app");
        app.view = View::Stats;
        app.dummy_run.context_budget = Some(agent_core::event::ContextBudget {
            model_context: 65_536,
            prompt_limit: 48_000,
            completion_limit: 8_000,
            safety_reserve: 8_000,
            estimated_prompt: 31_800,
        });

        let screen = rendered_screen(&app, 120, 36);

        assert!(screen.contains("reported after response"));
        assert!(!screen.contains("31.8K"));
    }

    #[test]
    fn waiting_for_user_is_a_dominant_non_spinner_state() {
        let mut app = App::new().expect("app");
        app.dummy_run
            .activate_plan_step("preflight", "Allow generated code?");
        app.dummy_run
            .mark_current_plan_step(PlanStepStatus::WaitingUser, "Allow generated code?");
        app.dummy_run.state = PipelineState::AwaitingConsent {
            action: "Allow generated code?".to_string(),
        };

        let screen = rendered_screen(&app, 120, 36);

        assert!(screen.contains("◆ WAITING FOR YOU"));
        assert!(screen.contains("Allow generated code?"));
        assert!(screen.contains("[y]"));
        assert!(screen.contains("[n]"));
    }

    #[test]
    fn token_formatter_uses_compact_units() {
        assert_eq!(format_tokens(999), "999");
        assert_eq!(format_tokens(12_400), "12.4K");
        assert_eq!(format_tokens(2_500_000), "2.5M");
    }

    #[test]
    fn interactive_prompt_is_visible_and_focused_by_default() {
        let mut app = App::new().expect("app");

        let screen = rendered_screen(&app, 120, 36);

        assert!(screen.contains("coding agent"));
        assert!(screen.contains("█▄▀ █   █ █▄ █ ▀█▀"));
        assert!(screen.contains(KLINT_SLOGAN));
        assert!(screen.contains("Built by TeaQL"));
        assert!(screen.contains("endpoint ·"));
        assert!(screen.contains(&app.profile.resolve_endpoint()));
        assert!(screen.contains("checking model service"));
        assert!(screen.contains("█"));
        assert!(screen.contains("Enter"));
        assert!(screen.contains("/stats"));
        assert!(!screen.contains("Context & Tokens"));
        assert!(screen.contains("Plan 0/6"));
        assert!(!screen.contains('│'));
        let rows = screen.lines().collect::<Vec<_>>();
        assert!(rows[32].starts_with('─'));
        assert!(!rows[33].starts_with('│'));
        assert!(rows[34].starts_with('─'));

        app.input_cursor_visible = false;
        let blink_off_screen = rendered_screen(&app, 120, 36);
        assert_eq!(
            screen.matches('█').count(),
            blink_off_screen.matches('█').count() + 1
        );
    }

    #[test]
    fn active_conversation_uses_compact_header_and_follows_latest_event() {
        let mut app = App::new().expect("app");
        for index in 0..40 {
            app.timeline.push(crate::app::TimelineEntry {
                role: TimelineRole::Activity,
                content: if index == 39 {
                    "latest-timeline-event".to_string()
                } else {
                    format!("older-timeline-event-{index}")
                },
            });
        }

        let screen = rendered_screen(&app, 120, 36);

        assert!(!screen.contains("█▀▀ █   █ █▄ █ ▀█▀"));
        assert!(!screen.contains(KLINT_SLOGAN));
        assert!(screen.contains(" klint ·"));
        assert!(screen.contains("latest-timeline-event"));
        assert!(!screen.contains("older-timeline-event-0"));

        app.transcript_scroll_back = 5;
        let browsing = rendered_screen(&app, 120, 36);
        assert!(browsing.contains('↓'));
        assert!(browsing.contains("j ·"));
        assert!(!browsing.contains("latest-timeline-event"));
    }

    #[tokio::test]
    async fn local_model_answer_does_not_show_a_stale_plan() {
        let mut app = App::new().expect("app");
        let model = app.profile.model.name.clone();
        app.input_buffer = "which model?".to_string();
        app.input_cursor = app.input_buffer.chars().count();

        app.submit_input().await.expect("local answer");
        let screen = rendered_screen(&app, 120, 36);

        assert!(screen.contains(&model));
        assert!(!screen.contains("Plan 0/6"));
        assert!(!screen.contains("cargo teaql"));
    }

    #[test]
    fn wider_status_panel_lists_plan_execution_steps() {
        let mut app = App::new().expect("app");
        app.dummy_run.complete_plan_step("preflight");
        app.dummy_run
            .activate_plan_step("generate", "Generating candidate");
        app.dummy_run.state = PipelineState::Generating { attempt: 1 };

        let screen = rendered_screen(&app, 120, 36);

        assert!(screen.contains("Plan 1/6"));
        assert!(screen.contains("1."));
        assert!(screen.contains("2."));
        assert!(screen.contains("6."));
        assert!(screen.contains("Artifact"));
        assert!(!screen.contains('│'));
    }

    #[test]
    fn completed_status_panel_omits_summary_and_bottom_rule() {
        let mut app = App::new().expect("app");
        for step in &mut app.dummy_run.plan {
            step.status = PlanStepStatus::Completed;
        }
        app.dummy_run.state = PipelineState::Completed;
        let height = status_panel_height(&app);
        let backend = TestBackend::new(42, height);
        let mut terminal = Terminal::new(backend).expect("status terminal");
        terminal
            .draw(|frame| draw_compact_status(frame, &app, frame.area()))
            .expect("render status");
        let buffer = terminal.backend().buffer();
        let mut rendered = String::new();
        for y in 0..height {
            for x in 0..42 {
                rendered.push_str(buffer[(x, y)].symbol());
            }
            rendered.push('\n');
        }

        assert!(rendered.contains("Plan 6/6"));
        assert!(!rendered.contains("COMPLETED"));
        assert!(
            !rendered
                .lines()
                .last()
                .expect("last status row")
                .trim_start()
                .starts_with('─')
        );
    }

    #[test]
    fn plan_step_visuals_collapse_to_three_states_and_current_step_pulses() {
        assert_eq!(plan_step_style(PlanStepStatus::Pending, 2).0, "○");
        assert_eq!(plan_step_style(PlanStepStatus::Failed, 2).0, "○");
        assert_eq!(plan_step_style(PlanStepStatus::InProgress, 2).0, "●");
        assert_eq!(plan_step_style(PlanStepStatus::WaitingUser, 2).0, "●");
        assert_eq!(plan_step_style(PlanStepStatus::Completed, 2).0, "✓");

        let bright = plan_step_style(PlanStepStatus::InProgress, 2).1;
        let dim = plan_step_style(PlanStepStatus::InProgress, 0).1;
        assert_ne!(bright.fg, dim.fg);
    }

    #[test]
    fn composer_grows_to_eight_lines_then_shows_only_the_latest_eight() {
        let mut app = App::new().expect("app");
        app.input_buffer = [
            "hidden-alpha",
            "hidden-beta",
            "visible-charlie",
            "visible-delta",
            "visible-echo",
            "visible-foxtrot",
            "visible-golf",
            "visible-hotel",
            "visible-india",
            "visible-juliet",
        ]
        .join("\n");
        app.input_cursor = app.input_buffer.chars().count();

        assert_eq!(visible_composer_lines(&app), 8);
        assert_eq!(composer_scroll(&app), 2);

        let screen = rendered_screen(&app, 120, 36);
        assert!(!screen.contains("hidden-alpha"));
        assert!(!screen.contains("hidden-beta"));
        assert!(screen.contains("visible-charlie"));
        assert!(screen.contains("visible-juliet"));
        let rows = screen.lines().collect::<Vec<_>>();
        assert!(rows[25].starts_with('─'));
        assert!(rows[34].starts_with('─'));
    }

    #[test]
    fn composer_height_tracks_explicit_new_lines() {
        let mut app = App::new().expect("app");
        assert_eq!(visible_composer_lines(&app), 1);

        app.input_buffer = "first\nsecond".to_string();
        app.input_cursor = app.input_buffer.chars().count();
        assert_eq!(visible_composer_lines(&app), 2);

        let screen = rendered_screen(&app, 120, 36);
        let rows = screen.lines().collect::<Vec<_>>();
        assert!(rows[31].starts_with('─'));
        assert!(rows[34].starts_with('─'));
        assert!(screen.contains("first"));
        assert!(screen.contains("second"));
    }

    #[test]
    fn composer_only_shows_tools_that_are_still_running() {
        let mut app = App::new().expect("app");
        for id in 1..=5 {
            app.dummy_run
                .start_tool_process(id, format!("klint-test-command-{id}"));
        }
        app.dummy_run.finish_tool_process(1, true, Some(0));
        app.dummy_run.finish_tool_process(2, false, Some(9));
        app.dummy_run.finish_tool_process(5, false, Some(17));

        let main = rendered_screen(&app, 120, 36);
        assert!(!main.contains("klint-test-command-1"));
        assert!(!main.contains("klint-test-command-2"));
        assert!(main.contains("klint-test-command-3"));
        assert!(main.contains("klint-test-command-4"));
        assert!(!main.contains("klint-test-command-5"));
        assert!(!main.contains("exit 17"));

        app.view = View::Stats;
        let stats = rendered_screen(&app, 120, 36);
        assert!(stats.contains("Tool History"));
        assert!(stats.contains("klint-test-command-1"));
        assert!(stats.contains("klint-test-command-5"));
        assert!(!stats.contains("exit 17"));
    }

    #[test]
    fn stats_are_kept_off_the_default_surface() {
        let mut app = App::new().expect("app");
        app.dummy_run.token_totals.input_tokens = 84_000;
        app.dummy_run.token_totals.output_tokens = 7_200;
        app.dummy_run.token_totals.model_calls = 3;

        let main = rendered_screen(&app, 120, 36);
        assert!(!main.contains("↑84.0K"));
        assert!(!main.contains("Validation Timeline"));

        app.view = View::Stats;
        let stats = rendered_screen(&app, 120, 36);
        assert!(stats.contains("Statistics"));
        assert!(stats.contains("↑84.0K"));
        assert!(stats.contains("Validation Timeline"));
        assert!(!stats.contains('│'));
    }
}
