# Demo Script

Target duration: 3:30 to 4:15. The submission capture combines a sanitized live
Radeon Cloud session with the existing product, fallback, benchmark, and
architecture footage at 1600x900. Use English narration and subtitles.

The timing-aligned subtitle file is [DEMO_SUBTITLES.srt](DEMO_SUBTITLES.srt).

## Shot list

| Time | Picture | Narration |
| --- | --- | --- |
| 00:00-00:22 | Product title, incident scenario, and bounded-agent framing | Local Incident Commander is a private, evidence-first SRE agent built for AMD AI DevMaster Track 2. |
| 00:22-00:39 | Live Radeon Cloud terminal: GPU, ROCm, vLLM model endpoint, and `local-radeon` health | The competition runtime uses Qwen3-8B with vLLM on a Radeon PRO W7900 and ROCm. |
| 00:39-01:48 | One continuous live Agent run: four-step plan, three tools, cited RCA, two operator decisions, and cited follow-up | The Agent executes only allow-listed read-only tools, creates server-owned evidence IDs, and requires human approval for simulation-only actions. |
| 01:48-02:35 | Existing GUI detail: evidence ledger, synthesis, decisions, and memory | The visible UI reinforces the same bounded workflow and auditable evidence chain. |
| 02:35-02:50 | Explicitly labelled deterministic fallback | If the model becomes unavailable, fallback preserves evidence and produces a conservative degraded result. |
| 02:50-03:18 | Radeon benchmark comparison | Eager vLLM reached 39.35 output tokens per second, about 2.5 times the compiled configuration for this workload. |
| 03:18-03:56 | Architecture, value summary, and repository | Private inference, bounded tools, auditable evidence, and human approval. |

## Recording gates

- The header must say `Private Radeon`, never `Shared Radeon API`.
- The health response must be backed by a current sanitized runtime evidence file.
- Show all four plan steps and three distinct tool calls.
- Show evidence IDs on both tool results and the final hypothesis.
- Show one approved and one rejected simulation-only action.
- Show a cited follow-up response and one degraded/fallback state.
- Do not show API keys, device serials, raw cookies, email addresses, or account UI.
- Confirm the final video is 3-5 minutes, 1600x900, H.264/AAC, and publicly viewable without login.
