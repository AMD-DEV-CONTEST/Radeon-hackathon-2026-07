// Bridges scripts/determinex_agents.py -- the registry of external coding-agent
// CLIs (Claude Code, Codex, Gemini CLI, aider, cursor-agent) that Determinex can
// host as sub-agents. Listing is read-only (just `shutil.which` probes). Running
// one shells out to the real installed CLI against the given workspace, then
// verifies its edits through Determinex's own oracle (repair_workspace) before
// reporting success -- an agent's own claim of "done" is never trusted alone.
//
// Ryan, live: "i want this ide addon to be available (claude for vsc)... as well
// as codex and gemini and all of that." The Python registry already existed with
// zero frontend surface; this is the missing bridge + a real addon panel.

// Python is resolved through `ipc_hive::resolve_python_exe()`, never `Command::new("python")`.
//
// That resolver exists for a specific reason: on Windows, PATH `python` is very
// often the Microsoft Store AppExecLink stub, which does not run Python -- it opens
// the Store. It also prefers the repo venv, so the interpreter that has the
// project's dependencies is the one used. Ten call sites across six files bypassed
// it and used bare `python`, which worked only on machines where PATH happened to
// resolve to a real interpreter.

use serde::{Deserialize, Serialize};
use std::io::{Read, Write};
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};
use tauri::{AppHandle, Emitter};

use crate::project_audit::run_with_timeout;
use crate::win_process::HideConsoleExt;

const AGENTS_SCRIPT: &str = "scripts/determinex_agents.py";

