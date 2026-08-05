#!/usr/bin/env python3
"""
determinex_user_profile.py — how technical is the person using this, and say it their way
==========================================================================================
Ryan, 2026-08-03: *"add a prescreen asking level of expertise ... you can be more technical,
middle tech (mix) or no tech but better on prose, and lets drive the user session that way."*

Determinex says a great deal to its user: what an oracle verified, why a build was refused,
what is still missing from a spec, why a provider declined. Every one of those sentences is
currently written for one reader — someone who knows what a compiler oracle and an API key
are. For anybody else the product is not wrong, it is *unreadable*, which lands in the same
place: they stop.

Asking once, at the start, is cheaper and kinder than guessing forever.

THE THREE LEVELS
----------------
    TECHNICAL   Show the real thing. Model ids, commands, exit codes, file paths, raw logs.
                Assume "stdout", "stderr", "oracle", "DAG" need no gloss.
    MIXED       Plain sentence first, detail available underneath. The default, because it is
                the only one that is never actively wrong for either other group.
    PROSE       No jargon and no identifiers. Explain in sentences what happened and what to
                do next. Never show a model id, a stack trace, or a flag.

WHAT THIS IS NOT
----------------
It is not a feature gate. Every level can do everything — a prose reader can run a verified
build, and the verification is identical. It changes *wording and density*, never capability,
because a tool that quietly does less for people who read less is a worse tool wearing a
friendlier face.

It is also not permanent: `set_level` is one call, and the UI is expected to offer "show me
the technical detail" inline rather than making anyone revisit a settings page.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

TECHNICAL = "technical"
MIXED = "mixed"
PROSE = "prose"
LEVELS = (TECHNICAL, MIXED, PROSE)

#: The prescreen itself. One question, three answers, no jargon in any of them -- a question
#: that asks how technical you are must not itself require technical vocabulary to answer.
PRESCREEN = {
    "question": "How would you like Determinex to talk to you?",
    "note": "You can change this at any time, and it never limits what the tool can do.",
    "choices": [
        {
            "id": TECHNICAL,
            "label": "Show me everything",
            "blurb": "Commands, model names, logs and exact errors. I'll read them.",
        },
        {
            "id": MIXED,
            "label": "Plain English, details when I ask",
            "blurb": "Tell me what happened in a sentence, and let me open the detail if I want it.",
            "recommended": True,
        },
        {
            "id": PROSE,
            "label": "Just tell me what's going on",
            "blurb": "No jargon, no file names, no error codes. Explain it and tell me what to do.",
        },
    ],
}

_PROFILE_PATH = Path(
    os.environ.get("DETERMINEX_PROFILE")
    or (Path.home() / ".determinex" / "profile.json")
)


@dataclass
class Profile:
    level: str = MIXED
    #: True once the prescreen has actually been answered. Distinguished from "defaulted to
    #: MIXED" so the UI can ask once and never nag again -- and so an unanswered prescreen is
    #: never mistaken for a deliberate choice.
    answered: bool = False


def load() -> Profile:
    try:
        raw = json.loads(_PROFILE_PATH.read_text(encoding="utf-8"))
        level = str(raw.get("level") or MIXED)
        return Profile(level=level if level in LEVELS else MIXED, answered=bool(raw.get("answered")))
    except (OSError, json.JSONDecodeError):
        return Profile()


def set_level(level: str) -> Profile:
    if level not in LEVELS:
        raise ValueError(f"unknown level {level!r}; expected one of {LEVELS}")
    prof = Profile(level=level, answered=True)
    _PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _PROFILE_PATH.write_text(json.dumps(asdict(prof), indent=2) + "\n", encoding="utf-8")
    return prof


def should_prescreen() -> bool:
    """Ask exactly once. A defaulted profile is not an answered one."""
    return not load().answered


def say(plain: str, technical: str = "", level: str | None = None) -> str:
    """Pick the wording for the current reader.

    `plain` is required and `technical` is optional, deliberately: it forces the plain
    sentence to exist. The opposite default -- technical required, plain optional -- is how
    every message in a developer tool ends up being the raw one.
    """
    lvl = level or load().level
    if lvl == TECHNICAL and technical:
        return technical
    if lvl == PROSE:
        return plain
    # MIXED: the plain sentence leads; the detail rides along for anyone who wants it.
    return f"{plain} ({technical})" if technical else plain


def show_identifiers(level: str | None = None) -> bool:
    """May this surface display a model id, path, flag or exit code at all?"""
    return (level or load().level) != PROSE


def detail_density(level: str | None = None) -> str:
    """`full` | `summary` | `headline` — how much of a log or report to render."""
    lvl = level or load().level
    return {TECHNICAL: "full", MIXED: "summary", PROSE: "headline"}[lvl]


def main() -> int:
    ap = argparse.ArgumentParser(description="Reader level for this Determinex install.")
    ap.add_argument("command", choices=["prescreen", "get", "set", "say"])
    ap.add_argument("--level", default="")
    ap.add_argument("--plain", default="")
    ap.add_argument("--technical", default="")
    a = ap.parse_args()
    if a.command == "prescreen":
        # The current level ships alongside the question so one call answers both "must I ask?"
        # and "how do I speak until they answer?". A caller forced to make a second round trip
        # for the level is a caller that will skip it and default to the developer wording.
        prof = load()
        print(json.dumps({**PRESCREEN, "needed": not prof.answered, "level": prof.level}, indent=2))
    elif a.command == "get":
        print(json.dumps(asdict(load()), indent=2))
    elif a.command == "set":
        print(json.dumps(asdict(set_level(a.level)), indent=2))
    else:
        print(say(a.plain, a.technical, a.level or None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
