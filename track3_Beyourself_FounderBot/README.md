FounderBot — Auditable Co-Founder Decisions in Motion
Submission Profile
	•	Track: Track 3 — Physical AI Challenge
	•	Team: Beyourself
	•	Application: FounderBot
	•	Project lead: chillihcc2020-hub
	•	Physical AI architecture and implementation: Jim Cheng (JimchengChina)
	•	Dedicated source repository: https://github.com/chillihcc2020-hub/founderbot-amd
	•	Frozen reviewed source: https://github.com/chillihcc2020-hub/founderbot-amd/tree/618e8580c9326c4f6bfb32a0a45a9091ee6c69c7
Official Deliverables
Requirement
Material
Technical Report
https://github.com/chillihcc2020-hub/founderbot-amd/blob/main/docs/TECHNICAL_REPORT.md
Reproducibility Instruction README
https://github.com/chillihcc2020-hub/founderbot-amd/blob/main/README.md
Evidence Index
https://github.com/chillihcc2020-hub/founderbot-amd/blob/main/docs/EVIDENCE_INDEX.md
AMD ROCm performance report
https://github.com/chillihcc2020-hub/founderbot-amd/blob/main/artifacts/rocm/performance.md
Sanitized ROCm evidence
https://github.com/chillihcc2020-hub/founderbot-amd/blob/main/artifacts/rocm/rocm_evidence.json
Demonstration video, 4:14
https://github.com/chillihcc2020-hub/founderbot-amd/releases/download/amd-track3-submission-v1/FounderBot_AMD_Physical_AI_Demo_v4.mp4
Editable presentation
https://github.com/chillihcc2020-hub/founderbot-amd/releases/download/amd-track3-submission-v1/FounderBot_AMD_Physical_AI_Submission_Deck_V4.pptx
Public media release
https://github.com/chillihcc2020-hub/founderbot-amd/releases/tag/amd-track3-submission-v1
Application
FounderBot is a Physical AI MVP for founder-work preparation. It observes a simulated desktop, converts camera pixels into a reviewable Scene JSON, identifies business context and sequencing risk, creates a dependency-aware task plan, and converts the first approved recommendation into visible robot motion.
The demonstrated workflow is:
PyBullet workspace → PyTorch/HIP perception → Scene JSON → Founder Agent decision trace → ordered Plan → robot Action → Result
In the investor-meeting scenario, FounderBot recommends validating the financial report before updating the pitch deck because unsupported financial claims can propagate into investor materials.
Four-Module Physical AI Loop
	1	PyBullet founder-workspace simulation and camera.
	2	PyTorch/HIP visual perception with versioned Scene JSON.
	3	Founder Agent with objective, risk, rationale, dependencies, and task ordering.
	4	Robot action execution with a 36-step motion and auditable result.
AMD Radeon and ROCm
The formal evidence was captured on Radeon Cloud using an AMD gfx1100 device with ROCm, PyTorch HIP, and amd-smi.
Representative Repeat 2 results:
Measurement
Result
AMD device
gfx1100, 49,136 MiB
2048×2048 GPU matrix median / p95
0.823 / 0.856 ms
Vision perception median
4.162 ms
Founder Agent median
0.014 ms
Robot action median
0.260 ms
amd-smi samples
5 / 5 pass
Overall status
pass
The evidence collector redacts hostname, serial, UUID, BDF, PCI, and related private hardware identifiers.
Product Direction and Truth Boundary
FounderBot is the proposed physical execution layer for the separately implemented Cofounder-OS:
https://github.com/JimchengChina/cofounder-os
Cofounder-OS provides a governed founder decision control plane with goals, specialist roles, dependencies, approvals, artifacts, and audit records. FounderBot validates the physical perception-and-action contract. This submission does not claim that the two repositories already constitute a finished production integration.
Reproducibility Result
The merge commit was independently validated in a clean Linux x86_64 environment:
	•	13 automated tests passed.
	•	Five workspace objects were detected.
	•	The investor-meeting context was identified.
	•	A dependency-aware three-task plan was generated.
	•	The first robot action completed in 36 steps.
	•	A 37-frame headless robot-motion animation was generated.
	•	The committed AMD evidence reports overall_status: pass.
Team Contributions
	•	chillihcc2020-hub: project lead, repository ownership, project coordination, final review, merge authority, and official contest submission.
	•	Jim Cheng (JimchengChina): Physical AI architecture and implementation, PyBullet simulation, perception, Founder Agent, robot execution, AMD ROCm evidence, testing, documentation, and demo production.
