> ⚠️ STALE：本文件已归档，唯一信源见 docs/TRUTH.md。
# ScrewShell — Demo Video Script (3–5 min)

**Format**: screen recording + voiceover (English). Target length **4:00**.
**Golden rule**: the judges must *see* it running on a real Radeon — keep `rocm_smi` output on screen at key moments.

---

## Shot list

### [0:00–0:20] Cold open — the problem (20 s)

*Visual*: a folder full of sensitive docs (contracts, migration plans, private repo) → a red "cloud upload" icon crossed out.

> "Your most valuable knowledge is also your most sensitive: contracts, design docs, private code. You can't paste it into a cloud AI. ScrewShell is a private investigator for your own machine — a fully local AI agent, running on an AMD Radeon GPU."

### [0:20–0:50] Proof of hardware (30 s)

*Visual*: terminal — `rocm-smi` showing Radeon PRO W7900, 48 GB; then `llama-server -m Qwen3.6-27B-Q4_K_M.gguf` starting (ROCm/HIP) and `MOL_BACKEND=llamacpp python -m screwshell.ui.app --workspace demo_workspace`; VRAM climbing to ~17 GB as the 27B base loads.

> "Everything you'll see runs on this AMD Radeon PRO W7900 with 48 gigabytes of VRAM, on ROCm 7.2.4. One frozen Qwen3.6-27B base loads into VRAM through llama.cpp — and stays there. Core functionality makes zero remote API calls."

### [0:50–1:50] Demo 1 — document investigation with citations (60 s)

*Visual*: Web UI. Type: **"What are the main risks in the ROCm migration plan? Cite the relevant documents."** Show: plan panel filling with skill-tagged steps; expert badges switching across the 4-step pipeline — teichai (plan) → btl3 (tool) → cybersec (security) → rag_n7 (doc); tool receipts (rag_search, read_file); final answer with `migration_plan.md#L…` citations; evidence panel.

> "I ask a real multi-step question. Watch the left panel: ScrewShell plans the investigation, and its Skill Router activates a different LoRA expert per step — planning, tool-calling — hot-swapped in milliseconds on the same resident base. It retrieves with a fully local RAG pipeline — embeddings computed on the Radeon — and answers with line-level citations. Every claim points to a file and a line range. Nothing left this machine."

### [1:50–2:40] Demo 2 — code investigation + multi-turn memory (50 s)

*Visual*: Type: **"Now investigate the repo and explain why the benchmark is slow."** Show btl3 (tool/code) expert badge; grep/read_file receipts; answer identifying the two planted perf bugs. Then follow-up: **"Which file supports that?"** — answered from evidence memory.

> "Now a code question. The router hot-swaps to a coding expert — btl3 — which greps the repo and finds both performance bugs: a tokenizer rebuilt inside the loop, and a float64 post-processing path. And because ScrewShell keeps evidence in session memory, follow-up questions resolve against prior findings — true multi-turn investigation."

### [2:40–3:30] The MoL optimization — benchmark (50 s)

*Visual*: split screen — `llama-server` loading the 27B base + `rocm_smi` live VRAM, and the MoL architecture diagram. Overlay the key numbers as large captions: **~50 GB → ~17 GB · one base, N adapters · seconds → sub-second switching**.

> "Here's the Radeon optimization at the heart of ScrewShell: Mixture-of-LoRA. Three specialist skills would naively need three twenty-seven-gigabyte models — over fifty gigabytes, which doesn't fit even this forty-eight-gigabyte card. ScrewShell keeps one frozen 27B base resident through llama.cpp and switches megabyte-scale LoRA adapters on that same base — no model reload, a fraction of the VRAM. That's what makes a multi-skill agent practical on a single Radeon GPU. (The 8-millisecond figure you may have seen was our earlier 9B stack; the 27B path-D numbers are in the repo's bench folder.)"

### [3:30–3:50] Safety & audit (20 s)

*Visual*: audit panel — JSON log lines; a blocked attempt to read `~/.ssh/id_rsa` shown rejected.

> "Every tool call is sandboxed, allowlisted, and logged. Secrets paths are blocked outright. Private by construction — and auditable."

### [3:50–4:00] Close (10 s)

*Visual*: architecture diagram from SPEC.md + repo URL.

> "ScrewShell: one Radeon GPU, one frozen base, unlimited community skills. Fully local, fully cited, fully yours."

---

## Recording checklist

- [ ] Terminal font ≥ 16 pt; UI at 125 % zoom; 1080p capture.
- [ ] Keep a second terminal with `watch rocm-smi` visible in shots 2 & 5.
- [ ] Pre-warm: start `llama-server` and run one throwaway query before recording (let the 27B base settle in VRAM).
- [ ] Rehearse timing; hard cap 5:00.
- [ ] Export MP4 (H.264), name: `screwshell-demo-radeon.mp4`.
