# PitchDock — Supplementary Presentation Deck
## AMD AI DevMaster Hackathon — Track 2: Agentic AI

---

## Slide 1: Title & Overview
### PitchDock — AI Agentic Recruiter Outreach Engine
**Submitting Track:** Track 2 (Development & Local Deployment of Private AI Agents)  
**Accelerated Hardware:** AMD Radeon™ GPUs & ROCm™ Software Stack  
**Author:** Shubranshu Shekhar  
**Live Application:** [pitchdock.xyz](https://www.pitchdock.xyz)  

> *Skip the ATS black hole. Land directly in the recruiter's inbox.*

---

## Slide 2: The Problem
### The ATS Black Hole
- **75% Rejection Rate:** Automated Applicant Tracking Systems (ATS) reject up to 75% of qualified technical applicants before a human recruiter reads their CV.
- **Generic Cold Emails Fail:** Recruiter inboxes receive hundreds of generic emails daily; unpersonalized pitches are deleted within 5 seconds.
- **Privacy & Rate Limiting Risks:** Bulk email blasts flag candidate domains as spam, while cloud AI APIs expose personal candidate resumes to 3rd-party servers.

---

## Slide 3: The Solution
### PitchDock Agentic Outreach Copilot
1. **Context-Aware Accomplishment Rewriting:** AI matches candidate background against target company profiles and role expectations.
2. **Local Privacy via AMD ROCm:** Executes local LLM inference on AMD Radeon GPUs, guaranteeing zero data leakage and zero API latency.
3. **Deliverability Safety Guard:** Enforces staggered email dispatches with configurable 5s–30s delay guards.
4. **Telegram Mobile Remote Copilot:** Monitor campaign progress, daily send quotas, and launch dispatches from your smartphone.

---

## Slide 4: Track 2 Agentic Architecture
```
+-----------------------------------------------------------------------+
|                       PitchDock Agentic System                        |
+-----------------------------------------------------------------------+
|  Candidate Interfaces : Web Console & Telegram Mobile Bot             |
|                                                                       |
|  Agent Planner       : Intent Parser & Tool Binding Router            |
|                                                                       |
|  Memory & Context    : SQLite Local State (Quotas, Contacts, Stats)   |
|                                                                       |
|  AMD Acceleration    : ROCm HIP PyTorch Engine (AMD Radeon GPU)       |
|                                                                       |
|  Deliverability Guard: Batch Stagger Engine -> Google OAuth / SMTP    |
+-----------------------------------------------------------------------+
```

---

## Slide 5: AMD Radeon GPU & ROCm Acceleration
### Local Performance & Benchmarks
- **Hardware Stack:** AMD Radeon™ GPUs + AMD ROCm™ 6.1 Software Stack
- **Engine:** PyTorch HIP (`rocm_inference.py`) + Ollama ROCm Local Engine
- **Inference Speed:** **~48.5 tokens/second**
- **Draft Latency:** **~0.421 seconds per recruiter pitch**
- **Privacy:** 100% On-device execution with zero external LLM API calls.

---

## Slide 6: Telegram Mobile Remote Copilot
### Natural Language & Command Control
- **/link CODE**: Secure 1-click token pairing between Telegram and PitchDock account.
- **status**: Instant real-time view of daily quotas, remaining emails, and recruiter queues.
- **send 5 emails**: Remote execution of deliverability-safe email batch dispatches.
- **Natural Language Agent**: Ask natural language questions regarding campaign status or recipient lists.

---

## Slide 7: Value Proposition & Future Impact
- **Candidate Empowerment:** Direct access to talent acquisition leads with personalized, high-converting pitches.
- **Domain Protection:** Deliverability pacing safeguards domain sender score.
- **AMD Community Contribution:** Demonstration of private agentic LLM workloads running seamlessly on AMD Radeon GPUs.

---
*Thank you for evaluating PitchDock for the AMD AI DevMaster Hackathon!*
