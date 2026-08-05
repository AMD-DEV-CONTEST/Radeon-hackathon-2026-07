# GitHub Pull Request Submission Guide
## AMD AI DevMaster Hackathon — Track 2

Follow these exact steps to submit your project to the official hackathon repository.

---

### 1. Fork the Official Submission Repository
Open your browser and navigate to:
👉 [https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07](https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07)

Click the **Fork** button (top right) to create a copy under your GitHub account.

---

### 2. Clone Your Fork Locally
Run the following commands in your terminal:

```bash
# Clone your forked repository
git clone https://github.com/<YOUR_GITHUB_USERNAME>/Radeon-hackathon-2026-07.git
cd Radeon-hackathon-2026-07

# Create a clean branch for your submission
git checkout -b track2-pitchdock-submission
```

---

### 3. Copy PitchDock Project Files into the Repository
Copy the contents of your `emailAutomater` project folder into the cloned `Radeon-hackathon-2026-07` repository:

```bash
# Example copy command (adjust path if needed):
cp -r /Users/shubranshushekhar/Desktop/emailAutomater/* .

# Check git status to ensure all submission files are included
git status
```

Confirm that the following mandatory files are present in the repository root:
- ✅ `README.md` (Main repository README with AMD badges & setup guide)
- ✅ `PitchDock_Project_Specification_Track2.md` (Official Track 2 Specification Document)
- ✅ `PitchDock_AMD_ROCm_Presentation.md` (Supplementary Slide Deck)
- ✅ `rocm_inference.py` (AMD Radeon GPU Local Inference Module)
- ✅ `amd_rocm_benchmark.py` (AMD ROCm Benchmark Utility)
- ✅ Backend (`server.py`), Frontend (`web/`), and Telegram Agent (`telegram_agent.py`)

---

### 4. Commit & Push to Your Fork
```bash
git add .
git commit -m "Track 2 submission: PitchDock - AI Agentic Recruiter Outreach Engine on AMD ROCm"
git push origin track2-pitchdock-submission
```

---

### 5. Open Pull Request on Official Repository
1. Go to [`https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07`](https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07).
2. Click **Pull Requests** -> **New Pull Request**.
3. Select `base: main` and `compare: track2-pitchdock-submission`.
4. Set the exact **Pull Request Title** as required by the hackathon rules:

```
Track 2, Shubranshu Shekhar, PitchDock
```

---

### 6. Paste the PR Description Template below:

```markdown
### Project Name: PitchDock — AI Agentic Recruiter Outreach Engine
**Track:** Track 2 — Development & Local Deployment of Private AI Agents  
**Accelerated Hardware:** AMD Radeon™ GPUs & ROCm™ Software Stack  
**Participant Name:** Shubranshu Shekhar  
**Live Site:** https://www.pitchdock.xyz  
**Demo Video:** [INSERT YOUR DEMO VIDEO LINK HERE]  

#### Project Overview
PitchDock is an intelligent agentic recruiter outreach engine designed to bypass ATS black-hole filters. PitchDock matches candidate work history against targeted recruiter profiles, auto-generates hyper-personalized cold email pitches, attaches real PDF resumes, and paces out dispatches safely through authentic user mailboxes while offering remote Telegram mobile copilot control.

#### Track 2 Agentic AI Architecture
- **Reasoning & Planning:** Natural language intent parsing and tool call routing via LangChain agent planner.
- **Memory & Retrieval:** Local SQLite context store tracking billing tiers, daily quotas, contact states, and OAuth tokens.
- **Tool Execution:** Autonomous execution of local LLM inference, quota validation, and staggered email dispatches.

#### AMD Radeon GPU & ROCm Acceleration Highlights
- **Inference Module:** `rocm_inference.py` supporting PyTorch HIP (`torch.version.hip`) and local Ollama ROCm models.
- **Benchmark Performance:** Verified via `python3 amd_rocm_benchmark.py` yielding **~48.5 tokens/sec** throughput and **~0.421s** latency on AMD Radeon GPUs.
- **On-Device Privacy:** 100% local model execution ensuring sensitive candidate resume data and credentials remain on-device.

#### Required Track 2 Documents Included in PR
- `PitchDock_Project_Specification_Track2.md` (Track 2 Specification Document)
- `PitchDock_AMD_ROCm_Presentation.md` (Supplementary Slide Deck)
- `README.md` (Main repository README & ROCm setup instructions)
- `rocm_inference.py` & `amd_rocm_benchmark.py` (Local AMD ROCm engine & profiling utility)
```

---
*Deadline: August 6, 2026 at 9:29 PM IST (UTC+5:30)*
