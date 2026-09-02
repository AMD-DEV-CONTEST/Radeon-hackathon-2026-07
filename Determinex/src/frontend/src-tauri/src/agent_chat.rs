// The "Agent Chat Room" -- several coding-agent CLIs (Claude Code, Codex,
// Gemini CLI, a local Ollama model via aider) share ONE conversation and
// workspace, each with real agentic file-editing capability, oracle-verified
// after every turn -- same trust model as agent_registry.rs: an agent's own
// "done" is never trusted, only a passing compiler/test run is.
//
// Given multiple file-editing participants, the one non-negotiable safety
// property is that turns run strictly SEQUENTIALLY: one CLI subprocess
// exits and gets oracle-verified before the next one starts. That
// invariant lives entirely in this file, enforced by ChatSession.running +
// the per-session queue, both behind one mutex -- never relaxed, not even
// for "everyone responds to this message" broadcast rounds (each
// participant still runs one at a time, in order).
//
// Session/transcript persistence, @mention parsing, and prompt-building are
// owned by scripts/determinex_agent_chat.py (see module docstring there);
// this file only owns process orchestration + live output streaming. Each
// turn's argv comes from `determinex_agents.py resolve` (the single source
// of truth for CLI invocation shape, shared with agent_registry.rs) so the
// argv template itself is never duplicated here.

// Python is resolved through `ipc_hive::resolve_python_exe()`, never `Command::new("python")`.
//
// That resolver exists for a specific reason: on Windows, PATH `python` is very
// often the Microsoft Store AppExecLink stub, which does not run Python -- it opens
// the Store. It also prefers the repo venv, so the interpreter that has the
// project's dependencies is the one used. Ten call sites across six files bypassed
// it and used bare `python`, which worked only on machines where PATH happened to
// resolve to a real interpreter.

use serde::{Deserialize, Serialize};
use std::collections::{HashMap, VecDeque};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};
use tauri::{AppHandle, Emitter, Manager, State};

use crate::project_audit::run_with_timeout;
use crate::win_process::HideConsoleExt;

const AGENTS_SCRIPT: &str = "scripts/determinex_agents.py";
const CHAT_SCRIPT: &str = "scripts/determinex_agent_chat.py";
const BENCH_SCRIPT: &str = "scripts/determinex_local_model_bench.py";
const TURN_TIMEOUT: Duration = Duration::from_secs(300);
const QUICK_TIMEOUT: Duration = Duration::from_secs(20);
// record-turn's oracle-verify path (determinex_repair.repair_workspace) runs a
// REAL compiler/test pass over the whole workspace for any non-user speaker.
// On THIS repo specifically it's not just a compile check -- a direct timing
// run of repair_workspace() against C:\Dev\Determinex exceeded 10 minutes before
// being stopped, almost certainly because it runs full test suites across an
// unusually large polyglot monorepo, not a typical target project. 300s
// already proved insufficient live (still hit the timeout twice). Raised to
// 900s (15 min) as a pragmatic ceiling -- most real projects finish in
// seconds; exceptionally large ones may still exceed even this. Either way,
// run_script_json_timeout's elapsed-time heuristic now reports a clear
// "killed for running too long" message instead of a cryptic JSON parse
// error when the bound IS hit, so this is a soft ceiling with an honest
// failure mode, not a silent data-loss trap like before.
const ORACLE_VERIFY_TIMEOUT: Duration = Duration::from_secs(900);
// The bench call itself may need to run a real (slow, uncached) local-model
// probe -- give it much more room than the other quick metadata round-trips.
const BENCH_TIMEOUT: Duration = Duration::from_secs(150);

static TURN_COUNTER: AtomicU64 = AtomicU64::new(0);

fn new_turn_id(session_id: &str) -> String {
    let n = TURN_COUNTER.fetch_add(1, Ordering::Relaxed);
    format!("{session_id}-{}-{n}", chrono::Utc::now().timestamp_millis())
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum TurnMode {
    Mention,
    Broadcast,
}

impl TurnMode {
    fn as_str(&self) -> &'static str {
        match self {
            TurnMode::Mention => "mention",
            TurnMode::Broadcast => "broadcast",
        }
    }
}

pub(crate) struct QueuedTurn {
    turn_id: String,
    agent: String,
    addressed_to: Vec<String>,
}

pub struct ChatSession {
    pub workspace: String,
    pub participants: Vec<String>,
    pub turn_mode: TurnMode,
    pub queue: VecDeque<QueuedTurn>,
    pub running: bool,
    // ANY LLM (Ryan, live: "fix it to where ANY llm can be used"): per-agent
    // model override for this session. Empty/absent means "use that agent's
    // own default" -- local-ollama falls back to local_model_tag(), cloud
    // agents run with no --model flag at all (their own CLI default).
    // In-memory only (like queue/running); a session's model choice resets
    // to default across an app restart, same lifecycle as everything else
    // in ChatState.
    pub models: HashMap<String, String>,
}

#[derive(Default)]
pub struct ChatState(pub Mutex<HashMap<String, ChatSession>>);

