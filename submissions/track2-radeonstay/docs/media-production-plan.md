# Final Media Production Record

The submission media is locked to frozen C2 v3 and the reviewed accepted B→C
Radeon comparison. This record replaces the earlier capture checklist.

## Final assets

| Asset | Path | Status |
| --- | --- | --- |
| English presentation | [`RadeonHotel-Track2-Submission.pptx`](RadeonHotel-Track2-Submission.pptx) | FINAL |
| English narrated demo | [`RadeonHotel-Track2-Demo.mp4`](RadeonHotel-Track2-Demo.mp4) | FINAL |
| English subtitle sidecar | [`RadeonHotel-Track2-Demo.en.srt`](RadeonHotel-Track2-Demo.en.srt) | FINAL |
| Public Optimized C deployment | [Radeon Cloud demo](https://rc-5ec89b08f896792e.radeon.firstdg.ai/) | LIVE |
| Reviewed B→C report | [`evidence/c3min-f7ba681-bc-comparison.json`](evidence/c3min-f7ba681-bc-comparison.json) | ACCEPTED MINIMAL B/C |

The video is a 4:53 narrated evidence tour assembled from the final nine-slide
deck and two sanitized captures of the current public C-profile UI. One capture
shows the editable English judge request; the other shows the real local quote
and room-hold preview. The edit does not invent intermediate confirmations or
claim that an unrecorded write occurred.

## Inputs and provenance

| Input | Bound value |
| --- | --- |
| C2 source | `f7ba6811205a40ba51ca74c82b43129b616f74c5` |
| C2 project tree | `b44fb212b77c06ee9c8d097b5a9f2f891f79a389` |
| Reference | B — Flash Attention off |
| Optimized profile | C — Flash Attention on |
| Accepted report | SHA256 `7f85a614a31da10e5484ee41034282210ac44caf84012617dea5c786c0f03f59` |
| Live proof | ROCm 7.2.1, gfx1100, 96 CUs, 41/41 offload, 100% peak GPU busy |
| Quality boundary | 16/16 request success, zero model-call failures, identical disclosed 15/16 citation projection |

## Export specification

| Field | Final value |
| --- | --- |
| Duration | 293.306 seconds |
| Canvas | 1920×1080 at 30 fps |
| Video codec | H.264 |
| Audio codec | AAC, mono English narration |
| Captions | 65-cue English SRT plus default embedded `mov_text` stream |
| File size | 8,116,726 bytes |
| MP4 SHA256 | `89e9e9779d1e15f34b5af81e41a6cb0eed9f47d5bec3ab9c5ee338af7544701b` |
| SRT SHA256 | `395471b927b5f036c53dc0192feb0507939c6899e5e65af617ef6788bd441889` |

## Claim controls

- Only reviewed B→C measurements appear in the deck and video: concurrency-4
  throughput `+6.491%`, concurrency-4 P95 latency `-5.428%`, and decode P50
  `+12.981%`.
- The final media never says `300/300`, `accepted_final`, complete A–H, five-run
  Stability, or soak.
- No `.env`, identity secret, confirmation capability, private host, process ID,
  internal path, or complete unique booking/session/audit identifier is shown.
- No retail Radeon board name is inferred from `gfx1100`; the detected target
  identity is reproduced as measured.
- The old pre-C1 video and subtitles remain historical and excluded.

## Verification performed

1. Decoded the complete final H.264 and AAC streams with FFmpeg and no errors.
2. Confirmed a 1920×1080, 30 fps H.264 video stream; AAC narration; and an
   English `mov_text` subtitle stream.
3. Extracted the embedded subtitle track and compared it with the sidecar; the
   text and timing match apart from a trailing newline.
4. Reviewed a 12-frame contact sheet spanning the full video for language,
   stale metrics, identifiers, cropping, and slide order.
5. Verified the final SHA256 values recorded above and in the evidence index.
