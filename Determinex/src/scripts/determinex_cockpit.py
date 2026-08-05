#!/usr/bin/env python3
"""
determinex_cockpit.py — what is happening, small enough to read on a phone
=========================================================================
Ryan, 2026-08-03: *"there's supposed to be a mobile update/notification/cockpit drive on the
go part."*

`determinex_notify.py` has posted to Discord/Slack/Telegram for a long time, and only two
batch scripts ever called it. The IDE never did, the hive never did, the agent chat room never
did — so the one situation the feature exists for (you are not at the machine) was the one it
never covered. This is the missing half: a status a phone can render, and a rule for WHEN
sending it is worth an interruption.

WHAT MAKES A NOTIFICATION WORTH SENDING
---------------------------------------
Not "something happened". A build that is proceeding normally is not news, and a stream of
those trains you to swipe them away — which means the one that mattered gets swiped too. Two
things earn an interruption:

    DONE     the work reached a verdict. Verified or not, it is over and you can decide.
    BLOCKED  it needs a person. The foreman already distinguishes this precisely:
             OUT_OF_PROPORTION means the loop is working and still will not finish, which is
             the case where waiting longer is the wrong answer.

Everything else is a status you can pull, not a message that should push.

    python scripts/determinex_cockpit.py status            # print the cockpit
    python scripts/determinex_cockpit.py notify --if-needed # send only if DONE or BLOCKED
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))


@dataclass
class Cockpit:
    #: DONE | BLOCKED | WORKING | IDLE — the only four a phone needs to distinguish.
    state: str = "IDLE"
    headline: str = "Nothing running."
    detail: str = ""
    #: Present only when a person is actually required, so a glance answers "is this mine?"
    needs_you: bool = False
    sessions: list = field(default_factory=list)
    verified: int = 0
    failing: int = 0

    def as_text(self) -> str:
        """Plain text, phone-width. No ANSI, no tables, no markdown that a webhook mangles."""
        lines = [f"[{self.state}] {self.headline}"]
        if self.detail:
            lines.append(self.detail)
        for s in self.sessions[:4]:
            lines.append(f"  - {s}")
        return "\n".join(lines)


def _chat_rooms() -> tuple[list, str, bool, str]:
    """Live agent-chat sessions, ruled on by the foreman."""
    rows: list[str] = []
    state, headline, needs_you = "IDLE", "", False
    try:
        from determinex_agent_chat import get_session, list_sessions, read_transcript
        from determinex_foreman import Foreman, Move
    except Exception:
        return rows, state, needs_you, headline

    for meta in (list_sessions() or [])[:6]:
        sid = meta.get("sessionId") or meta.get("session_id") or ""
        if not sid:
            continue
        turns = read_transcript(sid) or []
        if not turns:
            continue
        sess = get_session(sid) or {}
        fm = Foreman()
        for t in turns:
            fm.observe(t)
        ruling = fm.next_move(sess.get("participants", []))
        rows.append(f"{sid[-6:]}: {len(turns)} turns — {ruling.directive.value}")
        if ruling.directive is Move.ESCALATE:
            state, needs_you = "BLOCKED", True
            headline = ruling.because
        elif ruling.directive is Move.PROCEED and ruling.assign_to is None and state != "BLOCKED":
            state, headline = "DONE", ruling.because
        elif state == "IDLE":
            state, headline = "WORKING", ruling.because
    return rows, state, needs_you, headline


def build() -> Cockpit:
    rows, state, needs_you, headline = _chat_rooms()
    c = Cockpit(
        state=state,
        headline=headline or ("Nothing running." if state == "IDLE" else "In progress."),
        sessions=rows,
        needs_you=needs_you,
    )
    # A calibration profile is cheap to read and is the one number that says the machine was
    # actually measured rather than assumed.
    try:
        from determinex_calibrate import load_profile

        prof = load_profile() or {}
        if prof:
            c.detail = f"{len(prof)} calibrated rig(s); K set from measurement, not a constant."
    except Exception:
        pass
    return c


def should_notify(c: Cockpit) -> bool:
    """Only DONE or BLOCKED. A normal-progress ping is how the important one gets ignored."""
    return c.state in ("DONE", "BLOCKED")


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Cockpit status, phone-sized.")
    ap.add_argument("command", choices=["status", "notify"])
    ap.add_argument("--if-needed", action="store_true",
                    help="send only when the state is DONE or BLOCKED")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    c = build()
    if a.command == "status":
        print(json.dumps(asdict(c), indent=2) if a.json else c.as_text())
        return 0

    if a.if_needed and not should_notify(c):
        print(f"not sending: state is {c.state}, which is not worth an interruption")
        return 0
    if not os.environ.get("DETERMINEX_NOTIFY_URL"):
        # Say what is missing and how to set it. "Notifications are off" with no next step is
        # the same dead end as a blank API-key field.
        print(
            "DETERMINEX_NOTIFY_URL is not set, so there is nowhere to send this.\n"
            "Set it to a Discord/Slack/Telegram webhook in .env and this will reach your "
            "phone:\n  DETERMINEX_NOTIFY_URL=https://discord.com/api/webhooks/...\n\n"
            + c.as_text()
        )
        return 1

    from determinex_notify import send

    level = "critical" if c.needs_you else "info"
    ok = send(c.as_text(), level=level)
    print(f"sent={ok} state={c.state}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
