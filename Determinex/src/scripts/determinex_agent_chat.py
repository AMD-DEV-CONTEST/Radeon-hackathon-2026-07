#!/usr/bin/env python3
"""
determinex_agent_chat.py -- multi-agent chat room session/transcript logic
============================================================================
Backs the IDE's "Agent Chat Room" panel: several coding-agent CLIs (Claude
Code, Codex, Gemini CLI, a local Ollama model via aider) share ONE
conversation and workspace. This module owns everything that ISN'T spawning
a subprocess -- session/transcript persistence, @mention parsing, and
building each turn's prompt from the shared history -- because subprocess
spawn + live streaming lives in Rust (frontend/src-tauri/src/agent_chat.rs),
which calls back into this module (via `determinex_agents.py record-turn`)
once a turn's CLI process has exited.

Each agent CLI is stateless per-invocation (no cross-call session/continue
flag shared uniformly across claude/codex/gemini/aider), so every turn's
prompt re-serializes the last N transcript entries as context.

Trust model, same as the rest of Determinex: an agent's own "done" is never
trusted. record_turn() re-runs determinex_repair.repair_workspace() after
every agent turn -- only a passing oracle counts as verified.

Sequential execution (never two CLI subprocesses against one workspace at
once) is enforced on the Rust side (agent_chat.rs's per-session queue +
running flag), not here -- this module has no subprocess/concurrency
concerns of its own.

Project Cloak room (DETERMINEX_CLOAK=1)
----------------------------------------
Ryan: "cloak when enabled will put the api llms into a seperate room to work
from away from the sensitive data, and the local onboard can feed concepts
per the cloak protocol, as well as with api." -- "i think we have to have
that to truly claim cloak ability."

Prompt-level obfuscation alone is NOT enough here, unlike the SWE-bench Cloak
flow (a single text-in/patch-out round trip): claude-code/codex/gemini-cli
run as real AGENTIC CLIs with their OWN filesystem access -- they read/write
files themselves mid-turn, which would see raw content no matter how the
initial prompt was scrubbed. So when Cloak is on, a cloud participant's turn
runs against a SEPARATE, FULLY OBFUSCATED MIRROR of the workspace (the
"cloaked room" -- prepare_cloaked_workspace()), never the real one. Whatever
it edits there gets restored (de-obfuscated) and synced back into the real
workspace afterward (sync_cloaked_edits_to_real_workspace()), THEN the real
oracle runs -- same fail-closed posture as determinex_cloak's own
CloakContext (an unbuildable Cloak context refuses the cloud turn rather
than silently falling back to raw). local-ollama never leaves the machine,
so it always operates on the real workspace directly and is the one
participant trusted to "feed concepts" from the raw room into the cloaked
one -- its own messages get the same obfuscate_text() pass as everything
else when build_context_prompt() assembles a cloud agent's turn.

CLI
---
    python scripts/determinex_agent_chat.py create-session <id> --workspace W --participants a,b,c --mode broadcast
    python scripts/determinex_agent_chat.py list-sessions --json
    python scripts/determinex_agent_chat.py transcript <id> --json
    python scripts/determinex_agent_chat.py build-prompt <id> <speaker> --json
    python scripts/determinex_agent_chat.py cloak-prepare <id> --workspace W [--language L]
    python scripts/determinex_agent_chat.py cloak-sync <id> --workspace W
"""

from __future__ import annotations

import datetime as _dt
import json
import re
import sys
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

ROOT = Path(__file__).resolve().parent.parent
SESSIONS_DIR = ROOT / "logs" / "agent_chat_sessions"
INDEX_PATH = SESSIONS_DIR / "_index.json"

_RAW_OUTPUT_CAP = 20_000  # chars; chat turns are read live, not archived -- keep it light
_MAX_CONTEXT_TURNS_DEFAULT = 12


def _now_iso() -> str:
    return _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds")


@dataclass
class ChatTurn:
    turn_id: str
    session_id: str
    seq: int
    speaker: str  # "user" | agent name (e.g. "claude-code")
    speaker_kind: str  # "user" | "agent"
    addressed_to: list[str]  # @mentions this turn was addressed to, [] if none/broadcast
    mode: str  # "mention" | "broadcast"
    task_prompt: str  # what was actually sent to the CLI (context-built)
    raw_output: str  # captured stdout+stderr, capped
    returncode: int
    verified: bool  # oracle passed after this turn (True for user turns: n/a)
    oracle: str
    n_failures: int
    note: str
    started_at: str
    finished_at: str


def _session_path(session_id: str) -> Path:
    return SESSIONS_DIR / f"{session_id}.jsonl"


def _ensure_dir() -> None:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


def append_turn(turn: ChatTurn) -> None:
    """Atomic-enough append: one JSON object per line. Sequential turn
    execution on the Rust side already guarantees a single writer at a time
    per session, so no extra file locking is needed here (mirrors
    determinex_commit_training_capture.py's convention)."""
    _ensure_dir()
    path = _session_path(turn.session_id)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(turn), ensure_ascii=False) + "\n")


