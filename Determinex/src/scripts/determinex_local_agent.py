#!/usr/bin/env python3
"""
determinex_local_agent.py -- a real, no-extra-install local-model agent
=============================================================================
Ryan: "ollama is on the system though... so fix it." The chat room's
local-ollama participant was registered against `aider`, which isn't
installed here and can't be installed by this session (the auto-mode
classifier hard-blocks pip installs). Ollama itself IS already running on
this machine with models already pulled -- this script drives it directly,
reusing this project's own proven local-model primitives
(swe_agent.inference._ollama for the HTTP call, swe_agent.patch's
SEARCH/REPLACE parser+applicator, already battle-tested by the SWE-bench
agent) instead of depending on an external CLI package.

Same argv-driven contract as every other agent in determinex_agents.py's
registry (task positional, --workspace, --model) so it plugs into
resolve_argv()/agent_chat.rs without any special-casing.

Prompt protocol: the model is asked to prefix each edit with a
"### FILE: <relative/path>" marker line, followed by a
<<<SEARCH/===/>>>REPLACE block (swe_agent.patch's existing, fuzzy-matching
format) -- this is the one piece that doesn't already exist upstream (the
SWE-bench harness always targets one pre-known file; here the model must
name which file each edit targets, since a chat turn can touch several).

CLI
---
    python scripts/determinex_local_agent.py "<task>" --workspace W --model TAG
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import determinex_local_model_bench as _bench  # noqa: E402
from swe_agent.inference import _ollama  # noqa: E402
from swe_agent.patch import _apply_search_replace_blocks, _parse_search_replace_blocks  # noqa: E402

_FILE_MARKER_RE = re.compile(r"^###\s*FILE:\s*(.+?)\s*$", re.MULTILINE)
_MAX_LISTED_FILES = 60
_SKIP_DIRS = {
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
_DEFAULT_MODEL = "qwen2.5-coder:14b-instruct-q4_K_M"

# Retry with the real failure injected -- the project's core loop, which this
# file did not have. See run()'s docstring for why that mattered.
_MAX_ATTEMPTS = 3
# Verbatim source shown to the model. A SEARCH/REPLACE edit is byte-exact by
# definition, so a budget too small to show the target file makes the task
# impossible rather than merely hard.
_CONTENT_BUDGET_CHARS = 24_000
_PER_FILE_CHARS = 6_000
# Deliberately NOT "### FILE:" -- that marker is how _split_by_file() parses the
# model's REPLY, and using it in the prompt too invites a model that echoes its
# context back to be misread as emitting edits.
_CTX_BEGIN = "--- BEGIN file: {rel} ---"
_CTX_END = "--- END file: {rel} ---"

_SYSTEM = (
    "You are a careful software engineer editing a real codebase. Make "
    "minimal, correct changes using the SEARCH/REPLACE block format you "
    "were given. The SEARCH text must be copied character-for-character "
    "from the file contents you were shown -- never retype it from memory "
    "and never invent content you have not seen."
)

# Chat mode (2026-07-31). This agent is the local participant in the multi-agent chat room, and
# until now it had one system prompt, the one above, which orders the model to emit file edits.
# Measured: asked "What is the capital of France? One word." in a real chat session, the 1.5B
# engineer answered correctly -- and wrapped "Paris" in a `### FILE: msg.txt` block with malformed
# markers, because it had been told its job was editing. `_split_by_file` saw a file header, so the
# "no edit blocks means this was a discussion turn" escape hatch below never fired; the response was
# graded as a botched patch, retried three times, and the turn exited rc=1. The correct answer was
# thrown away and the user saw a failed turn.
#
# So a conversational message to the local participant could not succeed unless the model
# spontaneously ignored its system prompt. Chat mode states the actual contract: talk by default,
# edit when asked. Kept as an explicit flag rather than guessed from the task text -- an agent that
# decides for itself whether it was asked to change files is how you get a silent no-op reported as
# success, which is what the strict path below exists to prevent.
_SYSTEM_CHAT = (
    "You are one participant in a shared multi-agent chat about a real codebase. Reply "
    "conversationally, in prose, addressed to the other participants.\n\n"
    "Only if you are actually being asked to change a file, emit SEARCH/REPLACE blocks in the "
    "format you were given, with SEARCH text copied character-for-character from the file contents "
    "you were shown. If you are not changing a file, do not emit any block, any `### FILE:` header, "
    "or any SEARCH/REPLACE markers -- just answer."
)


def _rank_paths(workspace: Path, task: str) -> list[str]:
    """Which files to show verbatim, most relevant first.

    Reuses the existing Context Provisioner's keyword scoring rather than
    inventing a second relevance heuristic (AUDIT BEFORE BUILD). Its own output
    is NOT used directly: provision() returns elided definition snippets joined
    by "...", which is right for comprehension and wrong for a byte-exact SEARCH
    block. Only its ordering is borrowed; the bytes come from disk below.
    """
    ranked: list[str] = []
    try:
        import determinex_context

        ranked = [s.path for s in determinex_context.provision(workspace, task).snippets]
    except Exception:
        ranked = []
    # provision() only scores code extensions that had a keyword hit, so
    # everything else still has to be reachable -- appended in stable order.
    for rel in _list_workspace_files(workspace):
        if rel not in ranked:
            ranked.append(rel)
    return ranked


def _render_file_contents(
    workspace: Path,
    paths: list[str],
    budget_chars: int = _CONTENT_BUDGET_CHARS,
    per_file_chars: int = _PER_FILE_CHARS,
) -> tuple[str, list[str]]:
    """Verbatim contents for as many ranked files as the budget allows."""
    out: list[str] = []
    shown: list[str] = []
    used = 0
    for rel in paths:
        p = workspace / rel
        try:
            if not p.is_file() or p.stat().st_size > 2_000_000:
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "\x00" in text[:1024]:  # binary; nothing to SEARCH in
            continue
        truncated = len(text) > per_file_chars
        head = _CTX_BEGIN.format(rel=rel)
        if truncated:
            # Say so explicitly: a model that SEARCHes in the elided region
            # produces a block that cannot possibly match.
            head += "  (TRUNCATED -- only the text shown here can be matched)"
        block = f"{head}\n{text[:per_file_chars]}\n{_CTX_END.format(rel=rel)}\n"
        if shown and used + len(block) > budget_chars:
            break
        out.append(block)
        shown.append(rel)
        used += len(block)
    return "\n".join(out), shown


def _list_workspace_files(workspace: Path, limit: int = _MAX_LISTED_FILES) -> list[str]:
    out: list[str] = []
    try:
        for p in sorted(workspace.rglob("*")):
            if p.is_dir():
                continue
            rel = p.relative_to(workspace)
            if any(part in _SKIP_DIRS for part in rel.parts):
                continue
            out.append(str(rel))
            if len(out) >= limit:
                break
    except OSError:
        pass
    return out


def _build_prompt(
    task: str,
    workspace: Path,
    contents: str = "",
    shown: list[str] | None = None,
    feedback: str = "",
    chat_mode: bool = False,
) -> str:
    files = _list_workspace_files(workspace)
    file_list = "\n".join(files) if files else "(empty or unreadable workspace)"
    # The file CONTENTS, not just the paths. Sending only a path list while
    # demanding a byte-exact SEARCH block is what made this agent structurally
    # unable to succeed: asked to fix add.py, having never seen add.py, a 1.5B
    # model emitted `def subtract(a, b):` as its SEARCH text -- which is not in
    # the file, failed all 6 of the applicator's fuzzy passes, and was skipped.
    # Found live 2026-07-28.
    body = f"{task}\n\n"
    if contents:
        body += (
            "--- current file contents (VERBATIM -- copy SEARCH text from here) ---\n"
            f"{contents}\n--- end file contents ---\n\n"
        )
        unshown = [f for f in files if f not in (shown or [])]
        if unshown:
            body += (
                "Other files exist but are not shown (ask about them rather than "
                f"guessing their contents): {', '.join(unshown[:20])}\n\n"
            )
    else:
        body += f"--- workspace files (relative paths) ---\n{file_list}\n--- end file list ---\n\n"
    if feedback:
        body += f"{feedback}\n\n"

    edit_format = (
        "### FILE: relative/path/to/file.py\n"
        "<<<SEARCH\n"
        "<exact existing lines to find>\n"
        "===\n"
        "<replacement lines>\n"
        ">>>REPLACE\n"
    )

    if chat_mode:
        # A chat turn is built in the opposite order from an editing turn, and the reason is
        # measured rather than stylistic. The editing layout puts the task first and ends with a
        # fully worked example of the marker syntax, which for a 1.5B model is the strongest signal
        # in the prompt: asked "What is the capital of France?" in a real chat session, the engineer
        # answered "Paris" and wrapped it in `### FILE: msg.txt` with SEARCH/REPLACE markers.
        #
        # Moving the prose instruction to the end and keeping the format visible did not fix it
        # either -- it made things worse. The model read "Otherwise emit NO markers of any kind" and
        # replied, in full, "NO markers". A small model completes the nearest instruction rather
        # than obeying it, so the fix is not a firmer instruction: it is to put the QUESTION last
        # and keep the edit syntax terse and out of final position.
        # The FIRST chat attempt shows no workspace dump at all, and that is measured too. The chat
        # room's prompt already carries the mission plan and the conversation; appending a file list
        # (or file contents) on top of it is what turns "answer this question" into "edit
        # something". With main.rs listed, the 3b chat default answered the France question in prose
        # on one run and rewrote main.rs on the next -- same prompt, different sample. Removing the
        # dump removes the thing being reacted to.
        #
        # Escalation, not deprivation: if the model shows edit intent anyway, the retry arrives here
        # with `feedback` set, and that attempt gets the marker format AND the real file bytes
        # (_render_file_contents is refreshed before each retry). So a chat turn that genuinely needs
        # to edit sees everything it needs on attempt 2, and a chat turn that is just talking never
        # sees a file list to be tempted by.
        chat_body = ""
        if feedback:
            # The retry gets the file list AND the contents AND an explicit statement of the legal
            # paths. All three, because each failure mode showed up in turn: with no dump at all the
            # model emitted a ```rust fence (no markers); given the format it then wrote
            # `### FILE: <workspace>/src/main.rs` for a file that lives at `main.rs`, so the block
            # was well-formed, matched nothing, and was skipped. A model that cannot see the tree
            # invents a plausible one, and `src/` is the most plausible guess in the world for a Rust
            # file.
            chat_body += (
                f"--- workspace files (relative paths) ---\n{file_list}\n--- end file list ---\n\n"
            )
            if contents:
                chat_body += (
                    "--- current file contents (VERBATIM -- copy SEARCH text from here) ---\n"
                    f"{contents}\n--- end file contents ---\n\n"
                )
            if files:
                chat_body += (
                    "The path after '### FILE:' must be EXACTLY one of these, copied character for "
                    f"character -- not an absolute path, and not a guess: {', '.join(files[:20])}\n\n"
                )
            chat_body += f"{feedback}\n\n"
        # Chat mode does not mention the edit syntax AT ALL, and that is the third thing tried
        # here, each measured against the same question:
        #   1. format shown, task first (the editing layout) -> "Paris" wrapped in `### FILE:`,
        #      graded a malformed patch, 3 retries, rc=1.
        #   2. format shown, prose instruction last -> the model replied "NO markers", echoing the
        #      instruction instead of answering.
        #   3. format mentioned once, question last -> still `### FILE:` blocks, on both the
        #      DSL-tuned engineer AND the general 3b-instruct chat default.
        # Naming the markers is itself the instruction a small model follows, so the only reliable
        # way to stop a conversational turn from arriving as a patch is not to raise the subject.
        #
        # Edits are not lost by this: `_apply_edits` below still runs on anything well-formed the
        # model offers unprompted, so "fix the bug in x.rs" in a chat still lands. Chat mode simply
        # never ASKS for a patch. Editing turns are unaffected -- they take the branch below, which
        # keeps the full worked example.
        return chat_body + f"{task}\n"

    return body + (
        "For every change, emit a block in EXACTLY this format (one per file/edit):\n\n"
        f"{edit_format}\n"
        "Use a real relative path from the file list above (or a new path for a new file, "
        "with an empty SEARCH block). Only emit blocks for changes you actually intend -- "
        "don't restate the whole file. If you're only responding/discussing and not editing "
        "anything, emit no blocks at all."
    )


def _split_by_file(raw: str) -> dict:
    """Split the model's response on '### FILE: <path>' markers, returning
    {relative_path: raw_block_text_for_that_file}."""
    markers = list(_FILE_MARKER_RE.finditer(raw))
    out: dict = {}
    for i, m in enumerate(markers):
        path = m.group(1).strip()
        start = m.end()
        end = markers[i + 1].start() if i + 1 < len(markers) else len(raw)
        out.setdefault(path, "")
        out[path] += raw[start:end]
    return out


def _apply_edits(
    by_file: dict, workspace: Path, propose_only: bool = False, proposals: list | None = None
) -> tuple[bool, bool, list, list[str]]:
    """Apply one attempt's blocks. -> (any_applied, any_attempted, failures, notes)

    `failures` is [(rel_path, unmatched_search_text)] -- the material the next
    attempt's prompt is built from.

    `propose_only` computes and VALIDATES the result without writing a byte, appending
    {path, before, after} to `proposals`. Chat turns run this way: measured 2026-07-31, one in six
    conversational turns -- asked only "What is the capital of France?" -- rewrote the workspace's
    main.rs from `println!("hi")` to `println!("Hello, world!")`. That is sampling, not prompt
    wording, so no prompt makes it go away; the write has to be structurally unavailable. Validating
    rather than merely echoing matters because the retry escalation keys off `failures`, so a
    proposal the user is shown is one that provably applies to the current bytes.
    """
    notes: list[str] = []
    failures: list = []
    any_applied = False
    any_attempted = False
    for rel_path, block_text in by_file.items():
        blocks = _parse_search_replace_blocks(block_text)
        if not blocks:
            continue
        any_attempted = True
        target = workspace / rel_path
        try:
            current = (
                target.read_text(encoding="utf-8", errors="replace") if target.exists() else ""
            )
        except OSError as e:
            notes.append(f"  {rel_path}: FAILED to read ({e})")
            continue
        updated, failed = _apply_search_replace_blocks(current, blocks)
        if updated != current:
            applied_n = len(blocks) - len(failed)
            if propose_only:
                if proposals is not None:
                    proposals.append({"path": rel_path, "before": current, "after": updated})
                any_applied = True
                notes.append(
                    f"  {rel_path}: PROPOSED {applied_n}/{len(blocks)} block(s) "
                    f"(not written -- awaiting your approval)"
                )
            else:
                try:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(updated, encoding="utf-8")
                    any_applied = True
                    notes.append(f"  {rel_path}: applied {applied_n}/{len(blocks)} block(s)")
                except OSError as e:
                    notes.append(f"  {rel_path}: FAILED to write ({e})")
        if failed:
            notes.append(f"  {rel_path}: {len(failed)} block(s) did not match and were skipped")
            failures.extend((rel_path, s) for s in failed)
    return any_applied, any_attempted, failures, notes


PROPOSAL_BEGIN = "<<<DETERMINEX_PROPOSED_EDITS"
PROPOSAL_END = "DETERMINEX_PROPOSED_EDITS>>>"


def _render_proposal(proposals: list) -> str:
    """Render validated-but-unwritten edits as a block the IDE can apply and a human can read.

    Carries the full before AND after bytes rather than a diff. Applying needs the exact `before` to
    check that the file has not moved under the proposal since it was made -- a stale proposal
    applied blind is a silent overwrite, which is the failure mode approval exists to prevent. A
    unified diff would have to be re-derived and re-matched to get the same guarantee.
    """
    payload = {
        "schema": "determinex-chat-proposed-edits-v1",
        "files": [
            {"path": p["path"], "before": p["before"], "after": p["after"]} for p in proposals
        ],
    }
    summary = "\n".join(
        f"  {p['path']}: {len(p['before'].splitlines())} -> {len(p['after'].splitlines())} lines"
        for p in proposals
    )
    return (
        f"[proposed changes -- NOT written, awaiting your approval]\n{summary}\n"
        f"{PROPOSAL_BEGIN}\n{json.dumps(payload)}\n{PROPOSAL_END}"
    )


def _format_feedback(response: str) -> str:
    """Correction prompt for a response that named a file but emitted no parseable
    block -- a FORMAT failure, distinct from a SEARCH block that simply didn't match.

    Small models get this wrong in a few specific, nameable ways, so name them.
    Observed live from a 1.5B model: `<<<` instead of `<<<SEARCH`, no `>>>REPLACE`
    terminator, and the corrected code placed in the SEARCH half.
    """
    return (
        "YOUR PREVIOUS ATTEMPT PRODUCED NO USABLE EDIT. You named a file, but the "
        "SEARCH/REPLACE block was malformed and nothing could be applied.\n"
        "The usual mistakes: writing `<<<` instead of `<<<SEARCH`; leaving out the "
        "closing `>>>REPLACE` line; or putting the NEW code in the SEARCH half.\n"
        "SEARCH must hold text ALREADY IN THE FILE (the buggy lines). REPLACE must "
        "hold the corrected lines. Emit exactly this, including every marker:\n\n"
        "### FILE: <path>\n<<<SEARCH\n<existing buggy lines>\n===\n"
        "<corrected lines>\n>>>REPLACE\n\n"
        "This is what you emitted, which could not be parsed:\n"
        f"{response[:600]}"
    )


def _build_feedback(failures: list) -> str:
    """Turn unmatched SEARCH blocks into the next attempt's correction prompt."""
    parts = [
        "YOUR PREVIOUS ATTEMPT FAILED. These SEARCH blocks matched nothing in the "
        "file, so they were skipped and that edit did NOT happen:"
    ]
    for rel, search in failures[:6]:
        parts.append(f"\n>>> did not match in {rel}:\n{search}")
    parts.append(
        "\nThe verbatim current contents are above. Copy the SEARCH text "
        "character-for-character out of them -- including indentation and any "
        "trailing comment on the line. Emit corrected blocks now."
    )
    return "\n".join(parts)


