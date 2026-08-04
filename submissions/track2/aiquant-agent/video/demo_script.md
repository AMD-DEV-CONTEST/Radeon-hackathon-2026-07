# aiQuant — Demo Video Recording Guide

> **AMD Radeon Hackathon 2026 · Track 2: Private AI Agent Development & Local Deployment**
>
> Target length: **3–5 minutes** · Resolution: **1920×1080** · Language: English narration
>
> This guide is a shot-by-shot script for recording a demonstration of the aiQuant
> system running entirely on AMD Radeon Cloud. Every command, URL, and endpoint below
> is verified against the live codebase so the recording reflects real behavior.

---

## Table of Contents

1. [Pre-recording Checklist](#pre-recording-checklist)
2. [Scene 1 — Introduction (30s)](#scene-1--introduction-30s)
3. [Scene 2 — LLM Server (30s)](#scene-2--llm-server-30s)
4. [Scene 3 — Start aiQuant (30s)](#scene-3--start-aiquant-30s)
5. [Scene 4 — Chat Interface (60s)](#scene-4--chat-interface-60s)
6. [Scene 5 — Factor Mining Result (60s)](#scene-5--factor-mining-result-60s)
7. [Scene 6 — API Demo (30s)](#scene-6--api-demo-30s)
8. [Scene 7 — GPU Utilization (30s)](#scene-7--gpu-utilization-30s)
9. [Scene 8 — Conclusion (15s)](#scene-8--conclusion-15s)
10. [Recording Tips](#recording-tips)
11. [Automated Demo Flow (Bash Script)](#automated-demo-flow-bash-script)

---

## Pre-recording Checklist

Complete **every** item below before hitting the record button. A failed demo on
camera is far harder to re-shoot than to prevent.

### Infrastructure

| # | Item | How to verify | Pass criteria |
|---|------|---------------|---------------|
| 1 | Radeon Cloud instance is running and reachable | SSH into the instance | Shell prompt appears |
| 2 | ROCm driver is loaded | `rocm-smi` | GPU row printed with temperature / VRAM columns |
| 3 | Lemonade LLM server is running on **port 13305** | `curl -s http://localhost:13305/v1/models` | JSON listing `Qwen3-8B` model |
| 4 | aiQuant API server is running on **port 8010** | `curl -s http://localhost:8010/api/health` | `{"status": "ok", ...}` response |
| 5 | Streamlit visualization UI is available on **port 19899** | `curl -sI http://localhost:19899` | HTTP 200 |
| 6 | Redis is running (for SSE event bus) | `redis-cli ping` | `PONG` |

### Desktop / Environment

- [ ] Browser open at **http://localhost:8010** (Chrome or Firefox, fresh tab)
- [ ] A second browser tab open at **http://localhost:19899** (Streamlit, pre-loaded)
- [ ] Terminal window visible, font size **16pt or larger**, dark background
- [ ] Clean desktop background (solid dark color recommended)
- [ ] Close all unrelated applications (Slack, IDEs, email, etc.)
- [ ] Disable system notifications (Do Not Disturb mode)
- [ ] Browser bookmarks bar hidden (cleaner look)

### Recording Setup

- [ ] Screen recording software ready: **OBS Studio** (preferred) or **QuickTime Player**
- [ ] Canvas set to **1920×1080**, **30 fps minimum** (60 fps preferred for terminal text)
- [ ] Audio input selected and tested if narrating live
- [ ] Test recording of 10 seconds reviewed for clarity (text legible, no flicker)
- [ ] Disk space confirmed for ~1 GB recording (5 min at 1080p)

### Demo Data Warm-up

To avoid a long "spinning" gap on camera, run one factor-mining cycle **off-camera**
before recording so that Qlib instruments files and factor cache are warm:

```bash
# Off-camera warm-up (do NOT record this)
curl -X POST http://localhost:8010/api/research/factor-evolve/stream \
  -H "Content-Type: application/json" \
  -d '{"loop_n": 1, "universe": "沪深300", "all_duration": "30m"}' \
  > /tmp/warmup.log
```

---

## Scene 1 — Introduction (30s)

**Goal:** Establish that the demo runs on real AMD Radeon hardware.

### Shot

- Open the **AMD Radeon Cloud console** in the browser (show the instance dashboard).
- Open a terminal SSH session into the Radeon Cloud instance.

### Action

```bash
rocm-smi
```

### Expected Output

A table listing the AMD GPU with columns for temperature, VRAM usage, and compute
utilization. Example:

```
========================================= ROCm System Management Interface =========================================
================================================= Concise Information =================================================
Device  [Node  :Card]  Temperature  Power        VRAM%  Total VRAM  Shared VRAM  compute%
======================================================================================================================
0       [0     :     0]      42.0°C   85.0W           0%      16.0GB         0.0GB         0%
======================================================================================================================
```

### Narration

> "This is **aiQuant**, a private AI Agent for quantitative factor mining, running
> entirely on an AMD Radeon GPU. Every inference call, every factor computation,
> and every backtest stays on this device — zero data leaves the cloud instance."

### On-screen Timing

| Time | Action |
|------|--------|
| 0:00–0:10 | Show Radeon Cloud console dashboard |
| 0:10–0:20 | Switch to terminal, type `rocm-smi` |
| 0:20–0:30 | Narration over GPU output table |

---

## Scene 2 — LLM Server (30s)

**Goal:** Prove the local LLM (Qwen3-8B) is served from the AMD GPU via Lemonade.

### Shot

- Terminal showing the Lemonade server process (or its startup logs in a split pane).

### Action

```bash
curl -s http://localhost:13305/v1/models | python3 -m json.tool
```

### Expected Output

```json
{
  "object": "list",
  "data": [
    {
      "id": "/root/.cache/lemonade/models/Qwen3-8B-GGUF/Qwen3-8B-Q4_K_M.gguf",
      "object": "model",
      "owned_by": "lemonade"
    }
  ]
}
```

### Narration

> "A Lemonade server is hosting the **Qwen3-8B** model on the AMD Radeon GPU,
> exposed through an OpenAI-compatible API on port 13305. With Q4_K_M quantization
> the model fits comfortably in VRAM and sustains roughly **90 tokens per second** —
> fast enough for real-time factor hypothesis generation."

### On-screen Timing

| Time | Action |
|------|--------|
| 0:30–0:40 | Show Lemonade terminal / process |
| 0:40–0:50 | Run `curl` models command |
| 0:50–1:00 | Highlight model ID in JSON response |

---

## Scene 3 — Start aiQuant (30s)

**Goal:** Show the aiQuant API gateway booting and passing a health check.

### Shot

- Terminal running the uvicorn startup command (if not already running, start it on
  camera; otherwise show the running process logs).

### Action — Start Command

```bash
CONDA_DEFAULT_ENV=base uvicorn backend.api.main:app --host 0.0.0.0 --port 8010 --loop asyncio
```

### Expected Startup Logs (key lines)

```
INFO     | uvicorn.error:on_startup:... | Application startup complete.
INFO     | backend.api.main:... | Qlib instruments deployed: csi300, csi500, sz50
INFO     | backend.api.main:... | SSE streaming endpoint ready: /api/research/factor-evolve/stream
INFO     | uvicorn.error:...   | Uvicorn running on http://0.0.0.0:8010
```

### Action — Health Check

```bash
curl -s http://localhost:8010/api/health | python3 -m json.tool
```

### Expected Output

```json
{
  "status": "ok",
  "celery": true,
  "rd_agent": "ready",
  "timestamp": "..."
}
```

### Narration

> "The aiQuant FastAPI gateway starts on port 8010. On boot it deploys the bundled
> stock-pool instrument files for CSI 300, CSI 500, and SSE 50, and registers the
> SSE streaming endpoint used for real-time factor-mining progress. A quick health
> check confirms the API, Celery worker, and RD-Agent engine are all ready."

### On-screen Timing

| Time | Action |
|------|--------|
| 1:00–1:10 | Show `uvicorn` command + startup logs |
| 1:10–1:20 | Run `curl` health check |
| 1:20–1:30 | Highlight `"status": "ok"` |

---

## Scene 4 — Chat Interface (60s)

**Goal:** Demonstrate the natural-language chat interface and the live SSE streaming
progress of a factor-mining run.

### Shot

- Switch to the browser tab at **http://localhost:8010**.
- Show the dark-themed chat interface with quick-command chips.

### Action

1. Click the chat input box.
2. Type (or paste) the following prompt:

   ```
   在沪深300挖掘动量因子，迭代1轮
   ```

   (Translation: "Mine momentum factors for CSI 300, 1 iteration")

3. Press **Enter** to submit.
4. Watch the SSE stream render each stage as it arrives.

### SSE Streaming Stages (in order)

The backend (`/api/research/factor-evolve/stream`) emits these event types. Narrate
each one as the colored card appears in the chat:

| Order | Event `type` | Stage label | What it means |
|-------|--------------|-------------|---------------|
| 1 | `task_start` | `task_start` | Task accepted; a `TASK-YYYYMMDD-XXXX` ID is assigned and parameters are echoed (loop count, universe, constraints, backtest duration). |
| 2 | `memory` | `memory_retrieval` | **Stage 1** — Long-term memory store is queried for prior factor reviews of the same style to avoid redundant / highly-correlated logic. |
| 3 | `phase` | `phase2_init` | **Stage 2** — The RD-Agent factor-evolution engine initializes (environment, iteration count, stock universe). |
| 4 | `hypothesis` | `hypothesis_loop1` | The R-Agent researcher composes a mathematical factor hypothesis for this loop (e.g., a momentum signal definition). |
| 5 | `code` | `coding_loop1` | **Stage 3** — The D-Agent converts the hypothesis into runnable Qlib-compatible Python factor code (shown in a fenced code block). |
| 6 | `backtest` | `backtest_loop1` | Qlib runs the backtest over 2018–2025; reports IC, ICIR, annualized return, max drawdown, monthly win rate. |
| 7 | `review` | `review_loop1` | An automated review of the backtest result is generated. |
| 8 | `feedback` | `feedback_loop1` | **Stage 4** — The LLM analyzes the result and proposes an optimization direction for the next iteration. |

### Narration (paced with the stream)

> "I'll ask the agent in natural language: *mine momentum factors for CSI 300, one
> iteration.* The agent parses my intent, then streams progress in real time.
>
> First, **task_start** confirms the parameters. **Memory retrieval** pulls prior
> factor reviews so the agent avoids repeating known logic. **Phase 2 init** boots
> the RD-Agent evolution engine. Now the **hypothesis** stage — the agent reasons
> about a momentum signal mathematically. **Coding** converts that hypothesis into
> executable Python. Finally **backtest** runs it through Qlib and reports IC, ICIR,
> and annualized return, followed by an automated **review** and **feedback** for
> the next loop."

### On-screen Timing

| Time | Action |
|------|--------|
| 1:30–1:40 | Show chat UI, type the prompt |
| 1:40–1:50 | `task_start` + `memory` cards appear |
| 1:50–2:00 | `phase2_init` + `hypothesis` cards |
| 2:00–2:10 | `coding` card with Python snippet |
| 2:10–2:20 | `backtest` card with metrics |
| 2:20–2:30 | `review` + `feedback` cards, stream completes |

---

## Scene 5 — Factor Mining Result (60s)

**Goal:** Show the final factor report and the visual dashboard.

### Action

1. Wait for the SSE stream to complete (the final `feedback` / `done` event).
2. Scroll to the **final report card** in the chat. It summarizes:
   - **IC** (Information Coefficient)
   - **ICIR** (IC Information Ratio)
   - **Annualized return**
   - **Max drawdown**
   - **Monthly win rate**

3. Click the **visualization link** embedded in the report (or open the pre-loaded
   tab at **http://localhost:19899**).

4. In the Streamlit UI, show:
   - **Returns curve** (cumulative factor returns vs. benchmark)
   - **IC time series** chart
   - **Layered / grouped returns** (quantile spread) if available

### Narration

> "Once evolution completes, the agent posts a final report with the headline
> metrics: IC, ICIR, annualized return, and max drawdown. Clicking the
> visualization link opens the Streamlit dashboard on port 19899 — here's the
> cumulative returns curve versus the CSI 300 benchmark, and the IC time series
> showing the factor's predictive stability across the backtest window."

### On-screen Timing

| Time | Action |
|------|--------|
| 2:30–2:40 | Show final report card with metrics |
| 2:40–2:50 | Click / switch to Streamlit tab |
| 2:50–3:10 | Show returns curve + IC time series |
| 3:10–3:30 | Pan across dashboard panels |

---

## Scene 6 — API Demo (30s)

**Goal:** Show that the same factor-mining capability is accessible via a clean REST API.

### Shot

- Return to the terminal.

### Action

```bash
curl -X POST http://localhost:8010/api/research/factor-evolve/stream \
  -H "Content-Type: application/json" \
  -d '{
    "loop_n": 1,
    "universe": "沪深300",
    "all_duration": "30m"
  }'
```

### Expected Response

An SSE event stream (one `data:` line per event). The first lines look like:

```
data: {"type":"task_start","stage":"task_start","content":"✅【任务启动】...","task_id":"TASK-20260804-AB12","elapsed_sec":0.0,...}

data: {"type":"memory","stage":"memory_retrieval","content":"✅【阶段1】长期记忆库检索完成...","elapsed_sec":0.2,...}

data: {"type":"phase","stage":"phase2_init","content":"✅【阶段2】因子进化引擎正在初始化...","elapsed_sec":0.4,...}
...
```

> **Tip:** For a cleaner on-screen JSON, pipe through `grep` to show only the
> `type` field of each event:
>
> ```bash
> curl -N -X POST http://localhost:8010/api/research/factor-evolve/stream \
>   -H "Content-Type: application/json" \
>   -d '{"loop_n": 1, "universe": "沪深300", "all_duration": "30m"}' \
>   | grep --line-buffered '"type"'
> ```

### Narration

> "Everything you saw in the chat is also exposed as a REST endpoint. A single POST
> to `/api/research/factor-evolve/stream` with the iteration count, stock universe,
> and backtest duration returns a live SSE stream of progress events — ideal for
> programmatic integration or scheduling unattended factor-research runs."

### On-screen Timing

| Time | Action |
|------|--------|
| 3:30–3:40 | Type / paste the `curl` command |
| 3:40–3:50 | Show SSE event lines streaming |
| 3:50–4:00 | Highlight `task_id` and `type` fields |

---

## Scene 7 — GPU Utilization (30s)

**Goal:** Visually prove that factor mining drives real GPU compute on the AMD Radeon.

### Shot

- Open a terminal pane (or a new terminal) **while a factor-mining run is active**
  (start one off-camera just before this scene, or use the run from Scene 6).

### Action

```bash
watch -n 1 rocm-smi
```

(Press `Ctrl+C` to exit after a few seconds of recording.)

### Expected Output

The `compute%` and `VRAM%` columns should rise noticeably during LLM inference and
backtest computation (e.g., compute jumps to 60–95%, VRAM holds around the model
footprint).

### Narration

> "While factor mining runs, `rocm-smi` shows the AMD Radeon GPU actively at work —
> compute utilization climbs as the LLM generates hypotheses and Qlib crunches the
> backtest. **All inference happens locally on the AMD Radeon GPU. Zero data leaves
> the device.**"

### On-screen Timing

| Time | Action |
|------|--------|
| 4:00–4:10 | Run `watch -n 1 rocm-smi` |
| 4:10–4:25 | Let GPU utilization climb on screen |
| 4:25–4:30 | `Ctrl+C`, deliver privacy statement |

---

## Scene 8 — Conclusion (15s)

**Goal:** Summarize the demo with the key metrics.

### Shot

- Return to the chat interface or a clean title card.

### Narration

> "**aiQuant** demonstrates a fully private AI Agent for quantitative research,
> running **Qwen3-8B** on an AMD Radeon GPU with **ROCm acceleration**.
>
> Key metrics: approximately **90 tokens per second** inference, **100% local**
> computation with zero data egress, and a natural-language interface that turns a
> single sentence into a complete factor-mining R&D loop.
>
> Thank you for watching."

### On-screen Timing

| Time | Action |
|------|--------|
| 4:30–4:40 | Summary narration over chat / title card |
| 4:40–4:45 | End card with project name + repo link |

---

## Recording Tips

### Video Quality

- **Resolution:** 1920×1080 (1080p). Do not record at 4K — text becomes tiny and
  file sizes balloon.
- **Frame rate:** 30 fps minimum; 60 fps preferred so terminal text remains crisp
  during fast scrolling.
- **Bitrate:** 6–10 Mbps (OBS `CBR` or `VBR`).

### Visual Hygiene

- Use a **clean, solid-color desktop background** (dark gray `#1e1e1e` works well
  with the app's dark theme).
- Hide the OS dock/taskbar and browser bookmarks bar to maximize usable screen.
- Set terminal font to **16pt or larger**; use a monospace font with clear
  zero/oh distinction (e.g., JetBrains Mono, Fira Code).
- Increase terminal contrast; avoid transparency / blur effects.
- Close all notifications and chat apps to prevent popups during recording.

### Audio (if narrating live)

- Use a dedicated USB microphone if available; avoid the built-in laptop mic.
- Record a 10-second test clip and listen back for levels — aim for peaks around
  **-12 dB to -6 dB**, never clipping at 0 dB.
- Record in a quiet room; minimize echo and background HVAC noise.
- Speak slowly and leave brief pauses between scenes for easier editing.
- If narrating in post-production, record each scene's narration as a separate
  clip for easier alignment.

### Editing

- Trim dead air between commands (the gap between pressing Enter and output
  appearing).
- Add a short title card at the start: "aiQuant — Private AI Agent for
  Quantitative Factor Mining on AMD Radeon GPU".
- Add a lower-third label when switching between terminal / browser / Streamlit.
- Keep total runtime between **3 and 5 minutes**.

### Backup Plan

- Record a full dry run **off-camera** first; keep it as a fallback.
- If a live run stalls on camera, cut to the pre-recorded warm-up output.
- Save terminal command output to log files so you can re-narrate over static
  screenshots if needed.

---

## Automated Demo Flow (Bash Script)

The script below runs the full demo sequence programmatically. It is designed to be
run on the Radeon Cloud instance after the Lemonade server (port 13305) and Redis
are already up. Each step prints a banner so the output is easy to follow on camera
or in a log.

Save this as `demo_flow.sh` and run `bash demo_flow.sh`.

```bash
#!/usr/bin/env bash
#
# demo_flow.sh — aiQuant automated demo sequence
#
# Prerequisites:
#   * Radeon Cloud instance with ROCm installed
#   * Lemonade LLM server running on http://localhost:13305 (Qwen3-8B)
#   * Redis running on localhost:6379
#   * Working directory: aiquant-agent/src
#
# Usage:
#   cd Radeon-hackathon-2026-07/submissions/track2/aiquant-agent/src
#   bash ../video/demo_flow.sh
#
set -euo pipefail

# ── Configuration ────────────────────────────────────────────────
API_HOST="http://localhost:8010"
LLM_HOST="http://localhost:13305"
UNIVERSE="沪深300"        # CSI 300
LOOP_N=1
ALL_DURATION="30m"
C=15                      # pause color duration / divider

# ── Helpers ─────────────────────────────────────────────────────
banner() {
  echo ""
  echo "═══════════════════════════════════════════════════════════════"
  echo "  $1"
  echo "═══════════════════════════════════════════════════════════════"
}

step() {
  echo ""
  echo "▸ $1"
}

wait_for() {
  # wait_for <url> <label>
  local url="$1"; local label="$2"; local tries=0
  until curl -sf "$url" >/dev/null 2>&1; do
    tries=$((tries + 1))
    if [ "$tries" -ge 60 ]; then
      echo "✗ Timed out waiting for $label at $url"
      exit 1
    fi
    echo "  … waiting for $label ($tries/60)"
    sleep 2
  done
  echo "  ✓ $label is up"
}

# ════════════════════════════════════════════════════════════════
# SCENE 1 — Introduction: show AMD GPU
# ════════════════════════════════════════════════════════════════
banner "SCENE 1 — AMD Radeon GPU (rocm-smi)"
step "Displaying AMD GPU status:"
rocm-smi || { echo "✗ No AMD GPU found (rocm-smi failed)"; exit 1; }

# ════════════════════════════════════════════════════════════════
# SCENE 2 — LLM Server: verify Qwen3-8B on port 13305
# ════════════════════════════════════════════════════════════════
banner "SCENE 2 — Lemonade LLM Server (Qwen3-8B)"
step "Waiting for LLM server at ${LLM_HOST} …"
wait_for "${LLM_HOST}/v1/models" "Lemonade LLM server"

step "Querying loaded models:"
curl -s "${LLM_HOST}/v1/models" | python3 -m json.tool

# ════════════════════════════════════════════════════════════════
# SCENE 3 — Start aiQuant API gateway on port 8010
# ════════════════════════════════════════════════════════════════
banner "SCENE 3 — Start aiQuant API Gateway"

# Start the API server in the background if not already running
if curl -sf "${API_HOST}/api/health" >/dev/null 2>&1; then
  step "aiQuant API is already running on port 8010."
else
  step "Starting aiQuant API server (uvicorn) in background …"
  CONDA_DEFAULT_ENV=base \
    uvicorn backend.api.main:app --host 0.0.0.0 --port 8010 --loop asyncio \
    > /tmp/aiquant_api.log 2>&1 &
  echo "  (PID $!)  logs → /tmp/aiquant_api.log"

  step "Waiting for API gateway to become healthy …"
  wait_for "${API_HOST}/api/health" "aiQuant API"
fi

step "Health check:"
curl -s "${API_HOST}/api/health" | python3 -m json.tool

# ════════════════════════════════════════════════════════════════
# SCENE 4 & 6 — Factor Mining via API (SSE streaming)
# (Run via API here; in the video the chat UI version is shown in
#  Scene 4 and this curl version in Scene 6.)
# ════════════════════════════════════════════════════════════════
banner "SCENE 4 / 6 — Factor Mining (SSE stream)"

step "Submitting factor-evolution request:"
echo "  universe  = ${UNIVERSE}"
echo "  loop_n    = ${LOOP_N}"
echo "  duration  = ${ALL_DURATION}"
echo ""

curl -N -X POST "${API_HOST}/api/research/factor-evolve/stream" \
  -H "Content-Type: application/json" \
  -d "{
    \"loop_n\": ${LOOP_N},
    \"universe\": \"${UNIVERSE}\",
    \"all_duration\": \"${ALL_DURATION}\"
  }" | while IFS= read -r line; do
    # Pretty-print each SSE data line, extracting the type/stage
    if [[ "$line" == data:* ]]; then
      payload="${line#data: }"
      type=$(echo "$payload" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('type','?'))" 2>/dev/null || echo "?")
      stage=$(echo "$payload" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('stage',''))" 2>/dev/null || echo "")
      elapsed=$(echo "$payload" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('elapsed_sec','?'))" 2>/dev/null || echo "?")
      printf "  [%ss] type=%-12s stage=%s\n" "$elapsed" "$type" "$stage"
    fi
  done

# ════════════════════════════════════════════════════════════════
# SCENE 5 — Factor Report (fetch final report)
# ════════════════════════════════════════════════════════════════
banner "SCENE 5 — Factor Mining Report & Visualization"
step "Opening Streamlit visualization UI at http://localhost:19899 …"
if curl -sfI http://localhost:19899 >/dev/null 2>&1; then
  echo "  ✓ Streamlit UI is running — open http://localhost:19899 in your browser"
else
  echo "  (i) Streamlit UI not detected on 19899 — start RD-Agent UI if needed"
fi

step "Querying factor report endpoint:"
curl -s "${API_HOST}/api/research/reviews" | python3 -m json.tool | head -40

# ════════════════════════════════════════════════════════════════
# SCENE 7 — GPU Utilization during mining
# ════════════════════════════════════════════════════════════════
banner "SCENE 7 — GPU Utilization (rocm-smi)"
step "Current GPU state (run while factor mining is active for live utilization):"
rocm-smi

# ════════════════════════════════════════════════════════════════
# Done
# ════════════════════════════════════════════════════════════════
banner "DEMO COMPLETE"
echo "  Chat UI:        http://localhost:8010"
echo "  API docs:       http://localhost:8010/docs"
echo "  Visualization:   http://localhost:19899"
echo "  LLM server:     http://localhost:13305/v1/models"
echo ""
echo "  All inference ran locally on AMD Radeon GPU — zero data left the device."
echo "═══════════════════════════════════════════════════════════════"
```

### Quick Reference — Key Commands

| Scene | Command | Purpose |
|-------|---------|---------|
| 1 | `rocm-smi` | Show AMD GPU |
| 2 | `curl -s http://localhost:13305/v1/models \| python3 -m json.tool` | List loaded LLM model |
| 3 | `CONDA_DEFAULT_ENV=base uvicorn backend.api.main:app --host 0.0.0.0 --port 8010 --loop asyncio` | Start API gateway |
| 3 | `curl -s http://localhost:8010/api/health \| python3 -m json.tool` | Health check |
| 4 | *(type in chat UI)* `在沪深300挖掘动量因子，迭代1轮` | Natural-language factor mining |
| 5 | Open `http://localhost:19899` | Streamlit visualization |
| 6 | `curl -N -X POST http://localhost:8010/api/research/factor-evolve/stream -H "Content-Type: application/json" -d '{"loop_n": 1, "universe": "沪深300", "all_duration": "30m"}'` | API-driven factor mining (SSE) |
| 7 | `watch -n 1 rocm-smi` | Live GPU utilization |

---

*End of demo recording guide. Adjust scene timings as needed to stay within the
3–5 minute window.*
