# SUMMARY — AMD AI DevMaster Hackathon (Track 2) submission prep

Standalone repo at `hackathon-submission/` (own `git init`, no connection to production
RugBuster repos — nothing outside this folder was modified).

## What's done

- **Repo structure**: `src/`, `docs/`, `docker/`, `tests/`, `main.py`, `requirements.txt`,
  `.env.example`, `.gitignore`.
- **7 CIA modules ported** (`src/cia_modules.py`) from `rugbuster-api/avax_collector_v6.py`
  (read-only reference) — detection logic/thresholds unchanged, generalized off the AVAX-only
  globals onto a chain-agnostic `ChainClient` (`src/chain_client.py`). The hardcoded default
  SnowTrace API key present in the original file was **not** carried over — this repo takes
  every credential from the environment only.
- **LangChain tool wrappers + planner** (`src/tools.py`, `src/planner.py`) — each module is a
  `StructuredTool`; the planner explicitly decides module order/inclusion per input
  completeness (multi-step task planning, AMD capability #2).
- **HMAC-SHA256 auth** (`src/auth.py`) ported unchanged from
  `rugbuster-scoring-engine/rugbuster_scoring_engine/auth.py` (permission control, capability #3).
- **Local LLM client + portable GPU config** (`src/llm_client.py`, `src/gpu_config.py`) — loads
  the Qwen3-14B QLoRA GGUF (`ffurduj/syndicate-gguf`, file `qwen3-14b.Q4_K_M.gguf` — confirmed)
  via LangChain's `LlamaCpp`, ROCm/HIPBLAS build path documented. No gfx1151-specific
  hardcoding; backend/gfx target resolved at runtime (env override → `rocminfo` autodetect →
  generic fallback).
- **Orchestrator + CLI** (`src/orchestrator.py`, `main.py`) — `CIAAgent.scan()` (plan + tools,
  no GPU needed) and `CIAAgent.scan_with_verdict()` (adds the local LLM classification step).
- **Deterministic guardrail** (`src/risk_baseline.py`) — because the current fine-tuned
  checkpoint is an early/trial run known to hallucinate (per your note), `scan_with_verdict()`
  now also computes an LLM-free risk baseline straight from the raw findings and flags any
  case where the LLM's verdict disagrees with it, instead of trusting the model silently.
  Documented honestly in `docs/PROJECT_SPEC.md` §5 "Model status & roadmap" (scan now → wait
  for real outcomes to mature → verify label quality → retrain, before promoting the model
  from advisory to primary signal).
- **Tests** (`tests/test_planner.py`, `tests/test_risk_baseline.py`) — pass locally
  (`pytest tests/ -q` → 8 passed).
- **End-to-end smoke-verified**: ran `python main.py --chain AVAX --contract 0x0...0 --no-llm`
  against the **live** public AVAX RPC/SnowTrace-via-Routescan endpoints — planning, tool
  invocation, and JSON output all worked as designed. (The LLM verdict + guardrail path was
  *not* end-to-end tested yet — see below.)
- **README.md**, **docs/PROJECT_SPEC.md**, **docker/Dockerfile**, **requirements.txt** — all
  written to match the exact Track 2 Project Specification Document requirements, confirmed
  live from `AMD-DEV-CONTEST/Radeon-hackathon-2026-07`'s README via `gh api` (not guessed).
- **Committed**: commits `21321e6` (initial), `0f49911` (guardrail) on this repo's `main`
  branch.
- **Fork created**: `https://github.com/rugbusteraipatrol/Radeon-hackathon-2026-07` — ready to
  receive the submission folder once you push it (commands already given in chat).
- **Test repo pushed**: `https://github.com/rugbusteraipatrol/rugbuster-cia-agent` — public
  clone target for testing on Radeon Cloud / your local machine, separate from the final fork.
- **PR title decided**: `"Track 2, Fedja Furduj, RugBuster CIA Intelligence Agent"`.
- **Demo video script** (`docs/DEMO_VIDEO_SCRIPT.md`) — beat-by-beat script (~3-5 min),
  what to say and which commands to run, matches the actual CLI output fields
  (`plan`, `findings`, `verdict_text`, `guardrail`).
- **PPT deck** (`RugBuster_CIA_Agent_Track2.pptx`) — 10 slides covering problem, solution,
  architecture, the 3 covered capabilities, model/deployment, the honest model-status/roadmap
  slide, inference optimization, market positioning (incl. the "0 of 58 other Track 2 teams
  are doing blockchain fraud detection" finding), and closing/links. Passed structural
  validation and content QA; **visual QA (rendering to images) could not be run** — no
  LibreOffice installed on this machine — so layout was checked by hand-calculating every
  text box's coordinates instead of a rendered screenshot. Worth a quick look yourself before
  using it, in case anything still overflows in real PowerPoint.

## What's left for you to do manually

1. **Get a Radeon Cloud instance actually running** — the Gallery templates (unsloth-vincent,
   Unsloth Studio image, Huggingface Oneclick) all failed to launch during testing, most likely
   platform-side (a maintenance banner was observed, and AMD staff confirmed similar reports on
   Discord). Next thing to try: manually add a template with Container Image
   `amd-oneclick-base:rocm7.2.1-py3.12-v20260416` ("AMD OneClick Base" — AMD's own recommended
   default), with GitHub Repo URL set to `https://github.com/rugbusteraipatrol/rugbuster-cia-agent`
   so it auto-clones. AMD staff (Guo Hongwei) confirmed local Radeon GPU development is
   acceptable — the final project just needs to be *able* to run on Radeon Cloud, so this isn't
   a hard blocker, just needs to be confirmed before/at submission.
2. **Full pipeline end-to-end test** (with the local LLM + guardrail) — not yet run anywhere,
   neither locally nor on Radeon Cloud. Use `docs/DEMO_VIDEO_SCRIPT.md` beats 4-5 as the test
   script either way.
3. **Demo video recording** (3–5 min, required) — script is ready in
   `docs/DEMO_VIDEO_SCRIPT.md`, follow it beat by beat.
4. **PR submission** — fork is done, title is decided, PPT is done. Push the submission folder
   to the fork (`git` commands already given in chat) and run the prepared
   `hackathon-pr-command.sh` (in `RugBuster Growth/`, next to this folder) to open the PR.
   Still need: fill in the actual demo video link in the PR body before running it.
5. **Numbers worth double-checking in the PPT**: `Syndicate-Protocol/README.md`'s badge says
   "358K+" / lists 184,000+ verified records for the actual QLoRA run vs. 358,000+ for the full
   historical corpus — the deck currently says "358K+ training records" (the broader corpus
   figure), matching your original prompt. Confirm that's the number you want presented.
6. **Visual check of the PPT in real PowerPoint** — validated structurally and by content dump,
   but never rendered to an image (no LibreOffice on this machine) — see note above.

## Assumptions made without your input

- Hosted this as a **brand-new standalone git repo** (your explicit choice, given the
  top-level `RugBuster Growth/.git` is a broken stub and the real CIA code is split across two
  separate GitHub repos — `rugbuster-api` and `rugbuster-scoring-engine`).
- Chose **LangChain** over CrewAI/AutoGen/LlamaIndex/OpenWebUI: thinnest adapter for wrapping
  existing plain-Python functions as tools, and first-class local GGUF support via
  `langchain_community.llms.LlamaCpp` — no extra services to run, which fit the
  packaging-only scope. Rationale is also in `docs/PROJECT_SPEC.md` §3.
- The LLM is used as a **post-hoc classifier over aggregated structured findings**, not as the
  ReAct loop driving tool selection — reasoning is in `src/orchestrator.py`'s docstring
  (matches how the model was actually trained; avoids relying on a quantized local 14B to
  reliably emit tool-call syntax).
- Kept the agent to **exactly the 7 modules** you named (not the 8th "rug velocity" module
  that also exists in the production engine) to match your task scope precisely.
- **Guardrail thresholds are a simple red-flag count** (1 flag = WARN, 3+ = DANGER), not a
  calibrated score — it exists to catch gross LLM disagreement for this submission, not to
  replace the production engine's actual calibration. Flagged as intentionally coarse in
  `src/risk_baseline.py`'s docstring.

## Not yet done

- The demo video script (`docs/DEMO_VIDEO_SCRIPT.md`) and the PPT
  (`RugBuster_CIA_Agent_Track2.pptx`) are new in the working tree, **not yet committed** — say
  the word and I'll make that commit.