// The Python side (determinex_agents.py) emits plain snake_case JSON --
// Python convention, not negotiable there. These structs are deserialized
// FROM that JSON first, then re-serialized TO the frontend as camelCase --
// asymmetric rename so each direction matches its own side's convention.
// A single `rename_all = "camelCase"` here made deserialization expect
// "installHint" from Python's actual "install_hint", failing every call
// with "malformed agent list JSON: missing field `installHint`" -- found
// live the first time this panel was opened.
#[derive(Debug, Serialize, Deserialize, Clone)]
#[serde(rename_all(serialize = "camelCase", deserialize = "snake_case"))]
pub struct CodingAgentInfo {
    pub name: String,
    pub probe: String,
    pub installed: bool,
    pub install_hint: String,
    pub aliases: Vec<String>,
    /// Whether this agent can be pointed at a specific model, and whether it has a distinct
    /// conversational mode. Both were hardcoded in the panel as a name list
    /// (`["claude-code","codex","gemini-cli"].includes(...)`), so aider got no model picker despite
    /// its own --help documenting `--model MODEL`, and any agent added later would get none either.
    /// Defaulted so an older Python side still deserializes rather than failing the whole list.
    #[serde(default)]
    pub supports_model: bool,
    #[serde(default)]
    pub supports_chat_mode: bool,
    /// Curated model shortlist for this CLI, in the fast/balanced/deep vocabulary. Empty means
    /// no shortlist, and the panel falls back to free text. These are the CLI's OWN model
    /// strings, not LiteLLM ids -- `gemini --model gemini/gemini-3-pro-preview` would fail.
    #[serde(default)]
    pub models: Vec<CodingAgentModel>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
#[serde(rename_all(serialize = "camelCase", deserialize = "snake_case"))]
pub struct CodingAgentModel {
    /// fast | balanced | deep — the same three words for every provider, so the user learns
    /// the vocabulary once and it transfers.
    pub tier: String,
    /// The exact string this agent's --model flag accepts.
    pub model: String,
    /// What to show a human. Never the raw model string alone.
    pub label: String,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
#[serde(rename_all(serialize = "camelCase", deserialize = "snake_case"))]
pub struct CodingAgentRunResult {
    pub agent: String,
    pub verified: bool,
    pub ran: bool,
    pub raw: String,
    pub oracle: String,
    pub n_failures: u32,
    pub note: String,
    pub next_moves: Vec<String>,
}

fn locate_repo_root() -> Option<PathBuf> {
    let cwd = std::env::current_dir().ok()?;
    let mut cur: Option<&std::path::Path> = Some(cwd.as_path());
    while let Some(c) = cur {
        if c.join(AGENTS_SCRIPT).is_file() {
            return Some(c.to_path_buf());
        }
        cur = c.parent();
    }
    None
}

#[tauri::command]
pub async fn list_coding_agents() -> Result<Vec<CodingAgentInfo>, String> {
    let root = locate_repo_root()
        .ok_or_else(|| format!("could not locate repo root ({AGENTS_SCRIPT} missing)"))?;

    // Bundled-first (see ipc_hive::helper_command): this used to build
    // `python <root>/scripts/<name>.py`, which does not exist in an installed copy.
    let (mut cmd, _bundled) = crate::ipc_hive::helper_command(AGENTS_SCRIPT)?;
    cmd.arg("list");
    cmd.arg("--json");
    cmd.current_dir(&root);

    let output = run_with_timeout(cmd, Duration::from_secs(15))
        .map_err(|e| format!("could not run agent registry: {e}"))?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(format!("agent registry exited non-zero: {stderr}"));
    }
    let stdout = String::from_utf8_lossy(&output.stdout);
    crate::python_json::parse_python_json(&stdout, "agent registry")
}

/// Runs a real, installed coding-agent CLI against the given workspace with the
/// given task, then verifies the result through Determinex's oracle -- same
/// trust model as every other execution path in this app: the agent's own
/// "done" is advisory, the compiler/test run is the source of truth. Bounded to
/// 5 minutes so a hung agent CLI can't block the UI indefinitely.
#[tauri::command]
pub async fn run_coding_agent(
    agent: String,
    task: String,
    workspace: String,
) -> Result<CodingAgentRunResult, String> {
    let root = locate_repo_root()
        .ok_or_else(|| format!("could not locate repo root ({AGENTS_SCRIPT} missing)"))?;

    // Bundled-first (see ipc_hive::helper_command): this used to build
    // `python <root>/scripts/<name>.py`, which does not exist in an installed copy.
    let (mut cmd, _bundled) = crate::ipc_hive::helper_command(AGENTS_SCRIPT)?;
    cmd.arg("run");
    cmd.arg(&agent);
    cmd.arg(&task);
    cmd.arg("--workspace");
    cmd.arg(&workspace);
    cmd.current_dir(&root);

    let output = run_with_timeout(cmd, Duration::from_secs(310))
        .map_err(|e| format!("could not run agent: {e}"))?;
    let stdout = String::from_utf8_lossy(&output.stdout);
    crate::python_json::parse_python_json(&stdout, "agent run").map_err(|e| {
        let stderr = String::from_utf8_lossy(&output.stderr);
        format!("{e} (stderr: {stderr})")
    })
}

// ── Roster status (Ryan: "I want to see everything who's online, what their
// credits are at") ───────────────────────────────────────────────────────
// Two tiers, deliberately kept separate:
//   1. Cheap status (below): each CLI's own auth-status subcommand
//      (claude/codex) or, for gemini-cli which ships no such command, a
//      local credential-file presence check. Free, fast, no model call --
//      safe to poll on an interval.
//   2. Live probe (agent_probe_test): a REAL minimal prompt, actually
//      spawned and streamed. This is the only way to learn things a status
//      file can't contain -- proven live: gemini-cli's stored OAuth creds
//      parse fine, but a real call surfaces "Your prepayment credits are
//      depleted." Manual-trigger only (costs real quota), never auto-polled.
#[derive(Debug, Serialize, Deserialize, Clone)]
#[serde(rename_all(serialize = "camelCase", deserialize = "snake_case"))]
pub struct AgentStatusEntry {
    pub name: String,
    pub installed: bool,
    pub auth_known: bool,
    /// The NARROW claim only: a credential is present and usable locally. It is not "this agent
    /// will answer me" -- see `readiness`, which is what the panel should show.
    pub logged_in: bool,
    pub plan: String,
    pub detail: String,
    pub install_hint: String,
    /// Named state rather than a boolean: not_installed | no_credentials | no_auth_method |
    /// credentials_unverified | verified | provider_refused | quota_exhausted | failed.
    /// Defaulted so an older Python side (or an evidence file captured before this existed)
    /// deserializes instead of failing the whole roster.
    #[serde(default)]
    pub readiness: String,
    #[serde(default)]
    pub readiness_evidence: String,
    #[serde(default)]
    pub last_probe_status: String,
    #[serde(default)]
    pub last_probe_at: String,
}

#[tauri::command]
pub async fn agent_status_roster() -> Result<Vec<AgentStatusEntry>, String> {
    let root = locate_repo_root()
        .ok_or_else(|| format!("could not locate repo root ({AGENTS_SCRIPT} missing)"))?;

    // Bundled-first (see ipc_hive::helper_command): this used to build
    // `python <root>/scripts/<name>.py`, which does not exist in an installed copy.
    let (mut cmd, _bundled) = crate::ipc_hive::helper_command(AGENTS_SCRIPT)?;
    cmd.arg("status");
    cmd.arg("--json");
    cmd.current_dir(&root);

    let output = run_with_timeout(cmd, Duration::from_secs(20))
        .map_err(|e| format!("could not run agent status: {e}"))?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(format!("agent status exited non-zero: {stderr}"));
    }
    let stdout = String::from_utf8_lossy(&output.stdout);
    crate::python_json::parse_python_json(&stdout, "agent status")
}