def read_transcript(session_id: str) -> list[dict]:
    path = _session_path(session_id)
    if not path.exists():
        return []
    out: list[dict] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _read_index() -> dict:
    if not INDEX_PATH.exists():
        return {}
    try:
        return json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_index(index: dict) -> None:
    _ensure_dir()
    INDEX_PATH.write_text(json.dumps(index, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def update_index(session_id: str, **fields) -> None:
    index = _read_index()
    entry = index.setdefault(session_id, {})
    entry.update(fields)
    _write_index(index)


def create_session(
    session_id: str, workspace: str, participants: list[str], turn_mode: str
) -> dict:
    if turn_mode not in ("mention", "broadcast"):
        raise ValueError(f"turn_mode must be 'mention' or 'broadcast', got {turn_mode!r}")
    now = _now_iso()
    entry = {
        "workspace": workspace,
        "participants": participants,
        "turn_mode": turn_mode,
        "created_at": now,
        "last_active": now,
        "turn_count": 0,
        # Per-agent model overrides ride along with the session (2026-07-31).
        # `ensure_session_loaded` in agent_chat.rs rehydrates workspace, participants and turn_mode
        # from this record after an app restart, but had nothing to read models from, so it reset
        # them to empty. A user who picked opus for claude-code and qwen2.5-coder:14b for
        # local-ollama silently got the defaults back on the next launch -- and for local-ollama the
        # default is a DIFFERENT model (DEFAULT_LOCAL_CHAT_MODEL), so the answers changed with no
        # indication that the choice had been dropped.
        "models": {},
    }
    index = _read_index()
    index[session_id] = entry
    _write_index(index)
    _ensure_dir()
    _session_path(session_id).touch(exist_ok=True)
    if workspace:
        seed_plan_from_stewardship(session_id, Path(workspace))
    return {"session_id": session_id, **entry}


def list_sessions(workspace: str | None = None) -> list[dict]:
    index = _read_index()
    out = [{"session_id": sid, **fields} for sid, fields in index.items()]
    if workspace is not None:
        # Sessions are stored globally (one index for the whole machine), but
        # each IDE window only opens one project -- without this filter, any
        # session ever created in ANY workspace (including leftover dev-test
        # fixtures pointed at unrelated temp folders) shows up in every
        # project's picker. Compare normalized paths so a mix of
        # forward/back-slash workspace strings still matches.
        norm = Path(workspace).resolve()
        out = [s for s in out if _same_path(s.get("workspace", ""), norm)]
    out.sort(key=lambda s: s.get("last_active", ""), reverse=True)
    return out


def _same_path(raw: str, target: Path) -> bool:
    if not raw:
        return False
    try:
        return Path(raw).resolve() == target
    except (OSError, ValueError):
        return False


def get_session(session_id: str) -> dict | None:
    return _read_index().get(session_id)


PROPOSAL_BEGIN = "<<<DETERMINEX_PROPOSED_EDITS"
PROPOSAL_END = "DETERMINEX_PROPOSED_EDITS>>>"
PROPOSAL_SCHEMA = "determinex-chat-proposed-edits-v1"


def extract_proposals(text: str) -> list[dict]:
    """Pull the proposed-edit payloads out of a turn's captured output.

    A chat turn never writes to the workspace (measured 2026-07-31: one conversational turn in six
    silently rewrote a source file, so the write had to become structurally unavailable rather than
    merely discouraged). Instead the agent emits a validated proposal, and this reads it back so the
    user can approve it. Malformed or unknown-schema blocks are skipped rather than raised on -- a
    junk block in one turn must not make a whole transcript unreadable.
    """
    out: list[dict] = []
    cursor = 0
    while True:
        start = text.find(PROPOSAL_BEGIN, cursor)
        if start < 0:
            return out
        body_start = start + len(PROPOSAL_BEGIN)
        end = text.find(PROPOSAL_END, body_start)
        if end < 0:
            return out
        cursor = end + len(PROPOSAL_END)
        try:
            payload = json.loads(text[body_start:end].strip())
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict) or payload.get("schema") != PROPOSAL_SCHEMA:
            continue
        files = payload.get("files")
        if not isinstance(files, list):
            continue
        for entry in files:
            if (
                isinstance(entry, dict)
                and isinstance(entry.get("path"), str)
                and isinstance(entry.get("before"), str)
                and isinstance(entry.get("after"), str)
            ):
                out.append(
                    {"path": entry["path"], "before": entry["before"], "after": entry["after"]}
                )


def _resolve_inside(workspace: Path, rel_path: str) -> Path:
    """Resolve a proposal's path, refusing anything that leaves the workspace.

    The path comes from model output, so `../../etc/hosts` or an absolute path is a thing that can
    arrive here. Approving a diff is approving the change shown, not write access to the disk.
    """
    candidate = (workspace / rel_path).resolve()
    root = workspace.resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError(f"proposal path escapes the workspace: {rel_path!r}")
    return candidate


def apply_proposal(session_id: str, turn_id: str, workspace: str | Path) -> dict:
    """Apply an approved turn's proposed edits, refusing if the files have moved since.

    The staleness check is the point. A proposal carries the exact bytes it was computed against, so
    if the file changed in between -- the user edited it, another participant's approved proposal
    landed -- applying anyway would silently discard that work. That is the failure mode approval
    exists to prevent, so a stale proposal is refused with the path named, not merged hopefully.
    """
    ws = Path(workspace)
    turns = [t for t in read_transcript(session_id) if t.get("turn_id") == turn_id]
    if not turns:
        raise KeyError(f"no turn {turn_id!r} in session {session_id!r}")
    proposals = extract_proposals(turns[-1].get("raw_output") or "")
    if not proposals:
        raise ValueError(f"turn {turn_id!r} carries no proposed edits")

    # Verify everything BEFORE writing anything: a half-applied multi-file proposal is a worse
    # state than a refused one.
    targets: list[tuple[Path, str, str]] = []
    for p in proposals:
        target = _resolve_inside(ws, p["path"])
        current = target.read_text(encoding="utf-8", errors="replace") if target.exists() else ""
        if current != p["before"]:
            raise ValueError(
                f"{p['path']} has changed since this was proposed -- not applying. "
                f"Ask the agent again so it can propose against the current file."
            )
        targets.append((target, p["path"], p["after"]))

    written: list[str] = []
    for target, rel, after in targets:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(after, encoding="utf-8")
        written.append(rel)
    return {"session_id": session_id, "turn_id": turn_id, "applied": written}


def session_models(session_id: str) -> dict:
    """Return this session's per-agent model overrides, tolerating an older record.

    Sessions created before models were persisted have no `models` key, and a hand-edited index
    could hold something that is not a mapping. Either way the answer is "no overrides" rather
    than a crash, because a chat that cannot be opened is worse than one that opens on defaults.
    """
    entry = get_session(session_id) or {}
    raw = entry.get("models")
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items() if str(v).strip()}


def set_model(session_id: str, agent: str, model: str) -> dict:
    """Set (or clear, with an empty model) one participant's model override, on disk.

    Mirrors `agent_chat_set_model`'s in-memory semantics exactly: an empty or whitespace-only
    model removes the override rather than storing a blank, because a blank model tag is the
    empty-model 404 this file already guards against elsewhere.
    """
    if get_session(session_id) is None:
        raise KeyError(f"unknown chat session {session_id!r}")
    models = session_models(session_id)
    if model.strip():
        models[agent] = model.strip()
    else:
        models.pop(agent, None)
    update_index(session_id, models=models)
    return models


# ---------------------------------------------------------------------------
# @mention parsing
# ---------------------------------------------------------------------------
_MENTION_RE = re.compile(r"@([a-zA-Z0-9_-]+)")


