# Pull Request Submission Copy

## Title

`Track 2, lucianaib, PrivateOps Agent`

## Body

### Application

PrivateOps Agent — a permission-first private computer AI running locally on AMD Radeon GPU + ROCm.

### Idea

People increasingly say, “I gave my whole computer to my AI.” Useful AI needs permission if it is going to take work away from people, but permission must not mean silent control. PrivateOps gives the Agent broad supported observation across the computer or private project, defaults to read-only behavior, requires a second exact-action confirmation for supported side effects, blocks unsafe exfiltration, and records evidence for every decision.

**Broad visibility. Deliberate action. Evidence for every decision.**

### Track 2 capabilities

- Real bilingual local RAG with stable evidence IDs.
- Visible multi-step planning and LangChain Core `StructuredTool` calls.
- Fixed read-only Windows observation plus cross-platform project/readiness tools.
- Explicit local multi-turn memory.
- Safe, confirmation-required, and blocked permission levels.
- One-use exact-action tokens, redacted audit ledger, and reviewer-visible tool evidence.

### AMD Radeon + ROCm

Core `Qwen/Qwen2.5-7B-Instruct` inference ran through ROCm vLLM on `127.0.0.1` in the same Radeon Cloud instance as PrivateOps. The captured stack used AMD Radeon Graphics (`gfx1100`) and ROCm 7.2.1. The verified direct run measured 1,511.072 ms and 32.427 completion tokens/s; the complete Chinese Agent task measured 18,384.639 ms. Source diagnostics, model logs, benchmark JSON, Agent response, and audit export are included.

Remote/shared APIs are development-only and never count as competition proof. `rocm-local` rejects non-loopback endpoints and does not silently fall back.

### Materials

- Complete source and automated tests.
- Project specification PDF and editable HTML.
- Editable English deck, one-page poster, and architecture assets.
- Radeon Cloud reproduction runbook and verified evidence.
- Performance/stability report, example prompts, timed script, and shot list.
- Final demonstration video: <https://www.bilibili.com/video/BV1nQuA6qEFS/>.
- English-subtitled version: <https://www.bilibili.com/video/BV1A1M66VEqS/>.

### Reproduction

Follow `README.md` and `submission/radeon-cloud-runbook.md`.