const PROBE_PROMPT: &str = "Reply with exactly the single word: OK";
const PROBE_TIMEOUT: Duration = Duration::from_secs(45);

#[derive(Debug, Serialize, Clone)]
#[serde(rename_all = "camelCase")]
struct AgentProbeOutputEvent {
    agent: String,
    stream: String,
    chunk: String,
}

#[derive(Debug, Serialize, Clone)]
#[serde(rename_all = "camelCase")]
struct AgentProbeCompleteEvent {
    agent: String,
    status: String, // "ok" | "quota_exhausted" | "auth_error" | "timeout" | "error"
    detail: String,
    raw_tail: String,
}

/// Deterministic pattern match over the CLI's own real output -- never an
/// LLM judgement (this repo's whole thesis: a compiler/parser is the
/// oracle, not a model's opinion). Only recognizes patterns actually
/// observed live from these three CLIs; unrecognized non-zero exits fall
/// through to a generic "error" with the last non-empty line as detail
/// rather than guessing a category.
fn classify_probe(raw: &str, returncode: Option<i32>, timed_out: bool) -> (&'static str, String) {
    let lower = raw.to_lowercase();
    if lower.contains("resource_exhausted")
        || lower.contains("credits are depleted")
        || lower.contains("prepayment")
        || (lower.contains("quota") && (lower.contains("exceed") || lower.contains("exhaust")))
    {
        let detail = raw
            .lines()
            .find(|l| l.to_lowercase().contains("message"))
            .unwrap_or("quota/billing exhausted")
            .trim()
            .to_string();
        return ("quota_exhausted", detail);
    }
    if lower.contains("429") && lower.contains("rate") {
        return ("quota_exhausted", "rate limited (429)".to_string());
    }
    // An eligibility refusal is neither a quota problem nor bad credentials: the credentials are
    // valid and the product has stopped accepting them. Measured 2026-07-31 against gemini-cli
    // 0.51.0 holding valid oauth-personal credentials -- `IneligibleTierError: This client is no
    // longer supported for Gemini Code Assist for individuals. To continue using Gemini, please
    // migrate to the Antigravity suite of products`. It fell through to the generic arm below,
    // whose detail is the LAST non-empty line of output: `at
    // process.processTicksAndRejections (node:internal/process/task_queues:103:5)`. A user reading
    // that learns nothing about needing an API key, which is the actual next step.
    // Its own status, not auth_error. This is the one state no local check can ever discover -- the
    // credential is valid, the login refreshes, and the PROVIDER declines the client -- and its
    // remedy (a different auth method entirely) resembles none of the others. Collapsing it into
    // auth_error told the user to go re-authenticate, which cannot work.
    if lower.contains("ineligibletiererror")
        || lower.contains("no longer supported for gemini code assist")
        || (lower.contains("ineligible") && lower.contains("tier"))
    {
        let detail = raw
            .lines()
            .find(|l| {
                let l = l.to_lowercase();
                l.contains("no longer supported") || l.contains("ineligibletiererror")
            })
            .unwrap_or("account tier is not eligible for this client -- set GEMINI_API_KEY")
            .trim()
            .to_string();
        return ("provider_refused", detail);
    }
    if lower.contains("please set an auth method") {
        return (
            "auth_error",
            "no auth method selected -- set security.auth.selectedType in ~/.gemini/settings.json \
             (oauth-personal) or set GEMINI_API_KEY"
                .to_string(),
        );
    }
    if lower.contains("not logged in")
        || lower.contains("unauthorized")
        || lower.contains("401")
        || lower.contains("invalid api key")
        || lower.contains("authentication_error")
    {
        let detail = raw
            .lines()
            .rev()
            .find(|l| !l.trim().is_empty())
            .unwrap_or("authentication error")
            .trim()
            .to_string();
        return ("auth_error", detail);
    }
    if timed_out {
        return (
            "timeout",
            format!("no terminal response within {}s", PROBE_TIMEOUT.as_secs()),
        );
    }
    if returncode == Some(0) {
        return ("ok", "responded".to_string());
    }
    if returncode.is_none() {
        // Still running, no recognized pattern yet -- not a verdict.
        return ("pending", String::new());
    }
    let detail = raw
        .lines()
        .rev()
        .find(|l| !l.trim().is_empty())
        .unwrap_or("unknown error")
        .trim()
        .to_string();
    ("error", detail)
}

