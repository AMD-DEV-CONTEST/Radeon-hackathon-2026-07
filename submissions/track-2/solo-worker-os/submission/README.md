# Solo Worker OS — AMD AI DevMaster 2026 Submission

**Track:** Track 2 — Development & Local Deployment of Private AI Agents  
**Application:** Solo Worker OS  
**Primary submission language:** English

Solo Worker OS is a private AI operations layer for freelancers and solo
businesses. It turns natural-language requests into persistent business actions
such as project creation, contract and invoice generation, payment tracking,
private knowledge retrieval, and business analysis.

The competition build was verified with `Qwen/Qwen3-4B` served by vLLM on an
AMD Radeon GPU using ROCm 7.2.1. The application uses an OpenAI-compatible local
provider and does not require a commercial hosted LLM in the inference path.

## Submission package

- [English Project Specification](PROJECT_SPECIFICATION.md)
- [Chinese Companion Specification](PROJECT_SPECIFICATION_CN.md)
- [Repository setup and reproduction guide](../README.md)
- [AMD GPU evidence index](../docs/evidence/README.md)
- [Detailed AMD GPU verification record](../docs/AMD_GPU_PROOF_2026-08-06.md)
- [English poster](poster/solo-worker-os-poster-v2.html)
- [English poster PNG](poster/solo-worker-os-poster-v2.png)
- [Chinese supplementary poster](poster/solo-worker-os-poster-cn.html)
- [Demo recording script](../demo-video/AMD_DEMO_SCRIPT.md)
- [Chinese recording and narration script](../demo-video/AMD_DEMO_SCRIPT_CN.md)

## Verified competition configuration

| Item | Verified value |
|---|---|
| GPU environment | Radeon Cloud, one AMD Radeon GPU |
| Device family | AMD/ATI, ROCm architecture `gfx1100` |
| Runtime | ROCm 7.2.1, PyTorch 2.9, vLLM 0.16.x |
| Model | `Qwen/Qwen3-4B` |
| Context / output cap | 4,096 / 768 tokens |
| Agent tools / subagents | 14 / 5 |
| Validation | TypeScript passed; 57/57 tests passed |

## Reproduce

```bash
npm install
npm run typecheck
npm test
npm run dev
```

For the AMD local-provider configuration and vLLM launch command, see the
[Project Specification](PROJECT_SPECIFICATION.md#4-model-and-private-deployment-plan).
