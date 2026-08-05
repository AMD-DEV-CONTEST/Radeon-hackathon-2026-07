#!/usr/bin/env python3
"""
idea_oracle.py — Discovery conversation before spec generation

Replaces the "instant MD spec" approach with a guided conversation:
  --mode discover  : Analyze raw idea → return path cards + opening Oracle message
  --mode converse  : Continue conversation → Oracle response + ready-to-spec flag
                     Full conversation history is read from stdin as JSON array

When ready_to_spec=True, the frontend calls spec_generator.py with the full
conversation context so the spec is written once, informed by everything.
"""

import argparse
import json
import sys
from pathlib import Path

import litellm

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_SCRIPT_DIR))
sys.path.insert(0, str(_PROJECT_ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(_PROJECT_ROOT / ".env", override=False)
except ImportError:
    pass

try:
    from scripts.hive.api_client import api_call, load_role_assignments
except ImportError:
    from hive.api_client import api_call, load_role_assignments


# ─────────────────────────────────────────────────────────────────────────────
# DISCOVER MODE — analyze the idea, return path cards + opening question
# ─────────────────────────────────────────────────────────────────────────────

DISCOVER_SYSTEM = """You are the Oracle for the Determinex Hive Mind — a senior software architect helping users clarify their vision before any code is written.

Analyze the user's raw idea and return ONLY valid JSON. No markdown, no text outside the JSON:

{
  "paths": [
    {
      "id": "unique-slug",
      "name": "Path Name",
      "description": "One sentence: what this is and what it does for the user",
      "bestFor": "One short phrase: ideal when...",
      "stack": "Primary tech (e.g. Rust CLI)",
      "complexity": "low|medium|high",
      "buildTime": "e.g. 1-2 days",
      "color": "#hexcolor"
    }
  ],
  "message": "One sentence acknowledging their idea specifically. Then ask the ONE question that most determines the right direction. Be direct, not chatty.",
  "questions": ["The single most important clarifying question"]
}

Generate 3 to 5 paths representing genuinely different approaches.
Colors: cli tool=#fb923c, api/backend=#34d399, web app=#00e5ff, desktop=#f59e0b, data=#f472b6, mobile app=#c084fc, web+mobile=#2dd4bf
Complexity: low=days to 1 week, medium=1-4 weeks, high=months

SCOPE RULE:
- Honor the user's requested surface before any simplicity default.
- If the user asks for website, web app, browser app, dashboard, portal, or frontend, include Web App.
- If the user asks for mobile, phone, iOS, Android, native app, app store, or play store, include Mobile App.
- If the user asks for both web/website and mobile/app, the FIRST path must be Web + Mobile App with a shared backend.
- Suggest CLI Tool only when the user explicitly asks for CLI, command-line, terminal, shell, or console behavior.
- Suggest API/backend when the user mentions server, API, backend, endpoint, multiple users, auth, or a web/mobile client.
- Only suggest database if the user explicitly mentions accounts, persistence, records, sync, or scale.
- For personal tools with no product surface: JSON file persistence is a fine default."""


def _build_user_content(text: str, attachments: list) -> "str | list":
    """Return plain text or a multimodal content list depending on attachments."""
    images = [a for a in (attachments or []) if a.get("mime_type", "").startswith("image/")]
    if not images:
        return text
    content = [{"type": "text", "text": text}]
    for img in images:
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{img['mime_type']};base64,{img['data']}"},
            }
        )
    return content


_PATH_TEMPLATES = {
    "Web + Mobile App": {
        "id": "web-mobile",
        "name": "Web + Mobile App",
        "description": "A shared product delivered as a website plus mobile applications.",
        "bestFor": "cross-platform products with accounts, sync, and shared workflows",
        "stack": "Next.js + API + React Native or Flutter",
        "complexity": "high",
        "buildTime": "3-6 weeks",
        "color": "#2dd4bf",
    },
    "Web App": {
        "id": "web-app",
        "name": "Web App",
        "description": "A browser-based application with screens, workflows, and persistent state.",
        "bestFor": "public sites, dashboards, portals, and SaaS workflows",
        "stack": "Next.js + TypeScript",
        "complexity": "medium",
        "buildTime": "1-2 weeks",
        "color": "#00e5ff",
    },
    "Mobile App": {
        "id": "mobile-app",
        "name": "Mobile App",
        "description": "A phone-first application for iOS, Android, or both.",
        "bestFor": "native or cross-platform mobile experiences",
        "stack": "React Native, Flutter, Swift, or Kotlin",
        "complexity": "high",
        "buildTime": "2-4 weeks",
        "color": "#c084fc",
    },
    "Backend API": {
        "id": "api",
        "name": "Backend API",
        "description": "A service layer for app data, auth, integrations, and shared business logic.",
        "bestFor": "web/mobile clients and integrations needing a server",
        "stack": "FastAPI, Axum, Gin, or Express",
        "complexity": "medium",
        "buildTime": "1-2 weeks",
        "color": "#34d399",
    },
    "CLI Tool": {
        "id": "cli",
        "name": "CLI Tool",
        "description": "A command-line tool for scripted or terminal-driven workflows.",
        "bestFor": "developers and power users",
        "stack": "Rust, Go, Python, or Node",
        "complexity": "low",
        "buildTime": "1-3 days",
        "color": "#fb923c",
    },
    "Data Pipeline": {
        "id": "data-pipeline",
        "name": "Data Pipeline",
        "description": "A repeatable ingest, transform, validate, and export workflow.",
        "bestFor": "ETL, reporting, sync jobs, and event processing",
        "stack": "Python + SQL + scheduler",
        "complexity": "medium",
        "buildTime": "3-7 days",
        "color": "#f472b6",
    },
}