fn spawn_probe_stream_reader(
    app: AppHandle,
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
                        "agent-probe-output",
                        AgentProbeOutputEvent { agent: agent.clone(), stream: stream.clone(), chunk },
                    );
                }
                Err(_) => break,
            }
        }
    })
}

/// Fires one real, minimal prompt at an installed agent CLI and streams the
/// genuine result live -- the only trustworthy way to know an agent is
/// actually WORKING right now (not just "has stored credentials"). Manual
/// trigger only: this is a real model call and, for a quota-exhausted
/// account, will genuinely fail -- which is the point.
#[tauri::command]
pub async fn agent_probe_test(agent: String, workspace: String, app: AppHandle) -> Result<(), String> {
    let root = locate_repo_root()
        .ok_or_else(|| format!("could not locate repo root ({AGENTS_SCRIPT} missing)"))?;

    // Same single-source-of-truth `resolve` subcommand the chat pipeline
    // uses, with a short diagnostic prompt standing in for a real task.
    // Bundled-first (see ipc_hive::helper_command): this used to build
    // `python <root>/scripts/<name>.py`, which does not exist in an installed copy.
    let (mut resolve_cmd, _bundled) = crate::ipc_hive::helper_command(AGENTS_SCRIPT)?;
    resolve_cmd.arg("resolve");
    resolve_cmd.arg(&agent);
    resolve_cmd.arg(PROBE_PROMPT);
    resolve_cmd.arg("--workspace");
    resolve_cmd.arg(&workspace);
    resolve_cmd.current_dir(&root);
    let resolve_out = run_with_timeout(resolve_cmd, Duration::from_secs(15))
        .map_err(|e| format!("could not resolve probe argv: {e}"))?;
    let resolved: serde_json::Value = serde_json::from_slice(&resolve_out.stdout)
        .map_err(|e| format!("malformed resolve JSON: {e}"))?;
    if let Some(err) = resolved.get("error").and_then(|e| e.as_str()) {
        return Err(err.to_string());
    }
    let argv: Vec<String> = resolved
        .get("argv")
        .and_then(|a| a.as_array())
        .map(|arr| arr.iter().filter_map(|x| x.as_str().map(String::from)).collect())
        .unwrap_or_default();
    if argv.is_empty() {
        return Err("resolved probe argv was empty".to_string());
    }
    let installed = resolved.get("available").and_then(|a| a.as_bool()).unwrap_or(false);
    if !installed {
        let hint = resolved.get("install_hint").and_then(|h| h.as_str()).unwrap_or("");
        return Err(format!("agent '{agent}' is not installed ({hint})"));
    }
    let stdin_prompt = resolved.get("stdin_prompt").and_then(|b| b.as_bool()).unwrap_or(false);

    let mut cmd = Command::new(&argv[0]);
    cmd.hide_console();
    cmd.args(&argv[1..]);
    cmd.current_dir(&workspace);
    if stdin_prompt {
        cmd.stdin(Stdio::piped());
    }
    cmd.stdout(Stdio::piped());
    cmd.stderr(Stdio::piped());

    let mut child = cmd.spawn().map_err(|e| format!("failed to spawn agent CLI: {e}"))?;

    if stdin_prompt {
        if let Some(mut stdin) = child.stdin.take() {
            std::thread::spawn(move || {
                let _ = stdin.write_all(PROBE_PROMPT.as_bytes());
            });
        }
    }

    let accumulated = Arc::new(Mutex::new(String::new()));
    let out_handle = spawn_probe_stream_reader(
        app.clone(), agent.clone(), "stdout".to_string(), child.stdout.take(), accumulated.clone(),
    );
    let err_handle = spawn_probe_stream_reader(
        app.clone(), agent.clone(), "stderr".to_string(), child.stderr.take(), accumulated.clone(),
    );

    let start = Instant::now();
    let mut timed_out = false;
    loop {
        // Early-exit the moment the accumulated text already contains a
        // recognizable FAILURE pattern -- gemini-cli's own 3x
        // exponential-backoff retry loop otherwise burns 60-90s per probe
        // even though attempt 1 already said everything (proven live:
        // "prepayment credits are depleted" on the first try). Success can
        // only be confirmed by a real clean exit, so this never fires early
        // on "ok".
        let early = accumulated.lock().ok().map(|acc| classify_probe(&acc, None, false).0 != "pending");
        if early == Some(true) {
            break;
        }
        match child.try_wait() {
            Ok(Some(_)) => break,
            Ok(None) => {
                if start.elapsed() > PROBE_TIMEOUT {
                    timed_out = true;
                    break;
                }
                std::thread::sleep(Duration::from_millis(150));
            }
            Err(_) => break,
        }
    }
    let _ = child.kill();
    let returncode = child.wait().ok().and_then(|s| s.code());
    let _ = out_handle.join();
    let _ = err_handle.join();

    let raw = accumulated.lock().map(|g| g.clone()).unwrap_or_default();
    let (status, detail) = classify_probe(&raw, returncode, timed_out);
    let status = if status == "pending" { "error" } else { status };
    // Char-based (not byte-index) slicing -- raw came from
    // String::from_utf8_lossy chunks, but an arbitrary byte offset can still
    // land mid-character and panic a direct &raw[n..] slice.
    let raw_tail: String = {
        let chars: Vec<char> = raw.chars().collect();
        let start = chars.len().saturating_sub(2000);
        chars[start..].iter().collect()
    };

    // Persist the verdict before emitting it. The event is live-only, so a probe's finding used to
    // vanish the moment the panel re-rendered and the roster went back to inferring readiness from a
    // credential file -- which is how "logged in" survived next to an agent the provider had cut
    // off. Recorded through the Python side rather than written here so there is one store and one
    // classifier: this function decides what happened, that file remembers it.
    record_probe_verdict(&agent, status, &detail);

    let _ = app.emit(
        "agent-probe-complete",
        AgentProbeCompleteEvent { agent, status: status.to_string(), detail, raw_tail },
    );
    Ok(())
}

