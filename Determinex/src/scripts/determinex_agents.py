#!/usr/bin/env python3
"""
determinex_agents.py -- the agent-CLI sub-agent registry (host any coding agent)
=============================================================================
A PROVIDER is a model: generate(prompt, temperature) -> str.
An AGENT is a whole tool that edits a workspace: Codex CLI, Claude Code, Gemini
CLI, aider, cursor-agent, .... This registry hosts them as SUB-AGENTS: hand one a
task + a workspace, let it do its thing, then -- the part nobody else does --
VERIFY its result through Determinex's oracle. An agent that hallucinates or breaks
the build is caught; only an oracle-passing result is accepted.

That is the whole thesis applied to agents: correctness is bounded by the oracle,
not by trusting the agent. So you can bolt on any agent (present or future) and it
cannot make Determinex wrong -- it can only succeed (verified) or be rejected (with
the failure surfaced to the Adjudicator).

    from determinex_agents import available_agents, run_agent
    res = run_agent("claude-code", task="make the tests pass", workspace=Path("repo/"))
    if res.verified:
        ...   # the agent's edits PASS the oracle

Bringing in a new agent is one register_agent(); it also works through the
extension protocol (a plugin's register(api)).

CLI
---
    python scripts/determinex_agents.py            # which agents are installed here
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# An agent runner: (task, workspace, timeout, model) -> (raw_output, returncode)
AgentRunner = Callable[[str, Path, int, "str | None"], "tuple[str, int]"]


@dataclass
class Agent:
    name: str
    probe: str  # CLI binary that must be on PATH
    install_hint: str
    runner: AgentRunner
    aliases: tuple[str, ...] = ()
    argv_template: list[str] | None = None  # stashed so resolve_argv() can
    # substitute without invoking the runner
    # True for CLIs confirmed (empirically, not by doc alone) to read their
    # entire prompt from stdin when launched with no embedded {task}/{task_file}
    # in argv -- claude/codex only, verified live 2026-07-21. The task text
    # then never appears in the spawned command line at all, so it can never
    # blow through Windows' ~32K argv length limit (os error 206,
    # ERROR_FILENAME_EXCED_RANGE) regardless of Mission Plan + transcript
    # size. gemini-cli's own docs claim the same stdin support but it hung
    # under two different real invocations in this same session -- left on
    # its existing {task}-embedded argv rather than ship an unverified fix
    # that trades a fast, visible crash for a silent, permanent hang.
    stdin_prompt: bool = False
    # For agents whose argv_template has no {model} token (claude-code,
    # codex, gemini-cli -- confirmed via --help each ships a real --model/-m
    # flag of its own). When a caller passes model=..., [model_flag, model]
    # is appended to the resolved argv. None for agents that either take no
    # model override (aider/cursor-agent) or already handle it via an
    # explicit {model} token in their template (local-ollama).
    model_flag: str | None = None
    # Flag that switches this agent into conversational mode for a chat-room turn. None means the
    # agent has no separate mode (the cloud CLIs converse by default). See determinex_local_agent's
    # --chat: without it the local participant runs under an edit-or-fail contract and cannot answer
    # a question without failing the turn.
    chat_flag: str | None = None
    # Up to three models worth offering for this CLI, as (tier, model, label). Ryan, 2026-08-03:
    # *"the multichat and the services need to have an easy way to figure out usage and changing
    # between their different models -- claude has three, google like 4, open ai a few."* The
    # chat panel used to render a FREE-TEXT BOX with a placeholder like "e.g. gemini-2.5-pro",
    # which is a memory test, not a choice.
    #
    # `model` is the exact string this CLI's own --model flag accepts, and it is deliberately
    # NOT `determinex_provider_setup.MODEL_CHOICES` -- those ids carry LiteLLM routing prefixes
    # (`gemini/gemini-3-pro-preview`), and feeding one to `gemini --model` would fail. Same
    # vocabulary, different values, and conflating them would break the picker for the one
    # vendor whose setup story is already the hardest.
    models: tuple[tuple[str, str, str], ...] = ()

    def available(self) -> bool:
        return shutil.which(self.probe) is not None


@dataclass
class AgentResult:
    agent: str
    verified: bool  # the oracle PASSED after the agent's edits
    ran: bool  # the agent CLI actually executed
    raw: str
    oracle: str = ""
    n_failures: int = 0
    note: str = ""
    next_moves: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Built-in agent runners. Each invokes the real CLI non-interactively against a
# workspace. Commands are best-effort, override per your installed version.
# ---------------------------------------------------------------------------
def build_argv(
    template: list[str],
    task: str,
    workspace: Path,
    model: str | None = None,
    model_flag: str | None = None,
) -> tuple[list[str], str | None]:
    """Substitute an argv template. THE single argv builder for every caller.

    Returns `(argv, task_file)`, where `task_file` is the temp file written for a
    `{task_file}` template or None. The caller owns deleting it, because who may
    delete it differs: `resolve_argv`'s consumer spawns the CLI from a separate,
    LATER process that still has to read the file, while `_cli_runner` runs the
    CLI itself and can clean up after it.

    WHY THIS IS ONE FUNCTION
    ------------------------
    Because it already was two, and they diverged. `_cli_runner` substituted only
    `{task}`/`{model}`; `resolve_argv` also handled `{task_file}`/`{workspace}`
    and dropped empty flag pairs. `local-ollama` is the one agent whose template
    uses `{task_file}`, so every Python-side `run_agent("local-ollama", ...)`
    spawned the CLI with the *literal* string `{task_file}` as a path and died
    with `FileNotFoundError: '{task_file}'` -- while the same agent worked from
    the IDE, because the Rust path goes through `resolve_argv`. Found live
    2026-07-28 by running the local agent on a deliberately-broken workspace.
    A second copy of substitution logic is how that happens; there is now one.
    """
    task_file: str | None = None
    if any("{task_file}" in t for t in template):
        fd, task_file = tempfile.mkstemp(prefix="determinex-agent-task-", suffix=".txt")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(task)
    argv = [
        t.replace("{task_file}", task_file or "")
        .replace("{task}", task)
        .replace("{model}", model or "")
        .replace("{workspace}", str(workspace))
        for t in template
    ]
    # A {model} token with no model selected substitutes to "" and would be
    # passed as an explicit `--model ""` -- which BEATS the receiving script's
    # own argparse default (a default only applies when the flag is absent, not
    # when it's present-but-empty). That made every local-ollama chat turn die
    # with `HTTP 404 ... is '' pulled? (ollama pull )` whenever the user hadn't
    # explicitly picked a model in the UI, which is the default state. Drop the
    # flag+value pair entirely instead, so the default takes effect.
    if not model:
        argv = _strip_empty_flag_pairs(argv)
    # ANY LLM: agents with no {model} token in their template (claude-code/
    # codex/gemini-cli) get an explicit [model_flag, model] appended instead --
    # each ships a real --model/-m flag of its own.
    if model and model_flag and "{model}" not in " ".join(template):
        argv += [model_flag, model]
    # shutil.which resolves Windows' .cmd/.ps1 shims (PATHEXT) -- a bare name
    # like "gemini" or "codex" is a POSIX shell script / .cmd wrapper on this
    # platform (npm global installs), not a native .exe. Neither Rust's
    # std::process::Command::new nor a shell=False subprocess.run tries PATHEXT
    # extensions the way a real shell does, so BOTH spawn paths failed with
    # "program not found" for every codex/gemini-cli turn. Only argv[0] needs
    # this; the rest of argv is real argument text.
    if argv:
        argv[0] = shutil.which(argv[0]) or argv[0]
    return argv, task_file


def _cli_runner(
    argv_template: list[str], stdin_prompt: bool = False, model_flag: str | None = None
) -> AgentRunner:
    def _run(task: str, workspace: Path, timeout: int, model: str | None = None) -> tuple[str, int]:
        argv, task_file = build_argv(argv_template, task, Path(workspace), model, model_flag)
        # Load the repo .env into os.environ so the spawned CLI inherits the
        # credentials the project is already configured with. Without this,
        # gemini-cli died with "Please set an Auth method ... GEMINI_API_KEY"
        # while GEMINI_API_KEY was sitting in .env the whole time -- it only
        # worked when launched from a shell that happened to have it exported,
        # which is the definition of a tether. Found live 2026-07-28.
        #
        # The canonical loader, not a fourth copy of dotenv parsing, and it never
        # overwrites an already-set variable -- so the Tauri path's Passport
        # credentials (injected per-spawn in agent_chat.rs) still win, and in a
        # packaged app with no .env this is a no-op.
        try:
            import determinex_providers

            determinex_providers._load_env_once()
        except Exception:
            pass  # missing/unreadable .env must not stop an agent from running
        try:
            # input="" for non-stdin_prompt agents, NOT None. None inherits the
            # parent's stdin, so a CLI that stops to ask something blocks until
            # the timeout with no output at all -- aider burned the full 420s
            # that way (2026-07-28), looking like a hang rather than a prompt.
            # An empty, closed stdin gives it EOF, turning a silent stall into a
            # fast visible failure. Same reasoning as mechanism #1 of
            # determinex_subprocess_guard (stdin -> DEVNULL), which was built for
            # exactly this failure mode on the PB eval path.
            r = subprocess.run(
                argv,
                cwd=str(workspace),
                capture_output=True,
                text=True,
                timeout=timeout,
                input=task if stdin_prompt else "",
            )
            return (r.stdout + r.stderr), r.returncode
        except Exception as e:
            return f"agent run error: {e}", 1
        finally:
            # Safe to delete here (unlike in resolve_argv): this process ran the
            # CLI itself, so the file has already been read.
            if task_file:
                try:
                    os.unlink(task_file)
                except OSError:
                    pass

    return _run


_AGENTS: dict[str, Agent] = {}


def register_agent(
    name: str,
    *,
    probe: str,
    install_hint: str = "",
    runner: AgentRunner | None = None,
    argv_template: list[str] | None = None,
    aliases: tuple[str, ...] = (),
    stdin_prompt: bool = False,
    model_flag: str | None = None,
    chat_flag: str | None = None,
    models: tuple[tuple[str, str, str], ...] = (),
) -> None:
    """Host a coding agent. Provide a runner, or an argv_template using {task}."""
    resolved_template = argv_template or [probe, "{task}"]
    if runner is None:
        runner = _cli_runner(resolved_template, stdin_prompt=stdin_prompt, model_flag=model_flag)
    a = Agent(
        name=name,
        probe=probe,
        install_hint=install_hint,
        runner=runner,
        aliases=aliases,
        argv_template=resolved_template,
        stdin_prompt=stdin_prompt,
        model_flag=model_flag,
        chat_flag=chat_flag,
        models=models,
    )
    for k in (name, *aliases):
        _AGENTS[k.lower()] = a


# Built-ins (non-interactive invocations; adjust flags to your installed CLI).
# claude/codex: NO {task} embedded in argv -- confirmed live 2026-07-21 that
# both read their whole prompt from stdin when launched this way (`claude -p`
# with no positional prompt arg; `codex exec` with no positional PROMPT --
# its own --help says so explicitly). This is what keeps a chat-room turn's
# Mission-Plan-plus-transcript prompt (often tens of thousands of chars) out
# of the actual command line, so it can never trip os error 206
# (ERROR_FILENAME_EXCED_RANGE) on Windows regardless of size.
# --permission-mode acceptEdits: `claude -p` reasons correctly and then stops at
# "The edit is queued but needs your approval" -- found live 2026-07-28. In a
# spawned, non-interactive process there is nobody to approve, so the turn always
# ended with the fix described and the file untouched. acceptEdits auto-accepts
# FILE EDITS while leaving other tools gated, which is the same bounded position
# as codex's --sandbox workspace-write below.
#
# NOT used, deliberately: `bypassPermissions` / --dangerously-skip-permissions,
# which disable every check including arbitrary shell execution. The security
# carve-out in CLAUDE.md forbids that for model-generated code.
register_agent(
    "claude-code",
    probe="claude",
    install_hint="npm i -g @anthropic-ai/claude-code",
    argv_template=["claude", "-p", "--permission-mode", "acceptEdits"],
    aliases=("claude",),
    stdin_prompt=True,
    model_flag="--model",
    models=(
        ("fast", "haiku", "Haiku — quickest and cheapest"),
        ("balanced", "sonnet", "Sonnet — the everyday choice"),
        ("deep", "opus", "Opus — slowest, for the hard one"),
    ),
)
# --skip-git-repo-check: `codex exec` refuses to run in a directory that isn't a
# git repo ("Not inside a trusted directory and --skip-git-repo-check was not
# specified") -- found live 2026-07-28, every codex turn against a non-repo
# workspace died there. Same shape as gemini-cli's --skip-trust below, and the
# flag is confirmed present in `codex exec --help`, not assumed.
#
# Be clear about what this trades: codex's check exists so its edits are always
# revertable via git. Skipping it means edits to a non-repo workspace are not.
# Accepted because the workspace is one the user explicitly chose, and because
# Determinex never trusts an agent's edits either way -- every turn is
# oracle-verified afterwards, which is this file's whole thesis.
#
# --sandbox workspace-write: `codex exec` defaults to a READ-ONLY sandbox with
# approvals disabled, so it reasoned correctly and then reported "I couldn't edit
# add.py because the workspace is mounted read-only" -- a coding agent that
# cannot write is not a coding agent. Of the three possible values
# (read-only / workspace-write / danger-full-access) workspace-write is the one
# that matches the security carve-out's own standard: writes confined to the
# workspace, exactly the bound `intake.hardened_runner` enforces.
#
# NOT added, deliberately: `danger-full-access` and
# `--dangerously-bypass-approvals-and-sandbox`. Both let model-generated shell
# commands run unsandboxed against the whole machine, which CLAUDE.md forbids
# outright. The two flags here relax repo detection and widen writes to the
# workspace only; neither removes the sandbox.
register_agent(
    "codex",
    probe="codex",
    install_hint="npm i -g @openai/codex",
    argv_template=["codex", "exec", "--skip-git-repo-check", "--sandbox", "workspace-write"],
    aliases=("openai-codex",),
    stdin_prompt=True,
    model_flag="--model",
    models=(
        ("fast", "gpt-5.5-mini", "Mini — quickest and cheapest"),
        ("balanced", "gpt-5.5", "Standard — the everyday choice"),
        ("deep", "gpt-5.5-pro", "Pro — slowest, for the hard one"),
    ),
)
# --skip-trust: gemini-cli refuses to run non-interactively in a directory it
# hasn't been trusted in (its own workspace-trust prompt, which nothing in a
# spawned/piped context could ever answer) -- found live 2026-07-22, every
# gemini-cli chat turn failed with "Gemini CLI is not running in a trusted
# directory" the moment the separate PATHEXT spawn bug (above) stopped
# masking it. Safe here specifically because Determinex never trusts an
# agent's edits directly either way -- every turn is oracle-verified after
# the fact (this file's whole thesis), so skipping the CLI's own redundant
# interactive gate doesn't weaken that.
register_agent(
    "gemini-cli",
    probe="gemini",
    install_hint="npm i -g @google/gemini-cli",
    argv_template=["gemini", "-p", "{task}", "--skip-trust"],
    aliases=("gemini",),
    model_flag="--model",
    models=(
        ("fast", "gemini-3-flash-preview", "Flash — quickest and cheapest"),
        ("balanced", "gemini-flash-latest", "Flash latest — the everyday choice"),
        ("deep", "gemini-3-pro-preview", "Pro — slowest, for the hard one"),
    ),
)
register_agent(
    "aider",
    probe="aider",
    install_hint="pip install aider-chat",
    # model_flag added 2026-07-31. aider's own --help documents `--model MODEL` ("Specify
    # the model to use for the main chat"), and without this the registry reported
    # supports_model=False, so the panel offered no model picker for it and every aider
    # turn ran on whatever its config defaulted to. It is the most model-agnostic CLI in
    # the roster -- it will drive any provider aider itself supports -- so leaving it
    # unassignable was the opposite of the intent.
    model_flag="--model",
    argv_template=["aider", "--message", "{task}", "--yes"],
)
register_agent(
    "cursor-agent",
    probe="cursor-agent",
    install_hint="cursor agent CLI",
    argv_template=["cursor-agent", "{task}"],
)
# The local-model participant for the multi-agent chat room. Originally rode
# on aider's --model flag, but aider isn't installed here and this
# environment's auto-mode classifier hard-blocks pip installs -- "ollama is
# on the system though... so fix it." determinex_local_agent.py drives
# Ollama directly (HTTP, via swe_agent.inference._ollama -- already proven by
# the SWE-bench harness) with a SEARCH/REPLACE edit loop, needing nothing
# beyond what's already here: Python + a running Ollama. probe="ollama" (not
# "python", which is trivially always present) so `available()` actually
# reflects whether local inference is realistically usable on this machine.
register_agent(
    "local-ollama",
    probe="ollama",
    install_hint="install Ollama (https://ollama.com) and pull a model, e.g. "
    "`ollama pull qwen2.5-coder:14b-instruct-q4_K_M`",
    # {task_file}, not {task} -- a chat-room turn's prompt embeds the
    # Mission Plan (often the whole project's CLAUDE.md) plus a
    # windowed transcript, easily tens of thousands of characters.
    # Passed as a raw positional CLI argument this blew straight
    # through Windows' command-line length limit (os error 206,
    # ERROR_FILENAME_EXCED_RANGE) on every single turn. resolve_argv()
    # below writes the task to a temp file and substitutes its path
    # here instead, keeping the actual spawned command line short
    # regardless of prompt size.
    # sys.executable, not a bare "python": on Windows a bare `python`
    # resolves through PATH to the Store's AppExecLink stub on many
    # boxes (which exits without running anything), and even when it
    # does resolve it need not be the interpreter that has this repo's
    # dependencies. sys.executable is by definition the one already
    # running this module. Same tether class as the bare-`python`
    # spawns fixed on the Rust side, which is why resolve_python_exe()
    # exists there.
    argv_template=[
        sys.executable or "python",
        str(Path(__file__).resolve().parent / "determinex_local_agent.py"),
        "--task-file",
        "{task_file}",
        "--workspace",
        "{workspace}",
        "--model",
        "{model}",
    ],
    # Appended only when the caller says this is a chat turn. Without it the local agent
    # runs under an edit-or-fail system prompt, so a conversational reply comes back
    # wrapped in SEARCH/REPLACE syntax, is graded as a malformed patch, retried three
    # times and returned rc=1 -- with the correct answer inside the failure. Declared
    # here rather than hardcoded at the call site so a future local agent can opt in the
    # same way, and so `run_agent()` (non-chat) keeps the strict editing contract.
    chat_flag="--chat",
    aliases=("aider-local", "ollama"),
)


def available_agents() -> dict[str, bool]:
    out = {}
    for a in _AGENTS.values():
        out[a.name] = a.available()
    return dict(sorted(out.items()))


# ---------------------------------------------------------------------------
# Cheap auth status -- one fast, free, no-model-call round-trip per agent.
# Deliberately NOT an LLM judgement: each CLI already ships (or, for
# gemini-cli, implies via its on-disk OAuth store) a deterministic answer to
# "am I logged in", so that's what gets parsed. This is the roster's passive
# signal -- whether the agent is actually WORKING right now (rate limits,
# depleted billing) can only be known by really calling it, which is what the
# separate `probe` argv (a real minimal prompt, spawned+classified on the
# Rust side) is for. Ryan: "I want to see all of the working, not sit there
# and believe it errored out" -- so this stays honest about what it does and
# doesn't verify (gemini-cli's case: stored credentials present is NOT the
# same claim as "currently authenticated", and is labeled as such).
# ---------------------------------------------------------------------------
# ── Readiness: four different facts that used to be one boolean ─────────────────────────────────
#
# `logged_in` answered "is there a credential on disk", and the panel read it as "this agent will
# answer me". Those come apart in more ways than one, and 2026-07-31 produced three of them in a
# single afternoon on one machine:
#
#   claude-code   credential present, provider honours it, answered in 5.4s
#   gemini-cli    credential present, no auth method selected -> refused locally, no network call
#   gemini-cli    credential present AND method selected, and the PROVIDER refused the client:
#                 "IneligibleTierError: This client is no longer supported for Gemini Code Assist
#                 for individuals" -- the login is valid, the product access is revoked
#
# One boolean cannot carry that, and the third case is the one that matters most, because it is the
# one no local check can ever discover and the one whose remedy (a different auth method entirely)
# looks nothing like the others. So readiness is a named state, and the states that require a real
# call are only ever set BY a real call -- never inferred, never optimistic.
READY_NOT_INSTALLED = "not_installed"
READY_NO_CREDENTIALS = "no_credentials"
READY_NO_AUTH_METHOD = "no_auth_method"
READY_CREDENTIALS_UNVERIFIED = "credentials_unverified"
READY_VERIFIED = "verified"
READY_PROVIDER_REFUSED = "provider_refused"
READY_QUOTA_EXHAUSTED = "quota_exhausted"
READY_FAILED = "failed"

# Verdicts that only a live probe can reach, mapped from the Rust classifier's status strings.
# Anything not listed stays out of readiness rather than being guessed at.
_PROBE_READINESS = {
    "ok": READY_VERIFIED,
    "provider_refused": READY_PROVIDER_REFUSED,
    "quota_exhausted": READY_QUOTA_EXHAUSTED,
    "auth_error": READY_FAILED,
    "timeout": READY_FAILED,
    "error": READY_FAILED,
}

_PROBE_STORE = Path(".determinex") / "agent_probe_results.json"


def _probe_store_path() -> Path:
    return Path(__file__).resolve().parent.parent / _PROBE_STORE


def last_probe_result(agent: str) -> dict:
    """The last live-probe verdict for one agent, or {}.

    Read-only and forgiving: a missing or corrupt store means "never probed", which is the honest
    answer and leaves readiness at credentials_unverified rather than failing the roster.
    """
    path = _probe_store_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    entry = data.get(agent) if isinstance(data, dict) else None
    return entry if isinstance(entry, dict) else {}


def record_probe_result(agent: str, status: str, detail: str = "", at: str = "") -> dict:
    """Persist one live-probe verdict so the roster can show it instead of guessing.

    Written by the live probe (agent_registry.rs) through the `record-probe` subcommand rather than
    classified again here -- the classifier lives in exactly one place, or the two copies drift and
    the panel starts disagreeing with the thing that ran the test.
    """
    path = _probe_store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        if not isinstance(data, dict):
            data = {}
    except (OSError, json.JSONDecodeError):
        data = {}
    entry = {
        "status": status,
        "detail": detail,
        "at": at or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    data[agent] = entry
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.flush()
        os.fsync(fh.fileno())
    tmp.replace(path)
    return entry


def _readiness(row: dict, agent: str) -> tuple[str, str]:
    """-> (readiness, evidence) for one roster row.

    A stored probe verdict OUTRANKS the local checks, in both directions. If the provider refused
    the client, "credentials are present" is not the useful thing to say; and if a real call
    succeeded, that outranks any amount of file-sniffing. The local checks only decide the states
    that are knowable locally.
    """
    if not row.get("installed"):
        return READY_NOT_INSTALLED, "the CLI is not on PATH"

    probe = last_probe_result(agent)
    mapped = _PROBE_READINESS.get(str(probe.get("status") or ""))
    if mapped in (READY_PROVIDER_REFUSED, READY_QUOTA_EXHAUSTED):
        # Provider-side states persist until something changes on the provider's side, so they are
        # reported even when the local credential checks look perfect -- which is exactly the
        # gemini-cli case, where they do look perfect.
        return (
            mapped,
            f"live probe {probe.get('at', '?')}: {probe.get('detail') or probe['status']}",
        )

    detail = str(row.get("detail") or "")
    if not row.get("logged_in"):
        if "no auth method" in detail:
            return READY_NO_AUTH_METHOD, detail
        return READY_NO_CREDENTIALS, detail or "no credentials found"

    if mapped == READY_VERIFIED:
        return (
            READY_VERIFIED,
            f"live probe {probe.get('at', '?')}: {probe.get('detail') or 'responded'}",
        )
    if mapped == READY_FAILED:
        return (
            READY_FAILED,
            f"live probe {probe.get('at', '?')}: {probe.get('detail') or probe['status']}",
        )

    return READY_CREDENTIALS_UNVERIFIED, (
        detail or "credentials look usable; no live call has confirmed the provider accepts them"
    )


_GEMINI_AUTH_ENV = ("GEMINI_API_KEY", "GOOGLE_GENAI_USE_VERTEXAI", "GOOGLE_GENAI_USE_GCA")


def _gemini_auth_state() -> tuple[bool, str, str]:
    """-> (credentials_or_key_present, selected_auth_method, human detail)

    gemini-cli needs BOTH a credential source and a selected auth method; with credentials alone it
    exits immediately with "Please set an Auth method in your settings.json or specify one of the
    following environment variables". Checking only the credential file therefore reported an agent
    as logged in when it could not answer a single message -- found by running it, 2026-07-31.

    An env var counts as both halves: it names the method AND carries the credential.
    """
    for name in _GEMINI_AUTH_ENV:
        if os.environ.get(name, "").strip():
            return True, name, f"{name} set in the environment"

    home = Path.home() / ".gemini"
    creds = home / "oauth_creds.json"
    creds_ok = creds.is_file() and creds.stat().st_size > 0

    method = ""
    settings = home / "settings.json"
    if settings.is_file():
        try:
            data = json.loads(settings.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        if isinstance(data, dict):
            # 0.51 reads security.auth.selectedType; selectedAuthType is the legacy key it still
            # migrates from. Accept either rather than pinning one and going stale on an upgrade.
            nested = (data.get("security") or {}).get("auth") or {}
            method = str(nested.get("selectedType") or data.get("selectedAuthType") or "")

    if not creds_ok:
        return False, method, "no stored credentials -- run `gemini` once and sign in"
    if not method:
        return (
            False,
            "",
            (
                "credentials found but no auth method selected -- gemini-cli will refuse before it "
                "calls anything. Set security.auth.selectedType in ~/.gemini/settings.json "
                "(oauth-personal) or set GEMINI_API_KEY"
            ),
        )
    return (
        True,
        method,
        f"auth method {method!r}, stored credentials found (not live-verified -- use Test)",
    )


def _cheap_status(a: Agent) -> dict:
    out = {
        "name": a.name,
        "installed": a.available(),
        "auth_known": False,
        "logged_in": False,
        "plan": "",
        "detail": "",
    }
    if not out["installed"]:
        return out
    try:
        # shutil.which (not a bare probe name) -- Python's subprocess.run
        # without shell=True skips Windows' PATHEXT resolution that a real
        # shell (or Rust's std::process::Command) applies automatically, so
        # "codex" alone fails to resolve the npm-installed codex.cmd shim
        # (found live: WinError 2, "cannot find the file specified", even
        # though `codex` runs fine from any actual shell).
        exe = shutil.which(a.probe) or a.probe
        if a.name == "claude-code":
            r = subprocess.run([exe, "auth", "status"], capture_output=True, text=True, timeout=10)
            if r.stdout.strip():
                import json as _json

                d = _json.loads(r.stdout)
                out["auth_known"] = True
                out["logged_in"] = bool(d.get("loggedIn"))
                out["plan"] = d.get("subscriptionType") or d.get("apiProvider") or ""
                out["detail"] = d.get("email", "")
        elif a.name == "codex":
            r = subprocess.run([exe, "login", "status"], capture_output=True, text=True, timeout=10)
            text = (r.stdout + r.stderr).strip()
            out["auth_known"] = True
            out["logged_in"] = r.returncode == 0 and "not logged in" not in text.lower()
            out["detail"] = text
            out["plan"] = (
                "ChatGPT"
                if "chatgpt" in text.lower()
                else ("API key" if "api key" in text.lower() else "")
            )
        elif a.name == "gemini-cli":
            # Stored credentials are NOT the same as a usable agent, and reporting them as
            # `logged_in: true` was an overclaim the panel keyed on. Measured 2026-07-31: with
            # oauth_creds.json present and this status reporting "logged in / Google account", a real
            # turn failed instantly -- `Please set an Auth method in your settings.json`. The CLI
            # refuses before any network call when no auth method is selected, which makes that
            # deterministically knowable here rather than something only a live probe can find.
            out["auth_known"] = True
            creds_ok, method, detail = _gemini_auth_state()
            out["logged_in"] = creds_ok and bool(method)
            out["plan"] = "Google account" if out["logged_in"] else ""
            out["detail"] = detail
        elif a.name == "local-ollama":
            import urllib.request

            try:
                urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2)
                out["auth_known"] = True
                out["logged_in"] = True
                out["plan"] = "local"
                out["detail"] = "Ollama daemon reachable"
            except Exception:
                out["auth_known"] = True
                out["logged_in"] = False
                out["detail"] = "Ollama daemon not reachable"
    except Exception as e:
        out["detail"] = f"status check error: {e}"
    return out


def _agents_status_json() -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for a in _AGENTS.values():
        if a.name in seen:
            continue
        seen.add(a.name)
        s = _cheap_status(a)
        s["install_hint"] = a.install_hint
        # A named state instead of a boolean the panel has to interpret. `logged_in` is kept for
        # the existing callers, but it is the narrow claim ("a credential is present and usable
        # locally"), never the broad one the UI was reading it as.
        s["readiness"], s["readiness_evidence"] = _readiness(s, a.name)
        probe = last_probe_result(a.name)
        s["last_probe_status"] = str(probe.get("status") or "")
        s["last_probe_at"] = str(probe.get("at") or "")
        out.append(s)
    out.sort(key=lambda d: d["name"])
    return out


# The diagnostic prompt the Rust side sends via `resolve` for a REAL live
# probe (a genuine model call, not a status file read) -- short and cheap,
# but enough to surface auth failures and quota/billing exhaustion in the
# CLI's own real error output (proven live 2026-07-22: gemini-cli's stored
# OAuth creds parse fine, but a real call surfaces
# "Your prepayment credits are depleted" -- a fact no status file contains).
DIAGNOSTIC_PROMPT = "Reply with exactly the single word: OK"


def run_agent(
    name: str,
    task: str,
    workspace: Path,
    *,
    timeout: int = 300,
    verify: bool = True,
    model: str | None = None,
) -> AgentResult:
    """Run an agent on a workspace, then VERIFY the result through the oracle."""
    a = _AGENTS.get(name.lower())
    if a is None:
        return AgentResult(name, False, False, "", note=f"unknown agent '{name}'")
    if not a.available():
        return AgentResult(
            name, False, False, "", note=f"agent '{name}' not installed ({a.install_hint})"
        )
    raw, rc = a.runner(task, Path(workspace), timeout, model)
    if not verify:
        return AgentResult(name, rc == 0, True, raw, note="not oracle-verified")
    # The differentiator: judge the agent's edits with Determinex's oracle.
    try:
        import determinex_repair as _r

        diag = _r.repair_workspace(Path(workspace))  # runs the workspace oracle
        verified = diag.healthy
        return AgentResult(
            name,
            verified,
            True,
            raw,
            oracle=diag.oracle,
            n_failures=diag.n_failures,
            note=(
                "oracle PASSES after agent edits"
                if verified
                else "oracle still failing after agent edits"
            ),
            next_moves=[s for s in diag.verdicts],
        )
    except Exception as e:
        return AgentResult(name, rc == 0, True, raw, note=f"verify error: {e}")


def _strip_empty_flag_pairs(argv: list[str]) -> list[str]:
    """Remove every `--flag ""` pair from a resolved argv.

    Passing a flag with an empty value is NOT the same as omitting it: the
    receiving argparse sees the flag as present and stores "", overriding
    whatever default that script declared. Templates substitute unset
    placeholders to "", so those pairs have to be dropped rather than passed.
    """
    out: list[str] = []
    i = 0
    while i < len(argv):
        if argv[i].startswith("--") and i + 1 < len(argv) and argv[i + 1] == "":
            i += 2  # skip both the flag and its empty value
            continue
        out.append(argv[i])
        i += 1
    return out


def resolve_argv(
    name: str, task: str, workspace: Path, *, model: str | None = None, chat: bool = False
) -> list[str]:
    """Return the exact argv this agent would run, without running it -- the
    contract the Rust chat backend relies on to spawn+stream the CLI itself
    instead of shelling through a blocking Python subprocess.run().

    `chat=True` appends the agent's `chat_flag` when it declares one, which is how the chat room
    tells the local agent that this is a conversational turn rather than an editing task.
    """
    a = _AGENTS.get(name.lower())
    if a is None:
        raise KeyError(f"unknown agent '{name}'")
    template = a.argv_template or [a.probe, "{task}"]
    # The temp {task_file} is deliberately NOT deleted here: the caller (the Rust
    # chat backend) spawns the CLI in a separate, later process which still has
    # to read it. It lands in the OS temp dir, so it gets collected eventually.
    argv, _task_file = build_argv(template, task, Path(workspace), model, a.model_flag)
    if chat and a.chat_flag and a.chat_flag not in argv:
        argv.append(a.chat_flag)
    return argv


def _agents_json() -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for a in _AGENTS.values():
        if a.name in seen:
            continue
        seen.add(a.name)
        out.append(
            {
                "name": a.name,
                "probe": a.probe,
                "installed": a.available(),
                "install_hint": a.install_hint,
                "aliases": list(a.aliases),
                # Whether this agent can be pointed at a specific model, and whether it has a
                # conversational mode. Both were hardcoded in the UI as
                # `["claude-code", "codex", "gemini-cli"].includes(a.name)` -- a list of a fact that
                # lives here, which goes stale the moment an agent is added or gains a model flag. The
                # registry is the one place that knows; it should be the one place that says.
                "supports_model": bool(a.model_flag)
                or any("{model}" in t for t in (a.argv_template or [])),
                "supports_chat_mode": bool(a.chat_flag),
                # The models worth offering, in the one vocabulary used everywhere:
                # fast / balanced / deep. An empty list means "this agent takes a model but we
                # have no curated shortlist" -- the panel falls back to free text, which is
                # correct for aider (it reaches hundreds of models) and wrong as a DEFAULT,
                # which is what it used to be for all of them.
                "models": [
                    {"tier": t, "model": m, "label": lbl} for (t, m, lbl) in a.models
                ],
            }
        )
    out.sort(key=lambda d: d["name"])
    return out


def main() -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Determinex agent-CLI registry")
    sub = parser.add_subparsers(dest="cmd")

    p_list = sub.add_parser("list", help="list registered agents")
    p_list.add_argument("--json", action="store_true")

    p_status = sub.add_parser(
        "status", help="cheap installed+auth status per agent (no model calls)"
    )
    p_status.add_argument("--json", action="store_true")

    p_probe_rec = sub.add_parser(
        "record-probe",
        help="persist a live-probe verdict so the roster can report what a real call found "
        "instead of inferring it from a credential file",
    )
    p_probe_rec.add_argument("agent")
    p_probe_rec.add_argument(
        "--status",
        required=True,
        help="the classifier's verdict: ok | provider_refused | "
        "quota_exhausted | auth_error | timeout | error",
    )
    p_probe_rec.add_argument("--detail", default="")
    p_probe_rec.add_argument("--at", default="", help="ISO-8601 UTC; defaults to now")

    p_run = sub.add_parser("run", help="run an agent against a workspace, oracle-verified")
    p_run.add_argument("agent")
    p_run.add_argument("task")
    p_run.add_argument("--workspace", required=True)
    p_run.add_argument("--timeout", type=int, default=300)
    p_run.add_argument("--no-verify", action="store_true")
    p_run.add_argument("--model", default=None)

    p_resolve = sub.add_parser(
        "resolve", help="return the argv an agent would run, without running it"
    )
    p_resolve.add_argument("agent")
    p_resolve.add_argument("task", nargs="?", default=None)
    p_resolve.add_argument(
        "--task-file",
        default=None,
        help="read task from this file instead of the positional arg -- a chat-room "
        "prompt (Mission Plan + transcript window) as a raw CLI argument can "
        "exceed Windows' command-line length limit (os error 206)",
    )
    p_resolve.add_argument("--workspace", required=True)
    p_resolve.add_argument("--model", default=None)
    p_resolve.add_argument(
        "--chat",
        action="store_true",
        help="this is a chat-room turn: append the agent's conversational-mode "
        "flag if it declares one (local-ollama's --chat)",
    )

    p_record = sub.add_parser(
        "record-turn",
        help="oracle-verify a captured chat-room turn and append it to the transcript",
    )
    p_record.add_argument("session_id")
    p_record.add_argument("agent")
    p_record.add_argument("--workspace", required=True)
    p_record.add_argument("--raw-file", required=True, help="path to the captured stdout+stderr")
    p_record.add_argument("--returncode", type=int, default=0)
    p_record.add_argument("--turn-id", required=True)
    p_record.add_argument(
        "--task-prompt-file", required=True, help="path to the prompt that was sent to the agent"
    )
    p_record.add_argument("--speaker-kind", choices=["user", "agent"], default="agent")
    p_record.add_argument("--mode", choices=["mention", "broadcast"], default="broadcast")
    p_record.add_argument(
        "--dispatch-failed",
        action="store_true",
        help="the agent CLI never ran (not installed, bad argv, Cloak refused) -- "
        "skip the oracle recheck and record the raw text as a failure note",
    )

    args = parser.parse_args()

    if args.cmd == "run":
        res = run_agent(
            args.agent,
            args.task,
            Path(args.workspace),
            timeout=args.timeout,
            verify=not args.no_verify,
            model=args.model,
        )
        print(
            json.dumps(
                {
                    "agent": res.agent,
                    "verified": res.verified,
                    "ran": res.ran,
                    "raw": res.raw,
                    "oracle": res.oracle,
                    "n_failures": res.n_failures,
                    "note": res.note,
                    "next_moves": res.next_moves,
                }
            )
        )
        return 0

    if args.cmd == "resolve":
        a = _AGENTS.get(args.agent.lower())
        if args.task_file:
            task = Path(args.task_file).read_text(encoding="utf-8", errors="replace")
        elif args.task is not None:
            task = args.task
        else:
            parser.error("resolve: either the task positional or --task-file is required")
        try:
            argv = resolve_argv(
                args.agent, task, Path(args.workspace), model=args.model, chat=args.chat
            )
            print(
                json.dumps(
                    {
                        "argv": argv,
                        "available": a.available() if a else False,
                        "install_hint": a.install_hint if a else "",
                        "stdin_prompt": a.stdin_prompt if a else False,
                    }
                )
            )
        except KeyError as e:
            print(json.dumps({"error": str(e)}))
            return 1
        return 0

    if args.cmd == "record-turn":
        import dataclasses

        import determinex_agent_chat as _chat

        raw = Path(args.raw_file).read_text(encoding="utf-8", errors="replace")
        task_prompt = Path(args.task_prompt_file).read_text(encoding="utf-8", errors="replace")
        turn = _chat.record_turn(
            args.session_id,
            args.agent,
            Path(args.workspace),
            raw,
            args.returncode,
            args.turn_id,
            task_prompt,
            speaker_kind=args.speaker_kind,
            mode=args.mode,
            dispatch_failed=args.dispatch_failed,
        )
        print(json.dumps(dataclasses.asdict(turn)))
        return 0

    if args.cmd == "list" and args.json:
        print(json.dumps(_agents_json()))
        return 0

    if args.cmd == "status":
        print(json.dumps(_agents_status_json()))
        return 0

    if args.cmd == "record-probe":
        print(json.dumps(record_probe_result(args.agent, args.status, args.detail, args.at)))
        return 0

    print("=== Determinex agent-CLI registry (verified sub-agents) ===")
    for name, ok in available_agents().items():
        a = _AGENTS[name]
        mark = "INSTALLED" if ok else "---------"
        print(f"  {mark}  {name:14} (probe: {a.probe})" + ("" if ok else f"   {a.install_hint}"))
    rdy = [n for n, ok in available_agents().items() if ok]
    print(f"\n  {len(rdy)} agent(s) installed here: {rdy or '(none)'}")
    print("  Any agent's output is VERIFIED through the oracle -- hallucinations are caught.")
    print("  Add one with register_agent() or a plugin.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
