# Demo Video

**Primary playback:** [Bilibili - BV1t3up6iEhy](https://www.bilibili.com/video/BV1t3up6iEhy/)

**Backup playback/download:** [Baidu Cloud direct MP4](https://dagent-platform.bj.bcebos.com/amd-hackathon/amd-hackathon-2026-07.mp4?authorization=bce-auth-v1/ALTAKYR0nFJFHMGlFjuontyVVP/2026-08-06T12%3A43%3A01Z/-1/host/1a12970cc4c9439caa28199256b028f90e82ba41ac92c68fb921b271be0b0acd)

**Local master:** `submission/en/amd-hackathon-2026-07.mp4`

**Verified media:** 3:07.2, 1920x1080, H.264 video with AAC audio, 174,000,121 bytes (about 165.9 MiB).

**SHA-256:** `0cba7eec725a4c8d7e76a3b762c56ce1c96cc8edd9321daf0a2342c0cd0a0a4f`

**Recommended PR label:** `Demo video - 3-5 minutes`

The recording satisfies the required 3-5 minute duration. On 2026-08-06, the Bilibili page returned HTTP 200 and the Baidu Cloud endpoint returned HTTP 206 with `video/mp4` for a range request. The local master is intentionally excluded from ordinary Git; the two public links above are the submission endpoints.

## Suggested 3-5 minute chapter list

| Time | Content | Required evidence |
| --- | --- | --- |
| 0:00-0:25 | Problem and product | Natural language -> tested robot capability. |
| 0:25-0:50 | Architecture | Private model, RDK Agent, `sophonctl`, RDK X5. |
| 0:50-1:15 | Read-only board proof | `ping`, `state`, and `plugins list`. |
| 1:15-2:45 | Robot Development Mode | Intent gate; Test -> Code -> Verify; release and Skill installation. |
| 2:45-3:30 | Acceptance | CLI invocation, then natural-language Skill invocation; show physical result. |
| 3:30-4:15 | AMD execution | Participant-controlled Radeon Cloud instance, redacted ROCm/vLLM/model evidence, streaming response, and redacted runtime evidence. |
| 4:15-4:40 | Safety and value | Allowlists, offline tests, evidence gate, direction guard. |
| 4:40-5:00 | Closing | Source, reproducibility, and project value. |

## Privacy review

- Blur or crop API keys, SSH keys, private URLs, email addresses, MAC addresses, and internal IPs that are not needed.
- Do not show the contents of `~/.pi/agent/auth.json` or the private `apiKey` field.
- When showing the model configuration, use the sanitized example in `submission/en/config/`.
- Distinguish a generated cover illustration from real hardware footage.
