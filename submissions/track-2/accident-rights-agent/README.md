# Accident Rights Agent

**Track 2 | DataLink | Private AI Agent Development and Local Deployment**

Accident Rights Agent turns fragmented traffic-accident evidence into an auditable decision-support workflow for vehicle owners and insurers. It reconstructs evidence, keeps uncertainty visible, compares explainable liability hypotheses, creates rights-protection actions with owners and deadlines, and requires human approval before any external submission.

Core inference runs locally on AMD Radeon GPU with ROCm and vLLM. The system does not use a public model API.

## Start here

- [Project README](project/README.md)
- [Project specification PDF](project/docs/submission/project_description.pdf)
- [Pitch deck](project/docs/submission/accident_rights_agent_submission.pptx)
- [Demo video - 4:54 MP4](project/docs/submission/demo_video.mp4)
- [Architecture diagram](project/docs/submission/architecture.png)
- [AMD optimization report](project/docs/submission/amd_optimization.md)
- [Test report](project/docs/submission/test_report.md)
- [Privacy and security statement](project/docs/submission/privacy_security.md)
- [Model and license declaration](project/docs/submission/model_license.md)
- [Final submission manifest](SYNC_MANIFEST.md)

## Measured highlights

| Result | Measurement |
|---|---:|
| Context reduction | 50.9% |
| Protected-field retention | 100% |
| Repeated-case TTFT improvement | 98.8% |
| Concurrency-4 throughput | 89.48 tokens/s |
| 30-minute stability | 298/298 requests, zero OOM |

Accident Rights Agent is decision support, not legal advice or a judicial ruling. Missing policy inputs never produce fabricated payment amounts, and external submissions remain drafts until an authorized human approves the exact document version.
