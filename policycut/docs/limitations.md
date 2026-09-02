# Known Limitations

PolicyCut is a human-in-the-loop privacy redaction tool. It is **not** a guarantee of legal compliance (GDPR, HIPAA, PIPL or otherwise), and the contest build makes the following explicit trade-offs:

## Scope limits (by design, contest build)

- One project = one video, ≤ 60 seconds, ≤ 1080p (MP4/MOV/MKV/WebM).
- Visual targets: faces, license plates, identity documents, screens. Audio targets: phone numbers, email addresses, street addresses. Anything else typed in a policy is reported as `Unsupported target` — never silently ignored, never guessed.
- No face recognition or person whitelists ("blur everyone except the interviewee" is out of scope).
- No age / minor detection, no speaker diarization or voice anonymization, no generative inpainting, no live camera input, no multi-user accounts, no cloud sync, no batch processing of long videos.

## Detection quality

- Detection is recall-tuned, not perfect. Small, motion-blurred, heavily occluded or extreme-angle objects can be missed — this is exactly why export is blocked until a human has confirmed or ignored every automatic event, and why manual regions exist.
- Manual visual regions are **fixed rectangles** over their time interval (labeled "Manual fixed region" in the UI). Re-running SAM 2.1 tracking from a manual box is future work.
- Address detection in speech is heuristic (cue phrases + street suffixes + optional Presidio); low-confidence address events are flagged for mandatory human review.
- If Whisper cannot produce word-level timestamps for a segment, the whole segment is redacted and flagged — safe, but coarse.

## Performance / hardware

- The contest path assumes a ROCm PyTorch build on an AMD Radeon GPU; `--require-rocm` makes CPU fallback a hard error for core model stages. The YuNet small-face assist detector is intentionally CPU (documented, not hidden).
- Hardware video *encoding* uses libx264 (CPU); GPU work is model inference, which dominates the pipeline. This is stated to keep the Radeon performance claims honest.

## Security

- The web UI is a localhost tool for a single trusted operator. It has no authentication — do not expose it to an untrusted network.
