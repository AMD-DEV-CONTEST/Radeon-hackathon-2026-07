# XiangLens Submission Package

## Project

**XiangLens — Private, evidence-backed profile-image review on AMD Radeon and ROCm**

Track: **AMD AI DevMaster 2026, Track 2 — Private AI Agent Development and Local Deployment**

Repository: <https://github.com/ld0574/Radeon-hackathon-2026-07>

Live static frontend: <https://ld0574.github.io/Radeon-hackathon-2026-07/>

## Deliverables

| Artifact | Location |
|---|---|
| Project brief | `docs/SUBMISSION_BRIEF.md` |
| Agent and application design | `docs/XIANGLENS_APPLICATION_DESIGN.md` |
| Environment and startup | `README.md`, `docs/LOCAL_DEVELOPMENT.md` |
| Radeon production deployment | `docs/PRODUCTION_DEPLOYMENT.md`, `docs/REPRODUCE.md` |
| Benchmark protocol | `benchmarks/README.md`, `scripts/benchmark_llama.py` |
| Dataset and rights | `docs/KNOWLEDGE_BASE_DATASET_PLAN.md`, `data/**/LICENSE.*` |
| Video plan | `docs/DEMO_VIDEO_SCRIPT.md` |
| Supplementary PPT | `submission/XiangLens_Track2_Deck.pptx` |
| Release gate | `docs/SUBMISSION_CHECKLIST.md` |

Add the final video URL and benchmark-result links before opening the competition pull request.

## Pull Request Summary

```markdown
# XiangLens — Track 2 Submission

XiangLens is a private, source-backed profile-image review Agent running its core multimodal
inference through llama.cpp on AMD Radeon PRO W7900 and ROCm. It combines a bounded LangGraph
workflow, deterministic image/privacy tools, Milvus Lite RAG, consent-first SQLite memory, typed
structured output, and an English Nuxt interface.

## Track 2 capabilities

- multi-step planning and conditional policy routing;
- local tool calling for image, EXIF, QR, and safe-copy operations;
- local Milvus Lite retrieval with visible citations;
- multi-turn threads and approved long-term memory;
- short-lived access sessions, consent-first writes, and complete user-state deletion.

## Radeon execution

The final topology runs FastAPI, LangGraph, storage, and llama-server on the same user-controlled
Radeon environment. llama-server is private at `127.0.0.1:8000/v1`; only the authenticated
XiangLens API is tunneled to the static frontend.

See `docs/SUBMISSION_BRIEF.md` for the reviewer overview and `docs/REPRODUCE.md` plus
`docs/PRODUCTION_DEPLOYMENT.md` for reproduction.
```

## Final Values to Fill

```text
SUBMITTED_COMMIT=
VIDEO_URL=
BENCHMARK_RESULT=
ROCM_VERSION=
LLAMA_CPP_COMMIT=
PUBLIC_DEMO_WINDOW=
```

Do not fill this block with secrets or a permanent tunnel credential.
