## Solo Worker OS — Track 2

Solo Worker OS is a private AI operations layer for freelancers and solo
businesses. It converts natural-language requests into persistent actions such
as creating projects, generating contracts and invoices, tracking payments,
searching private knowledge, and analyzing business performance.

### AMD Radeon deployment

- Radeon Cloud, one AMD Radeon GPU (`gfx1100`)
- ROCm 7.2.1, PyTorch 2.9, vLLM 0.16.x
- `Qwen/Qwen3-4B`, 4,096-token context
- OpenAI-compatible local inference provider
- Verified `create_project` and `generate_contract` end to end
- 14 registered tools, 5 specialist subagents
- TypeScript check passed; 57/57 tests passed

### Submission materials

- [Submission overview](https://github.com/HpIahtcthocw/Radeon-hackathon-2026-07/blob/codex/track-2-solo-worker-os/submissions/track-2/solo-worker-os/submission/README.md)
- [Project Specification](https://github.com/HpIahtcthocw/Radeon-hackathon-2026-07/blob/codex/track-2-solo-worker-os/submissions/track-2/solo-worker-os/submission/PROJECT_SPECIFICATION.md)
- [Setup and reproduction guide](https://github.com/HpIahtcthocw/Radeon-hackathon-2026-07/blob/codex/track-2-solo-worker-os/submissions/track-2/solo-worker-os/README.md)
- [AMD GPU evidence](https://github.com/HpIahtcthocw/Radeon-hackathon-2026-07/blob/codex/track-2-solo-worker-os/submissions/track-2/solo-worker-os/docs/evidence/README.md)
- [Live GPU demo evidence](https://github.com/HpIahtcthocw/Radeon-hackathon-2026-07/blob/codex/track-2-solo-worker-os/submissions/track-2/solo-worker-os/docs/AMD_GPU_LIVE_DEMO_EVIDENCE_2026-08-06.md)
- [Poster](https://github.com/HpIahtcthocw/Radeon-hackathon-2026-07/blob/codex/track-2-solo-worker-os/submissions/track-2/solo-worker-os/submission/poster/solo-worker-os-poster-v2.png)
- [Live narrated demo - 1:14, 1080p WebM](https://github.com/HpIahtcthocw/Radeon-hackathon-2026-07/blob/codex/track-2-solo-worker-os/submissions/track-2/solo-worker-os/demo-video/final/solo-worker-os-live-radeon-demo-2026-08-06-en-vo.webm?raw=1)
- [Extended evidence-based demo - 3:09, 1080p WebM](https://github.com/HpIahtcthocw/Radeon-hackathon-2026-07/blob/codex/track-2-solo-worker-os/submissions/track-2/solo-worker-os/demo-video/final/solo-worker-os-amd-demo-3m05s.webm?raw=1)

### Notes

The recorded competition configuration used a participant-controlled AMD
Radeon inference endpoint. The temporary public tunnel was stopped after
evidence capture. No temporary endpoint, API key, private key, or account email
is included in the submission.
