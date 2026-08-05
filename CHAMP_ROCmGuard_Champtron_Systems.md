# Submission: CHAMP ROCmGuard

**Track:** Track 2: Development & Local Deployment of Private AI Agents
**Team / Participant Name:** Champtron Systems

## 🔗 Project Links & Deliverables

* **Project Source Code Repository:** [https://github.com/Ces1231/champ-containerguard](https://github.com/Ces1231/champ-containerguard) (branch `feature/amd-devmaster-rocm-agent`, commit [`7154b50`](https://github.com/Ces1231/champ-containerguard/commit/7154b50172d07692d3e6f364f055c2629ab2be45))
* **Demo Video (YouTube):** [https://youtu.be/LHVIPtKzolc](https://youtu.be/LHVIPtKzolc)
* **Full Submission Document (all claims traced to evidence):** [submission/FINAL_SUBMISSION_TEXT.md](https://github.com/Ces1231/champ-containerguard/blob/7154b50172d07692d3e6f364f055c2629ab2be45/submission/FINAL_SUBMISSION_TEXT.md)
* **Project Specification / Hackathon Overview:** [HACKATHON.md](https://github.com/Ces1231/champ-containerguard/blob/7154b50172d07692d3e6f364f055c2629ab2be45/HACKATHON.md)
* **Known Limitations (disclosed, not hidden):** [docs/hackathon/KNOWN_LIMITATIONS.md](https://github.com/Ces1231/champ-containerguard/blob/7154b50172d07692d3e6f364f055c2629ab2be45/docs/hackathon/KNOWN_LIMITATIONS.md)
* **Independent Submission-Readiness Audit:** [submission/SUBMISSION_READINESS_AUDIT.md](https://github.com/Ces1231/champ-containerguard/blob/7154b50172d07692d3e6f364f055c2629ab2be45/submission/SUBMISSION_READINESS_AUDIT.md)

## 🚀 Project Summary

**CHAMP ROCmGuard** is an AMD ROCm security capability within **CHAMP ContainerGuard**, an existing, in-production container/GPU security scanning platform. Traditional container scanners don't check whether an AI workload's declared intent, its container/orchestration configuration, and the accelerator vendor actually present all line up — a container can declare ROCm environment variables, request GPU devices, pass a generic security scan, and still run on the wrong hardware or with far more device access than it needs.

CHAMP ROCmGuard adds:

* AMD ROCm-specific Dockerfile/Compose/Kubernetes scanning (privileged mode, `/dev/kfd`/`/dev/dri` over-exposure, unpinned images, Docker-socket exposure, host networking, AMD/NVIDIA vendor-mismatch env vars) — deterministic, never model-generated.
* A vendor-neutral GPU provider architecture treating NVIDIA and AMD as peers under one interface.
* A controlled agentic investigation workflow: deterministic scan → evidence-grounded analysis → **mandatory human approval** → proposed remediation → real rescan verification. The reasoning provider (deterministic by default, optionally a locally-hosted model) can never invent a finding the scanner didn't produce, and remediation is never auto-deployed.
* A hardware-provenance and ROCm-validation policy that never infers real-hardware acceleration from configuration alone, and distinguishes fixture-backed, deterministic, and physically-verified evidence with distinct, non-interchangeable status labels.

## Current validation status — disclosed honestly

| Level | Status |
|---|---|
| Deterministic scanning / remediation / verification logic | Implemented, unit/integration tested (951 passed, 1 skipped, 0 failed) |
| Fixture-backed demonstration mode | Implemented, real-browser (Playwright) verified |
| Jetson (ARM64, non-AMD GPU) live application run | Executed, real evidence — full agent lifecycle passing |
| **Supported AMD physical hardware (AMD Instinct MI300X, AMD Developer Cloud, two independent hosts)** | **Attempted 2026-08-02 — `CONFIGURED_NOT_VALIDATED`.** Real GPU/ROCm runtime confirmed present; a provider-level KFD compute-context limitation (`amdgpu: no gpu node!`) blocked actual acceleration — root-caused with reproducible evidence, not a defect in this project's deployment package. **Final for this submission: no further AMD hardware access is available before the deadline.** |
| Real benchmark numbers | Collected 2026-08-02 on the CPU path of that same MI300X host: 24.9 tokens/sec, 15.2s mean latency, 5/5 availability, 93% CPU utilization. **Not a ROCm-acceleration benchmark** — a genuine ROCm-accelerated comparison remains pending a working KFD compute path. |

**No `VALIDATED_ROCM` or `PHYSICAL AMD VERIFIED` claim is made anywhere in this submission.** The demo video's on-screen ROCm validation status is `NOT_APPLICABLE`, consistent with the non-AMD development host it was recorded on.

## Commercial use cases

Pre-production AI-container security assessment, secure local inference validation, GPU/accelerator configuration review, multi-tenant accelerator security, DevSecOps pipeline gating, compliance/audit evidence generation, private AI infrastructure assessment, and mixed-vendor AI infrastructure governance.
