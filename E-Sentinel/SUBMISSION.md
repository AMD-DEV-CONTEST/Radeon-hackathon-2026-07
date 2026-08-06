# AMD AI DevMaster Hackathon — Track 2 Submission

## Project

**E-Sentinel — Private AI Quality Assurance Agent on AMD Radeon / ROCm**

E-Sentinel is a private, evidence-grounded quality-assurance agent for customer-service conversations. It combines deterministic safety rules, semantic judgment, retrieval-backed evidence, human review, and an AMD Radeon / ROCm inference path.

## Submission Materials

| Required artifact | Submitted file |
|---|---|
| Project specification | [`SPECIFICATION.md`](./SPECIFICATION.md) |
| Source-code setup, dependencies, and startup guide | [`README.md`](./README.md) |
| AMD Radeon / ROCm deployment and optimization record | [`docs/AMD-ROCM-DEPLOYMENT-EN.md`](./docs/AMD-ROCM-DEPLOYMENT-EN.md) |
| Supplementary presentation | [`docs/E-Sentinel-Track2-Submission.pptx`](./docs/E-Sentinel-Track2-Submission.pptx) |
| Three-minute operating video | [`submission/Track-2-E-Sentinel-Video.mp4`](./submission/Track-2-E-Sentinel-Video.mp4) |

## Reproduction Checks

```bash
npm install
npm run typecheck
npm test -- --runInBand
npm run eval:validate:human-gold
npm run eval:metrics
npm run benchmark:radeon
```

The frozen human-gold evaluation set contains 105 cases. AMD cloud-35B and local-vLLM-8B results are reported separately; benchmark evidence is located in `benchmarks/amd/`.
