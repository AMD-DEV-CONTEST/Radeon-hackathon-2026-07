# RedactFlow AMD Submission Checklist

## Account and registration

- [ ] Join the AMD AI Developer Program with the same email used on Luma.
- [ ] Complete Luma registration for Track 2 / Agentic AI.
- [ ] Receive registration approval and Radeon Cloud access, if allocated.
- [ ] Confirm the public GitHub account and fork the official repository.

## Radeon Cloud evidence

- [ ] Run `python scripts/rocm_probe.py > artifacts/rocm-environment.json`.
- [ ] Start ROCm-enabled llama.cpp with a local Qwen2.5 instruct model.
- [ ] Run `python scripts/benchmark.py --url http://127.0.0.1:8080/v1 --model qwen2.5-7b-instruct --runs 10 > artifacts/rocm-benchmark.json`.
- [ ] Verify that the environment and benchmark JSON files contain no credentials.
- [ ] Update the report and demo only with measurements produced by that run.

## Deliverables

- [x] Complete source code and English README.
- [x] Reproducible local and ROCm startup instructions.
- [x] Project specification PDF.
- [x] Supplementary pitch deck.
- [x] Three-minute demo video.
- [x] Automated tests.
- [ ] Radeon Cloud evidence files.

## Pull request

- [ ] Copy the `RedactFlow-AMD` directory into a fork of the official repository.
- [ ] Use the title `Track 2, N/A, RedactFlow AMD` for an individual entry.
- [ ] Paste `docs/pr-body.md` into the pull request description.
- [ ] Confirm all materials are in English and visible from the pull request.
- [ ] Open the pull request before August 6, 2026 at 23:59 UTC+8.
