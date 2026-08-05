# Accident Rights Agent - Final Submission Manifest

- Track: 2 - Development and Local Deployment of Private AI Agents
- Team: DataLink
- Application: Accident Rights Agent
- Final source commit: `e36577a`
- Final packaging date: 2026-08-05 (UTC+8)
- Source layout: browsable under `project/`
- License: Apache-2.0
- Public inference APIs: none
- Radeon deployment: AMD Radeon GPU, ROCm 7.2.1, local vLLM on `127.0.0.1:8000`
- UI evaluation path: Mac Chrome -> SSH tunnel for port 7860 -> Radeon Cloud Gradio
- Automated validation: 164 passed, 1 skipped; Ruff passed; mypy passed across 82 source files
- Golden Case local-vLLM validation: 61.951 seconds, zero failures
- Dynamic memory result: 11,808 -> 5,795 input tokens, 50.9% reduction, 100% protected-field retention
- Prefix Cache result: TTFT p50 9.003 -> 0.113 seconds, 98.8% improvement, 99.4% peak hit rate
- Concurrency result: 20/20 successful requests at concurrency 1, 2, and 4; 89.48 tokens/s at concurrency 4
- Stability result: 298/298 successful requests over 30.16 minutes; zero OOM; vLLM and checkpoints healthy

## Final deliverables

- Project README: `project/README.md`
- Project specification PDF: `project/docs/submission/project_description.pdf`
- Pitch deck: `project/docs/submission/accident_rights_agent_submission.pptx`
- Demo video: `project/docs/submission/demo_video.mp4`
- Architecture: `project/docs/submission/architecture.png`
- AMD optimization report: `project/docs/submission/amd_optimization.md`
- Test report: `project/docs/submission/test_report.md`
- Privacy and security statement: `project/docs/submission/privacy_security.md`
- Model and license declaration: `project/docs/submission/model_license.md`

The older compressed snapshots remain in this directory as recoverable synchronization history. The `project/` directory is the final, directly reviewable submission and includes the complete source, tests, legal-source snapshots, documentation, and required competition materials. Model weights, runtime credentials, private case data, checkpoints, and internal recording working files are intentionally excluded.