def parse_mentions(text: str, known_agents: list[str]) -> list[str]:
    """Extract @name tokens from text and resolve them against known agent
    names/aliases, case-insensitively. Unrecognized @tokens are ignored (not
    an error -- a stray @ in prose shouldn't crash a chat message)."""
    import determinex_agents as _agents

    known_lower = {n.lower() for n in known_agents}
    resolved: list[str] = []
    seen: set[str] = set()
    for raw in _MENTION_RE.findall(text):
        candidate = raw.lower()
        agent = _agents._AGENTS.get(candidate)  # resolves aliases too
        canonical = (
            agent.name
            if (agent and agent.name.lower() in known_lower)
            else (candidate if candidate in known_lower else None)
        )
        if canonical and canonical not in seen:
            seen.add(canonical)
            resolved.append(canonical)
    return resolved


# ---------------------------------------------------------------------------
# Project Cloak room -- see module docstring for the "why prompt-obfuscation
# alone isn't enough" reasoning. A cloud participant's turn runs against a
# fully-obfuscated MIRROR of the workspace, never the real one; local-ollama
# always sees the real workspace directly.
# ---------------------------------------------------------------------------
_LOCAL_AGENT_NAMES = {"local-ollama", "aider-local", "ollama"}
_CLOAK_SKIP_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "target",
    "dist",
    "build",
    ".next",
    ".pytest_cache",
}

# session_id -> CloakContext | None (None cached deliberately -- a failed
# build shouldn't retry the expensive whole-repo scan on every single turn).
_CLOAK_CONTEXTS: dict = {}


def is_cloud_participant(agent: str) -> bool:
    """Conservative default: anything NOT explicitly known-local is treated
    as a cloud/untrusted participant for Cloak purposes, so a future agent
    type is cloaked by default rather than silently trusted with raw data."""
    return agent.lower() not in _LOCAL_AGENT_NAMES


def cloak_enabled() -> bool:
    import os

    return bool(os.environ.get("DETERMINEX_CLOAK", "").strip())


def _detect_repo_language(workspace: Path) -> str:
    """Small local glob-count heuristic -- same lightweight pattern this
    project already repeats per-module (determinex_swebench_agent.py,
    codebase_explorer.py, etc.) rather than a shared canonical detector,
    since this one call site doesn't need SWE-bench's fuller machinery."""
    globs = [
        ("python", "*.py"),
        ("rust", "*.rs"),
        ("go", "*.go"),
        ("typescript", "*.ts"),
        ("javascript", "*.js"),
        ("java", "*.java"),
        ("ruby", "*.rb"),
        ("cpp", "*.cpp"),
        ("c", "*.c"),
        ("php", "*.php"),
    ]
    counts: dict[str, int] = {}
    for lang, pattern in globs:
        try:
            counts[lang] = sum(
                1
                for p in workspace.rglob(pattern)
                if not any(part in _CLOAK_SKIP_DIRS for part in p.parts)
            )
        except OSError:
            counts[lang] = 0
    if not any(counts.values()):
        return "python"
    return max(counts.keys(), key=lambda k: counts[k])


