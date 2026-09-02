#!/usr/bin/env python3
"""
determinex_foreman.py — who is right, and who goes next, in a multi-agent room
=============================================================================
Ryan, 2026-08-03: *"we need to figure out on the multichat who takes priority based on what
information is presented. So the corpus should be the authority, and the answers should be
looked at by time, because tokens and prose can slide. There really needs to be a mechanism
that allows for the AIs to not collide and stop working but listen to a foreman and keep
pushing to the end even on APIs."*

The room already had turn-taking: the Rust side serialises turns per session, so two agents
never write at once. That prevents a COLLISION. It does not answer either of the questions
that actually decide whether the room finishes:

    when two participants disagree, who wins?
    when nobody is making progress, who goes next?

Without answers, a room degrades in the way rooms do: the last agent to speak wins by default
(recency masquerading as authority), agents politely defer to each other, and the work stops
with everyone still "working".

AUTHORITY IS NOT SENIORITY, IT IS EVIDENCE
------------------------------------------
The ranking is by what a claim is BACKED BY, never by which model made it:

    ORACLE     a turn whose edits made the compiler/tests pass. Ground truth, and a fact
               about the workspace rather than an opinion about it. Nothing outranks it.
    CORPUS     Determinex's own verified, hard-won lessons. Authority on what is ALREADY
               KNOWN -- it cannot be outvoted by an agent's confidence, which is the whole
               reason Ryan named it the authority.
    REFUTED    a turn the oracle REJECTED. Ranked deliberately above prose: "this exact
               approach fails with these 3 errors" is evidence, and a room that discards it
               re-proposes the same thing forever.
    PROSE      an agent talking. No verification attached. Lowest, however fluent.

WITHIN A TIER, LATER WINS
-------------------------
Ryan: *"the answers should be looked at by time, because tokens and prose can slide."* Two
claims with the SAME backing are ordered by when they landed, because the later one saw the
earlier one. Across tiers time is irrelevant: a passing oracle result from turn 3 outranks
beautiful prose from turn 40, and always will.

KEEP PUSHING
------------
Stall detection reuses `ProgressTracker.round_errors` -- the room's failing-check count over
turns IS the error series that rule was written for, so the foreman inherits "go until the
number stops, and say so when the remainder is out of proportion" for free rather than
inventing a second stopping story.

    from determinex_foreman import Foreman
    fm = Foreman()
    for t in transcript:
        fm.observe(t)
    d = fm.next_move(participants=["claude-code", "codex", "local-ollama"])
    d.directive   # PROCEED / ARBITRATE / UNSTICK / ESCALATE
    d.assign_to   # who should take the next turn
    d.because     # a sentence naming the evidence, never "the model said so"
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from determinex_progress import Directive, ProgressTracker  # noqa: E402


class Authority(int, Enum):
    """Higher wins. Ordered by what backs the claim, never by who made it."""

    PROSE = 0
    REFUTED = 1
    CORPUS = 2
    ORACLE = 3

    @property
    def label(self) -> str:
        return {
            Authority.ORACLE: "an oracle-verified result",
            Authority.CORPUS: "the corpus",
            Authority.REFUTED: "an oracle rejection",
            Authority.PROSE: "unverified prose",
        }[self]


class Move(str, Enum):
    PROCEED = "PROCEED"  # healthy: hand the next turn to someone
    ARBITRATE = "ARBITRATE"  # two claims conflict; the foreman rules
    UNSTICK = "UNSTICK"  # nobody is progressing; force a different mover
    ESCALATE = "ESCALATE"  # out of the room's reach; name what is needed


@dataclass
class Claim:
    speaker: str
    authority: Authority
    at: str  # ISO timestamp; ordering WITHIN a tier only
    n_failures: int
    summary: str


@dataclass
class Ruling:
    directive: Move
    assign_to: str | None
    because: str
    winning: Claim | None = None


def classify(turn: dict) -> Authority:
    """What backs this turn? Read from the record, never inferred from the text.

    A turn's own prose is exactly the thing that cannot be trusted to describe its status --
    an agent writing "fixed it" is prose whatever it claims, and the oracle field next to it
    is the fact.
    """
    kind = str(turn.get("speaker_kind") or turn.get("speakerKind") or "").lower()
    if kind == "corpus" or str(turn.get("speaker") or "").lower() == "corpus":
        return Authority.CORPUS
    if bool(turn.get("verified")):
        return Authority.ORACLE
    if int(turn.get("n_failures") or turn.get("nFailures") or 0) > 0:
        return Authority.REFUTED
    return Authority.PROSE


@dataclass
class Foreman:
    """Watches a transcript and rules on it. Deterministic; no model is consulted."""

    claims: list[Claim] = field(default_factory=list)
    _rate: ProgressTracker = field(default_factory=ProgressTracker)
    _last_rate: Directive = Directive.CONTINUE
    #: Consecutive turns by the same speaker that changed nothing. A room where one agent
    #: keeps the floor without moving the failure count is the "politely stuck" case.
    _idle_by: dict = field(default_factory=dict)

    def observe(self, turn: dict) -> None:
        auth = classify(turn)
        speaker = str(turn.get("speaker") or "?")
        n_fail = int(turn.get("n_failures") or turn.get("nFailures") or 0)
        self.claims.append(
            Claim(
                speaker=speaker,
                authority=auth,
                at=str(turn.get("finished_at") or turn.get("finishedAt") or ""),
                n_failures=n_fail,
                summary=(str(turn.get("note") or turn.get("oracle") or "")[:160]),
            )
        )
        # Only turns that could MOVE the number feed the rate rule. A corpus lookup or a user
        # message makes no edits, so counting them as "a round that removed nothing" would
        # manufacture a plateau out of people talking.
        if auth in (Authority.ORACLE, Authority.REFUTED):
            self._last_rate = self._rate.round_errors(n_fail)
            prev = self._idle_by.get(speaker, 0)
            self._idle_by[speaker] = 0 if auth is Authority.ORACLE else prev + 1

    # ── who is right ────────────────────────────────────────────────────────────────────

    def authoritative(self) -> Claim | None:
        """The claim that currently stands: highest authority, then latest within it."""
        if not self.claims:
            return None
        return sorted(self.claims, key=lambda c: (int(c.authority), c.at))[-1]

    def conflict(self) -> tuple[Claim, Claim] | None:
        """Two live claims at the SAME authority from DIFFERENT speakers.

        Only same-tier disagreement is a conflict worth ruling on. An agent contradicting a
        passing oracle is not a conflict, it is simply wrong, and `authoritative()` already
        says so without ceremony.
        """
        top = self.authoritative()
        if top is None:
            return None
        peers = [c for c in self.claims if c.authority == top.authority and c.speaker != top.speaker]
        return (top, peers[-1]) if peers else None

    # ── who goes next ───────────────────────────────────────────────────────────────────

    def next_move(self, participants: list[str]) -> Ruling:
        top = self.authoritative()

        if top is not None and top.authority is Authority.ORACLE and top.n_failures == 0:
            return Ruling(
                Move.PROCEED,
                None,
                f"{top.speaker}'s change is oracle-verified with no failing checks. "
                f"Nothing outranks that; the room is done unless the user asks for more.",
                top,
            )

        if self._last_rate is Directive.OUT_OF_PROPORTION:
            return Ruling(
                Move.ESCALATE,
                None,
                # Deliberately distinct from "stuck": the room is WORKING and still will not
                # finish, so more turns are not the remedy. Same distinction the rate rule
                # draws, carried through to the people in the room.
                f"the room is making progress but not enough of it -- {self._rate.reason()}. "
                f"More turns will not close this: it needs a missing toolchain, a stronger "
                f"model, or a person.",
                top,
            )

        if self._last_rate is Directive.ESCALATE:
            # Stalled. Hand the floor to whoever has NOT been failing at it.
            stuck = {a for a, n in self._idle_by.items() if n >= 2}
            fresh = [p for p in participants if p not in stuck]
            if fresh:
                return Ruling(
                    Move.UNSTICK,
                    fresh[0],
                    f"progress stopped -- {self._rate.reason()}. "
                    f"{', '.join(sorted(stuck)) or 'the current mover'} has not moved the "
                    f"number; handing the floor to {fresh[0]}.",
                    top,
                )
            return Ruling(
                Move.ESCALATE,
                None,
                f"progress stopped and every participant has already tried -- "
                f"{self._rate.reason()}.",
                top,
            )

        c = self.conflict()
        if c is not None:
            win, lose = c
            return Ruling(
                Move.ARBITRATE,
                win.speaker,
                f"{win.speaker} and {lose.speaker} both offer {win.authority.label}; "
                f"{win.speaker}'s is later, so it stands. Time breaks a tie WITHIN a tier "
                f"only -- it never promotes prose over a verified result.",
                win,
            )

        # Healthy: rotate so one agent cannot hold the floor.
        last = self.claims[-1].speaker if self.claims else None
        nxt = next((p for p in participants if p != last), (participants or [None])[0])
        return Ruling(
            Move.PROCEED,
            nxt,
            (f"the room is still removing failures ({self._rate.reason()})"
             if self._rate._round_errors
             else "no verified work yet; continuing"),
            top,
        )


def main() -> int:
    import argparse
    import json

    ap = argparse.ArgumentParser(description="Rule on a multi-agent chat transcript.")
    ap.add_argument("session_id")
    ap.add_argument("--participants", default="")
    a = ap.parse_args()

    from determinex_agent_chat import get_session, read_transcript

    sess = get_session(a.session_id) or {}
    parts = [p for p in (a.participants.split(",") if a.participants else sess.get("participants", [])) if p]
    fm = Foreman()
    for t in read_transcript(a.session_id):
        fm.observe(t)
    r = fm.next_move(parts)
    print(json.dumps({
        "directive": r.directive.value,
        "assign_to": r.assign_to,
        "because": r.because,
        "authoritative": (None if r.winning is None else {
            "speaker": r.winning.speaker,
            "authority": r.winning.authority.name,
            "at": r.winning.at,
        }),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
