# 4:53 Final Demo Script — English Narration and Subtitles

This is the locked script for
[`RadeonHotel-Track2-Demo.mp4`](RadeonHotel-Track2-Demo.mp4). The video is a
narrated evidence tour built from the final English deck plus two sanitized
captures of the live Optimized C deployment. It does not simulate additional
business writes or represent deferred experiments as completed.

## Truth boundary

- Frozen executable/evaluation source: C2 v3 commit
  `f7ba6811205a40ba51ca74c82b43129b616f74c5`.
- Released performance evidence: accepted single-variable B→C comparison,
  Flash Attention off versus on.
- Both runs completed 16/16 requests with zero model-call failures and the same
  disclosed 15/16 citation-section projection.
- The video does **not** claim 300/300, a complete A–H matrix, five fresh
  Stability lifecycles, a long soak, or `accepted_final`.
- All guests, bookings, dates, prices, and hotel records shown are synthetic.

## Locked sequence

| Time | Visual | Narration focus |
| --- | --- | --- |
| 0:00–0:17 | Cover | Private journey recovery on AMD Radeon and ROCm; local inference and reversible actions. |
| 0:17–0:41 | Scenario | A disrupted stay combines policy, inventory, personal needs, transfer state, and staff escalation. |
| 0:41–1:05 | Live English request | Current public C-profile UI; future dates, child, late arrival, allergy, transfer, citations, quote, and preview-only intent. |
| 1:05–1:29 | Live quote preview | Real local result: eight rooms, CNY 258 total, zero confirmed writes, and one explicit confirmation choice. |
| 1:29–1:57 | Architecture | Model proposal behind a deterministic control plane, local RAG, typed tools, minimized state, and HMAC audit. |
| 1:57–2:19 | Five capabilities | RAG, tool calling, multi-step planning, consented local memory, and privacy/access controls share one JourneyState. |
| 2:19–2:50 | Golden journey | Quote and hold, transfer, independently recoverable stay and transport changes, privacy proof, safety handoff, and Final Stay Brief. |
| 2:50–3:16 | Trust and privacy | One preview and one confirmation per write; mixed-scope injection is partitioned before inference or tools. |
| 3:16–3:46 | Radeon proof | ROCm 7.2.1, gfx1100, 96 CUs, 41/41 offload, 100% peak GPU activity, and request/process binding. |
| 3:46–4:34 | Optimization | Only Flash Attention changed; C4 throughput +6.491%, C4 P95 -5.428%, decode P50 +12.981%, VRAM 58%→57%. |
| 4:34–4:53 | Closing | Live C profile, frozen source, final English deck/video, and reviewed B→C report are available to judges. |

The authoritative subtitle text is
[`RadeonHotel-Track2-Demo.en.srt`](RadeonHotel-Track2-Demo.en.srt). Its 65 cues
were generated from the same narration used for the audio track. The MP4 also
contains that English subtitle stream as the default embedded `mov_text` track.

## Export record

| Field | Value |
| --- | --- |
| Duration | 293.306 seconds |
| Video | H.264, 1920×1080, 30 fps |
| Audio | AAC, mono English narration |
| Subtitles | Default embedded English `mov_text` + sidecar SRT |
| MP4 size | 8,116,726 bytes |
| MP4 SHA256 | `89e9e9779d1e15f34b5af81e41a6cb0eed9f47d5bec3ab9c5ee338af7544701b` |
| SRT size | 7,316 bytes |
| SRT SHA256 | `395471b927b5f036c53dc0192feb0507939c6899e5e65af617ef6788bd441889` |

## Review result

The complete H.264/AAC streams decode without error. A 12-frame contact-sheet
review found only English, sanitized identifiers, the reviewed B→C metrics, and
the current C2/report short hashes. The embedded subtitle stream round-trips to
the sidecar text exactly apart from a trailing newline.
