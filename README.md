<div align="center">

# PitchDock
### Skip the ATS. Land directly in the recruiter's inbox.

An AI-powered recruiter outreach engine designed to connect job seekers directly with hiring managers through personalized cold emails, PDF résumé attachments, deliverability pacing, and Telegram mobile remote control.

[![AMD Hackathon](https://img.shields.io/badge/AMD_AI_DevMaster-Track_2_Agentic_AI-ED1C24?style=for-the-badge&logo=amd)](https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07)
[![AMD ROCm](https://img.shields.io/badge/AMD_ROCm-Accelerated_GPU-000000?style=for-the-badge&logo=amd)](https://rocm.docs.amd.com/)
[![Production](https://img.shields.io/badge/Production-pitchdock.xyz-2563eb?style=for-the-badge&logo=google-chrome)](https://www.pitchdock.xyz)
[![Google OAuth](https://img.shields.io/badge/Google_OAuth-Gmail_API_Verified-10b981?style=for-the-badge&logo=google)](https://www.pitchdock.xyz/privacy)
[![Telegram Bot](https://img.shields.io/badge/Telegram-Mobile_Agent-8b5cf6?style=for-the-badge&logo=telegram)](https://www.pitchdock.xyz/#telegram)

---

</div>

## 🏆 AMD AI DevMaster Hackathon Submission
* **Track:** Track 2 — Agentic AI
* **Acceleration Platform:** AMD Radeon™ GPUs & ROCm™ Software Stack
* **Submission Report:** [AMD_DevMaster_Submission.md](file:///Users/shubranshushekhar/Desktop/emailAutomater/AMD_DevMaster_Submission.md)
* **Benchmark Utility:** `python3 amd_rocm_benchmark.py`
* **Demo Video:** [Watch on YouTube](https://www.youtube.com/watch?v=f5x53-gkbyQ)

---

## 🌟 Vision & Overview

Traditional job portals drop candidate résumés into black-hole Applicant Tracking Systems (ATS) where automated keyword parsers reject up to 75% of qualified applicants before a human recruiter ever sees them.

**PitchDock** reimagines the job hunt by automating personalized, high-converting cold email outreach directly to targeted technical recruiters and talent acquisition leads.

Rather than sending generic bulk emails, PitchDock matches a candidate's background against company categories, rewrites key accomplishments specifically for each target, attaches a PDF résumé, and paces out dispatches so every message arrives naturally in the recruiter's primary inbox.

---

## ⚡ What PitchDock Does

### 🎯 01 · Context-Aware Pitch Personalization (AMD ROCm Accelerated)
PitchDock's AI engine analyzes a candidate’s work history and matches key technical highlights against the target recruiter’s company profile. Powered by **AMD Radeon GPUs and the ROCm software stack**, local model inference runs with zero cloud API latency and zero data leakage.

### ✉️ 02 · Direct Inbox Routing via Gmail API
Integrates directly with Google OAuth (`https://www.googleapis.com/auth/gmail.send`) to dispatch emails directly through the user's authentic Gmail account.
* Every message includes a real PDF résumé attachment (not an untrusted third-party download link).
* Zero inbox reading, indexing, or data retention—strictly send-only authorization.

### 🛡️ 03 · Deliverability & Stagger Queue Guard
Bulk email blasts get flagged as spam. PitchDock features an automated deliverability pacing engine that spaces out email sends across batches, enforcing strict daily quotas to preserve domain reputation and guarantee high deliverability.

### 📱 04 · Telegram Mobile Remote Copilot (Agentic Tool Execution)
Never lose momentum on your job search. PitchDock includes a dedicated **Telegram Mobile Agent** that allows users to monitor and trigger outreach campaigns from their phone:
* **/link CODE**: Secure 1-click single-use token pairing between Telegram and PitchDock accounts.
* **status**: Check live campaign progress, daily send quotas, and pending recruiter queues in real time.
* **send 5 emails**: Remote execution of email dispatches from Telegram chat.
* **Natural Language AI**: Ask questions about queue status or pending drafts anytime.

---

## 🚀 AMD Radeon™ GPU & ROCm Acceleration Setup

### 1. AMD ROCm Environment Setup
```bash
# Clone the repository
git clone https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07.git
cd Radeon-hackathon-2026-07

# Install Python dependencies & PyTorch ROCm HIP build
pip install -r requirements.txt
pip install torch --index-url https://download.pytorch.org/whl/rocm6.1
```

### 2. Run ROCm Performance Benchmark
```bash
python3 amd_rocm_benchmark.py
```

---

## 🔄 System Architecture & Execution Pipeline

```mermaid
flowchart TD
    subgraph Candidate ["👤 Candidate Interface"]
        A[Candidate Profile & CV] --> B[Target Recruiter Queue]
        C[Telegram Mobile App] -->|Chat Commands| D[PitchDock Telegram Agent]
    end

    subgraph Engine ["⚡ PitchDock Agentic Engine & AMD ROCm Core"]
        B --> E[Company Category Matcher]
        E --> F[AMD ROCm Local Model Worker]
        F --> G[Stagger Queue & Delay Guard]
    end

    subgraph Delivery ["🚀 Dispatch & Delivery"]
        G -->|Gmail API / OAuth| H[Recruiter Inbox]
        D -->|Remote Dispatch Trigger| G
    end

    subgraph Verification ["🛡️ Security & Privacy Guard"]
        H --> I[Direct Email Delivery + PDF Attachment]
    end
```

---

## 💎 Core Platform Capabilities

| Capability | PitchDock | Manual Cold Pitching | Bulk Email Tools |
| :--- | :---: | :---: | :---: |
| **AMD ROCm GPU Acceleration** | **✓ Local GPU inference** | ✕ No GPU engine | ✕ Cloud API only |
| **Personalized Pitch Accomplishments** | **✓ AI-tailored per recruiter** | ✓ Manual & slow | ✕ Single template |
| **Direct Résumé PDF Attachment** | **✓ Attached automatically** | ✓ Supported | ✕ Links only (spam risk) |
| **Send Pacing & Delay Guard** | **✓ Staggered safety queue** | — Not applicable | ✕ Bulk blasts (domain risk) |
| **Telegram Remote Control** | **✓ Full chat control** | ✕ No mobile bot | ✕ No mobile bot |

---

## 🛡️ Security, Privacy & Compliance

1. **Gmail Send Scope (`gmail.send`)**: Minimal scope required to deliver outreach emails authorized by the candidate.
2. **Zero Read Policy**: PitchDock **never** reads, scans, indexes, or stores your Gmail inbox messages or threads.
3. **Google User Data Policy**: Full compliance with the [Google API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy).

---

<div align="center">

**PitchDock** — *Reach the recruiter, not the filter.*

[Visit pitchdock.xyz](https://www.pitchdock.xyz) · [Privacy Policy](https://www.pitchdock.xyz/privacy) · [Terms of Service](https://www.pitchdock.xyz/terms)

</div>
