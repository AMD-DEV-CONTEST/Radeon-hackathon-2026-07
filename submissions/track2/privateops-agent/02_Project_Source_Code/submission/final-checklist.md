# Final Submission Checklist

## Engineering and reviewer package

- [x] Complete source, dependencies, startup commands, and MIT license are present.
- [x] Permission-first scenario and plain-language product promise are consistent across the package.
- [x] Local RAG, tools, planning, memory, permissions, privacy, and audit are implemented.
- [x] Fourteen bilingual knowledge documents replace the original canned samples.
- [x] LangChain Core StructuredTool routing is implemented and tested.
- [x] Fixed read-only Windows collectors inspect startup entries, processes, services, scheduled tasks, listeners, system overview, and security posture.
- [x] Workspace inventory excludes environments, dependencies, caches, builds, Git internals, and generated state.
- [x] Model tool context is bounded without mutating reviewer-visible evidence.
- [x] Remote/shared APIs are development-only and report `competition_eligible=false`.
- [x] `rocm-local` accepts only same-instance loopback inference and never silently falls back.
- [x] Markdown, bilingual output, persistent themes/language, active navigation, audit deletion, and the explicit Remote model / Local ROCm switch are implemented.
- [x] Local ROCm restores the loopback Qwen defaults without requiring an API key; Remote model requires its own key.
- [x] Project specification PDF, editable PPTX, poster PDF, architecture assets, example prompts, script, and shot list are present.
- [x] Submission validator checks required artifacts, secrets, stale copy, and benchmark provenance.
- [x] Deterministic software stability check covers repeated requests, memory, audit ordering, visible provider failure, and zero silent fallbacks.

## Verified Radeon Cloud capture

- [x] Radeon Cloud instance `u-15477-db2e6f27` ran AMD Radeon Graphics (`gfx1100`) with ROCm 7.2.1.
- [x] The full cloud test and submission validation logs were retained.
- [x] vLLM served `Qwen/Qwen2.5-7B-Instruct` on `127.0.0.1:8000`.
- [x] PrivateOps ran as `rocm-local` / `openai-compatible-rocm` in the same instance.
- [x] Machine-generated diagnostics, benchmark JSON, Agent response, audit export, vLLM log, and cloud retest log were retained.
- [x] Direct latency of 1,511.072 ms and throughput of 32.427 tokens/s were synchronized into final JSON/CSV.
- [x] Full Chinese Agent latency of 18,384.639 ms was retained with its different measurement scope.
- [x] The completed instance was destroyed after evidence capture to stop credit usage.
- [x] A reproduction instance was launched on 2026-08-04 and again verified `gfx1100`, ROCm 7.2.1, Qwen2.5-7B-Instruct, same-instance loopback, a real Chinese Agent response, and a fresh 1,513.115 ms / 32.384 tokens/s benchmark.

## Final video — completed

- [x] Launch a fresh Radeon Cloud instance for the continuous 3–5 minute recording.
- [x] Follow `video-shot-list.md`; show `rocminfo`, vLLM `/v1/models`, the Local ROCm selector, loopback endpoint, `ROCM-LOCAL`, and same-instance runtime location.
- [x] Run the project-readiness multi-turn prompts from `example-prompts.md`.
- [x] Show retrieved evidence, plan, tool result, memory, confirmation, blocked request, audit ID, and measured Radeon proof.
- [x] Publish the final video at <https://www.bilibili.com/video/BV1nQuA6qEFS/> without exposing credentials.
- [x] Publish the English-subtitled version at <https://www.bilibili.com/video/BV1A1M66VEqS/>.
- [x] Keep instance lifecycle separate from the submission package; no live endpoint or credential is required for review.

## Registration and official Fork/PR

- [x] Use the participant identity `lucianaib` in the English PR title.
- [x] Fork `AMD-DEV-CONTEST/Radeon-hackathon-2026-07`.
- [x] Place the final package under `submissions/track2/privateops-agent`.
- [x] Use the English title `Track 2, lucianaib, PrivateOps Agent`.
- [x] Add the public video URL to the English pull-request copy.
- [x] Open Pull Request #87 in the official repository.
- [x] Verify the public Fork, Pull Request, and Bilibili video links.