def _requested_types(idea: str) -> list[str]:
    import re

    text = idea.lower()
    wants_web = bool(
        re.search(
            r"\b(web ?site|site|web app|webapp|frontend|browser|dashboard|portal|landing page|saas)\b",
            text,
        )
    )
    wants_mobile = bool(
        re.search(
            r"\b(mobile|phone|ios|android|native app|mobile app|app store|play store)\b", text
        )
    )
    wants_cli = bool(
        re.search(r"\b(cli|command.?line|terminal tool|shell command|console app)\b", text)
    )
    wants_api = bool(
        re.search(
            r"\b(api|backend|server|service|endpoint|auth|login|account|sync|rest|graphql)\b", text
        )
    )
    wants_pipeline = bool(
        re.search(r"\b(pipeline|etl|ingest|stream|warehouse|data flow|dataflow)\b", text)
    )

    types: list[str] = []
    if wants_web and wants_mobile:
        types.append("Web + Mobile App")
    if wants_web:
        types.append("Web App")
    if wants_mobile:
        types.append("Mobile App")
    if wants_api or wants_web or wants_mobile:
        types.append("Backend API")
    if wants_pipeline:
        types.append("Data Pipeline")
    if wants_cli:
        types.append("CLI Tool")
    return list(dict.fromkeys(types))


def _dedupe_paths(paths: list) -> list:
    """One card per direction, always.

    Dedup used to live INSIDE `_merge_intent_paths`, which early-returns when no intent regex
    matched -- so on any idea the regexes did not recognise, the model's raw paths passed
    through untouched and a model that emitted "CLI Tool" twice rendered two identical cards.
    Seen live. Normalised on the name so "CLI Tool" and "Command-Line Tool" collapse, while a
    genuinely different direction like "Calendar Merge CLI Tool" survives.
    """
    seen: set[str] = set()
    out = []
    for path in paths:
        if not isinstance(path, dict):
            continue
        raw = str(path.get("name", "")).strip().lower()
        if not raw:
            continue
        key = raw.replace("command-line", "cli").replace("command line", "cli")
        if key in seen:
            continue
        seen.add(key)
        out.append(path)
    return out


