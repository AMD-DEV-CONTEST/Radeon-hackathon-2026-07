// Real interactive terminal backend using portable-pty (ConPTY on Windows,
// termios PTY on Unix). Replaces the one-shot, 30-second-timeout subprocess
// model in terminal.rs for the interactive terminal panel specifically:
//   - a real shell process stays alive across commands (cwd, env vars,
//     running background processes all persist)
//   - input is streamed keystroke-by-keystroke, so arrow keys, Ctrl+C, tab
//     completion, and interactive programs (less, vim, a REPL) all work
//   - output streams continuously via a Tauri event instead of waiting for
//     the whole command to finish
//
// Sessions are keyed by an id chosen by the frontend (one per terminal tab)
// and live in Tauri-managed state independent of any single window/component
// lifecycle, so the underlying shell keeps running even if the terminal
// panel is temporarily hidden. A capped ring buffer of recent output lets a
// freshly (re)mounted xterm instance replay recent scrollback on reconnect.

use portable_pty::{native_pty_system, CommandBuilder, MasterPty, PtySize};
use serde::Serialize;
use std::collections::HashMap;
use std::io::{Read, Write};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use tauri::{AppHandle, Emitter, State};

const SCROLLBACK_CAP_BYTES: usize = 256 * 1024;

struct PtySession {
    writer: Box<dyn Write + Send>,
    master: Box<dyn MasterPty + Send>,
    child: Box<dyn portable_pty::Child + Send + Sync>,
    scrollback: Arc<Mutex<Vec<u8>>>,
    alive: Arc<AtomicBool>,
}

#[derive(Default)]
pub struct PtyState(Mutex<HashMap<String, PtySession>>);

#[derive(Serialize, Clone)]
struct PtyOutputEvent {
    id: String,
    chunk: String,
}

#[derive(Serialize, Clone)]
struct PtyExitEvent {
    id: String,
    code: Option<i32>,
}

fn push_scrollback(buf: &Arc<Mutex<Vec<u8>>>, data: &[u8]) {
    if let Ok(mut guard) = buf.lock() {
        guard.extend_from_slice(data);
        if guard.len() > SCROLLBACK_CAP_BYTES {
            let excess = guard.len() - SCROLLBACK_CAP_BYTES;
            guard.drain(0..excess);
        }
    }
}

/// Spawn a new PTY-backed shell for `id`, or return immediately (with the
/// buffered scrollback so far) if a session for this id is already running --
/// this makes re-mounting the terminal panel idempotent instead of spawning
/// duplicate shells.
#[tauri::command]
pub fn pty_spawn(
    id: String,
    cwd: Option<String>,
    rows: Option<u16>,
    cols: Option<u16>,
    app: AppHandle,
    state: State<'_, PtyState>,
) -> Result<String, String> {
    let mut sessions = state.0.lock().map_err(|e| format!("PtyState mutex poisoned: {e}"))?;

    if let Some(existing) = sessions.get(&id) {
        if existing.alive.load(Ordering::Relaxed) {
            let buf = existing.scrollback.lock().map_err(|e| e.to_string())?;
            return Ok(String::from_utf8_lossy(&buf).to_string());
        }
        sessions.remove(&id);
    }

    let pty_system = native_pty_system();
    let pair = pty_system
        .openpty(PtySize {
            rows: rows.unwrap_or(24),
            cols: cols.unwrap_or(80),
            pixel_width: 0,
            pixel_height: 0,
        })
        .map_err(|e| format!("Failed to open pty: {e}"))?;

    #[cfg(target_os = "windows")]
    let mut cmd = CommandBuilder::new("powershell.exe");
    #[cfg(not(target_os = "windows"))]
    let mut cmd = CommandBuilder::new(std::env::var("SHELL").unwrap_or_else(|_| "/bin/bash".to_string()));

    if let Some(dir) = cwd.as_ref().filter(|s| !s.trim().is_empty()) {
        cmd.cwd(dir);
    }

    let child = pair
        .slave
        .spawn_command(cmd)
        .map_err(|e| format!("Failed to spawn shell: {e}"))?;
    // Drop our handle to the slave end -- the child process owns the real one.
    drop(pair.slave);

    let mut reader = pair
        .master
        .try_clone_reader()
        .map_err(|e| format!("Failed to clone pty reader: {e}"))?;
    let writer = pair
        .master
        .take_writer()
        .map_err(|e| format!("Failed to take pty writer: {e}"))?;

    let scrollback: Arc<Mutex<Vec<u8>>> = Arc::new(Mutex::new(Vec::new()));
    let alive = Arc::new(AtomicBool::new(true));

    // Background OS thread: blocking reads off the PTY, forwarded as Tauri
    // events. Not a tokio task -- this is genuinely blocking I/O and would
    // stall the async runtime if run there.
    {
        let scrollback = scrollback.clone();
        let alive = alive.clone();
        let app = app.clone();
        let id = id.clone();
        std::thread::spawn(move || {
            let mut buf = [0u8; 4096];
            loop {
                match reader.read(&mut buf) {
                    Ok(0) => break,
                    Ok(n) => {
                        push_scrollback(&scrollback, &buf[..n]);
                        let chunk = String::from_utf8_lossy(&buf[..n]).to_string();
                        let _ = app.emit("pty-output", PtyOutputEvent { id: id.clone(), chunk });
                    }
                    Err(_) => break,
                }
            }
            alive.store(false, Ordering::Relaxed);
            let _ = app.emit("pty-exit", PtyExitEvent { id: id.clone(), code: None });
        });
    }

    sessions.insert(
        id,
        PtySession {
            writer,
            master: pair.master,
            child,
            scrollback,
            alive,
        },
    );

    Ok(String::new())
}

#[tauri::command]
pub fn pty_write(id: String, data: String, state: State<'_, PtyState>) -> Result<(), String> {
    let mut sessions = state.0.lock().map_err(|e| format!("PtyState mutex poisoned: {e}"))?;
    let session = sessions
        .get_mut(&id)
        .ok_or_else(|| format!("No pty session for id {id}"))?;
    session
        .writer
        .write_all(data.as_bytes())
        .map_err(|e| format!("Failed to write to pty: {e}"))?;
    session.writer.flush().map_err(|e| e.to_string())
}

#[tauri::command]
pub fn pty_resize(id: String, rows: u16, cols: u16, state: State<'_, PtyState>) -> Result<(), String> {
    let sessions = state.0.lock().map_err(|e| format!("PtyState mutex poisoned: {e}"))?;
    let session = sessions
        .get(&id)
        .ok_or_else(|| format!("No pty session for id {id}"))?;
    session
        .master
        .resize(PtySize {
            rows,
            cols,
            pixel_width: 0,
            pixel_height: 0,
        })
        .map_err(|e| format!("Failed to resize pty: {e}"))
}

#[tauri::command]
pub fn pty_kill(id: String, state: State<'_, PtyState>) -> Result<(), String> {
    let mut sessions = state.0.lock().map_err(|e| format!("PtyState mutex poisoned: {e}"))?;
    if let Some(mut session) = sessions.remove(&id) {
        session.alive.store(false, Ordering::Relaxed);
        let _ = session.child.kill();
    }
    Ok(())
}

#[tauri::command]
pub fn pty_is_alive(id: String, state: State<'_, PtyState>) -> Result<bool, String> {
    let sessions = state.0.lock().map_err(|e| format!("PtyState mutex poisoned: {e}"))?;
    Ok(sessions
        .get(&id)
        .map(|s| s.alive.load(Ordering::Relaxed))
        .unwrap_or(false))
}
