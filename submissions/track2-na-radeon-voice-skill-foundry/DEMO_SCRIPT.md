# 3-5 Minute Demo Script

Target duration: 4 minutes 15 seconds.

Final rendered duration: 3 minutes 59 seconds.

## Recording Requirements

- Narration and on-screen captions: English
- Narration model: AIDP `gemini-3.1-flash-tts-preview`, voice `Kore`
- Show the Radeon Cloud runtime or terminal before the product workflow
- Show the actual web UI, not a slide-only demo
- Keep benchmark numbers on screen long enough to read
- Do not describe the synthetic Chinese fixture as a human recording

## Shot List and Narration

### 0:00-0:20 - Problem and Product

**Visual**

- Title: Radeon Voice Skill Foundry
- Subtitle: Speak the SOP. Prove the Skill.
- Brief product UI view

**Narration**

> A local Agent can observe what a user clicks, but it cannot reliably infer
> why a step is required, which exception applies, or what must never happen.
> Radeon Voice Skill Foundry lets a domain expert speak those hidden SOP rules
> and turns them into a verified Agent Skill before the first risky run.

### 0:20-0:45 - Radeon Runtime

**Visual**

- Radeon Cloud terminal
- `rocm-smi` showing `gfx1100` and approximately 48 GiB VRAM
- Agent and ASR health endpoints

**Narration**

> The complete inference path runs locally on a Radeon Pro W7900-class
> allocation with ROCm 7.2.1. Qwen3-ASR-0.6B handles speech recognition and
> Qwen3-4B-Instruct compiles the SOP into structured constraints.

### 0:45-1:20 - Voice and Action Capture

**Visual**

- Product Capture panel
- Record or upload the SOP audio
- Voice Evidence Gate score, acoustic metrics, source hash, and transcript state
- Live transcript
- Aligned action trace

**Narration**

> In this private project-review scenario, the expert demonstrates the workflow
> and explains rules such as P0 and P1 only, redact compensation data, draft
> email but never send automatically, require confirmation for missing owners,
> and create calendar holds only when a due date exists. Before those words can
> become executable policy, a local Voice Evidence Gate measures level,
> clipping, silence, format, and source integrity. The server also binds the
> original ASR transcript hash, so later edits require explicit review.

### 1:20-2:00 - Local RAG and Skill Compilation

**Visual**

- Enable Radeon model adapter
- Compile
- Show retrieved policy evidence
- Show learned typed constraints
- Show generated `SKILL.md`

**Narration**

> The Agent retrieves local policy evidence, combines it with the spoken SOP and
> action trace, and generates typed rules, a GAIA-compatible skill, a
> least-privilege capability policy, and adversarial fixtures. Deterministic
> guardrails remain ahead of model output for high-risk behavior.

### 2:00-2:40 - Safety Verification

**Visual**

- Permission decisions
- Highlight `mail.send = deny`
- Run local verification
- Show 7/7 fixtures passed
- Show BLOCK receipts and proof hashes

**Narration**

> Verification first proves the voice evidence, then attempts the unsafe paths
> before promotion. Automatic sending,
> sensitive-field leakage, invalid conditions, and unapproved network writes
> are blocked. The final Radeon audio-backed proof run passes all seven
> fixtures, denies mail sending, and issues governance receipts plus a
> hash-bound proof bundle.

### 2:40-3:10 - Multi-Turn Refinement and Memory

**Visual**

- Refine with: "Always require confirmation before creating calendar holds."
- Show revision and parent run
- Save as Verified Skill
- Click Reuse

**Narration**

> The user can refine a rule in natural language without losing provenance.
> Once verified, the skill is versioned in local procedural memory. Exact reuse
> loads the proven skill instead of generating its policy and tests again.

### 3:10-3:45 - Radeon Optimization Results

**Visual**

- Optimization benchmark table or poster
- Highlight 656 to 463 tokens
- Highlight 30.80 to 21.55 seconds
- Highlight 24.09 seconds to 2.18 milliseconds

**Narration**

> On the same Radeon allocation, a compact structured-output protocol reduced
> median model output by 29.42 percent and generation latency by 30.03 percent
> while preserving compensation-redaction and no-send semantics. Exact reuse
> measured 2.18 milliseconds median HTTP round-trip versus 24.09 seconds for a
> full compilation, an 11,052 times fast path for this identical verified skill.

### 3:45-4:15 - Final Artifact and AMD Fit

**Visual**

- Download proof package
- Open ZIP file list
- End on architecture/poster

**Narration**

> The result is not a recording or a transcript. It is a proof-carrying local
> Agent Skill: skill definition, permission policy, adversarial tests,
> governance receipts, and reproducible Radeon evidence. Actions capture what
> the expert does. Voice captures why, when, and what must never happen.

## Caption Cards

Use these exact short cards:

- `Local voice -> governed Agent Skill`
- `Radeon Pro W7900-class | ROCm 7.2.1`
- `Qwen3-ASR-0.6B + Qwen3-4B-Instruct`
- `mail.send = DENY`
- `Voice Evidence Gate: PASS`
- `Radeon audio proof: 7/7 fixtures passed`
- `29.42% fewer output tokens`
- `30.03% lower generation latency`
- `2.18 ms exact Verified Skill reuse`
- `Proof, not just a workflow`

## Recording Checklist

- [x] Radeon terminal and health endpoints are readable
- [x] Voice waveform/transcript is visible
- [x] Voice Evidence Gate score, source hash, and transcript state are visible
- [x] Retrieved policy evidence is visible
- [x] `mail.send = deny` is visible
- [x] Verification shows 7/7
- [x] Governance receipts are visible
- [x] Reuse latency is visible
- [x] Benchmark source filename is visible
- [x] Final proof ZIP contents are visible
- [x] Uploaded video URL is added to submission README and official PR
