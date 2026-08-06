# Track 2, Xenix, Xenix Radeon Edition

> Submission-body draft. Replace every `TBD` value and recheck relative links
> after copying the frozen entry into the official contest fork.

## Application

**Xenix Radeon Edition** is a private conversational data workbench for
non-technical business users. It turns documents, tables, and images into
source-linked Datasets and Artifacts while keeping business state and canonical
results authoritative on the Windows desktop.

For Track 2, Xenix independently deploys manifest-verified Chat, Embedding, and
OCR runtimes to a participant-controlled Radeon/ROCm Linux target. Each runtime
must pass identity, compatibility, capacity, authentication, protocol, and real
ROCm workload checks before Xenix registers its provider projection. Deployment
never selects a provider for the user.

## Business scenario

The demo follows a rainy-season restocking task. An operations user imports a
scanned policy, attaches an inventory table, asks Xenix to retrieve the rule and
calculate restock quantities, reviews a separate derived Dataset, and asks a
grounded follow-up in the same conversation. The deterministic outcome is
`U100 = 130` and `R200 = 75`, with `B500` excluded.

## Track 2 capability coverage

- Local RAG with BGE-M3 embeddings and source-located `knowledge.lookup`
  results.
- Structured Tool calling through domain-backed Dataset, Knowledge, analysis,
  visualization, and model operations.
- Iterative multi-step execution across Tool Calls and typed Tool Results.
- Local multi-turn conversation history and context projection.
- Privacy controls: explicit SSH identity confirmation, authenticated
  loopback-only runtimes, session-local live bindings and secrets, preserved
  source files, and explicit provider selection.

## Radeon/ROCm evidence boundary

The current operational evidence is bounded to one exact Private SSH cell:

```text
Ubuntu 24.04 · kernel 6.8.0-106-generic · x86_64
gfx1100 · AMDGPU 6.16.6 · ROCm 7.2.1
HIP 7.2.53211-e1a6bc5663 · Python 3.12.3
```

The admitted capability options are Qwen3.5 9B, Qwen3.5 4B, BGE-M3
(1024-dimensional output), and RapidOCR with PP-OCRv6. This submission does not
claim comparative speedup, generic Radeon support, native Windows ROCm, or an
accepted Local WSL hardware path.

## Materials

- [Project Specification](PROJECT_SPEC.md) · [PDF](PROJECT_SPEC.pdf)
- [Evidence Register](EVIDENCE.md)
- [Complete source and run guide](../../README.md)
- [A3 poster](poster/Xenix-Radeon-Edition-Track-2-Poster.pdf) ·
  [PNG](poster/Xenix-Radeon-Edition-Track-2-Poster.png)
- Demo video: `DEMO_PUBLIC_URL_TBD`
- Demo SHA-256: `DEMO_SHA256_TBD`

## Run and verify

```powershell
pdm install
pdm run dev

pdm run check
pdm run test
pdm run smoke
```

Hardware publication remains gated by the selected manifest's live preflight,
capacity, protocol, authentication, and Radeon workload self-tests.

## Team

**Team:** Xenix

| Participant | Contribution | GitHub |
| --- | --- | --- |
| 袁翊闳 (Yuan Yihong; also known as Lan_zhijiang) | Product design, Radeon integration, implementation, testing, and demo production | [@xiaoland](https://github.com/xiaoland) |

The team has reviewed the official Rules and Conditions, the repository rights
notices, third-party notices, and the publication rights for every submitted
source and media asset before opening this pull request: `RIGHTS_REVIEW_TBD`.
