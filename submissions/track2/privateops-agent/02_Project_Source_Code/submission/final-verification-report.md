# Final Verification Report

Date: 2026-08-05

## Automated acceptance

- 102 local automated tests passed during final submission preparation.
- The 101-test Radeon Cloud capture baseline passed inside the instance in 11.327 seconds; its immutable log remains included.
- Submission validation passed locally and in Radeon Cloud with 27 required artifacts.
- The 10-iteration software stability check completed 10 successful requests.
- Provider failures visible: 1.
- Silent fallbacks: 0.
- Memory persistence: passed.
- Audit ordering and count: passed with 11 entries.
- Mean software workflow latency: 6.645 ms.
- Unconfigured-provider smoke path: `409 provider_required`, with no audit entry written.
- JavaScript syntax check: passed.

The software workflow latency above is a deterministic local verification measurement. It is not an AMD Radeon performance claim.

## Reviewer materials

- All seven project-specification pages were rendered and visually inspected.
- The one-page poster was rendered and visually inspected.
- All ten competition slides were rendered and visually inspected.
- PowerPoint overflow detection passed with no overflow.
- The Local Trust Console was checked in Chinese and English, light and dark themes.
- The explicit Remote model / Local ROCm selector was exercised in the browser; local defaults, key rules, profile separation, apply behavior, and the visible connection-refused failure were verified.
- The removed `比赛核心推理 / 仅开发辅助 · 不作为比赛证明` row had zero DOM matches.
- The console exposes 14 bilingual RAG sources, marks the shared AMD API as development-only, and displays verified Radeon evidence separately from the current browser session.

## Verified Radeon evidence

The immutable evidence bundle records AMD Radeon Graphics (`gfx1100`), ROCm 7.2.1, Qwen2.5-7B-Instruct, a same-instance loopback endpoint, 1,511.072 ms direct latency, 32.427 tokens/s, and 18,384.639 ms complete Agent latency. No baseline speedup, P50/P95, VRAM peak, concurrency, or hardware soak value is claimed without a new Radeon measurement.

The 2026-08-04 reproduction independently recorded the same GPU architecture, 48.0 GiB VRAM, ROCm 7.2.1, PyTorch `2.9.1+gitff65f5b`, HIP `7.2.53211`, vLLM `0.16.1.dev0+g89a77b108.d20260317.rocm721`, and `competition_eligible=true`. Its direct machine benchmark was 1,513.115 ms at 32.384 completion tokens/s. A real Local ROCm Chinese Agent response completed in 3,158.876 ms and a separate AMD Cloud API development response completed in 14,140.651 ms; each produced its own audit ID.

## Public submission status

- Fork: <https://github.com/LucianaiB2004/Radeon-hackathon-2026-07/tree/privateops-agent-submission/submissions/track2/privateops-agent>
- Official Pull Request: <https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07/pull/87>
- Final video: <https://www.bilibili.com/video/BV1nQuA6qEFS/>