def get_cloak_context(session_id: str, workspace: Path, language: str | None = None):
    """Lazily build (once per session -- a whole-repo AST scan) and cache a
    Cloak symbol map. Returns None if Cloak is unavailable/fails to build --
    callers MUST treat None as a refusal to send anything to a cloud agent,
    never as "fall back to raw" (same fail-closed posture CloakContext
    itself documents for per-file obfuscation).

    Rust spawns a FRESH python process for every subcommand (build-prompt,
    cloak-prepare, cloak-sync, restore-text can all fire multiple times per
    turn) -- the in-memory _CLOAK_CONTEXTS cache above only survives one
    process's lifetime. SymbolMap.build() is deterministic (sorted
    case-insensitive, no randomness -- see symbol_map.py), so it's CORRECT to
    rebuild from scratch every call, just wasteful (a full-repo AST scan each
    time). Persist the built map to disk (SymbolMap already ships
    to_dict()/from_dict() for exactly this) so later calls in the same
    session reload instantly instead of re-scanning."""
    if session_id in _CLOAK_CONTEXTS:
        return _CLOAK_CONTEXTS[session_id]

    cache_path = SESSIONS_DIR / f"{session_id}.cloak_map.json"
    if cache_path.exists():
        try:
            from determinex_cloak import CloakContext, SymbolMap

            data = json.loads(cache_path.read_text(encoding="utf-8"))
            ctx = CloakContext(
                instance_id=session_id,
                symbol_map=SymbolMap.from_dict(data["symbol_map"]),
                star_import_warnings=data.get("star_import_warnings", []),
            )
            _CLOAK_CONTEXTS[session_id] = ctx
            return ctx
        except Exception as e:
            print(
                f"[agent_chat] Cloak map cache reload failed for {session_id}, rebuilding: {e}",
                file=sys.stderr,
            )

    try:
        from determinex_cloak import build_cloak_context

        ctx = build_cloak_context(
            session_id, workspace, language or _detect_repo_language(workspace)
        )
        _CLOAK_CONTEXTS[session_id] = ctx
        _ensure_dir()
        cache_path.write_text(
            json.dumps(
                {
                    "symbol_map": ctx.symbol_map.to_dict(),
                    "star_import_warnings": ctx.star_import_warnings,
                },
                indent=1,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return ctx
    except Exception as e:
        print(
            f"[agent_chat] Cloak context build FAILED for session {session_id}: {e}",
            file=sys.stderr,
        )
        _CLOAK_CONTEXTS[session_id] = None
        return None


def _shadow_workspace_dir(session_id: str) -> Path:
    return SESSIONS_DIR / f"{session_id}.cloak_shadow"


def prepare_cloaked_workspace(
    session_id: str, workspace: Path, language: str | None = None
) -> Path | None:
    """Build (once per session, then reused across every cloud-agent turn so
    edits accumulate the same way they would in a real shared workspace) an
    obfuscated mirror of `workspace` for cloud CLI agents to operate against
    directly. Returns None if Cloak is unavailable -- the caller must refuse
    the cloud turn rather than pointing it at the real workspace."""
    ctx = get_cloak_context(session_id, workspace, language)
    if ctx is None:
        return None
    shadow = _shadow_workspace_dir(session_id)
    if shadow.exists():
        return shadow
    shadow.mkdir(parents=True, exist_ok=True)
    for src in workspace.rglob("*"):
        if src.is_dir():
            continue
        rel = src.relative_to(workspace)
        if any(part in _CLOAK_SKIP_DIRS for part in rel.parts):
            continue
        dst = shadow / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            text = src.read_text(encoding="utf-8", errors="strict")
        except (UnicodeDecodeError, OSError):
            # Binary/unreadable -- copy verbatim rather than crash; a byte
            # blob carries no text identifiers for a source-aware obfuscator
            # to find anyway, so this doesn't leak anything obfuscation would
            # have caught.
            try:
                dst.write_bytes(src.read_bytes())
            except OSError:
                pass
            continue
        try:
            obfuscated = ctx.obfuscate_source_str(text, cache_key=str(rel))
        except Exception:
            # A single file's obfuscation failing must not block the whole
            # shadow build -- write the ORIGINAL only for files Cloak itself
            # already exempts via its safe-list/keep-list; anything else we
            # can't obfuscate is safer omitted than leaked, so skip it.
            continue
        dst.write_text(obfuscated, encoding="utf-8")
    return shadow


def sync_cloaked_edits_to_real_workspace(session_id: str, workspace: Path) -> list:
    """After a cloud agent's turn against the shadow workspace, restore
    (de-obfuscate) every file that differs from the real workspace and write
    the real identifiers back in. The other half of the round-trip: SWE-bench's
    Cloak flow restores a single patch; this restores whole changed files,
    since an agentic CLI edits files directly rather than emitting one diff."""
    shadow = _shadow_workspace_dir(session_id)
    if not shadow.exists():
        return []
    ctx = get_cloak_context(session_id, workspace)
    if ctx is None:
        return []
    synced = []
    for shadow_file in shadow.rglob("*"):
        if shadow_file.is_dir():
            continue
        rel = shadow_file.relative_to(shadow)
        real_file = workspace / rel
        try:
            obfuscated_now = shadow_file.read_text(encoding="utf-8", errors="strict")
        except (UnicodeDecodeError, OSError):
            continue
        try:
            restored = ctx.restore_content(obfuscated_now)
        except Exception as e:
            print(
                f"[agent_chat] Cloak restore FAILED for {rel} in session {session_id}: {e}",
                file=sys.stderr,
            )
            continue
        try:
            existing = (
                real_file.read_text(encoding="utf-8", errors="replace")
                if real_file.exists()
                else None
            )
        except OSError:
            existing = None
        if restored != existing:
            real_file.parent.mkdir(parents=True, exist_ok=True)
            real_file.write_text(restored, encoding="utf-8")
            synced.append(str(rel))
    return synced


def restore_text(session_id: str, text: str, workspace: Path | None = None) -> str:
    """De-obfuscate a cloud agent's own captured stdout/stderr before it's
    stored in the transcript -- otherwise a human (or the local participant)
    reading the chat would see raw x_NNNN tokens instead of real names.
    Returns `text` unchanged if this session was never cloaked, or if no
    context can be recovered (nothing cached in-memory or on disk and no
    workspace given to rebuild from) -- never raises."""
    ctx = _CLOAK_CONTEXTS.get(session_id)
    if ctx is None and workspace is not None:
        ctx = get_cloak_context(session_id, workspace)
    if ctx is None:
        return text
    try:
        return ctx.restore_content(text)
    except Exception as e:
        print(
            f"[agent_chat] Cloak restore_text FAILED for session {session_id}: {e}", file=sys.stderr
        )
        return text


# ---------------------------------------------------------------------------
# Shared mission plan -- the ONE canonical doc every participant reads before
# acting. Ryan: "i want them all to work from the same set of plans and mds
# and all, there should be a universal place they all run to for their
# marching orders or we will have chaos and duplication." Without this, each
# agent's only shared context is the rolling chat transcript, which drifts
# (an agent joining turn 40 doesn't necessarily re-derive the same "what are
# we actually building" understanding a human would from re-reading it) --
# the plan doc is the single, explicitly-maintained source of truth,
# independent of transcript length/drift, that every build_context_prompt()
# call prepends verbatim, unlike the transcript, which is windowed to the
# last max_turns.
# ---------------------------------------------------------------------------
_DEFAULT_PLAN_TEMPLATE = (
    "# Mission Plan\n\n"
    "_No plan set yet for this session. Every participant reads this exact "
    "document before each turn -- write down what you're actually building, "
    "the constraints, and who owns which piece, so agents don't duplicate or "
    "contradict each other's work. Edit this from the Mission Plan panel._\n"
)

# Ryan: "that unified md can help with the positions when they are
# building/fixing/verifying." A live board every participant can update
# (via the Mission Plan panel, or by asking an agent to note its own
# position) so it's visible who's doing what phase of work right now --
# not a one-time doc, part of the SESSION plan every turn re-reads.
_POSITIONS_SECTION = (
    "\n\n## Positions\n\n"
    "_Who's doing what right now -- update as work moves between building, "
    "fixing, and verifying so participants don't collide._\n\n"
    "| Participant | Position | Task |\n"
    "|---|---|---|\n"
    "| _(none yet)_ | | |\n"
)


def _plan_path(session_id: str) -> Path:
    return SESSIONS_DIR / f"{session_id}.plan.md"


def read_plan(session_id: str) -> str:
    path = _plan_path(session_id)
    if not path.exists():
        return _DEFAULT_PLAN_TEMPLATE + _POSITIONS_SECTION
    return path.read_text(encoding="utf-8")


def write_plan(session_id: str, content: str) -> None:
    _ensure_dir()
    _plan_path(session_id).write_text(content, encoding="utf-8")
    update_index(session_id, last_active=_now_iso())


def seed_plan_from_stewardship(session_id: str, workspace: Path) -> str:
    """Populate a freshly created session's plan with a REFERENCE to the
    project's real stewardship docs (root runtime CLAUDE.md + the
    workspace's own CLAUDE.md/PROJECT.md, generating a PROJECT.md if neither
    is adequate -- see determinex_stewardship.py) instead of leaving every
    session to start from the generic template. A reference (file paths),
    not the full doc bodies -- see resolve_stewardship_reference's docstring
    for why: the full-content version overwhelmed every participant's
    context on every single turn. Best-effort: a stewardship failure falls
    back to the plain template rather than blocking session creation."""
    try:
        import determinex_stewardship as _steward

        content = _steward.resolve_stewardship_reference(workspace)
        seeded = f"# Mission Plan\n\n{content}" + _POSITIONS_SECTION
    except Exception as e:
        print(
            f"[agent_chat] stewardship seed failed for session {session_id}: {e}", file=sys.stderr
        )
        seeded = _DEFAULT_PLAN_TEMPLATE + _POSITIONS_SECTION
    write_plan(session_id, seeded)
    return seeded


_CORPUS_MAX_HITS = 3
_CORPUS_SNIPPET_CHARS = 300

# ---------------------------------------------------------------------------
# Corpus as an addressable chat entity + the oracle feedback loop.
# ---------------------------------------------------------------------------
# Ryan: "i meant the corpus have an interface and an oracle feedback loop.
# lets make this chat dynamic so that all of them can build from the chat."
# Two halves:
#   READ  -- answer_as_corpus() lets a session @mention "corpus" like any
#            other participant; it responds with the corpus's own hard-won
#            lessons (determinex_corpus_api.ask, already used passively by
#            corpus_context_for above) PLUS this session's own oracle
#            verification history (session_oracle_digest, below).
#   WRITE -- _record_oracle_outcome() is the feedback loop itself: every
#            REAL oracle-verify outcome from an agent's chat turn becomes
#            durable corpus data, not just a line in this session's own
#            ephemeral transcript (logs/agent_chat_sessions/*.jsonl, which
#            nothing outside this one session ever reads again).
#
# Deliberately its OWN small store (corpus/chat_sessions/oracle_outcomes.jsonl),
# not corpus/programbench/build_knowledge.json's learned_classes -- that
# registry is PB-specific (compile.sh-diff-shaped) and gated so ONLY
# determinex_pb_amplified_fix.learn_class ever writes a verified=True entry
# (see determinex_corpus_api.py's module docstring: "Writers stay exactly
# where they already are"). Writing arbitrary multi-language IDE-chat
# outcomes into that PB flywheel would violate its own contract and could
# corrupt a corpus consumer that assumes every learned_class came from a
# real ProgramBench compile.sh fix.
CORPUS_SPEAKER = "corpus"
_ORACLE_OUTCOMES_PATH = ROOT / "corpus" / "chat_sessions" / "oracle_outcomes.jsonl"


def _record_oracle_outcome(
    session_id: str,
    agent: str,
    workspace: Path | str,
    oracle: str,
    verified: bool,
    n_failures: int,
    note: str,
) -> None:
    """The write side of the oracle feedback loop. Best-effort: a corpus
    write failure must never break the chat turn it's recording (same
    posture as corpus_context_for/stewardship seeding elsewhere in this
    file) -- this is supplementary durable memory, not the turn's own
    correctness record (that's still the transcript's job)."""
    try:
        _ORACLE_OUTCOMES_PATH.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "session_id": session_id,
            "agent": agent,
            "workspace": str(workspace),
            "oracle": oracle,
            "verified": verified,
            "n_failures": n_failures,
            "note": note,
            "timestamp": _now_iso(),
        }
        with open(_ORACLE_OUTCOMES_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[agent_chat] oracle-outcome corpus write failed (non-fatal): {e}", file=sys.stderr)


def session_oracle_digest(session_id: str, max_lines: int = 5) -> str:
    """Read side of the feedback loop's own history: a short summary of
    this session's real oracle-verify outcomes so far, pulled from the
    durable corpus store (not the session transcript, which is windowed
    and per-session-ephemeral by design)."""
    if not _ORACLE_OUTCOMES_PATH.exists():
        return ""
    records: list[dict] = []
    try:
        with open(_ORACLE_OUTCOMES_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("session_id") == session_id:
                    records.append(rec)
    except OSError:
        return ""
    if not records:
        return ""
    n_verified = sum(1 for r in records if r.get("verified"))
    lines = [f"{n_verified}/{len(records)} agent turns verified against a real oracle so far."]
    for r in records[-max_lines:]:
        status = "PASS" if r.get("verified") else "FAIL"
        lines.append(
            f"- [{status}] {r.get('agent')} via {r.get('oracle') or '?'}: "
            f"{str(r.get('note', ''))[:120]}"
        )
    return "\n".join(lines)


def _last_query_for_session(session_id: str) -> str:
    """What "corpus" responds to when addressed: the most recent message in
    the transcript, same source corpus_context_for already uses passively
    for background context on every turn."""
    turns = read_transcript(session_id)
    if not turns:
        return ""
    last = turns[-1]
    return (last.get("raw_output") or last.get("task_prompt") or "").strip()


def answer_as_corpus(session_id: str) -> str:
    """The corpus as an addressable participant (@corpus). Never spawns a
    CLI, never touches the workspace -- record_turn() below treats
    speaker_kind="corpus" like "user" (no oracle recheck), since a corpus
    lookup makes no code changes to verify."""
    query = _last_query_for_session(session_id)
    lines: list[str] = []
    result = None
    if query:
        try:
            import determinex_corpus_api as _corpus

            result = _corpus.ask(query)
        except Exception as e:
            print(f"[agent_chat] answer_as_corpus corpus.ask failed: {e}", file=sys.stderr)
    if result and result.hits:
        lines.append("**From the corpus (hard-won lessons):**")
        for hit in result.hits[:5]:
            snippet = hit.snippet.strip()
            if len(snippet) > 500:
                snippet = snippet[:500] + " …"
            lines.append(f"- **{hit.title}** ({hit.key}): {snippet}")
        if result.warnings:
            lines.append(f"- _note: {result.warnings[0]}_")
    elif query:
        lines.append("**From the corpus:** no hits for the current topic.")
    digest = session_oracle_digest(session_id)
    if digest:
        lines.append("")
        lines.append("**This session's oracle-verification history:**")
        lines.append(digest)
    if not lines:
        lines.append("No corpus hits and no oracle-verification history yet for this session.")
    return "\n".join(lines)


def corpus_context_for(query: str, max_hits: int = _CORPUS_MAX_HITS) -> str:
    """Ryan: 'make sure corpus is tied in.' Determinex already maintains a
    real corpus of hard-won lessons (corpus/programbench/build_knowledge.json,
    queried via determinex_corpus_api.ask()) -- the whole point of the
    chat room's shared mission plan is avoiding duplicated/contradicted work,
    and the corpus is literally this project's own record of past mistakes
    and their fixes. Without this, an agent could re-discover (or re-commit)
    something the corpus already knows. Best-effort: a corpus load failure
    must never block prompt building, so any exception here just means "no
    corpus context this turn," not a broken turn."""
    if not query.strip():
        return ""
    try:
        import determinex_corpus_api as _corpus

        result = _corpus.ask(query)
    except Exception as e:
        print(f"[agent_chat] corpus query failed (non-fatal): {e}", file=sys.stderr)
        return ""
    if not result.hits:
        return ""
    lines = []
    for hit in result.hits[:max_hits]:
        snippet = hit.snippet.strip()
        if len(snippet) > _CORPUS_SNIPPET_CHARS:
            snippet = snippet[:_CORPUS_SNIPPET_CHARS] + " …"
        lines.append(f"- **{hit.title}** ({hit.key}): {snippet}")
    if result.warnings:
        lines.append(f"- _note: {result.warnings[0]}_")
    return "\n".join(lines)


_RESYNC_MARKER = "## Resynced from project docs"


def resync_plan_from_stewardship(session_id: str, workspace: Path) -> str:
    """Pull a fresh stewardship-doc REFERENCE into an EXISTING session's plan
    without destroying whatever the user/agents have already written --
    replaces the PRIOR resync section (if any) rather than appending another
    copy on top of it every time (was: unbounded growth, one full-content
    copy per click -- see resolve_stewardship_reference's docstring). The
    user's own edits and the live Positions board are exactly what a blind
    overwrite of the WHOLE plan would clobber, so only the resync section
    itself is replaced."""
    import determinex_stewardship as _steward

    fresh = _steward.resolve_stewardship_reference(workspace)
    current = read_plan(session_id)
    # Drop any previous resync section (from the marker to the next "---"
    # divider or end of doc) before appending the fresh one.
    marker_idx = current.find(_RESYNC_MARKER)
    if marker_idx != -1:
        divider_idx = current.rfind("\n\n---\n\n", 0, marker_idx)
        current = current[:divider_idx] if divider_idx != -1 else current[:marker_idx].rstrip()
    updated = f"{current.rstrip()}\n\n---\n\n{_RESYNC_MARKER} ({_now_iso()})\n\n{fresh}\n"
    write_plan(session_id, updated)
    return updated


# ---------------------------------------------------------------------------
# Prompt building -- each CLI agent is stateless per-invocation, so every
# turn re-serializes the shared plan + recent transcript as context. The
# plan is NOT windowed like the transcript -- it's the point of it.
# ---------------------------------------------------------------------------
def build_context_prompt(
    session_id: str, speaker: str, *, max_turns: int = _MAX_CONTEXT_TURNS_DEFAULT
) -> str:
    session = get_session(session_id)
    workspace_str = session.get("workspace", "") if session else ""
    turns = read_transcript(session_id)[-max_turns:]
    plan = read_plan(session_id)

    cloud = is_cloud_participant(speaker)
    ctx = None
    if cloud and cloak_enabled():
        if not workspace_str:
            return (
                f"[CLOAK ERROR] Cloak is enabled but session {session_id} has no workspace "
                f"set; refusing to build a prompt for cloud agent '{speaker}'."
            )
        ctx = get_cloak_context(session_id, Path(workspace_str))
        if ctx is None:
            return (
                f"[CLOAK ERROR] Cloak is enabled but the privacy context could not be built "
                f"for {workspace_str}; refusing to send raw content to cloud agent "
                f"'{speaker}'. See stderr for the underlying error, or disable "
                f"DETERMINEX_CLOAK for this session."
            )

    def _maybe_obfuscate(text: str) -> str:
        if ctx is None:
            return text
        try:
            return ctx.obfuscate_text(text)
        except Exception:
            # Fail closed on THIS string specifically -- better an opaque
            # marker reaches the cloud agent than raw content leaking past a
            # per-call obfuscation failure.
            return "[cloak: could not obfuscate this content]"

    privacy_note = ""
    if cloak_enabled():
        privacy_note = "\n\n[PRIVACY] Project Cloak is ON for this session. " + (
            "You are in the CLOAKED room and are working against an obfuscated MIRROR of "
            "the workspace -- every identifier you see (x_NNNN tokens) stands in for a real "
            "name; work with them exactly as given, never guess or invent real names. Edits "
            "you make here get restored and synced back to the real workspace afterward. The "
            "on-device local participant can see real names and translates what you need into "
            "this room's vocabulary."
            if cloud
            else "You have full raw access as the on-device LOCAL participant -- cloud "
            "participants in this room only ever see a Cloak-obfuscated mirror, never your "
            "raw content. Anything you post here gets auto-obfuscated before a cloud agent "
            "reads it."
        )

    # Query Determinex's own corpus of hard-won lessons for anything
    # relevant to the most recent message -- the whole point of the shared
    # plan is avoiding duplicated/contradicted work, and the corpus is this
    # project's own record of past mistakes and fixes. Best-effort: never
    # blocks prompt building (see corpus_context_for's docstring).
    corpus_query = (
        (turns[-1].get("raw_output") or turns[-1].get("task_prompt") or "") if turns else ""
    )
    corpus_block = corpus_context_for(corpus_query)

    # This framing said "respond and/or make the edits that best move the task forward", and then
    # reinforced editing twice more ("your own edits will be checked...", "make changes you believe
    # will actually pass"). Read by a small local model, the instruction is unambiguous: edit.
    #
    # Measured 2026-07-31 -- asked "What is the capital of France? One word." in a real session,
    # every model tried to patch a file. The DSL-tuned engineer answered "Paris" inside a
    # `### FILE: msg.txt` block; the general 3b-instruct chat default rewrote main.rs. The local
    # agent then graded the malformed patch as a failed edit, retried three times and returned rc=1,
    # so a plain question to the local participant could not produce a successful turn. Three
    # separate attempts to fix it inside determinex_local_agent.py all failed, because the room was
    # still telling the participant its job was editing and no downstream prompt could outvote that.
    #
    # Answering and editing are now separated, and the condition is the conversation itself rather
    # than a flag: reply to what was said, and change files when the conversation asks for a change.
    # The oracle sentence stays, but attached to the edit case where it belongs -- it was reading as
    # a general instruction to produce changes.
    lines = [
        f"You are '{speaker}', one of several AI collaborators (plus the human "
        f"user) in a shared multi-agent chat working on the workspace at "
        f"{workspace_str}. Other participants may have already made changes -- "
        f"read the shared mission plan and conversation below, then reply to "
        f"what has been said.\n\n"
        f"If the conversation is asking for a change to the code, make that "
        f"change; your edits are checked against the project's real "
        f"compiler/test oracle afterward, so make changes you believe will "
        f"actually pass, not just look plausible. If you are being asked a "
        f"question, or for your view, or for a plan, then answer it in prose "
        f"and do not modify any files." + privacy_note,
        "",
        "--- shared mission plan (the same document every participant reads) ---",
        _maybe_obfuscate(plan.strip()),
        "--- end mission plan ---",
    ]
    if corpus_block:
        lines += [
            "",
            "--- relevant lessons from Determinex's own corpus (past mistakes/fixes) ---",
            _maybe_obfuscate(corpus_block),
            "--- end corpus lessons ---",
        ]
    lines += [
        "",
        "--- conversation so far ---",
    ]
    for t in turns:
        spk = t.get("speaker", "?")
        out = (t.get("raw_output") or t.get("task_prompt") or "").strip()
        if len(out) > 1500:
            out = out[:1500] + " …[truncated]"
        lines.append(f"[{spk}]: {_maybe_obfuscate(out)}")
    lines.append("--- end conversation ---")
    lines.append("")
    lines.append(f"Now respond/act as '{speaker}'.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# record_turn -- the oracle-verification step. Reuses determinex_repair, does
# not reimplement it.
# ---------------------------------------------------------------------------
def record_turn(
    session_id: str,
    agent: str,
    workspace: Path,
    raw: str,
    returncode: int,
    turn_id: str,
    task_prompt: str,
    *,
    speaker_kind: str = "agent",
    addressed_to: list[str] | None = None,
    mode: str = "broadcast",
    dispatch_failed: bool = False,
) -> ChatTurn:
    started_at = _now_iso()
    capped_raw = raw if len(raw) <= _RAW_OUTPUT_CAP else raw[:_RAW_OUTPUT_CAP] + "\n…[truncated]"

    if speaker_kind in ("user", "corpus"):
        # Neither a user message nor a corpus response touches the
        # workspace -- nothing to oracle-check.
        verified, oracle, n_failures, note = (
            True,
            "",
            0,
            "user message" if speaker_kind == "user" else "corpus response",
        )
    elif dispatch_failed:
        # The agent CLI never ran (not installed, bad argv, Cloak refused the
        # turn, etc.) -- re-running the oracle here would just report the
        # workspace's pre-existing state and could misleadingly show
        # "verified" on a turn whose content is an error message. Record the
        # failure as-is instead of silently dropping it (previously this path
        # only emitted a live frontend event with nothing written to the
        # persisted transcript -- a failed turn could vanish with zero trace
        # if no listener was attached at the moment it happened).
        verified, oracle, n_failures, note = False, "", 0, raw
    else:
        import determinex_repair as _r

        try:
            diag = _r.repair_workspace(workspace)
            verified, oracle, n_failures = diag.healthy, diag.oracle, diag.n_failures
            note = (
                "oracle PASSES after agent edits"
                if verified
                else "oracle still failing after agent edits"
            )
        except Exception as e:
            verified, oracle, n_failures, note = False, "", 0, f"verify error: {e}"
        # Oracle feedback loop (write side): every REAL oracle-verify outcome
        # becomes durable corpus data, not just a line in this session's own
        # transcript. See the module-level comment above answer_as_corpus.
        _record_oracle_outcome(session_id, agent, workspace, oracle, verified, n_failures, note)

    turns_so_far = read_transcript(session_id)
    turn = ChatTurn(
        turn_id=turn_id,
        session_id=session_id,
        seq=len(turns_so_far),
        speaker=agent,
        speaker_kind=speaker_kind,
        addressed_to=addressed_to or [],
        mode=mode,
        task_prompt=task_prompt,
        raw_output=capped_raw,
        returncode=returncode,
        verified=verified,
        oracle=oracle,
        n_failures=n_failures,
        note=note,
        started_at=started_at,
        finished_at=_now_iso(),
    )
    append_turn(turn)
    update_index(session_id, last_active=turn.finished_at, turn_count=len(turns_so_far) + 1)
    return turn


def new_turn_id(session_id: str) -> str:
    return f"{session_id}-{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Determinex agent chat room session store")
    sub = parser.add_subparsers(dest="cmd")

    p_create = sub.add_parser("create-session")
    p_create.add_argument("session_id")
    p_create.add_argument("--workspace", required=True)
    p_create.add_argument("--participants", required=True, help="comma-separated agent names")
    p_create.add_argument("--mode", choices=["mention", "broadcast"], default="broadcast")

    p_list = sub.add_parser("list-sessions")
    p_list.add_argument("--json", action="store_true")
    p_list.add_argument(
        "--workspace",
        default=None,
        help="only return sessions for this workspace (omit for every session on this machine)",
    )

    p_get = sub.add_parser(
        "get-session",
        help="print one session's persisted metadata (workspace/participants/mode), "
        "or null -- used to rehydrate in-memory session state after an app restart",
    )
    p_get.add_argument("session_id")

    p_apply = sub.add_parser(
        "apply-proposal",
        help="apply one turn's proposed edits after the user approves them; "
        "refuses if the files changed since the proposal was made",
    )
    p_apply.add_argument("session_id")
    p_apply.add_argument("turn_id")
    p_apply.add_argument("--workspace", required=True)

    p_proposals = sub.add_parser("proposals", help="list turns carrying unapplied proposed edits")
    p_proposals.add_argument("session_id")
    p_proposals.add_argument("turn_id", nargs="?", default="")

    p_set_model = sub.add_parser(
        "set-model",
        help="persist one participant's model override on the session "
        "record; an empty model clears it",
    )
    p_set_model.add_argument("session_id")
    p_set_model.add_argument("agent")
    p_set_model.add_argument("model", nargs="?", default="")

    p_transcript = sub.add_parser("transcript")
    p_transcript.add_argument("session_id")
    p_transcript.add_argument("--json", action="store_true")

    p_prompt = sub.add_parser("build-prompt")
    p_prompt.add_argument("session_id")
    p_prompt.add_argument("speaker")
    p_prompt.add_argument("--max-turns", type=int, default=_MAX_CONTEXT_TURNS_DEFAULT)
    p_prompt.add_argument("--json", action="store_true")

    p_mentions = sub.add_parser("parse-mentions")
    p_mentions.add_argument("text")
    p_mentions.add_argument("--known-agents", required=True, help="comma-separated")

    p_plan_read = sub.add_parser("plan-read", help="print the session's shared mission plan")
    p_plan_read.add_argument("session_id")

    p_plan_write = sub.add_parser("plan-write", help="overwrite the session's shared mission plan")
    p_plan_write.add_argument("session_id")
    p_plan_write.add_argument(
        "--content-file",
        required=True,
        help="path to the new plan content (avoids CLI arg-length limits)",
    )

    p_cloak_prepare = sub.add_parser(
        "cloak-prepare", help="build (or reuse) the obfuscated shadow workspace for cloud agents"
    )
    p_cloak_prepare.add_argument("session_id")
    p_cloak_prepare.add_argument("--workspace", required=True)
    p_cloak_prepare.add_argument("--language", default=None)

    p_cloak_sync = sub.add_parser(
        "cloak-sync",
        help="restore+sync a cloud agent's shadow-workspace edits into the real workspace",
    )
    p_cloak_sync.add_argument("session_id")
    p_cloak_sync.add_argument("--workspace", required=True)

    p_restore_text = sub.add_parser(
        "restore-text", help="de-obfuscate a cloud agent's captured stdout before it's stored"
    )
    p_restore_text.add_argument("session_id")
    p_restore_text.add_argument("--text-file", required=True)
    p_restore_text.add_argument("--workspace", default=None)

    p_resync = sub.add_parser(
        "resync-plan", help="pull fresh project-doc content into an existing session's plan"
    )
    p_resync.add_argument("session_id")
    p_resync.add_argument("--workspace", required=True)

    p_ask_corpus = sub.add_parser(
        "ask-corpus",
        help="query the corpus as an addressable chat participant "
        "(@corpus) and record the response as a turn",
    )
    p_ask_corpus.add_argument("session_id")
    p_ask_corpus.add_argument("--workspace", default="")
    p_ask_corpus.add_argument("--turn-id", required=True)
    p_ask_corpus.add_argument("--mode", choices=["mention", "broadcast"], default="mention")

    # THE FOREMAN. Ryan, 2026-08-03: "who takes priority based on what information is
    # presented... the corpus should be the authority, and the answers should be looked at by
    # time... a mechanism that allows for the AIs to not collide and stop working but listen
    # to a foreman and keep pushing to the end even on APIs."
    #
    # Serialising turns (agent_chat.rs's per-session queue) prevents a COLLISION. It does not
    # say who is right when participants disagree, or who goes next when nobody is
    # progressing -- and a room without those answers stops with everyone still "working".
    p_foreman = sub.add_parser(
        "foreman",
        help="rule on the transcript: who is authoritative, and who should take the next turn",
    )
    p_foreman.add_argument("session_id")
    p_foreman.add_argument("--participants", default="")

    args = parser.parse_args()

    if args.cmd == "create-session":
        participants = [p.strip() for p in args.participants.split(",") if p.strip()]
        result = create_session(args.session_id, args.workspace, participants, args.mode)
        print(json.dumps(result))
        return 0

    if args.cmd == "foreman":
        from determinex_foreman import Foreman

        sess = get_session(args.session_id) or {}
        parts = [
            x.strip()
            for x in (args.participants.split(",") if args.participants else sess.get("participants", []))
            if str(x).strip()
        ]
        fm = Foreman()
        for t in read_transcript(args.session_id):
            fm.observe(t)
        ruling = fm.next_move(parts)
        top = ruling.winning
        print(json.dumps({
            "directive": ruling.directive.value,
            "assign_to": ruling.assign_to,
            "because": ruling.because,
            "authoritative": (None if top is None else {
                "speaker": top.speaker,
                "authority": top.authority.name,
                "backed_by": top.authority.label,
                "at": top.at,
            }),
        }))
        return 0

    if args.cmd == "list-sessions":
        print(json.dumps(list_sessions(args.workspace)))
        return 0

    if args.cmd == "get-session":
        print(json.dumps(get_session(args.session_id)))
        return 0

    if args.cmd == "apply-proposal":
        try:
            print(json.dumps(apply_proposal(args.session_id, args.turn_id, args.workspace)))
        except (KeyError, ValueError, OSError) as exc:
            print(json.dumps({"error": str(exc)}), file=sys.stderr)
            return 2
        return 0

    if args.cmd == "proposals":
        turns = [
            t
            for t in read_transcript(args.session_id)
            if not args.turn_id or t.get("turn_id") == args.turn_id
        ]
        print(
            json.dumps(
                [
                    {
                        "turn_id": t.get("turn_id"),
                        "speaker": t.get("speaker"),
                        "files": [
                            {
                                "path": p["path"],
                                "before_lines": len(p["before"].splitlines()),
                                "after_lines": len(p["after"].splitlines()),
                            }
                            for p in extract_proposals(t.get("raw_output") or "")
                        ],
                    }
                    for t in turns
                    if extract_proposals(t.get("raw_output") or "")
                ]
            )
        )
        return 0

    if args.cmd == "set-model":
        try:
            print(json.dumps(set_model(args.session_id, args.agent, args.model)))
        except KeyError as exc:
            print(json.dumps({"error": str(exc)}), file=sys.stderr)
            return 2
        return 0

    if args.cmd == "transcript":
        print(json.dumps(read_transcript(args.session_id)))
        return 0

    if args.cmd == "build-prompt":
        prompt = build_context_prompt(args.session_id, args.speaker, max_turns=args.max_turns)
        print(json.dumps({"prompt": prompt}))
        return 0

    if args.cmd == "parse-mentions":
        known = [a.strip() for a in args.known_agents.split(",") if a.strip()]
        print(json.dumps(parse_mentions(args.text, known)))
        return 0

    if args.cmd == "plan-read":
        print(json.dumps({"content": read_plan(args.session_id)}))
        return 0

    if args.cmd == "plan-write":
        content = Path(args.content_file).read_text(encoding="utf-8")
        write_plan(args.session_id, content)
        print(json.dumps({"ok": True}))
        return 0

    if args.cmd == "cloak-prepare":
        shadow = prepare_cloaked_workspace(args.session_id, Path(args.workspace), args.language)
        print(
            json.dumps(
                {
                    "shadow_workspace": str(shadow) if shadow else None,
                    "cloak_available": shadow is not None,
                }
            )
        )
        return 0

    if args.cmd == "cloak-sync":
        synced = sync_cloaked_edits_to_real_workspace(args.session_id, Path(args.workspace))
        print(
            json.dumps(
                {
                    "synced_files": synced,
                    "cloak_active": args.session_id in _CLOAK_CONTEXTS
                    and _CLOAK_CONTEXTS[args.session_id] is not None,
                }
            )
        )
        return 0

    if args.cmd == "restore-text":
        text = Path(args.text_file).read_text(encoding="utf-8", errors="replace")
        ws = Path(args.workspace) if args.workspace else None
        print(json.dumps({"text": restore_text(args.session_id, text, ws)}))
        return 0

    if args.cmd == "resync-plan":
        updated = resync_plan_from_stewardship(args.session_id, Path(args.workspace))
        print(json.dumps({"content": updated}))
        return 0

    if args.cmd == "ask-corpus":
        query = _last_query_for_session(args.session_id)
        answer = answer_as_corpus(args.session_id)
        turn = record_turn(
            args.session_id,
            CORPUS_SPEAKER,
            Path(args.workspace or "."),
            answer,
            0,
            args.turn_id,
            query,
            speaker_kind="corpus",
            mode=args.mode,
        )
        print(json.dumps(asdict(turn)))
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