def narrow_paths(paths: list, idea: str, answers: list) -> dict:
    """Re-rank and RULE OUT directions as the interview answers arrive.

    Ryan, 2026-08-03: *"that top part of the setup... needs to change to where they can be
    opened or selected based on the answers and it narrows down as the user answers
    questions."*

    Directions were computed once, at discovery, from the one-line idea and never touched
    again -- so a user could answer "no, this is terminal only, nobody opens a browser" and
    still be staring at "Web + Mobile App, 3-6 weeks, high". The grid asked for a decision it
    then ignored.

    Deterministic on purpose. This is the same intent extraction that produced the cards,
    re-run over the idea PLUS everything the user has since said, so a direction survives only
    while the accumulated text still supports it. No model is consulted: a narrowing that a
    model could hallucinate away is worse than no narrowing, because the user watched their
    own answer remove the wrong card.

    Returns `{"paths": [...], "ruled_out": [{"name", "why"}], "reason": str}` -- what was
    removed is returned, not silently dropped, so the UI can say WHY a card disappeared. A
    card that vanishes without explanation reads as a bug.
    """
    kept = _dedupe_paths([p for p in paths if isinstance(p, dict)])
    said = " ".join([idea] + [str(a) for a in answers if a]).strip()
    if not said or not kept:
        return {"paths": kept, "ruled_out": [], "reason": "nothing to narrow on yet"}

    supported = set(_requested_types(said))
    if not supported:
        # The answers say nothing the extractor recognises. Removing everything on that basis
        # would be inventing a decision the user never made.
        return {"paths": kept, "ruled_out": [], "reason": "answers do not yet name a surface"}

    # An explicit negation removes a direction even when the word appears -- "no mobile app"
    # must not keep Mobile App alive merely by containing "mobile".
    import re as _re

    negated: set[str] = set()
    for name, pat in (
        ("Mobile App", r"\b(no|not|without|skip|never)\b[^.]{0,30}\b(mobile|ios|android|phone)\b"),
        ("Web App", r"\b(no|not|without|skip|never)\b[^.]{0,30}\b(web|browser|site|dashboard)\b"),
        ("CLI Tool", r"\b(no|not|without|skip|never)\b[^.]{0,30}\b(cli|command.?line|terminal)\b"),
        ("Backend API", r"\b(no|not|without|skip|never)\b[^.]{0,30}\b(api|backend|server)\b"),
    ):
        if _re.search(pat, said.lower()):
            negated.add(name)

    def _negated(name: str) -> bool:
        """A negated component also kills any COMPOSITE that contains it.

        "no mobile app" removed `Mobile App` and left `Web + Mobile App` standing -- which is
        the same direction wearing a longer name, so the user's answer visibly did nothing.
        """
        if name in negated:
            return True
        return any(part in name for part in ("Mobile", "Web", "CLI") if f"{part} App" in negated
                   or (part == "CLI" and "CLI Tool" in negated))

    ruled_out = []
    survivors = []
    for path in kept:
        name = str(path.get("name", ""))
        if _negated(name):
            ruled_out.append({"name": name, "why": "you said this is not part of it"})
            continue
        # Keep anything the accumulated text still supports, plus anything the extractor has
        # no opinion about (a bespoke direction the model proposed is not ruled out just
        # because a regex does not know the word for it).
        if name in supported or name not in _PATH_TEMPLATES:
            survivors.append(path)
        else:
            ruled_out.append({"name": name, "why": "nothing you have said points at this"})

    if not survivors:
        return {
            "paths": kept,
            "ruled_out": [],
            "reason": "narrowing would have removed every direction, so nothing was removed",
        }

    order = {n: i for i, n in enumerate(_requested_types(said))}
    survivors.sort(key=lambda p: order.get(str(p.get("name", "")), 99))
    return {
        "paths": survivors,
        "ruled_out": ruled_out,
        "reason": (
            f"{len(survivors)} direction(s) still fit what you have told me"
            + (f"; {len(ruled_out)} ruled out" if ruled_out else "")
        ),
    }


def _merge_intent_paths(result: dict, idea: str) -> dict:
    requested = _requested_types(idea)
    if not requested:
        result = dict(result)
        result["paths"] = _dedupe_paths(result.get("paths", []))
        return result

    requested_paths = [dict(_PATH_TEMPLATES[name]) for name in requested if name in _PATH_TEMPLATES]
    model_paths = [p for p in result.get("paths", []) if isinstance(p, dict)]
    if "CLI Tool" not in requested:
        model_paths = [
            p
            for p in model_paths
            if str(p.get("name", "")).lower() not in {"cli tool", "command-line tool"}
        ]

    merged = _dedupe_paths(requested_paths + model_paths)

    result = dict(result)
    result["paths"] = merged[:5]
    if requested[0] == "Web + Mobile App":
        result["message"] = (
            "You asked for both a website and mobile applications. I will treat this as a cross-platform product, not a CLI tool."
        )
        result["questions"] = [
            "Should the website and mobile apps share one account system and backend?"
        ]
    return result


def _discover_fallback_for(idea: str) -> dict:
    if _requested_types(idea):
        return _merge_intent_paths(
            {
                "paths": [],
                "message": "I found the product surfaces in your idea. Which direction should we build first?",
                "questions": [
                    "Which surface should be first: shared web+mobile, web, mobile, or backend?"
                ],
            },
            idea,
        )
    return {
        "paths": [dict(_PATH_TEMPLATES["CLI Tool"]), dict(_PATH_TEMPLATES["Backend API"])],
        "message": "Tell me more about what you want to build and I'll ask the right questions.",
        "questions": ["What should this do for you day-to-day?"],
    }


