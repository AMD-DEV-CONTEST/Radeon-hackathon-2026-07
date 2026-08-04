# Demo Video Script — RugBuster CIA Intelligence Agent

Target length: 3–5 minutes. Read this once before recording so you know what to say —
you don't have to follow it word-for-word, just hit these beats in order.

Record in two passes (see chat): first a "dirty" pass with no recording to make sure
everything works, THEN a clean recorded pass. Don't record installation/download waiting.

---

## Beat 1 — Intro (15–20s)

**Say something like:**
> "Hi, I'm Fedja. This is RugBuster CIA Intelligence Agent, my submission for Track 2 —
> Development & Local Deployment of Private AI Agents. It's a token fraud detection agent
> for DeFi — it wraps an existing production system, RugBuster's CIA Intelligence Engine,
> as a LangChain agent with local AI inference on an AMD Radeon GPU."

**Show:** your face or just the terminal, whichever you're comfortable with.

---

## Beat 2 — Prove it's really on the Radeon GPU (10–15s)

**Command:**
```bash
rocm-smi
```

**Say:**
> "First, confirming we're actually on an AMD Radeon GPU via ROCm — that's a hard
> requirement for Track 2, no closed remote APIs for core inference."

---

## Beat 3 — Show the architecture, briefly (30–40s)

**Show:** `docs/PROJECT_SPEC.md` section 2 (the diagram) — either scroll to it in an editor,
or just describe it out loud over the terminal:

> "The agent has three pieces that map to the three AMD capabilities I'm covering:
> First, a planner that decides which of 7 fraud-detection modules to run and in what
> order, based on what data is available for a given token — that's multi-step task
> planning. Second, each of those 7 modules — things like funding origin tracing,
> contract backdoor detection, holder concentration — is exposed as a LangChain tool,
> that's tool invocation. Third, every call is HMAC-SHA256 signed, that's the permission
> control layer."

---

## Beat 4 — Run it: planning + tools only, no GPU needed yet (30–40s)

**Command:**
```bash
python3 main.py --chain AVAX --contract 0xTOKEN_ADDRESS --no-llm
```
(pick any real-looking AVAX contract address, or reuse the all-zeros test one)

**Say while it runs:**
> "This is the fast path — planning and tool invocation only, no model involved yet.
> You can see it decided the order to run modules in, and here are the structured
> findings from each of the 7 modules — this part runs on plain CPU, it's the
> deterministic, already-QA'd part of the pipeline."

**Point out in the output:** the `"plan"` array (shows the rationale per step) and the
`"findings"` object.

---

## Beat 5 — Run it: full pipeline with local LLM verdict (60–90s, the main event)

**Command:**
```bash
python3 main.py --chain AVAX --contract 0xTOKEN_ADDRESS --deployer 0xDEPLOYER --deploy-timestamp 1735689600
```

**Say while the model loads/runs:**
> "Now the full pipeline — this loads a Qwen3-14B model, QLoRA fine-tuned on 358,000+
> historical fraud-scan records, running locally via llama.cpp on the Radeon GPU. It
> reads the structured findings and produces a natural-language verdict."

**When output appears, point at `"verdict_text"` and especially `"guardrail"`:**
> "One honesty note — this fine-tuned checkpoint is an early/trial run, it can still
> hallucinate. So I added a guardrail: a separate, deterministic risk baseline computed
> straight from the raw on-chain findings, no LLM involved, and the agent flags it if the
> model's verdict disagrees with that baseline instead of trusting the model blindly.
> That's this `guardrail` field here."

(If it happens to show `"agrees": false` in your test run, even better — call it out
explicitly, it proves the guardrail actually catches something.)

---

## Beat 6 — Wrap-up (15–20s)

**Say:**
> "That's RugBuster CIA Intelligence Agent — tool invocation, multi-step planning, and
> permission control, all running locally on an AMD Radeon GPU, wrapping a production
> fraud-detection engine that's already been tested on 257 real tokens. Thanks for
> watching."

**Optional last shot:** `python3 -m pytest tests/ -q` to show tests passing (green), if you
have 10 extra seconds.

---

## Checklist before you stop recording

- [ ] `rocm-smi` shown (proves Radeon GPU)
- [ ] `--no-llm` run shown (proves tool invocation + planning)
- [ ] Full run with LLM shown (proves local inference)
- [ ] `guardrail` field visible in output (proves the honesty/guardrail design)
- [ ] Total under 5 minutes

## After recording

Destroy the Radeon Cloud instance immediately (Profile → Active Instance → Destroy
Instance) — don't let it idle and burn credits.
