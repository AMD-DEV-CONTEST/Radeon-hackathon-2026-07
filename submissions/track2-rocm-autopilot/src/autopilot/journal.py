"""Run journal + dashboard state contract.

Appends every run to runs/journal.jsonl and rewrites runs/state.json -
the single file the dashboard polls. Leaderboard score: tokens/s if the
TTFT constraint holds, else 0 (constraint violations never rank).
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

# Optional: set these env vars to push every run to the Cloudflare live dashboard.
# LIVE_ENDPOINT=https://gemma-autopilot-live.<subdomain>.workers.dev
# LIVE_API_KEY=<your-secret-key>
_LIVE_ENDPOINT = os.environ.get("LIVE_ENDPOINT", "").rstrip("/")
_LIVE_API_KEY = os.environ.get("LIVE_API_KEY", "")

TTFT_CONSTRAINT_MS = 500.0

OBJECTIVE = {
    "maximize": "tokens_per_s",
    "constraint_ttft_ms": TTFT_CONSTRAINT_MS,
    "secondary": "joules_per_token",
}


def score(run: dict) -> float:
    m = run["metrics"]
    return m["tokens_per_s"] if m["ttft_ms"] <= TTFT_CONSTRAINT_MS else 0.0


class Journal:
    def __init__(self, directory: str = "runs"):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._runs: list[dict] = []
        self._reasoning: list[dict] = []
        journal_file = self.dir / "journal.jsonl"
        if journal_file.exists():
            for line in journal_file.read_text().splitlines():
                if not line.strip():
                    continue
                entry = json.loads(line)
                self._runs.append(entry["run"])
                self._reasoning.append({
                    "iter": len(self._runs),
                    "text": entry.get("reasoning", ""),
                    "label": entry["run"].get("label", "?"),
                    "ts": entry["run"].get("ts", ""),
                })

    def add_run(self, run: dict, reasoning: str, label: str | None = None) -> None:
        run = dict(run)
        run["label"] = label or f"agent-iter-{sum(1 for r in self._runs if str(r.get('label','')).startswith('agent-iter')) + 1}"
        parent_id = self._runs[-1].get("label") if self._runs else None
        self._runs.append(run)
        self._reasoning.append({
            "iter": len(self._runs),
            "text": reasoning,
            "label": run["label"],
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })
        with open(self.dir / "journal.jsonl", "a") as f:
            f.write(json.dumps({"run": run, "reasoning": reasoning}) + "\n")
        self._write_state()
        self._push_live(run, reasoning, parent_id=parent_id)

    def add_note(self, text: str) -> None:
        """Journal a reasoning-only entry (e.g. a search or a rejected action)."""
        self._reasoning.append({
            "iter": len(self._runs),
            "text": text,
            "label": "note",
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })
        self._write_state()

    def leaderboard(self) -> list[dict]:
        from autopilot import carbon
        rows = [
            {
                "label": r["label"],
                "tokens_per_s": r["metrics"]["tokens_per_s"],
                "ttft_ms": r["metrics"]["ttft_ms"],
                "joules_per_token": r["energy"]["joules_per_token"],
                "gco2e_per_1k_tokens": carbon.gco2e_per_1k_tokens(
                    r["energy"]["joules_per_token"]),
                "carbon_label": carbon.label(r["energy"]["joules_per_token"]),
                "score": score(r),
            }
            for r in self._runs
        ]
        rows.sort(key=lambda x: x["score"], reverse=True)
        for i, row in enumerate(rows, 1):
            row["rank"] = i
        return rows

    def _write_state(self) -> None:
        state = {
            "runs": self._runs,
            "reasoning": self._reasoning,
            "leaderboard": self.leaderboard(),
            "objective": OBJECTIVE,
        }
        tmp = self.dir / "state.json.tmp"
        tmp.write_text(json.dumps(state, indent=1))
        tmp.replace(self.dir / "state.json")

    @property
    def runs(self) -> list[dict]:
        return list(self._runs)

    # ── Live push (fire-and-forget, never raises) ─────────────────────────

    def push_live_running(self, label: str, reasoning: str) -> None:
        """Call before a benchmark to mark a run as 'running' on the dashboard."""
        if not _LIVE_ENDPOINT or not _LIVE_API_KEY:
            return
        parent_id = self._runs[-1].get("label") if self._runs else None
        payload = {
            "id": label,
            "parent_id": parent_id,
            "label": label,
            "status": "running",
            "reasoning": reasoning,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        threading.Thread(target=self._do_push, args=(payload,), daemon=True).start()

    def _push_live(self, run: dict, reasoning: str, *, parent_id: str | None) -> None:
        if not _LIVE_ENDPOINT or not _LIVE_API_KEY:
            return
        payload = {
            "id": run["label"],
            "parent_id": parent_id,
            "label": run["label"],
            "status": "done",
            "config": run.get("config"),
            "metrics": run.get("metrics"),
            "energy": run.get("energy"),
            "reasoning": reasoning,
            "ts": run.get("ts", time.strftime("%Y-%m-%dT%H:%M:%S")),
        }
        threading.Thread(target=self._do_push, args=(payload,), daemon=True).start()

    def _do_push(self, payload: dict) -> None:
        try:
            import urllib.request
            data = json.dumps(payload).encode()
            req = urllib.request.Request(
                f"{_LIVE_ENDPOINT}/api/push",
                data=data,
                headers={"Content-Type": "application/json",
                         "Authorization": f"Bearer {_LIVE_API_KEY}"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=10)
        except Exception as exc:  # noqa: BLE001
            print(f"[live push] failed: {exc}")
