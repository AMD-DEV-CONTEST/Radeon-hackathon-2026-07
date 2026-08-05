"""learning_studio_content.py -- grounds the 9 Learning Studio modes in the verified corpus.

Rung 7 of DETERMINEX_LIVE_REACT_UNIFIED_PRODUCT_SHELL_SERIES (content generation). Rung 6
(learning_studio_workflow.py) only validated a supplied LearningStudioOutput for non-authorizing
compliance; nothing ever produced one. This module is the producer.

Every mode's output is built ONLY from real corpus (determinex_corpus_api) or real filesystem
data -- if nothing grounds an answer, the output SAYS SO instead of fabricating a plausible-
sounding filler. This is the same anti-slop discipline the rest of the correctness substrate
uses: an ungrounded claim is worse than an honest "I don't know yet".

generate() returns a LearningStudioOutput. The CALLER (backend_command_surface) must still run
it through learning_studio_workflow.evaluate() before it reaches the frontend -- this module
never claims non-authorizing compliance for itself.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Callable
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import determinex_corpus_api as corpus  # noqa: E402

from .learning_studio_workflow_record import LearningStudioOutput  # noqa: E402

MAX_HITS = 5


def _hits_block(hits: list) -> str:
    if not hits:
        return "(no matching corpus knowledge found for this input)"
    return "\n".join(f"  * [{h.source}] {h.title}: {h.snippet}" for h in hits[:MAX_HITS])


def _warnings_block(warnings: list[str]) -> str:
    """Renders corpus.ask()'s supersession warnings, if any -- the whole point of using
    ask() instead of raw search() here: a learner should never be quietly handed a
    corrected/invalidated corpus entry as if it were still true."""
    if not warnings:
        return ""
    return "\n\nCORPUS CAUTION:\n" + "\n".join(f"  ! {w}" for w in warnings)


def _input_text(context: dict, *keys: str) -> str:
    for k in keys:
        v = context.get(k)
        if v:
            return str(v).strip()
    return ""


def _explain_error(context: dict) -> LearningStudioOutput:
    text = _input_text(context, "text", "error_text")
    if not text:
        return LearningStudioOutput(
            mode="explain_this_error",
            text="No error text provided. Paste the error/traceback to search the verified "
            "corpus for a known cause and fix.",
        )
    asked = corpus.ask(text)
    hits = asked.hits[:MAX_HITS]
    class_hits = [h for h in hits if h.source in ("class_pattern", "learned_class")]
    if class_hits:
        top = class_hits[0]
        body = (
            f"Matched known failure class '{top.title}' (source: {top.source}).\n"
            f"  likely fix: {top.snippet}\n\nOther corpus matches:\n{_hits_block(hits)}"
            f"{_warnings_block(asked.warnings)}"
        )
        return LearningStudioOutput(
            mode="explain_this_error", text=body, suggests_fix=True, routes_to="repo_clinic"
        )
    if hits:
        return LearningStudioOutput(
            mode="explain_this_error",
            text=f"No exact known-fix class matched, but related corpus context was found:\n"
            f"{_hits_block(hits)}{_warnings_block(asked.warnings)}",
        )
    return LearningStudioOutput(
        mode="explain_this_error",
        text="No corpus match for this error. This system does not fabricate an explanation it "
        "cannot ground -- try Repo Clinic's diagnose flow for a live, oracle-backed diagnosis.",
    )


def _explain_test_failure(context: dict) -> LearningStudioOutput:
    inner = _explain_error({**context, "text": _input_text(context, "text", "failure_text")})
    return LearningStudioOutput(
        mode="explain_this_test_failure",
        text=inner.text,
        suggests_fix=inner.suggests_fix,
        routes_to=inner.routes_to,
    )


def _teach_concept(context: dict) -> LearningStudioOutput:
    concept = _input_text(context, "text", "concept")
    if not concept:
        return LearningStudioOutput(
            mode="teach_me_the_concept",
            text="Name a concept (e.g. 'go build target', 'cgo sqlite', 'oracle verification') "
            "to pull its corpus lesson.",
        )
    asked = corpus.ask(concept)
    hits = asked.hits[:MAX_HITS]
    if not hits:
        return LearningStudioOutput(
            mode="teach_me_the_concept",
            text=f"No corpus entry teaches '{concept}' yet. Nothing fabricated -- this concept "
            "isn't in the verified corpus.",
        )
    related = asked.top_hit_related
    related_block = ""
    if related["inbound"] or related["outbound"]:
        parts = []
        if related["inbound"]:
            parts.append(f"referenced BY: {', '.join(related['inbound'][:5])}")
        if related["outbound"]:
            parts.append(f"references: {', '.join(related['outbound'][:5])}")
        related_block = f"\n\nRELATED CORPUS ENTRIES ({hits[0].key}) -- {'; '.join(parts)}"
    return LearningStudioOutput(
        mode="teach_me_the_concept",
        text=f"What the verified corpus knows about '{concept}':\n{_hits_block(hits)}"
        f"{related_block}{_warnings_block(asked.warnings)}",
    )


def _compare_fixes(context: dict) -> LearningStudioOutput:
    symptom = _input_text(context, "text", "symptom")
    if not symptom:
        return LearningStudioOutput(
            mode="compare_possible_fixes",
            text="Describe the symptom to compare known fixes for it.",
        )
    hits = [
        h for h in corpus.search(symptom, limit=8) if h.source in ("class_pattern", "learned_class")
    ]
    if not hits:
        return LearningStudioOutput(
            mode="compare_possible_fixes",
            text="No alternative known fixes found in the verified corpus for this symptom.",
        )
    lines = [f"{i + 1}. [{h.source}] {h.title} -> {h.snippet}" for i, h in enumerate(hits[:5])]
    return LearningStudioOutput(
        mode="compare_possible_fixes",
        text="Known fixes for comparison, ranked by relevance:\n" + "\n".join(lines),
        suggests_fix=True,
        routes_to="repo_clinic",
    )


_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@")


def _walk_patch(context: dict) -> LearningStudioOutput:
    diff = _input_text(context, "text", "diff", "patch")
    if not diff:
        return LearningStudioOutput(
            mode="walk_me_through_the_patch",
            text="Paste a unified diff to get a per-hunk walkthrough.",
        )
    added = removed = 0
    walk_lines: list[str] = []
    for ln in diff.splitlines():
        if ln.startswith("+++ "):
            walk_lines.append(f"File: {ln[4:].strip()}")
        elif _HUNK_RE.match(ln):
            walk_lines.append(f"  Hunk {ln.strip()}")
        elif ln.startswith("+") and not ln.startswith("+++"):
            added += 1
        elif ln.startswith("-") and not ln.startswith("---"):
            removed += 1
    if not walk_lines:
        return LearningStudioOutput(
            mode="walk_me_through_the_patch",
            text="Input did not parse as a unified diff (expected '--- '/'+++ '/'@@ ' headers).",
        )
    summary = f"{added} line(s) added, {removed} line(s) removed across the patch."
    return LearningStudioOutput(
        mode="walk_me_through_the_patch",
        text="Structural walkthrough (mechanical, from the diff itself -- not a semantic review):\n"
        + "\n".join(walk_lines)
        + f"\n\n{summary}",
    )


def _beginner_vs_pro(context: dict) -> LearningStudioOutput:
    concept = _input_text(context, "text", "concept")
    if not concept:
        return LearningStudioOutput(
            mode="show_beginner_vs_professional_version",
            text="Name a concept to get both a beginner and a professional rendering.",
        )
    hits = corpus.search(concept, limit=MAX_HITS)
    if not hits:
        return LearningStudioOutput(
            mode="show_beginner_vs_professional_version",
            text=f"No corpus grounding for '{concept}' yet -- nothing to render at either level.",
        )
    top = hits[0]
    beginner = f"In plain terms: {top.snippet}"
    pro = f"[{top.source}:{top.key}] {top.snippet} (matched {len(hits)} corpus entries; top score {top.score})"
    return LearningStudioOutput(
        mode="show_beginner_vs_professional_version",
        text=f"BEGINNER VERSION:\n  {beginner}\n\nPROFESSIONAL VERSION:\n  {pro}",
    )


def _checklist(context: dict) -> LearningStudioOutput:
    topic = _input_text(context, "text", "topic")
    if topic and topic.upper() in corpus.topics():
        rows = corpus.topic_entries(topic.upper())
        if rows:
            items = [f"[ ] {r['key']}: {r['summary'] or '(see full entry)'}" for r in rows[:12]]
            return LearningStudioOutput(
                mode="generate_learning_checklist",
                text=f"Checklist derived from topic '{topic.upper()}':\n" + "\n".join(items),
            )
    hits = corpus.search(topic, limit=8) if topic else []
    if hits:
        items = [f"[ ] {h.title}: {h.snippet}" for h in hits]
        return LearningStudioOutput(
            mode="generate_learning_checklist",
            text="Checklist derived from matching corpus entries:\n" + "\n".join(items),
        )
    return LearningStudioOutput(
        mode="generate_learning_checklist",
        text=f"Name a topic ({', '.join(corpus.topics())}) or a keyword to generate a checklist "
        "from the verified corpus.",
    )


_DEF_RE = re.compile(r"^\s*(?:def|class|fn|func|function|pub fn)\s+([A-Za-z_]\w*)", re.M)


def _explain_file(context: dict) -> LearningStudioOutput:
    path = _input_text(context, "path", "text")
    if not path or not Path(path).is_file():
        return LearningStudioOutput(
            mode="explain_this_file",
            text="Provide a real file path to get a structural summary (line count, top-level defs).",
        )
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return LearningStudioOutput(mode="explain_this_file", text=f"Could not read file: {e}")
    n_lines = text.count("\n") + 1
    defs = _DEF_RE.findall(text)
    body = (
        f"{p.name}: {n_lines} lines, {len(defs)} top-level def/class/fn found.\n"
        "Structural summary only (not a semantic walkthrough): "
        + (", ".join(defs[:20]) if defs else "no def/class/fn pattern matched")
    )
    return LearningStudioOutput(mode="explain_this_file", text=body)


def _explain_repo(context: dict) -> LearningStudioOutput:
    ws = _input_text(context, "workspace", "path", "text")
    if not ws or not Path(ws).is_dir():
        return LearningStudioOutput(
            mode="explain_this_repo",
            text="Provide a real workspace path to get a structural summary of the repo layout.",
        )
    p = Path(ws)
    top_dirs = sorted(d.name for d in p.iterdir() if d.is_dir() and not d.name.startswith("."))[:20]
    readme_note = ""
    readme = next(iter(p.glob("README*")), None)
    if readme is not None:
        try:
            first_lines = readme.read_text(encoding="utf-8", errors="replace").strip().splitlines()
            readme_note = first_lines[0][:200] if first_lines else ""
        except Exception:
            pass
    body = f"Top-level directories: {', '.join(top_dirs) or '(none)'}\n"
    if readme_note:
        body += f"README first line: {readme_note}\n"
    body += "Structural summary only (directory layout + README headline) -- not a semantic code review."
    return LearningStudioOutput(mode="explain_this_repo", text=body)


_GENERATORS: dict[str, Callable[[dict], LearningStudioOutput]] = {
    "explain_this_repo": _explain_repo,
    "explain_this_file": _explain_file,
    "explain_this_error": _explain_error,
    "explain_this_test_failure": _explain_test_failure,
    "teach_me_the_concept": _teach_concept,
    "compare_possible_fixes": _compare_fixes,
    "walk_me_through_the_patch": _walk_patch,
    "show_beginner_vs_professional_version": _beginner_vs_pro,
    "generate_learning_checklist": _checklist,
}


def generate(mode: str, context: dict | None = None) -> LearningStudioOutput:
    ctx = context or {}
    fn = _GENERATORS.get(mode)
    if fn is None:
        return LearningStudioOutput(mode=mode, text=f"Unknown learning mode: {mode!r}")
    return fn(ctx)


__all__ = ["generate"]