const PROVIDERS_SCRIPT: &str = "scripts/determinex_providers.py";

/// The built-in AI provider roster: every provider Determinex can drive through its universal
/// `generate()` contract, whether its key is present, and which variable to set if not.
///
/// Added 2026-07-31. `determinex_providers.py` knew about seventeen providers and nothing could
/// list them, so none could be offered for a hive role or a chat participant's model -- registering
/// a provider changed nothing a user could see. Kimi/Moonshot, Vertex, xAI, Mistral, Together,
/// Cerebras, Fireworks and OpenRouter were added to that registry in the same pass; this command is
/// what makes them selectable rather than merely present.
///
/// Each row names its env var, because "unavailable" without "set MOONSHOT_API_KEY" is the same
/// unhelpful shape as a bare `logged_in: false`. No key is ever read or returned here -- only
/// whether one is set.
#[tauri::command]
pub async fn list_ai_providers() -> Result<serde_json::Value, String> {
    let root = locate_repo_root()
        .ok_or_else(|| format!("could not locate repo root ({AGENTS_SCRIPT} missing)"))?;
    let (mut cmd, _bundled) = crate::ipc_hive::helper_command(PROVIDERS_SCRIPT)?;
    cmd.arg("--json");
    cmd.current_dir(&root);

    let output = run_with_timeout(cmd, Duration::from_secs(30))
        .map_err(|e| format!("could not run provider registry: {e}"))?;
    if !output.status.success() {
        return Err(format!(
            "provider registry exited non-zero: {}",
            String::from_utf8_lossy(&output.stderr)
        ));
    }
    let stdout = String::from_utf8_lossy(&output.stdout);
    crate::python_json::parse_python_json(&stdout, "provider registry")
}

