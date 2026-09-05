"""HUD output: format SOAP notes for the glasses display and push updates.

The HUD (Mentra glasses) receives small JSON payloads over a webhook / HTTPS
POST. This module formats the structured note into HUD-friendly chunks and
manages the outbound push with a failure-tolerant stub so the pipeline works
even with no physical glasses (simulator/listener fallback).
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Callable

from config import CONFIG

LOG = logging.getLogger("medglass.hud")


@dataclass
class HUDMessage:
    kind: str          # "note_progress" | "note_complete" | "alert" | "status"
    title: str
    body: str
    section: str | None = None      # S/O/A/P for the note-building HUD
    confidence: float | None = None
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["ts"] = round(d["ts"], 3)
        return d


class HUDOutput:
    """Pushes HUD payloads to the glasses endpoint or a local sink.

    If no endpoint is configured the messages are written to a local sink
    (default: a JSONL file) so the demo and web simulator still work.
    """

    def __init__(self, cfg: dict | None = None,
                 sink: Callable[[dict], None] | None = None) -> None:
        self.cfg = cfg or CONFIG
        self._endpoint = self.cfg.get("hud_endpoint") or ""
        self._sink = sink or self._default_sink
        self._last_alerts: dict[str, float] = {}

    @staticmethod
    def _default_sink(payload: dict) -> None:
        import json as _json
        from pathlib import Path
        out = Path("output") / "hud_events.jsonl"
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(_json.dumps(payload) + "\n")

    def _send(self, message: HUDMessage) -> None:
        payload = message.to_dict()
        self._sink(payload)
        if self._endpoint:
            self._post(payload)

    def _post(self, payload: dict) -> None:
        try:
            req = urllib.request.Request(
                self._endpoint,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5):
                pass
        except (urllib.error.URLError, OSError) as exc:
            LOG.warning("HUD webhook failed: %s", exc)

    # -- public events ------------------------------------------------------

    def alert(self, text: str, title: str = "MedGlass", cooldown: float = 5.0):
        now = time.time()
        if now - self._last_alerts.get(text, 0) < cooldown:
            return
        self._last_alerts[text] = now
        self._send(HUDMessage(kind="alert", title=title, body=text))

    def status(self, text: str, confidence: float | None = None):
        self._send(HUDMessage(kind="status", title="Status", body=text,
                              confidence=confidence))

    def note_section(self, section: str, text: str):
        self._send(HUDMessage(kind="note_progress", title=section, body=text,
                              section=section))

    def note_complete(self, note: str):
        self._send(HUDMessage(kind="note_complete", title="SOAP Note",
                              body=note))


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def split_soap(note: str) -> dict[str, str]:
    """Split a SOAP note into {S, O, A, P} strings using section headers.

    Falls back to heuristics (S:, O:, A:, P:) when markdown headers are
    missing. Returns only the sections found.
    """
    sections: dict[str, str] = {}
    current: str | None = None
    order = ["S", "O", "A", "P"]
    label_re = {
        "S": (r"\*\*Subjective(?:\s*\(S\))?|\*\*S\s*[:.]|^\s*S\s*[:.]|"
              r"^\s*Subjective(?:\s*\(S\))?\s*[:.]"),
        "O": (r"\*\*Objective(?:\s*\(O\))?|\*\*O\s*[:.]|^\s*O\s*[:.]|"
              r"^\s*Objective(?:\s*\(O\))?\s*[:.]"),
        "A": (r"\*\*Assessment(?:\s*\(A\))?|\*\*A\s*[:.]|^\s*A\s*[:.]|"
              r"^\s*Assessment(?:\s*\(A\))?\s*[:.]"),
        "P": (r"\*\*Plan(?:\s*\(P\))?|\*\*P\s*[:.]|^\s*P\s*[:.]|"
              r"^\s*Plan(?:\s*\(P\))?\s*[:.]"),
    }
    buf: dict[str, list[str]] = {k: [] for k in order}

    for line in note.splitlines():
        found = None
        for key, pattern in label_re.items():
            import re
            if re.search(pattern, line, re.IGNORECASE):
                found = key
                break
        if found:
            current = found
            rest = re.sub(label_re[found], "", line, flags=re.IGNORECASE)
            rest = rest.strip(" :*-\t")
            if rest:
                buf[current].append(rest)
            continue
        if current:
            buf[current].append(line.strip())

    for key in order:
        body = " ".join(x for x in buf[key] if x).strip()
        if body:
            sections[key] = body
    return sections


def format_for_hud(note: str, max_chars: int = 90) -> list[dict]:
    """Produce HUD-friendly section chunks for the glasses display."""
    chunks = []
    for key, body in split_soap(note).items():
        # Chunk long sections so they fit on a single HUD screen.
        words = body.split()
        for i in range(0, len(words), max_chars):
            piece = " ".join(words[i:i + max_chars])
            chunks.append({"section": key, "text": piece})
    return chunks
