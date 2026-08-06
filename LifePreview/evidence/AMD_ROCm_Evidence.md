# AMD Radeon / ROCm Evidence Index

## Purpose and scope

This is a pre-submission evidence index, compiled from the AMD release-worktree handoff on 2026-08-06. It records the reported minimum end-to-end loop and smoke-test status; it does not substitute for preserving the final browser action and its corresponding AMD GPU evidence.

The project has been deployed in an NVIDIA environment. Because the competition cloud server has constrained memory and compute capacity, some input data and showcase media were generated locally in advance. Those pre-generated materials are not presented as the output of a current live AMD request.

## Reported AMD environment

| Item | Reported value |
| --- | --- |
| GPU architecture | AMD Radeon `gfx1100` |
| ROCm | 7.2.1 / 7.2 runtime family |
| PyTorch | `2.9.1+rocm7.2.1` |
| Competition flow | English web UI → Search/Reader → research script → prepared FLUX reference image → MiniMax H3 request → ComfyUI / AMD GPU activity |

## Reported minimal-loop and smoke-test evidence

- A MiniMax H3 compatibility probe reported successful text-encoder execution, one H3 denoising step, native video/audio decode, and H.264/AAC MP4 output on the AMD runtime.
- The release handoff reported the focused Python competition suite as `212 passed, 1 skipped`, the web checks as `91` passing tests, and a successful production web build.
- The intended final path is one user-initiated `POST /api/video-jobs`, followed by a persisted script digest, prepared-image metadata, H3 DTO and prompt/queue ID, a ComfyUI running entry, and `rocm-smi` activity.

These are reported handoff results, not a claim that every dataset, generated asset, or production feature was regenerated on the competition server.

## Final live-run evidence still required

For the competition submission, preserve the following from the designated AMD Radeon environment:

1. the browser's single `POST /api/video-jobs` after the user selects **Start generation**;
2. the Search/Reader response and non-empty research-script digest;
3. the prepared FLUX reference-image request ID, prompt, seed, workflow SHA-256, and image SHA-256;
4. the H3 request DTO, prompt or queue ID, job ID, submission nonce, and timestamp;
5. a ComfyUI execution record that corresponds to that prompt; and
6. `rocm-smi` output showing the AMD GPU working during that request.

If a final MP4 is available, record its filename, duration, codec metadata, SHA-256, and the connection to the same prompt or job ID. Do not describe earlier showcase videos as that final live output.

## Included-artifact integrity

See [SHA256SUMS.txt](SHA256SUMS.txt) for hashes of the demo video, project profile, and presentation deck included in this submission directory.