/// Best-effort: a roster that cannot remember the last probe is worse than one that cannot record
/// this one, so a failure here is logged and swallowed rather than failing the probe the user just
/// watched succeed.
fn record_probe_verdict(agent: &str, status: &str, detail: &str) {
    let Some(root) = locate_repo_root() else { return };
    let Ok((mut cmd, _bundled)) = crate::ipc_hive::helper_command(AGENTS_SCRIPT) else { return };
    cmd.arg("record-probe")
        .arg(agent)
        .arg("--status")
        .arg(status)
        .arg("--detail")
        .arg(detail)
        .current_dir(&root);
    match run_with_timeout(cmd, Duration::from_secs(15)) {
        Ok(out) if out.status.success() => {}
        Ok(out) => log::warn!(
            "record-probe for {agent} exited {:?}: {}",
            out.status.code(),
            String::from_utf8_lossy(&out.stderr)
        ),
        Err(e) => log::warn!("record-probe for {agent} could not run: {e}"),
    }
}

#[cfg(test)]
mod tests {
    //! Probe classification, guarded because its whole job is telling the user what to DO next.
    //!
    //! Added 2026-07-31 after running the three cloud agents through the real chat path.
    //! claude-code and codex answered. gemini-cli, holding valid credentials, refused twice -- first
    //! with "Please set an Auth method in your settings.json", then, once that was set, with
    //! `IneligibleTierError: This client is no longer supported for Gemini Code Assist for
    //! individuals`. Both fell through to the generic arm, whose detail is the last non-empty line
    //! of output: for the second that is `at process.processTicksAndRejections
    //! (node:internal/process/task_queues:103:5)`. Correct as a verdict, useless as guidance.
    use super::classify_probe;

