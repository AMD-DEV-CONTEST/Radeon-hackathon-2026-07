# AMD AI DevMaster Hackathon 2026 — Submission Guide

## Official identity

- **Track:** 2 — Development & Local Deployment of Private AI Agents
- **Team:** Physics-First AI
- **Application:** NuclidePath
- **Required PR title:** `Track 2, Physics-First AI, NuclidePath`
- **Final deadline:** 6 August 2026, 17:59 CEST
- **Official event:** <https://luma.com/amd-4dhi>
- **Official repository:** <https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07>
- **Official rules:** [Google document](https://docs.google.com/document/d/1TwgwBNUAv8fRNQbkcTZmcRR0__Oi4WMsBfkW38ALZp4/edit)

## Eligibility actions that require the participant

These cannot be proven or completed by code:

1. Luma registration and AMD approval;
2. AMD Developer Program membership;
3. valid GitHub and Discord IDs;
4. legal-name/contact registration;
5. final confirmation that eligibility and sanctions rules are satisfied.

## Track 2 functional requirements

At least two capabilities are required; more earn extra credit.

| Official capability | NuclidePath evidence |
|---|---|
| Local knowledge retrieval | `knowledge.py`, bundled Markdown corpus, citations in `workflow.json` |
| Tool invocation | `contracts.py`, deterministic `environment_agent` |
| Multi-step planning | deterministic and Qwen3.5-9B planners, six-step allowlist |
| Local multi-turn memory | private JSONL session store, mode `0600` |
| Permission/privacy | local-only policy, action allowlist, redaction, denied actions |

**Result: 5/5 implemented and exercised end to end.**

## Judging criteria — 120 points

### Functional completeness — 60 points

- clear task and creative industry scenario — 20;
- task decomposition, tool invocation, RAG and memory — 20;
- smooth multi-turn interaction — 20.

### AMD Radeon / ROCm — 40 points

- core inference on AMD Radeon — 20;
- targeted inference-speed optimization — 20.

### Optional bonus — 20 points

- Radeon-cloud core inference with quantization, distillation or comparable optimization.

NuclidePath uses Qwen3.5-9B Q8 (`8.86 GiB`) with all layers offloaded through HIP/ROCm. Measured benchmark evidence is in `docs/AMD_LLM_BENCHMARK.md`.

## Required deliverables

1. **Project Specification Document**
   - application scenario;
   - architecture diagram;
   - core capabilities;
   - model and local deployment plan;
   - AMD inference optimization.
2. **Project Source Code**
   - complete repository;
   - README with environment, startup and dependencies.
3. **Demo Video**
   - recommended 3–5 minutes;
   - actual AMD execution from UI/CLI to result;
   - show fluidity and completeness.
4. **Supplementary material**
   - PPT or poster.

## Repository delivery

The official process is:

1. fork `AMD-DEV-CONTEST/Radeon-hackathon-2026-07`;
2. add the NuclidePath submission under the fork using the structure used by the contest repository;
3. include source, README, specification link/PDF, video link and deck;
4. open a Pull Request to the official repository;
5. use exactly `Track 2, Physics-First AI, NuclidePath` as title;
6. keep every submitted material in English;
7. treat the current private `main` tree as the source snapshot and refresh the contest copy only after the publication decision.

## Recommended final PR description

```markdown
## NuclidePath

A private, physics-first AI agent for traceable Cs-137 groundwater screening.

- Track: 2 — Development & Local Deployment of Private AI Agents
- Team: Physics-First AI
- Capabilities: 5/5 official capabilities
- AMD: Radeon gfx1100, ROCm 7.2.1, llama.cpp HIP, Qwen3.5-9B Q8
- Demo video: `<FINAL_VIDEO_URL>` *(human upload gate; submission remains pending)*
- Specification PDF: submission/NuclidePath_Project_Specification.pdf
- Deck: submission/NuclidePath_Track2_Deck.pptx

All physical values are produced by a deterministic, versioned tool; the local LLM only plans the allow-listed workflow.
```

## Final human-only gate

Before PR submission, confirm:

- [x] contest fork branch exists and is synchronized to current `main`; complete source copied under `submissions/Track2-Physics-First-AI-NuclidePath/source/` with contest-local manifest v2.0;
- [ ] Luma registration approved;
- [ ] AMD Developer Program membership active;
- [ ] final video URL is public or judge-accessible;
- [x] complete source is judge-accessible because the current source is copied into the contest submission;
- [x] no personal secrets or SSH keys are tracked (verified 6 August 2026: no keys,
      tokens or credentials in any tracked file; the only match is a synthetic
      redaction fixture in `tests/test_security_memory.py`);
- [ ] final PR title is exact;
- [ ] PR opened before the official deadline;
- [x] publication/copy of the complete current source authorized by the participant.