def discover(idea: str, attachments: list = None) -> dict:
    import re as _re

    roles = load_role_assignments()
    oracle_model = roles.get("oracle", "openai/gpt-4o")

    user_text = f"USER IDEA:\n{idea}\n\nReturn JSON analysis:"
    user_content = _build_user_content(user_text, attachments or [])

    try:
        response = api_call(
            litellm.completion,
            model=oracle_model,
            messages=[
                {"role": "system", "content": DISCOVER_SYSTEM},
                {"role": "user", "content": user_content},
            ],
            temperature=0.4,
            estimated_tokens=900,
        )
        raw = (response.choices[0].message.content or "").strip()
    except Exception:
        return _discover_fallback_for(idea)

    # Strip markdown fences if model wrapped output
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    # Try to extract the first complete JSON object/array if full parse fails
    result = None
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        m = _re.search(r"\{.*\}", raw, _re.DOTALL)
        if m:
            try:
                result = json.loads(m.group(0))
            except json.JSONDecodeError:
                pass

    # Normalize: small models sometimes return a bare array instead of the wrapper object
    if isinstance(result, list):
        result = {
            "paths": result,
            "message": "Here are some directions we could take this. Which fits what you have in mind?",
            "questions": ["Which of these directions fits what you have in mind?"],
        }

    # Ensure message key is always present
    if isinstance(result, dict) and "message" not in result:
        result["message"] = "Which of these directions fits what you have in mind?"

    # Final fallback: return deterministic intent-aware paths so the UI never crashes.
    if not result or "paths" not in result:
        return _discover_fallback_for(idea)
    return _merge_intent_paths(result, idea)


# ─────────────────────────────────────────────────────────────────────────────
# CONVERSE MODE — back and forth until Oracle has full clarity
# ─────────────────────────────────────────────────────────────────────────────

CONVERSE_SYSTEM = """You are a senior software architect. Your ONLY job is to ask ONE clarifying question per turn, then generate a spec when you have enough.

Reply with ONLY valid JSON — no text outside it:
{"response": "One sentence acknowledging what they said. Then ONE question.", "ready_to_spec": false, "spec_summary": null}

When ready (see TURN LIMIT rule below), reply:
{"response": "Perfect, writing your spec now.", "ready_to_spec": true, "spec_summary": "Platform: X. Features: A, B, C. Stack: Y. Constraints: Z."}

RULES:
- Ask ONE question per turn — never two.
- Do NOT re-ask about topics already answered in the conversation. Read the history carefully.
- Ask questions in this order (skip any already answered): (1) product surface/platform, (2) core user actions, (3) data/auth/sync, (4) any hard constraints.
- TURN LIMIT: If the user has answered 3 or more times, ALWAYS set ready_to_spec: true. Do not ask more questions — you have enough.
- Do not convert website, web app, mobile app, dashboard, SaaS, or cross-platform product requests into CLI tools.
- Default to simple CLI only when the user explicitly asked for CLI, command-line, terminal, shell, or console behavior.
- ONLY valid JSON. Nothing outside the JSON object."""


