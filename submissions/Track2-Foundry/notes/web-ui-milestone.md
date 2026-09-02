# Web UI validated July 17 — Flask + one static page, live-driven in browser

One-liner: serve_ui.py (Flask) + static/index.html (vanilla JS, no
frameworks) give the multi-turn UX rubric line a real surface: chat with
streamed NDJSON agent events, tool chips with live timings, a 2s-poll
GPU telemetry card (VRAM/util — nvidia-smi with rocm-smi fallback, so
the Radeon demo shows AMD silicon working ON SCREEN), build-stage
badges, registry rail, and the bench chart inline once it exists.

Validated by driving it in a real browser: sent turns, watched
list_experiments/resume_build chips render with timings, build card
flip to the task name, and the agent's before/after table match
eval_report.json on disk exactly.

Design decision recorded: this intentionally spends effort on UI
despite the charter's "a polished UI scores nothing" — the rubric puts 20
points on "smooth multi-turn interaction experience", and a thin web
view (one afternoon, ~500 lines total, zero build tooling) raises that
ceiling while ALSO putting rocm-smi telemetry into every demo frame.
The line stays thin: no frameworks, no npm, portable to the instance
unchanged (flask pip-installs into /opt/venv; JupyterLab can proxy or
cloudflared can tunnel the port — decide at Radeon session).

Bonus finding: the build-state card exposes the 4B's
narrate-without-calling quirk instantly (agent says "resumed", card
still says "no build loaded") — the UI is also a truthfulness monitor
for rehearsals.

Known quirk: the in-app browser pane's screenshot capture timed out
repeatedly (page text/DOM extraction worked fine) — UI itself is
healthy; verify visuals by eye when running it interactively.

Run it:  .venv\Scripts\python serve_ui.py --config configs/pilot_4060.toml
Then open http://127.0.0.1:8300. Kill both ports (8300 UI, 8123
teacher) when done.