def run(
    task: str,
    workspace: Path,
    model: str,
    max_attempts: int = _MAX_ATTEMPTS,
    chat_mode: bool = False,
) -> tuple[str, int]:
    """prompt -> local model -> apply -> ON FAILURE, retry with the failure injected.

    WHY THERE IS A LOOP HERE NOW
    ---------------------------
    There wasn't one. This file was a stopgap to give the chat room a local
    participant, and a chat participant only had to talk -- so it generated once,
    applied what matched, and returned. The project's two real retry loops (the
    hive executor's compile gate, 5 attempts with errors re-injected; and the
    amplifier's best-of-K verified search) were never wired into it.

    That made `run_agent("local-ollama", ...)` an OPEN loop wearing a closed
    loop's clothes: run_agent does judge the result with the oracle afterwards,
    but nothing ever told the agent what the oracle found, so a weak model got
    exactly one guess. Now a failed apply feeds the unmatched SEARCH text and the
    file's real bytes back in, which is the same (error -> corrected retry) shape
    the rest of the system runs on -- and the same shape the WAL records as
    flywheel training pairs.
    """
    # _ollama's own 180s default is too short on constrained hardware --
    # live-measured 113s just to generate 2 tokens for a 14B model on a 6GB
    # card (see determinex_local_model_bench.py) -- reuse the same
    # measured/community/placeholder-tiered estimate the chat backend uses
    # for its own process-level timeout, rather than a second guessed number.
    timeout = _bench.estimate_timeout_seconds(model)
    ranked = _rank_paths(workspace, task)
    contents, shown = _render_file_contents(workspace, ranked)
    log: list[str] = []
    feedback = ""
    response = ""

    for attempt in range(1, max(1, max_attempts) + 1):
        prompt = _build_prompt(task, workspace, contents, shown, feedback, chat_mode=chat_mode)
        response = (
            _ollama(model, prompt, system=_SYSTEM_CHAT if chat_mode else _SYSTEM, timeout=timeout)
            or ""
        )
        if not response:
            return (
                "[local-agent] Ollama returned no response -- is it running and is "
                f"'{model}' pulled? (ollama pull {model})",
                1,
            )

        by_file = _split_by_file(response)
        if not by_file:
            # No edit blocks -- a discussion/reply turn, same as a cloud agent
            # that only talks. Not a failure, so not retried.
            return (response, 0)

        proposals: list = []
        any_applied, any_attempted, failures, notes = _apply_edits(
            by_file, workspace, propose_only=chat_mode, proposals=proposals
        )
        log.append(f"--- attempt {attempt}/{max_attempts} ---")
        log.extend(notes)

        if not any_attempted:
            # The model named a file but emitted nothing PARSEABLE. Returning 0
            # here (which the first version of this loop did) reported success
            # while changing not one byte -- the same false-success shape the
            # oracle exists to prevent. It is a format failure: retry and say so.
            #
            # This holds in chat mode too, and an earlier version of this fix got it wrong by
            # returning (response, 0) here. Measured: asked in a chat to change main.rs, the model
            # emitted the right change as a ```diff hunk -- correct intent, wrong syntax, nothing
            # applied -- and rc=0 reported a successful turn over an unmodified file. That is the
            # false success this branch exists to prevent, so chat mode does not get an exemption.
            #
            # A conversational reply never reaches here: with no `### FILE:` header at all it
            # returns above as talk. Arriving here means the model named a file, which is edit
            # intent, and the retry below hands it the exact marker format (see _format_feedback) --
            # which is how an edit asked for in chat still lands even though the first, deliberately
            # conversational, prompt never showed the syntax.
            log.append("  (no parseable SEARCH/REPLACE block -- malformed markers)")
            if attempt >= max_attempts:
                break
            feedback = _format_feedback(response)
            continue

        if not failures:
            if chat_mode and proposals:
                # A chat turn ends with a PROPOSAL, never a write. The block is machine-readable so
                # the IDE can render a diff and apply it on the user's word (see
                # determinex_agent_chat.py apply-proposal), and human-readable so the turn still
                # says something useful in a transcript that has no button attached to it.
                return ("\n".join([response, "", _render_proposal(proposals), ""] + log), 0)
            return ("\n".join([response, ""] + log), 0 if any_applied else 1)
        if attempt >= max_attempts:
            break
        # Re-read from disk: a partial apply means the bytes the next attempt has
        # to match are no longer the ones already in the prompt.
        feedback = _build_feedback(failures)
        contents, shown = _render_file_contents(workspace, ranked)

    log.append(f"[local-agent] {max_attempts} attempts exhausted without a clean edit")
    return ("\n".join([response, ""] + log), 1)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Local Ollama-driven agent (no external CLI dependency)"
    )
    parser.add_argument("task", nargs="?", default=None)
    parser.add_argument(
        "--task-file",
        default=None,
        help="read the task prompt from this file instead of the positional arg -- "
        "a large prompt (mission plan + transcript window) as a raw CLI argument "
        "can exceed Windows' command-line length limit (os error 206, "
        "ERROR_FILENAME_EXCED_RANGE)",
    )
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--model", default=_DEFAULT_MODEL)
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=_MAX_ATTEMPTS,
        help="retries when a SEARCH block matches nothing; each retry "
        "gets the unmatched text and the file's real bytes injected",
    )
    parser.add_argument(
        "--chat",
        action="store_true",
        help="conversational turn in the multi-agent chat room: reply in prose by "
        "default and only edit files when asked. Without this the agent is "
        "told its job is editing, so a plain answer comes back dressed in "
        "SEARCH/REPLACE syntax, gets graded as a malformed patch, and the "
        "turn fails with the right answer inside it",
    )
    args = parser.parse_args()

    if args.task_file:
        task = Path(args.task_file).read_text(encoding="utf-8", errors="replace")
    elif args.task is not None:
        task = args.task
    else:
        parser.error("either the task positional or --task-file is required")

    # An explicitly-passed-but-empty `--model ""` beats argparse's default
    # (a default only applies when the flag is absent), which would send an
    # empty model name to Ollama and 404. Callers that have no model selected
    # should omit the flag, but treat empty as "use the default" here too so a
    # regression upstream can never resurrect that failure mode.
    model = args.model.strip() if args.model else ""
    summary, code = run(
        task,
        Path(args.workspace),
        model or _DEFAULT_MODEL,
        max_attempts=args.max_attempts,
        chat_mode=args.chat,
    )
    print(summary)
    return code


if __name__ == "__main__":
    sys.exit(main())