def converse(idea: str, messages: list, user_message: str, attachments: list = None) -> dict:
    roles = load_role_assignments()
    oracle_model = roles.get("oracle", "openai/gpt-4o")

    # Count how many times the user has already replied (user turns in history, excluding the current one)
    user_turn_count = sum(1 for m in messages if m.get("role") == "user")

    # READINESS IS MEASURED, NOT COUNTED.
    #
    # This used to be `if user_turn_count >= 2: ready_to_spec = True`, commented "The 3B
    # model reliably loops on the 3rd exchange; cut it off here." That diagnosis was right
    # and the remedy traded the user's spec for the model's stamina: two answers to a
    # five-answer problem produced a confident build of the wrong thing, and the compiler
    # oracle certified it, because compiling is not the same as being what was asked for.
    #
    # `idea_context.assess_round` asks the question that actually matters -- can a SOUND
    # ORACLE be synthesized from what we have been told? -- using the same synthesizer that
    # will later build it, so the interview's notion of "enough" cannot drift from the
    # verifier's. The loop the cap was protecting against is handled directly: follow-ups
    # come from a deterministic checklist of what is ABSENT, so a question can only be asked
    # while the thing it asks for is genuinely missing, and a round that establishes nothing
    # new is reported as `stalled` rather than rephrased.
    from idea_context import assess_round

    answers = [m.get("text", "") for m in messages if m.get("role") == "user"]
    answers.append(user_message)
    asked = [m.get("text", "") for m in messages if m.get("role") != "user"]
    assessment = assess_round(idea, answers, asked)

    # NARROW THE DIRECTIONS AS THE ANSWERS ARRIVE. Ryan, 2026-08-03: "that top part of the
    # setup... needs to change to where they can be opened or selected based on the answers
    # and it narrows down as the user answers questions." The cards were computed once at
    # discovery and never touched, so a user could say "terminal only, no browser" and keep
    # staring at "Web + Mobile App, 3-6 weeks, high" -- the grid asked for a decision and then
    # ignored it. Attached to EVERY return below so the UI can update on any reply, not only
    # the ones that end the interview.
    _narrowed = narrow_paths(
        [dict(_PATH_TEMPLATES[n]) for n in _requested_types(idea) if n in _PATH_TEMPLATES]
        or [dict(v) for v in _PATH_TEMPLATES.values()],
        idea,
        answers,
    )

    if assessment.sufficient or assessment.stalled:
        history_summary = " | ".join(a[:80] for a in answers if a)
        if assessment.sufficient:
            response = f"Got it — I have enough to write your spec ({assessment.rationale})."
        else:
            # Stalled: say so plainly and hand the choice back. Grinding through rephrased
            # questions is what made a hard cap look reasonable in the first place.
            still = ", ".join(assessment.missing[:3])
            response = (
                "We're going in circles — the last round didn't add anything new. "
                f"I can still write the spec, but I don't have: {still}. "
                "Add any of that and I'll fold it in, or say 'go' and I'll build with what we have."
            )
        return {
            "response": response,
            "ready_to_spec": True,
            "paths": _narrowed["paths"],
            "ruled_out": _narrowed["ruled_out"],
            "context_sufficient": assessment.sufficient,
            "context_missing": assessment.missing,
            "context_rationale": assessment.rationale,
            "spec_summary": (
                f"Idea: {idea[:200]}. User clarifications: {history_summary}. "
                f"Latest: {user_message[:200]}."
            ),
        }

    # Format conversation history for the model
    history_lines = []
    for msg in messages:
        role = "User" if msg.get("role") == "user" else "Oracle"
        history_lines.append(f"{role}: {msg.get('text', '')}")
    history_text = "\n\n".join(history_lines)

    # Inject a "topics already covered" hint so the model doesn't loop
    covered_hint = ""
    if user_turn_count > 0:
        covered_hint = (
            f"\n\nIMPORTANT: The user has already answered {user_turn_count} question(s). "
            "Do NOT ask about the same topic again. Read the history above and ask about something NEW."
        )

    user_text = (
        f"ORIGINAL IDEA: {idea}\n\n"
        f"CONVERSATION SO FAR:\n{history_text}\n\n"
        f"USER'S LATEST REPLY: {user_message}"
        f"{covered_hint}\n\n"
        "Return your JSON response:"
    )
    user_content = _build_user_content(user_text, attachments or [])

    try:
        response = api_call(
            litellm.completion,
            model=oracle_model,
            messages=[
                {"role": "system", "content": CONVERSE_SYSTEM},
                {"role": "user", "content": user_content},
            ],
            temperature=0.3,
            estimated_tokens=700,
        )
        raw = (response.choices[0].message.content or "").strip()
    except Exception:
        return {
            "response": "Could you tell me more about what you have in mind?",
            "ready_to_spec": False,
            "paths": _narrowed["paths"],
            "ruled_out": _narrowed["ruled_out"],
            "spec_summary": None,
        }

    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()
    try:
        result = json.loads(raw)
        # The model's reply is the COMMON path, and it was the one return that did not carry
        # the narrowed directions -- so on a normal turn the grid still never updated. The
        # narrowing is deterministic and computed above; the model does not get to overwrite
        # it, because a card the user's own answer removed must not reappear because a model
        # felt like mentioning it.
        result["paths"] = _narrowed["paths"]
        result["ruled_out"] = _narrowed["ruled_out"]
        return result
    except (json.JSONDecodeError, Exception):
        return {
            "response": raw if raw else "Could you tell me more about what you have in mind?",
            "ready_to_spec": False,
            "paths": _narrowed["paths"],
            "ruled_out": _narrowed["ruled_out"],
            "spec_summary": None,
        }


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Oracle discovery conversation.")
    parser.add_argument("--mode", required=True, choices=["discover", "converse"])
    args = parser.parse_args()

    # Both modes now receive full payload JSON via stdin (supports large image data)
    stdin_raw = sys.stdin.read().strip()
    payload = json.loads(stdin_raw) if stdin_raw else {}

    try:
        if args.mode == "discover":
            result = discover(
                idea=payload.get("idea", ""),
                attachments=payload.get("attachments") or [],
            )
        else:
            result = converse(
                idea=payload.get("idea", ""),
                messages=payload.get("messages") or [],
                user_message=payload.get("user_message", ""),
                attachments=payload.get("attachments") or [],
            )
        print(json.dumps(result))
    except Exception as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
