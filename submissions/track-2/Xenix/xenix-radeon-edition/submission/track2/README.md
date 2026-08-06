# Xenix Radeon Edition — Track 2 Submission Materials

Xenix Radeon Edition is an entry for **Track 2: Development & Local Deployment
of Private AI Agents** in the 2026 AMD AI DevMaster Radeon GPU Hackathon. It is
a Windows desktop AI workbench that keeps business state and canonical results
locally authoritative while running managed Chat, Embedding, and OCR inference
on a participant-controlled Radeon/ROCm target.

This page is an index, not a substitute for the project specification or the
source README.

## Judge route

1. Read the [Project Specification](PROJECT_SPEC.md) for the business scenario,
   Agent flow, architecture, models, deployment plan, and Radeon strategy.
2. Review the [Evidence Register](EVIDENCE.md) for the exact claim boundaries,
   the admitted `gfx1100 / ROCm 7.2.1` cell, and the work that is still pending.
3. Use the [repository README](../../README.md) to configure, run, and verify the
   complete source.
4. Populate the [pull-request description draft](PR_DESCRIPTION.md) only after
   the final team, video, source snapshot, and publication rights are known.
5. Before publication, complete every gate in the
   [Submission Checklist](SUBMISSION_CHECKLIST.md).

## Material index

| Material | Location | Current state |
| --- | --- | --- |
| Project specification | [Markdown](PROJECT_SPEC.md) · [PDF](PROJECT_SPEC.pdf) | Rendered and reviewed in English; performance and final Hero evidence remain explicitly bounded |
| Complete source and run guide | [Repository root](../../README.md) | Present; dependencies are locked by [`pyproject.toml`](../../pyproject.toml) and [`pdm.lock`](../../pdm.lock) |
| Evidence register | [EVIDENCE.md](EVIDENCE.md) | Present; separates implementation, observed evidence, boundaries, and non-claims |
| Pull-request description | [PR_DESCRIPTION.md](PR_DESCRIPTION.md) | Drafted for team Xenix; video links are final and the rights-review placeholder remains open |
| Architecture diagram | [assets/architecture.svg](assets/architecture.svg) | Submission asset |
| Hero key art | [assets/hero-keyart.png](assets/hero-keyart.png) | Submission asset; illustrative, not runtime proof |
| Primary demo video | [Watch](https://config.lanzhijiang.dev/xenix-track2-demo.mp4) | 4:14 · 1920×1080 · end-to-end workflow and managed AMD Radeon/ROCm capabilities |
| Supplementary live walkthrough | [Watch](https://drive.hadream.ltd/s/QSFKwAtxYe5PAqG) | 2:39 · 960×544 · live-narrated end-to-end data-analysis case |
| Supplementary poster | [PDF](poster/Xenix-Radeon-Edition-Track-2-Poster.pdf) · [PNG](poster/Xenix-Radeon-Edition-Track-2-Poster.png) · [HTML source](poster/index.html) | Selected supplementary format; A3 render and visual review passed, with final human rights review still required |
| Final publication controls | [SUBMISSION_CHECKLIST.md](SUBMISSION_CHECKLIST.md) | Open gates remain |

## Evidence posture

- Core managed inference does not depend on a remote model API or a closed
  Agent platform. The Chat, Embedding, and OCR runtimes are materialized from
  fixed manifests and reached through ordinary Xenix provider boundaries.
- The precise currently evidenced cell is one Private SSH Linux target with
  Ubuntu 24.04, kernel `6.8.0-106-generic`, `gfx1100`, driver `6.16.6`, ROCm
  `7.2.1`, HIP `7.2.53211-e1a6bc5663`, and Python `3.12.3`.
- No tokens-per-second, latency, speedup, energy, cost, CPU comparison, or NVIDIA
  comparison is claimed. A repeated same-cell performance bundle is still
  required.
- The deterministic rainy-season Hero oracle is `U100 = 130` and `R200 = 75`.
  The final accepted end-to-end Hero result and multi-turn follow-up are still
  required and must not be inferred from the key art.
- Public materials must never include private endpoints, credentials, SSH key
  material, bearer secrets, personal information, raw target logs, or internal
  production notes.

## Official references

- [Official hackathon repository and Track 2 requirements](https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07/blob/main/README.md)
- [Official Rules and Conditions](https://docs.google.com/document/d/1TwgwBNUAv8fRNQbkcTZmcRR0__Oi4WMsBfkW38ALZp4/edit?tab=t.0)

The organizers provide no mandatory submission directory or document template.
The official repository nevertheless requires an English pull request from a
fork, with a title in the specified Track/team/application format. This package
does not link to volatile internal work files; every linked local item is either
a submission material or durable repository evidence.