    const INELIGIBLE: &str = "An unexpected critical error occurred:IneligibleTierError: This client \
is no longer supported for Gemini Code Assist for individuals. To continue using Gemini, please \
migrate to the Antigravity suite of products: https://antigravity.google
    at throwIneligibleOrProjectIdError (file:///C:/x/chunk.js:301064:11)
    at process.processTicksAndRejections (node:internal/process/task_queues:103:5)";

    #[test]
    fn an_ineligible_tier_gets_its_own_status_naming_the_cause() {
        // Its own status, not auth_error. The credential is valid and refreshes; the PROVIDER
        // declines the client, and the remedy is a different auth method entirely. Told
        // "auth_error", a user goes and re-authenticates, which cannot work.
        let (status, detail) = classify_probe(INELIGIBLE, Some(1), false);
        assert_eq!(status, "provider_refused");
        assert!(
            detail.contains("no longer supported"),
            "the detail must name the cause, got {detail:?}"
        );
        assert!(
            !detail.contains("processTicksAndRejections"),
            "a stack frame is not guidance, got {detail:?}"
        );
    }

    #[test]
    fn a_provider_refusal_is_not_confused_with_a_local_auth_failure() {
        // The two live one branch apart and have opposite remedies: one needs a different auth
        // method, the other needs the same one configured.
        assert_eq!(classify_probe(INELIGIBLE, Some(1), false).0, "provider_refused");
        assert_eq!(classify_probe("not logged in", Some(1), false).0, "auth_error");
    }

    #[test]
    fn a_missing_auth_method_says_how_to_set_one() {
        let raw = concat!(
            r"Please set an Auth method in your C:\Users\x\.gemini\settings.json or specify ",
            "one of the following environment variables before running: GEMINI_API_KEY, ",
            "GOOGLE_GENAI_USE_VERTEXAI, GOOGLE_GENAI_USE_GCA"
        );
        let (status, detail) = classify_probe(raw, Some(41), false);
        assert_eq!(status, "auth_error");
        assert!(detail.contains("settings.json"), "got {detail:?}");
        assert!(detail.contains("GEMINI_API_KEY"), "got {detail:?}");
    }

    #[test]
    fn an_eligibility_refusal_is_not_reported_as_a_quota_problem() {
        // Distinct remedies: a quota problem waits or pays, this one needs a different auth method.
        let (status, _) = classify_probe(INELIGIBLE, Some(1), false);
        assert_ne!(status, "quota_exhausted");
    }

    #[test]
    fn a_clean_run_is_ok() {
        assert_eq!(classify_probe("OK", Some(0), false).0, "ok");
    }

    #[test]
    fn quota_and_rate_limits_still_classify() {
        assert_eq!(classify_probe("RESOURCE_EXHAUSTED", Some(1), false).0, "quota_exhausted");
        assert_eq!(classify_probe("429 rate limit", Some(1), false).0, "quota_exhausted");
        assert_eq!(
            classify_probe("your credits are depleted", Some(1), false).0,
            "quota_exhausted"
        );
    }

    #[test]
    fn plain_auth_failures_still_classify() {
        assert_eq!(classify_probe("not logged in", Some(1), false).0, "auth_error");
        assert_eq!(classify_probe("401 Unauthorized", Some(1), false).0, "auth_error");
        assert_eq!(classify_probe("invalid api key", Some(1), false).0, "auth_error");
    }

    #[test]
    fn a_timeout_is_a_timeout() {
        assert_eq!(classify_probe("thinking...", None, true).0, "timeout");
    }

    #[test]
    fn a_still_running_probe_is_not_a_verdict() {
        assert_eq!(classify_probe("thinking...", None, false).0, "pending");
    }

    #[test]
    fn an_unrecognized_failure_still_reports_something() {
        let (status, detail) = classify_probe("boom\nsomething broke", Some(2), false);
        assert_eq!(status, "error");
        assert_eq!(detail, "something broke");
    }
}
