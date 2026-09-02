"""tests/test_determinex_usage_ledger.py

Ryan: "we need to also add the token limits for those api's like their
level and how much til they end of credits and all that fun stuff, the gas
gauge if you will." Covers the honest scope: real spend from the existing
logs/api_ledger/providers.jsonl (already written by
determinex_providers._ledger_append), streamed rather than fully loaded --
and cli_subscription_status()'s deliberate "not available" answer for the
claude-code/codex/gemini-cli subscription CLIs, which don't expose a safely
queryable remaining-usage API via the credentials already on this machine.
"""

from __future__ import annotations

import datetime as _dt
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT, _ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import determinex_usage_ledger as ledger  # noqa: E402


def _write_ledger(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def test_summarize_ledger_missing_file_reports_not_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "LEDGER_PATH", tmp_path / "nope.jsonl")
    result = ledger.summarize_ledger()
    assert result["exists"] is False
    assert result["total_calls"] == 0


def test_summarize_ledger_aggregates_by_provider(tmp_path, monkeypatch):
    path = tmp_path / "providers.jsonl"
    now = _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds")
    _write_ledger(
        path,
        [
            {
                "ts": now,
                "model": "openai/gpt-4o",
                "tokens_in": 100,
                "tokens_out": 50,
                "est_usd": 0.01,
            },
            {
                "ts": now,
                "model": "openai/gpt-4o",
                "tokens_in": 200,
                "tokens_out": 100,
                "est_usd": 0.02,
            },
            {
                "ts": now,
                "model": "ollama/llama3",
                "tokens_in": 10,
                "tokens_out": 5,
                "est_usd": 0.0001,
            },
        ],
    )
    monkeypatch.setattr(ledger, "LEDGER_PATH", path)

    result = ledger.summarize_ledger(window_hours=None)
    assert result["exists"] is True
    assert result["total_calls"] == 3
    assert result["providers"]["openai"]["calls"] == 2
    assert result["providers"]["openai"]["tokens_in"] == 300
    assert result["providers"]["ollama"]["calls"] == 1
    assert round(result["total_est_usd"], 4) == round(0.01 + 0.02 + 0.0001, 4)


def test_summarize_ledger_window_excludes_old_rows(tmp_path, monkeypatch):
    path = tmp_path / "providers.jsonl"
    old_ts = (_dt.datetime.now(_dt.UTC) - _dt.timedelta(hours=48)).isoformat(timespec="seconds")
    recent_ts = _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds")
    _write_ledger(
        path,
        [
            {
                "ts": old_ts,
                "model": "openai/gpt-4o",
                "tokens_in": 1000,
                "tokens_out": 1000,
                "est_usd": 1.0,
            },
            {
                "ts": recent_ts,
                "model": "openai/gpt-4o",
                "tokens_in": 10,
                "tokens_out": 10,
                "est_usd": 0.001,
            },
        ],
    )
    monkeypatch.setattr(ledger, "LEDGER_PATH", path)

    result = ledger.summarize_ledger(window_hours=24.0)
    assert result["total_calls"] == 1
    assert result["providers"]["openai"]["tokens_in"] == 10


def test_summarize_ledger_skips_malformed_lines(tmp_path, monkeypatch):
    path = tmp_path / "providers.jsonl"
    now = _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds")
    with open(path, "w", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {
                    "ts": now,
                    "model": "openai/gpt-4o",
                    "tokens_in": 1,
                    "tokens_out": 1,
                    "est_usd": 0.0,
                }
            )
            + "\n"
        )
        f.write("not valid json{{{\n")
        f.write(
            json.dumps(
                {
                    "ts": now,
                    "model": "openai/gpt-4o",
                    "tokens_in": 2,
                    "tokens_out": 2,
                    "est_usd": 0.0,
                }
            )
            + "\n"
        )
    monkeypatch.setattr(ledger, "LEDGER_PATH", path)

    result = ledger.summarize_ledger(window_hours=None)
    assert result["total_calls"] == 2
    assert result["malformed_lines_skipped"] == 1


def test_cli_subscription_status_honestly_reports_unavailable():
    status = ledger.cli_subscription_status()
    assert set(status.keys()) == {"claude-code", "codex", "gemini-cli"}
    for entry in status.values():
        assert entry["available"] is False
        assert "reason" in entry and len(entry["reason"]) > 0