// ---------------------------------------------------------------------------
// DTOs to/from the frontend. Same asymmetric snake_case-in/camelCase-out
// convention as agent_registry.rs's CodingAgentInfo/CodingAgentRunResult.
// ---------------------------------------------------------------------------
#[derive(Debug, Serialize, Deserialize, Clone)]
#[serde(rename_all(serialize = "camelCase", deserialize = "snake_case"))]
pub struct ChatSessionSummary {
    pub session_id: String,
    pub workspace: String,
    pub participants: Vec<String>,
    pub turn_mode: String,
    pub created_at: String,
    pub last_active: String,
    pub turn_count: u32,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
#[serde(rename_all(serialize = "camelCase", deserialize = "snake_case"))]
pub struct ChatTurnDto {
    pub turn_id: String,
    pub session_id: String,
    pub seq: u32,
    pub speaker: String,
    pub speaker_kind: String,
    pub addressed_to: Vec<String>,
    pub mode: String,
    pub task_prompt: String,
    pub raw_output: String,
    pub returncode: i32,
    pub verified: bool,
    pub oracle: String,
    pub n_failures: u32,
    pub note: String,
    pub started_at: String,
    pub finished_at: String,
}

// These three cross the Rust->TS event boundary (agent-chat-output /
// agent-chat-turn-complete / agent-chat-queue-update), same as every other
// emitted event/DTO in this codebase (see git.rs, lsp.rs, onboarding.rs,
// project_audit.rs, passport.rs, agent_registry.rs) -- rename_all=camelCase
// is mandatory here. Without it, serde emits snake_case JSON keys
// (session_id, turn_id, n_failures) while AgentChatPanel.tsx's listeners
// read camelCase (event.payload.sessionId) -- every field silently
// deserializes to `undefined`, so `event.payload.sessionId !== activeSessionId`
// is ALWAYS true and every listener permanently no-ops. This was the root
// cause of the live transcript never updating in-place: turns really were
// being recorded (confirmed via the persisted JSONL), but no live event ever
// passed its own session-match guard, so refreshTranscript/refreshSessions
// were never invoked. Only a full remount (which refetches once on mount,
// not via events) ever showed fresh data.
#[derive(Serialize, Clone)]
#[serde(rename_all = "camelCase")]
struct AgentChatOutputEvent {
    session_id: String,
    turn_id: String,
    agent: String,
    stream: String, // "stdout" | "stderr"
    chunk: String,
}

#[derive(Serialize, Clone)]
#[serde(rename_all = "camelCase")]
struct AgentChatTurnCompleteEvent {
    session_id: String,
    turn_id: String,
    agent: String,
    verified: bool,
    oracle: String,
    n_failures: u32,
    note: String,
    error: Option<String>,
}

#[derive(Serialize, Clone)]
#[serde(rename_all = "camelCase")]
struct AgentChatQueueEvent {
    session_id: String,
    pending: Vec<String>,
    running: Option<String>,
}

// ---------------------------------------------------------------------------
// Python bridge helpers
// ---------------------------------------------------------------------------
fn locate_repo_root() -> Option<PathBuf> {
    let cwd = std::env::current_dir().ok()?;
    let mut cur: Option<&Path> = Some(cwd.as_path());
    while let Some(c) = cur {
        if c.join(AGENTS_SCRIPT).is_file() {
            return Some(c.to_path_buf());
        }
        cur = c.parent();
    }
    None
}

/// One quick, blocking round-trip to a Python script that prints one JSON
/// value to stdout. Used for everything that ISN'T the long-running agent
/// CLI itself (session bookkeeping, prompt building, argv resolution,
/// turn recording) -- all fast, deterministic, no live-streaming need.
fn run_script_json(root: &Path, script: &str, args: &[&str]) -> Result<serde_json::Value, String> {
    run_script_json_timeout(root, script, args, QUICK_TIMEOUT)
}

fn run_script_json_timeout(
    root: &Path, script: &str, args: &[&str], timeout: Duration,
) -> Result<serde_json::Value, String> {
    // BUNDLED-FIRST. This used to build `python <root>/scripts/<name>.py` directly,
    // which meant every panel routed through here -- the agent chat room, the agent
    // registry, the usage ledger, the toolchain installer, the model bench -- worked
    // only in a dev checkout, because an installed copy has no scripts/ directory.
    // hive_command had been bundled-first for a while; this second path was not, so the
    // hive shipped and the panels around it did not. helper_command resolves the
    // bundled engine's `helper <module>` dispatch and falls back to the repo script.
    let (mut cmd, bundled) = crate::ipc_hive::helper_command(script)?;
    for a in args {
        cmd.arg(a);
    }
    cmd.current_dir(root);
    if !bundled {
        log::debug!("{script}: bundled engine not found, using the repo script");
    }
    let start = Instant::now();
    let output = run_with_timeout(cmd, timeout)
        .map_err(|e| format!("could not run {script}: {e}"))?;
    let elapsed = start.elapsed();
    let stdout = String::from_utf8_lossy(&output.stdout);
    crate::python_json::parse_python_json(&stdout, script).map_err(|e| {
        let stderr = String::from_utf8_lossy(&output.stderr);
        // run_with_timeout (project_audit.rs) kills the child and returns
        // Ok(empty output) on timeout -- indistinguishable at the type level
        // from a process that legitimately printed nothing. Elapsed time
        // close to the bound is the only signal available without a bigger
        // refactor of that shared helper; surface it so a killed oracle
        // check reads as an honest timeout instead of a confusing JSON
        // parse error (found live: a real local-ollama turn ran to
        // completion but its result was lost this way before this note was
        // added, twice, even after the timeout was already raised once).
        if stdout.is_empty() && stderr.is_empty() && elapsed >= timeout.mul_f32(0.9) {
            format!(
                "{script} produced no output after {:.0}s (timeout {:.0}s) -- most likely killed for \
                 running too long, not a real parse error. {args:?}",
                elapsed.as_secs_f32(), timeout.as_secs_f32()
            )
        } else {
            format!("{e} (args={args:?}, stderr={stderr})")
        }
    })
}

fn write_temp_file(prefix: &str, content: &str) -> Result<PathBuf, String> {
    let path = std::env::temp_dir().join(format!(
        "determinex-agent-chat-{prefix}-{}.txt",
        chrono::Utc::now().timestamp_nanos_opt().unwrap_or(0)
    ));
    std::fs::write(&path, content).map_err(|e| format!("failed to write temp file: {e}"))?;
    Ok(path)
}

fn is_local_participant(agent: &str) -> bool {
    matches!(agent, "local-ollama" | "aider-local" | "ollama")
}

/// The corpus as an addressable chat participant (@corpus) -- Ryan: "the
/// corpus have an interface and an oracle feedback loop... this chat should
/// be layered throughout." Not a CLI agent: never spawned, never resolved
/// via determinex_agents.py, never subject to Cloak (a corpus lookup reads
/// determinex_corpus_api's own knowledge base + this session's own oracle
/// history, never the workspace's source files). Handled as its own branch
/// at the top of run_one_turn, entirely before the CLI-resolve/spawn path.
fn is_corpus_participant(agent: &str) -> bool {
    agent.eq_ignore_ascii_case("corpus")
}

fn cloak_enabled() -> bool {
    std::env::var("DETERMINEX_CLOAK").map(|v| !v.trim().is_empty()).unwrap_or(false)
}

/// The model a local chat participant uses when the session sets no override.
///
/// The fallback comes from `model_puller::DEFAULT_LOCAL_CHAT_MODEL` rather than a literal here.
/// This used to hardcode `qwen2.5-coder:14b-instruct-q4_K_M`, which the installer deliberately does
/// NOT pull, so on a fresh install every first chat message asked Ollama for a model that was never
/// downloaded. It was invisible on a dev box because the repo `.env` sets
/// `DETERMINEX_LOCAL_BUILDER_MODEL` -- and `.env` is not shipped in the installer.
///
/// The env var still wins, so a machine that does have the 14b keeps using it.
fn local_model_tag() -> String {
    std::env::var("DETERMINEX_LOCAL_BUILDER_MODEL")
        .ok()
        .map(|v| v.trim().to_string())
        // An env var set to whitespace must not resolve to an empty model tag: that is the
        // empty-model 404 this file already guards against in agent_chat_set_model.
        .filter(|v| !v.is_empty())
        .unwrap_or_else(|| crate::model_puller::DEFAULT_LOCAL_CHAT_MODEL.to_string())
}

fn local_ollama_base_url() -> String {
    std::env::var("DETERMINEX_OLLAMA_URL")
        .or_else(|_| std::env::var("OLLAMA_HOST"))
        .unwrap_or_else(|_| "http://localhost:11434".to_string())
}

/// Cloud CLI agents (Claude Code, Codex, Gemini CLI) get the flat
/// TURN_TIMEOUT -- their response time is roughly hardware-independent. A
/// local Ollama model's real latency depends entirely on THIS machine's
/// VRAM/RAM (measured live during development: 113s to generate 2 tokens for
/// a 14B model on a 6GB card), so it gets a real, measured-or-placeholder
/// timeout instead of guessing. Falls back to the flat default if the
/// benchmark call itself fails -- calibration must never block a turn from
/// being attempted.
fn local_turn_timeout(root: &Path, model: &str) -> Duration {
    match run_script_json_timeout(root, BENCH_SCRIPT, &["estimate-timeout", "--model", model], BENCH_TIMEOUT) {
        Ok(v) => v.get("timeout_seconds").and_then(|t| t.as_u64())
            .map(Duration::from_secs)
            .unwrap_or(TURN_TIMEOUT),
        Err(_) => TURN_TIMEOUT,
    }
}

// ---------------------------------------------------------------------------
// Commands
// ---------------------------------------------------------------------------

/// Whether the Cloak room is active for cloud participants in this session --
/// previously only visible by checking the DETERMINEX_CLOAK env var outside
/// the app; a user had no in-app way to confirm cloud agents were actually
/// being shielded.
#[tauri::command]
pub fn agent_chat_cloak_status() -> bool {
    cloak_enabled()
}

#[tauri::command]
pub async fn agent_chat_create_session(
    session_id: String,
    workspace: String,
    participants: Vec<String>,
    turn_mode: String,
    state: State<'_, ChatState>,
) -> Result<(), String> {
    let root = locate_repo_root().ok_or_else(|| "could not locate repo root".to_string())?;
    let participants_csv = participants.join(",");
    run_script_json(
        &root,
        CHAT_SCRIPT,
        &[
            "create-session",
            &session_id,
            "--workspace",
            &workspace,
            "--participants",
            &participants_csv,
            "--mode",
            &turn_mode,
        ],
    )?;

    let mode = if turn_mode == "mention" {
        TurnMode::Mention
    } else {
        TurnMode::Broadcast
    };
    let mut sessions = state.0.lock().map_err(|e| format!("ChatState mutex poisoned: {e}"))?;
    sessions.insert(
        session_id,
        ChatSession {
            workspace,
            participants,
            turn_mode: mode,
            queue: VecDeque::new(),
            running: false,
            models: HashMap::new(),
        },
    );
    Ok(())
}

#[tauri::command]
pub async fn agent_chat_list_sessions(workspace: String) -> Result<Vec<ChatSessionSummary>, String> {
    let root = locate_repo_root().ok_or_else(|| "could not locate repo root".to_string())?;
    let raw = run_script_json(&root, CHAT_SCRIPT, &["list-sessions", "--workspace", &workspace])?;
    let arr = raw.as_array().ok_or_else(|| "list-sessions: expected a JSON array".to_string())?;
    let mut out = Vec::with_capacity(arr.len());
    for v in arr {
        out.push(serde_json::from_value(v.clone()).map_err(|e| format!("malformed session summary: {e}"))?);
    }
    Ok(out)
}

#[tauri::command]
pub async fn agent_chat_get_transcript(session_id: String) -> Result<Vec<ChatTurnDto>, String> {
    let root = locate_repo_root().ok_or_else(|| "could not locate repo root".to_string())?;
    let raw = run_script_json(&root, CHAT_SCRIPT, &["transcript", &session_id])?;
    let arr = raw.as_array().ok_or_else(|| "transcript: expected a JSON array".to_string())?;
    let mut out = Vec::with_capacity(arr.len());
    for v in arr {
        out.push(serde_json::from_value(v.clone()).map_err(|e| format!("malformed chat turn: {e}"))?);
    }
    Ok(out)
}

/// The shared mission plan doc -- the ONE canonical document every
/// participant's prompt is built from (see build_context_prompt() in
/// determinex_agent_chat.py). Deliberately separate from the transcript:
/// it's not windowed, and it's meant to be explicitly authored/edited, not
/// inferred from a rolling chat log.
#[tauri::command]
pub async fn agent_chat_get_plan(session_id: String) -> Result<String, String> {
    let root = locate_repo_root().ok_or_else(|| "could not locate repo root".to_string())?;
    let raw = run_script_json(&root, CHAT_SCRIPT, &["plan-read", &session_id])?;
    Ok(raw.get("content").and_then(|c| c.as_str()).unwrap_or("").to_string())
}

#[tauri::command]
pub async fn agent_chat_set_plan(session_id: String, content: String) -> Result<(), String> {
    let root = locate_repo_root().ok_or_else(|| "could not locate repo root".to_string())?;
    let content_file = write_temp_file("plan", &content)?;
    let content_file_str = content_file.to_string_lossy().to_string();
    let result = run_script_json(
        &root,
        CHAT_SCRIPT,
        &["plan-write", &session_id, "--content-file", &content_file_str],
    );
    let _ = std::fs::remove_file(&content_file);
    result.map(|_| ())
}

/// Pull fresh content from the workspace's root/project stewardship docs
/// (see determinex_stewardship.py) into an EXISTING session's plan --
/// appends a timestamped section rather than overwriting, so it never
/// destroys what the user or agents have already written into the plan
/// (including the live Positions board).
#[tauri::command]
pub async fn agent_chat_resync_plan(session_id: String, workspace: String) -> Result<String, String> {
    let root = locate_repo_root().ok_or_else(|| "could not locate repo root".to_string())?;
    let raw = run_script_json(&root, CHAT_SCRIPT, &["resync-plan", &session_id, "--workspace", &workspace])?;
    Ok(raw.get("content").and_then(|c| c.as_str()).unwrap_or("").to_string())
}

/// Post a message (from the user, or as an agent-initiated follow-up) into a
/// session. Records it immediately (no oracle run for non-agent turns), then
/// figures out who should respond this round (explicit @mentions always win;
/// otherwise broadcast mode queues every participant, mention mode queues
/// nobody) and queues their turns. Returns as soon as the message is
/// recorded and the round is queued -- does NOT wait for agent turns to
/// finish; those stream via agent-chat-output / agent-chat-turn-complete.
/// ChatState is in-memory only (queue/running have no business being
/// persisted) and only ever gets populated by agent_chat_create_session --
/// so a session that existed before an app restart (dev rebuild, or a real
/// user relaunching the app) vanished from the map entirely even though its
/// metadata and transcript are still sitting on disk, and calling send() on
/// it failed hard with "unknown chat session". Self-heal by pulling the
/// persisted metadata back in on first use after a restart.
fn ensure_session_loaded(
    root: &Path,
    session_id: &str,
    state: &State<'_, ChatState>,
) -> Result<(), String> {
    {
        let sessions = state.0.lock().map_err(|e| format!("ChatState mutex poisoned: {e}"))?;
        if sessions.contains_key(session_id) {
            return Ok(());
        }
    }

    let persisted = run_script_json(root, CHAT_SCRIPT, &["get-session", session_id])?;
    if persisted.is_null() {
        return Err(format!("unknown chat session '{session_id}'"));
    }
    let workspace = persisted.get("workspace").and_then(|v| v.as_str()).unwrap_or("").to_string();
    let participants: Vec<String> = persisted
        .get("participants")
        .and_then(|v| v.as_array())
        .map(|arr| arr.iter().filter_map(|x| x.as_str().map(String::from)).collect())
        .unwrap_or_default();
    let turn_mode = match persisted.get("turn_mode").and_then(|v| v.as_str()) {
        Some("mention") => TurnMode::Mention,
        _ => TurnMode::Broadcast,
    };

    // Model overrides are rehydrated too (2026-07-31). This used to be `HashMap::new()`, so a
    // restart restored the session's participants and mode but silently dropped which model each
    // one was using. That is worse than losing a preference: local-ollama's default is a DIFFERENT
    // model from whatever the user picked, so the same session started answering with a different
    // model and nothing in the UI said so. `models` now lives on the persisted record next to
    // participants, which is where a per-session choice belongs.
    let models: HashMap<String, String> = persisted
        .get("models")
        .and_then(|v| v.as_object())
        .map(|obj| {
            obj.iter()
                .filter_map(|(k, v)| v.as_str().map(|s| (k.clone(), s.to_string())))
                .filter(|(_, v)| !v.trim().is_empty())
                .collect()
        })
        .unwrap_or_default();

    let mut sessions = state.0.lock().map_err(|e| format!("ChatState mutex poisoned: {e}"))?;
    sessions.entry(session_id.to_string()).or_insert(ChatSession {
        workspace,
        participants,
        turn_mode,
        queue: VecDeque::new(),
        running: false,
        models,
    });
    Ok(())
}

/// ANY LLM: set (or clear, with an empty string) this session's model
/// override for one participant. claude-code/codex/gemini-cli each accept
/// any model name their own CLI recognizes (their --model/-m flag, wired in
/// determinex_agents.py's model_flag); local-ollama accepts any tag already
/// pulled in Ollama (see ollama_probe::get_ollama_models for the picker's
/// source of truth).
///
/// Persisted on the session record as of 2026-07-31, so the choice survives an
/// app restart the same way participants and turn mode do. It used to be
/// in-memory only and reset to defaults on relaunch.
#[tauri::command]
pub async fn agent_chat_set_model(
    session_id: String,
    agent: String,
    model: String,
    state: State<'_, ChatState>,
) -> Result<(), String> {
    let root = locate_repo_root().ok_or_else(|| "could not locate repo root".to_string())?;
    ensure_session_loaded(&root, &session_id, &state)?;
    {
        let mut sessions = state.0.lock().map_err(|e| format!("ChatState mutex poisoned: {e}"))?;
        let session = sessions
            .get_mut(&session_id)
            .ok_or_else(|| format!("unknown chat session '{session_id}'"))?;
        if model.trim().is_empty() {
            session.models.remove(&agent);
        } else {
            session.models.insert(agent.clone(), model.clone());
        }
    }
    // Write it through AFTER the in-memory update, and let a write failure surface. Swallowing it
    // would leave the running session on the new model and the next launch on the old one, which
    // reads to the user as the setting randomly forgetting itself.
    run_script_json(&root, CHAT_SCRIPT, &["set-model", &session_id, &agent, &model])?;
    Ok(())
}

/// Apply one turn's proposed edits, after the user has approved them.
///
/// Chat turns never write to the workspace. Measured 2026-07-31: one conversational turn in six --
/// a turn whose whole content was answering a question -- silently rewrote a source file, because a
/// small model in a workspace context sometimes decides to edit. That is sampling, not prompt
/// wording, so the write is structurally unavailable instead of discouraged: the agent emits a
/// validated proposal and this is the only path that puts bytes on disk.
///
/// Refuses a stale proposal (the file changed since it was proposed) and a path that leaves the
/// workspace; both are enforced in determinex_agent_chat.apply_proposal so the CLI and the IDE
/// cannot disagree about what approval permits.
#[tauri::command]
pub async fn agent_chat_apply_proposal(
    session_id: String,
    turn_id: String,
    workspace: String,
) -> Result<Vec<String>, String> {
    let root = locate_repo_root().ok_or_else(|| "could not locate repo root".to_string())?;
    let raw = run_script_json(
        &root,
        CHAT_SCRIPT,
        &["apply-proposal", &session_id, &turn_id, "--workspace", &workspace],
    )?;
    Ok(raw
        .get("applied")
        .and_then(|v| v.as_array())
        .map(|arr| arr.iter().filter_map(|x| x.as_str().map(String::from)).collect())
        .unwrap_or_default())
}

/// List the turns in a session that carry proposed edits nobody has applied yet, so the panel can
/// show an approval affordance without parsing transcript text in the UI layer.
#[tauri::command]
pub async fn agent_chat_list_proposals(session_id: String) -> Result<serde_json::Value, String> {
    let root = locate_repo_root().ok_or_else(|| "could not locate repo root".to_string())?;
    run_script_json(&root, CHAT_SCRIPT, &["proposals", &session_id])
}

#[tauri::command]
pub async fn agent_chat_send(
    session_id: String,
    message: String,
    sender: String,
    app: AppHandle,
    state: State<'_, ChatState>,
) -> Result<bool, String> {
    let root = locate_repo_root().ok_or_else(|| "could not locate repo root".to_string())?;
    ensure_session_loaded(&root, &session_id, &state)?;

    let (workspace, participants, turn_mode) = {
        let sessions = state.0.lock().map_err(|e| format!("ChatState mutex poisoned: {e}"))?;
        let session = sessions
            .get(&session_id)
            .ok_or_else(|| format!("unknown chat session '{session_id}'"))?;
        (session.workspace.clone(), session.participants.clone(), session.turn_mode)
    };

    // 1. Record the message itself as a turn. Fast, no CLI spawn, no oracle
    //    run for a "user" speaker (see determinex_agent_chat.record_turn).
    let speaker_kind = if sender == "user" { "user" } else { "agent" };
    let msg_file = write_temp_file("msg", &message)?;
    let msg_turn_id = new_turn_id(&session_id);
    let record_result = run_script_json(
        &root,
        AGENTS_SCRIPT,
        &[
            "record-turn",
            &session_id,
            &sender,
            "--workspace",
            &workspace,
            "--raw-file",
            msg_file.to_string_lossy().as_ref(),
            "--returncode",
            "0",
            "--turn-id",
            &msg_turn_id,
            "--task-prompt-file",
            msg_file.to_string_lossy().as_ref(),
            "--speaker-kind",
            speaker_kind,
            "--mode",
            turn_mode.as_str(),
        ],
    );
    let _ = std::fs::remove_file(&msg_file);
    record_result?;
    let _ = app.emit(
        "agent-chat-turn-complete",
        AgentChatTurnCompleteEvent {
            session_id: session_id.clone(),
            turn_id: msg_turn_id,
            agent: sender,
            verified: true,
            oracle: String::new(),
            n_failures: 0,
            note: "message recorded".to_string(),
            error: None,
        },
    );

    // 2. Who responds this round? An explicit @mention always wins over the
    //    session's default mode -- lets a user in broadcast mode direct a
    //    single question, and lets mention mode still work as intended.
    let mentions_raw = run_script_json(
        &root,
        CHAT_SCRIPT,
        &["parse-mentions", &message, "--known-agents", &participants.join(",")],
    )
    .unwrap_or_else(|_| serde_json::json!([]));
    let mentions: Vec<String> = mentions_raw
        .as_array()
        .map(|arr| arr.iter().filter_map(|v| v.as_str().map(String::from)).collect())
        .unwrap_or_default();

    let responders: Vec<String> = if !mentions.is_empty() {
        mentions.clone()
    } else if matches!(turn_mode, TurnMode::Broadcast) {
        participants.clone()
    } else {
        Vec::new() // mention mode, no one addressed -> nobody auto-responds
    };

    if responders.is_empty() {
        return Ok(true);
    }

    // 3. Queue the round; dispatch a worker only if the session was idle.
    let should_dispatch = {
        let mut sessions = state.0.lock().map_err(|e| format!("ChatState mutex poisoned: {e}"))?;
        let session = sessions
            .get_mut(&session_id)
            .ok_or_else(|| format!("unknown chat session '{session_id}'"))?;
        for agent in &responders {
            session.queue.push_back(QueuedTurn {
                turn_id: new_turn_id(&session_id),
                agent: agent.clone(),
                addressed_to: mentions.clone(),
            });
        }
        if !session.running {
            session.running = true;
            true
        } else {
            false
        }
    };

    emit_queue_update(&app, &session_id, &state);

    if should_dispatch {
        dispatch_loop(session_id, app);
    }
    Ok(true)
}

fn emit_queue_update(app: &AppHandle, session_id: &str, state: &State<'_, ChatState>) {
    if let Ok(sessions) = state.0.lock() {
        if let Some(session) = sessions.get(session_id) {
            let pending = session.queue.iter().map(|q| q.agent.clone()).collect();
            let _ = app.emit(
                "agent-chat-queue-update",
                AgentChatQueueEvent {
                    session_id: session_id.to_string(),
                    pending,
                    running: None,
                },
            );
        }
    }
}

/// Runs queued turns for `session_id` one at a time, strictly sequentially,
/// until the queue is empty -- the entire sequential-execution guarantee for
/// this feature. Spawned as its own OS thread (not a tokio task) because
/// each turn involves genuinely blocking subprocess I/O.
fn dispatch_loop(session_id: String, app: AppHandle) {
    std::thread::spawn(move || loop {
        let next = {
            let state = app.state::<ChatState>();
            let mut sessions = match state.0.lock() {
                Ok(g) => g,
                Err(_) => return,
            };
            let Some(session) = sessions.get_mut(&session_id) else { return };
            match session.queue.pop_front() {
                Some(qt) => {
                    let model_override = session.models.get(&qt.agent).cloned();
                    Some((qt, session.workspace.clone(), model_override))
                }
                None => {
                    session.running = false;
                    None
                }
            }
        };

        let Some((turn, workspace, model_override)) = next else { break };
        run_one_turn(&app, &session_id, &workspace, &turn, model_override);
    });
}

fn run_one_turn(
    app: &AppHandle, session_id: &str, workspace: &str, turn: &QueuedTurn,
    model_override: Option<String>,
) {
    // Computed once up front (doesn't depend on root/workspace) so every
    // failure branch below -- not just the successful path -- can persist
    // with the correct mode.
    let mode_str = if turn.addressed_to.is_empty() { "broadcast" } else { "mention" };

    let root = match locate_repo_root() {
        Some(r) => r,
        None => {
            // No root means no Python to shell out to -- can't persist this
            // one, but it's an extremely rare environment failure, not a
            // realistic dispatch error.
            emit_turn_failure_no_root(app, session_id, &turn.turn_id, &turn.agent, "could not locate repo root");
            return;
        }
    };

    // 0. "corpus" is not a CLI agent -- no argv resolution, no spawn, no
    // Cloak shadow, no oracle recheck (see determinex_agent_chat.py's
    // answer_as_corpus/record_turn "corpus" speaker_kind). One quick,
    // synchronous Python round-trip, same shape as build-prompt/record-turn.
    if is_corpus_participant(&turn.agent) {
        let args = ["ask-corpus", session_id, "--workspace", workspace, "--turn-id", &turn.turn_id, "--mode", mode_str];
        match run_script_json_timeout(&root, CHAT_SCRIPT, &args, QUICK_TIMEOUT) {
            Ok(v) => {
                let _ = app.emit(
                    "agent-chat-turn-complete",
                    AgentChatTurnCompleteEvent {
                        session_id: session_id.to_string(),
                        turn_id: turn.turn_id.clone(),
                        agent: turn.agent.clone(),
                        verified: v.get("verified").and_then(|b| b.as_bool()).unwrap_or(true),
                        oracle: String::new(),
                        n_failures: 0,
                        note: v.get("note").and_then(|s| s.as_str()).unwrap_or("corpus response").to_string(),
                        error: None,
                    },
                );
            }
            Err(e) => emit_turn_failure(app, &root, session_id, workspace, mode_str, &turn.turn_id, &turn.agent, &format!("ask-corpus failed: {e}")),
        }
        let state = app.state::<ChatState>();
        emit_queue_update(app, session_id, &state);
        return;
    }

    // 1. Build this turn's prompt from the shared transcript.
    let prompt = match run_script_json(&root, CHAT_SCRIPT, &["build-prompt", session_id, &turn.agent]) {
        Ok(v) => v.get("prompt").and_then(|p| p.as_str()).unwrap_or("").to_string(),
        Err(e) => {
            emit_turn_failure(app, &root, session_id, workspace, mode_str, &turn.turn_id, &turn.agent, &format!("build-prompt failed: {e}"));
            return;
        }
    };

    // ANY LLM: an explicit per-session override (agent_chat_set_model) wins;
    // local-ollama otherwise falls back to the env-var default, cloud
    // agents otherwise get no --model flag at all (their own CLI default).
    let model = model_override.or_else(|| is_local_participant(&turn.agent).then(local_model_tag));

    // 2. Resolve the argv (single source of truth: determinex_agents.py).
    // The prompt goes in via --task-file, never as a raw positional -- a chat
    // turn's prompt embeds the Mission Plan (often the whole project's
    // CLAUDE.md) plus a windowed transcript, easily tens of thousands of
    // characters, which blew straight through Windows' command-line length
    // limit (os error 206 / ERROR_FILENAME_EXCED_RANGE) on every turn.
    let prompt_for_resolve = match write_temp_file("resolve-task", &prompt) {
        Ok(p) => p,
        Err(e) => {
            emit_turn_failure(app, &root, session_id, workspace, mode_str, &turn.turn_id, &turn.agent, &e);
            return;
        }
    };
    let prompt_for_resolve_str = prompt_for_resolve.to_string_lossy().to_string();
    let mut resolve_args: Vec<String> = vec![
        "resolve".to_string(),
        turn.agent.clone(),
        "--task-file".to_string(),
        prompt_for_resolve_str,
        "--workspace".to_string(),
        workspace.to_string(),
        // Every resolve from this module is a chat-room turn, so the conversational contract is
        // always the right one here. It matters for local-ollama: without it the local agent runs
        // under an edit-or-fail system prompt, and a plain answer comes back wrapped in
        // SEARCH/REPLACE syntax, is graded as a malformed patch, retried three times, and the turn
        // fails carrying the correct answer inside it. Measured live 2026-07-31 -- "What is the
        // capital of France?" produced "Paris" inside a `### FILE: msg.txt` block and rc=1.
        // Agents that declare no chat_flag (the cloud CLIs, which converse by default) are
        // unaffected; `run_agent()` outside chat keeps the strict editing contract.
        "--chat".to_string(),
    ];
    if let Some(m) = &model {
        resolve_args.push("--model".to_string());
        resolve_args.push(m.clone());
    }
    let resolve_args_ref: Vec<&str> = resolve_args.iter().map(String::as_str).collect();
    let resolved = run_script_json(&root, AGENTS_SCRIPT, &resolve_args_ref);
    let _ = std::fs::remove_file(&prompt_for_resolve);
    let resolved = match resolved {
        Ok(v) => v,
        Err(e) => {
            emit_turn_failure(app, &root, session_id, workspace, mode_str, &turn.turn_id, &turn.agent, &format!("resolve failed: {e}"));
            return;
        }
    };
    if let Some(err) = resolved.get("error").and_then(|e| e.as_str()) {
        emit_turn_failure(app, &root, session_id, workspace, mode_str, &turn.turn_id, &turn.agent, err);
        return;
    }
    let argv: Vec<String> = resolved
        .get("argv")
        .and_then(|a| a.as_array())
        .map(|arr| arr.iter().filter_map(|x| x.as_str().map(String::from)).collect())
        .unwrap_or_default();
    if argv.is_empty() {
        emit_turn_failure(app, &root, session_id, workspace, mode_str, &turn.turn_id, &turn.agent, "resolved argv was empty");
        return;
    }
    let installed = resolved.get("available").and_then(|a| a.as_bool()).unwrap_or(false);
    if !installed {
        let hint = resolved.get("install_hint").and_then(|h| h.as_str()).unwrap_or("");
        emit_turn_failure(
            app,
            &root,
            session_id,
            workspace,
            mode_str,
            &turn.turn_id,
            &turn.agent,
            &format!("agent '{}' is not installed ({hint})", turn.agent),
        );
        return;
    }

    // 2b. Project Cloak room: a cloud participant never runs against the real
    // workspace when Cloak is on -- prompt obfuscation alone doesn't stop an
    // agentic CLI from reading real files itself, so it gets pointed at a
    // fully obfuscated mirror instead (determinex_agent_chat.py's
    // prepare_cloaked_workspace). Fails CLOSED: if Cloak is requested but the
    // shadow workspace can't be built, the turn is refused, never silently
    // run against real data. local-ollama is exempt -- it never leaves the
    // machine and always sees the real workspace.
    let is_cloud = !is_local_participant(&turn.agent);
    let mut effective_workspace = workspace.to_string();
    let mut cloaked = false;
    if is_cloud && cloak_enabled() {
        match run_script_json(&root, CHAT_SCRIPT, &["cloak-prepare", session_id, "--workspace", workspace]) {
            Ok(v) if v.get("cloak_available").and_then(|b| b.as_bool()).unwrap_or(false) => {
                if let Some(shadow) = v.get("shadow_workspace").and_then(|s| s.as_str()) {
                    effective_workspace = shadow.to_string();
                    cloaked = true;
                }
            }
            Ok(_) => {
                emit_turn_failure(
                    app, &root, session_id, workspace, mode_str, &turn.turn_id, &turn.agent,
                    "Cloak is enabled but the privacy context could not be built -- refusing to \
                     run this cloud agent against the real workspace. See server logs.",
                );
                return;
            }
            Err(e) => {
                emit_turn_failure(app, &root, session_id, workspace, mode_str, &turn.turn_id, &turn.agent, &format!("cloak-prepare failed: {e}"));
                return;
            }
        }
    }

    // 3. Spawn, streaming stdout/stderr live via agent-chat-output.
    // stdin_prompt (claude-code/codex): the resolved argv deliberately has NO
    // embedded task text (see determinex_agents.py) -- the full prompt is
    // written to the child's stdin instead, right after spawn, so it never
    // touches the command line and can never trip os error 206 regardless of
    // Mission Plan + transcript size.
    let stdin_prompt = resolved.get("stdin_prompt").and_then(|b| b.as_bool()).unwrap_or(false);
    let mut cmd = Command::new(&argv[0]);
    cmd.hide_console();
    cmd.args(&argv[1..]);
    cmd.current_dir(&effective_workspace);
    if stdin_prompt {
        cmd.stdin(Stdio::piped());
    }
    if let Some(_m) = &model {
        cmd.env("OLLAMA_API_BASE", local_ollama_base_url());
    }
    // Passport credentials (GitHub/HuggingFace tokens the user explicitly
    // connected) -- injected as env vars on THIS subprocess only, never into
    // the built prompt or the chat transcript. Native CLI logins
    // (claude-code/codex/gemini-cli's own OAuth sessions) need nothing
    // injected -- those tools already read their own session files.
    {
        let db_state = app.state::<crate::db::DbState>();
        for (k, v) in crate::passport::env_credentials(&db_state) {
            cmd.env(k, v);
        }
    }
    cmd.stdout(Stdio::piped());
    cmd.stderr(Stdio::piped());

    let mut child = match cmd.spawn() {
        Ok(c) => c,
        Err(e) => {
            emit_turn_failure(app, &root, session_id, workspace, mode_str, &turn.turn_id, &turn.agent, &format!("failed to spawn agent CLI: {e}"));
            return;
        }
    };

    if stdin_prompt {
        // Written on its own thread, concurrently with the stdout/stderr
        // readers below -- a prompt this size can exceed the OS pipe buffer,
        // and writing it synchronously here (before those readers start
        // draining stdout/stderr) would deadlock against a CLI that starts
        // emitting output before it has finished reading stdin.
        if let Some(mut stdin) = child.stdin.take() {
            let prompt_bytes = prompt.clone().into_bytes();
            std::thread::spawn(move || {
                let _ = stdin.write_all(&prompt_bytes);
                // Dropping `stdin` here closes the pipe, sending EOF -- the
                // CLI is waiting for exactly that to know the prompt is complete.
            });
        }
    }

    let accumulated = Arc::new(Mutex::new(String::new()));
    let out_handle = spawn_stream_reader(
        app.clone(), session_id.to_string(), turn.turn_id.clone(), turn.agent.clone(),
        "stdout".to_string(), child.stdout.take(), accumulated.clone(),
    );
    let err_handle = spawn_stream_reader(
        app.clone(), session_id.to_string(), turn.turn_id.clone(), turn.agent.clone(),
        "stderr".to_string(), child.stderr.take(), accumulated.clone(),
    );

    let effective_timeout = if let Some(m) = &model {
        local_turn_timeout(&root, m)
    } else {
        TURN_TIMEOUT
    };
    let start = Instant::now();
    let mut timed_out = false;
    loop {
        match child.try_wait() {
            Ok(Some(_)) => break,
            Ok(None) => {
                if start.elapsed() > effective_timeout {
                    timed_out = true;
                    let _ = child.kill();
                    let _ = child.wait();
                    break;
                }
                std::thread::sleep(Duration::from_millis(150));
            }
            Err(_) => break,
        }
    }
    let returncode = child.try_wait().ok().flatten().and_then(|s| s.code()).unwrap_or(-1);
    let _ = out_handle.join();
    let _ = err_handle.join();

    let raw = accumulated.lock().map(|g| g.clone()).unwrap_or_default();
    let mut raw = if timed_out {
        format!("{raw}\n[determinex] turn killed after exceeding {}s timeout", effective_timeout.as_secs())
    } else {
        raw
    };

    // 3b. Cloak room round-trip: restore (de-obfuscate) this cloud agent's
    // shadow-workspace edits into the REAL workspace before anything gets
    // oracle-verified. A sync failure fails the whole turn closed (never
    // leave the real workspace out of sync with what was "verified") --
    // de-obfuscating the agent's own stdout for display is lower-stakes and
    // degrades gracefully (best-effort) since the actual file edits are
    // already safely restored by the time it runs.
    if cloaked {
        if let Err(e) = run_script_json(&root, CHAT_SCRIPT, &["cloak-sync", session_id, "--workspace", workspace]) {
            emit_turn_failure(app, &root, session_id, workspace, mode_str, &turn.turn_id, &turn.agent, &format!("cloak-sync failed: {e}"));
            return;
        }
        if let Ok(raw_in) = write_temp_file("cloak-raw", &raw) {
            let raw_in_str = raw_in.to_string_lossy().to_string();
            let restored = run_script_json(
                &root, CHAT_SCRIPT,
                &["restore-text", session_id, "--text-file", &raw_in_str, "--workspace", workspace],
            );
            let _ = std::fs::remove_file(&raw_in);
            if let Ok(v) = restored {
                if let Some(t) = v.get("text").and_then(|t| t.as_str()) {
                    raw = t.to_string();
                }
            }
        }
    }

    // 4. Oracle-verify + append to the transcript (record-turn).
    let raw_file = match write_temp_file("raw", &raw) {
        Ok(p) => p,
        Err(e) => {
            emit_turn_failure(app, &root, session_id, workspace, mode_str, &turn.turn_id, &turn.agent, &e);
            return;
        }
    };
    let prompt_file = match write_temp_file("prompt", &prompt) {
        Ok(p) => p,
        Err(e) => {
            let _ = std::fs::remove_file(&raw_file);
            emit_turn_failure(app, &root, session_id, workspace, mode_str, &turn.turn_id, &turn.agent, &e);
            return;
        }
    };
    let raw_file_str = raw_file.to_string_lossy().to_string();
    let prompt_file_str = prompt_file.to_string_lossy().to_string();
    let record_args = [
        "record-turn",
        session_id,
        &turn.agent,
        "--workspace",
        workspace,
        "--raw-file",
        &raw_file_str,
        "--returncode",
        &returncode.to_string(),
        "--turn-id",
        &turn.turn_id,
        "--task-prompt-file",
        &prompt_file_str,
        "--speaker-kind",
        "agent",
        "--mode",
        mode_str,
    ];
    let verdict = run_script_json_timeout(&root, AGENTS_SCRIPT, &record_args, ORACLE_VERIFY_TIMEOUT);
    let _ = std::fs::remove_file(&raw_file);
    let _ = std::fs::remove_file(&prompt_file);

    match verdict {
        Ok(v) => {
            let _ = app.emit(
                "agent-chat-turn-complete",
                AgentChatTurnCompleteEvent {
                    session_id: session_id.to_string(),
                    turn_id: turn.turn_id.clone(),
                    agent: turn.agent.clone(),
                    verified: v.get("verified").and_then(|b| b.as_bool()).unwrap_or(false),
                    oracle: v.get("oracle").and_then(|s| s.as_str()).unwrap_or("").to_string(),
                    n_failures: v.get("n_failures").and_then(|n| n.as_u64()).unwrap_or(0) as u32,
                    note: v.get("note").and_then(|s| s.as_str()).unwrap_or("").to_string(),
                    error: None,
                },
            );
        }
        Err(e) => emit_turn_failure(app, &root, session_id, workspace, mode_str, &turn.turn_id, &turn.agent, &format!("record-turn failed: {e}")),
    }

    let state = app.state::<ChatState>();
    emit_queue_update(app, session_id, &state);
}

/// Persists a turn that failed before or during dispatch (agent not
/// installed, bad argv, Cloak refused, spawn failed, record-turn itself
/// erroring, etc.) via `record-turn --dispatch-failed`, THEN emits the live
/// event. Previously this only emitted a live frontend event -- nothing was
/// ever written to the transcript, so a failed turn could vanish with zero
/// trace if no listener happened to be attached at that exact moment (and a
/// turn attempted while the panel was closed/backgrounded left no record at
/// all). `--dispatch-failed` skips determinex_agent_chat.py's usual oracle
/// recheck for agent turns -- the CLI never ran, so re-verifying the
/// workspace would just report its pre-existing state and could misleadingly
/// mark a failed dispatch as "verified".
fn emit_turn_failure(
    app: &AppHandle,
    root: &Path,
    session_id: &str,
    workspace: &str,
    mode: &str,
    turn_id: &str,
    agent: &str,
    error: &str,
) {
    if let Ok(err_file) = write_temp_file("err", error) {
        let err_file_str = err_file.to_string_lossy().to_string();
        let _ = run_script_json(
            root,
            AGENTS_SCRIPT,
            &[
                "record-turn",
                session_id,
                agent,
                "--workspace",
                workspace,
                "--raw-file",
                &err_file_str,
                "--returncode",
                "1",
                "--turn-id",
                turn_id,
                "--task-prompt-file",
                &err_file_str,
                "--speaker-kind",
                "agent",
                "--mode",
                mode,
                "--dispatch-failed",
            ],
        );
        let _ = std::fs::remove_file(&err_file);
    }

    let _ = app.emit(
        "agent-chat-turn-complete",
        AgentChatTurnCompleteEvent {
            session_id: session_id.to_string(),
            turn_id: turn_id.to_string(),
            agent: agent.to_string(),
            verified: false,
            oracle: String::new(),
            n_failures: 0,
            note: error.to_string(),
            error: Some(error.to_string()),
        },
    );
}

/// Used only when the repo root itself can't be located -- there's no Python
/// to shell out to, so this one case genuinely can't persist. Extremely rare
/// (environment misconfiguration), unlike every other failure branch above.
fn emit_turn_failure_no_root(app: &AppHandle, session_id: &str, turn_id: &str, agent: &str, error: &str) {
    let _ = app.emit(
        "agent-chat-turn-complete",
        AgentChatTurnCompleteEvent {
            session_id: session_id.to_string(),
            turn_id: turn_id.to_string(),
            agent: agent.to_string(),
            verified: false,
            oracle: String::new(),
            n_failures: 0,
            note: error.to_string(),
            error: Some(error.to_string()),
        },
    );
}

fn spawn_stream_reader(
    app: AppHandle,
    session_id: String,
    turn_id: String,
    agent: String,
    stream: String,
    pipe: Option<impl Read + Send + 'static>,
    accumulated: Arc<Mutex<String>>,
) -> std::thread::JoinHandle<()> {
    std::thread::spawn(move || {
        let Some(mut pipe) = pipe else { return };
        let mut buf = [0u8; 4096];
        loop {
            match pipe.read(&mut buf) {
                Ok(0) => break,
                Ok(n) => {
                    let chunk = String::from_utf8_lossy(&buf[..n]).to_string();
                    if let Ok(mut acc) = accumulated.lock() {
                        acc.push_str(&chunk);
                    }
                    let _ = app.emit(
                        "agent-chat-output",
                        AgentChatOutputEvent {
                            session_id: session_id.clone(),
                            turn_id: turn_id.clone(),
                            agent: agent.clone(),
                            stream: stream.clone(),
                            chunk,
                        },
                    );
                }
                Err(_) => break,
            }
        }
    })
}
