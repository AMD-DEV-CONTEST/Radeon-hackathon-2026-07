# Demo Video Shot List

Target: 3:45–4:15, 1920×1080 or higher, recorded in a fresh Radeon Cloud instance.

| Time | Visual proof | Acceptance check |
| --- | --- | --- |
| 0:00 | Radeon Cloud terminal | AMD Radeon device, `gfx1100`, and ROCm readable |
| 0:12 | vLLM `/v1/models` | `Qwen/Qwen2.5-7B-Instruct` returned from loopback |
| 0:22 | PrivateOps inference panel/runtime | `Local ROCm`, loopback endpoint, Qwen model, `ROCM-LOCAL`, and same-instance location visible |
| 0:30 | Permission-first narration | Broad visibility is distinguished from unrestricted control |
| 0:42 | Project-readiness prompt | Full prompt visible before execution |
| 0:55 | Local RAG and plan | Real knowledge source, evidence ID, and active plan visible |
| 1:12 | Tool result and Markdown | `submission_readiness`, provider, latency, audit ID readable |
| 1:25 | Follow-up question | Same task context continues without restarting the UI |
| 1:45 | Explicit memory prompt | Saved local priority appears in the memory panel |
| 2:05 | Modifying request | `CONFIRM`; no side effect before exact-action confirmation |
| 2:28 | Secret exfiltration request | `BLOCKED`; no tool executes |
| 2:45 | Radeon proof panel | GPU, ROCm, model, direct latency, throughput, Agent latency |
| 3:15 | Optimization explanation | Context cap, memory headroom, loopback, bounded RAG/tools |
| 3:35 | Audit export/deletion | Matching audit ID; delete only a disposable row |
| 3:55 | Closing screen | Permission-first tagline and product name visible |

The panel may demonstrate switching between **Remote model** and **Local ROCm**, but the recorded competition response must run after Local ROCm is selected. Do not mix a Windows-inspection result into the Linux cloud run. Do not display API keys, SSH keys, cloud tokens, personal files, or unsupported performance claims.
