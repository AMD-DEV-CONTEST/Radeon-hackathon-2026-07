# Shoot day checklist

Everything needed to record the demo, in order. Target: one continuous
screen recording of the live build (~15 min of footage), edited down to
3–5 minutes. Nothing here needs typing beyond copy-paste.

---

## STEP 0 — before recording (10 min)

- [ ] Radeon Cloud portal → launch the **unsloth-vincent** workspace.
- [ ] Drag `foundry-transfer.tar.gz` (in this folder) into the JupyterLab
      file browser sidebar.
- [ ] Close every app you don't need. Browser: one window, no personal
      tabs, bookmarks bar hidden (Ctrl+Shift+B).
- [ ] Paste **BLOCK 1** into a notebook cell. It runs `scripts/up.sh`:
      parallel accelerated downloads, models cached in
      `/workspace/foundry-models` (a repeat session on a rebuilt instance
      skips the 19GB entirely), then starts and verifies the UI. It ends
      by printing `READY` with the actual bring-up time — wait for that.

```bash
!Z=$(find / -maxdepth 4 -name "foundry-transfer.tar.gz" 2>/dev/null | head -1); mkdir -p ~/foundry-project && tar -xzf "$Z" -C ~/foundry-project && cd ~/foundry-project && LLAMA_CPP_BUILD=1 bash scripts/up.sh
!nohup cloudflared tunnel --url http://localhost:8300 > tunnel.log 2>&1 & sleep 10 && grep -o "https://[a-z0-9-]*\.trycloudflare\.com" tunnel.log | head -1
```

(`LLAMA_CPP_BUILD=1` covers images without a prebuilt llama.cpp — the
Aug 5 image dropped it. When a prebuilt exists it is found first and
the flag does nothing. Measured Aug 5: READY in 446s on a bare image,
source build + 18GB download included, overlapped.)

- [ ] Open the printed `trycloudflare.com` URL. Welcome screen + GPU card
      showing ~24 GB = ready.
- [ ] OBS → Sources → **+** → Window Capture → that browser window →
      fit to canvas.

---

## STEP 1 — the main take (~15 min, one continuous recording)

- [ ] **Start Recording.** Do not stop until the end of this section.
      Mistakes are fine — they get cut.

1. **Click the first suggestion card** ("Support-ticket triage model").
   The prompt sends itself. The agent drafts the spec and previews
   3 sample tickets. (~1 min)

2. When it asks for approval, paste:
   ```
   Approved — 900 train, 100 holdout. Go.
   ```

3. **Now do nothing for ~20 minutes.** Watch: plan bar ticking, chips
   with live counters (`datagen: 320/1000 accepted…`, training steps),
   GPU utilization pegged. It runs datagen → train → eval → diagnose →
   (improvement round) by itself and reports the before/after.

   *Only if it ever stalls >2 min with no counter moving:* paste
   `Continue.` — that is the one allowed nudge.

4. When it presents results and asks about export, paste:
   ```
   Benchmark the quantizations, then export the best one.
   ```
   (~8 min: ladder + chart appear in the right rail.)

5. Screenshots now (Win+Shift+S, save to Downloads):
   - [ ] whole UI with the finished build + chart
   - [ ] close-up of the build card (all four badges lit)
   - [ ] close-up of the experiment registry

6. Paste the closing line:
   ```
   That's all — thanks.
   ```

- [ ] **Stop Recording.**

---

## STEP 2 — the cold-open clip (~3 min, second recording)

The opening shot: the finished model answering instantly, before the
viewer knows where it came from.

- [ ] In JupyterLab: **File → New → Terminal**. Point OBS at that window,
      **Start Recording**.
- [ ] Paste, one at a time, pausing so each result is readable:

```bash
cd ~/foundry-project && ls -lh runs/slice-*/student-q5_k_m.gguf | tail -1
```
```bash
/opt/llama.cpp/build/bin/llama-server -m $(ls -t runs/slice-*/student-q5_k_m.gguf | head -1) --port 8200 --jinja > /dev/null 2>&1 & sleep 20 && echo model served
```
```bash
curl -s localhost:8200/v1/chat/completions -H 'Content-Type: application/json' -d '{"messages":[{"role":"system","content":"You are the ticket triage engine for Northbeam Software. Given a support ticket, respond with a single JSON object and nothing else: {\"category\": <one of outage, account_access, billing, technical_issue, data_request, feature_request>, \"priority\": <one of P1, P2, P3, P4>}"},{"role":"user","content":"Nobody on my team can log in, the app shows a 503"}],"temperature":0,"chat_template_kwargs":{"enable_thinking":false}}' | python3 -c "import json,sys; print(json.load(sys.stdin)['choices'][0]['message']['content'])"
```
```bash
curl -s localhost:8200/v1/chat/completions -H 'Content-Type: application/json' -d '{"messages":[{"role":"system","content":"You are the ticket triage engine for Northbeam Software. Given a support ticket, respond with a single JSON object and nothing else: {\"category\": <one of outage, account_access, billing, technical_issue, data_request, feature_request>, \"priority\": <one of P1, P2, P3, P4>}"},{"role":"user","content":"You should really add a Notion integration"}],"temperature":0,"chat_template_kwargs":{"enable_thinking":false}}' | python3 -c "import json,sys; print(json.load(sys.stdin)['choices'][0]['message']['content'])"
```

- [ ] **Stop Recording.**

---

## STEP 3 — save everything, then destroy (5 min)

```bash
!cd ~/foundry-project && tar --exclude "*.gguf" --exclude merged --exclude adapter -czf /workspace/radeon-final.tar.gz runs && ls -lh /workspace/radeon-final.tar.gz
```

- [ ] Download `radeon-final.tar.gz` from the file browser.
- [ ] **Destroy the instance** (portal → Active Instance → Destroy).
- [ ] Put both recordings + the 3 screenshots + the tarball in Downloads.

---

## STEP 4 — edit (Clipchamp, built into Windows, ~40 min)

Structure (target 4:30, hard cap 5:00):

| # | Source | Treatment |
|---|---|---|
| 1 | Cold-open clip | Real time. Caption: *"This model triages support tickets. 424 MB. It runs offline. It didn't exist this morning."* |
| 2 | Main take: prompt + spec + samples | Real time (~1 min) |
| 3 | Datagen | **Speed 8×**, keep counter + GPU meter visible (~30 s on screen) |
| 4 | Training + eval table | 4× through training, **real time on the eval table** |
| 5 | Diagnosis + improvement round | 4×, real time on the before/after table |
| 6 | Benchmark + chart | 8×, real time on the chart |
| 7 | Export + final state | Real time, hold on the finished build card |

Captions to add (Clipchamp → Text): the numbers are the star —
*"1,000 examples, 99% accepted"*, *"base 15% → tuned 97%"*,
*"424 MB, 2.6× faster than its 30B teacher"*, *"all on one AMD Radeon,
nothing left the machine"*.

End card: **Foundry · AMD AI DevMaster Hackathon Track 2 · github.com/abidedavana/foundry-amd-hackathon**

- [ ] Export 1080p → `foundry-demo.mp4` in this folder.
