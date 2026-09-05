# Work Report — 2026-07-21

Timestamp: 2026-07-21T01:50:05+10:00
Keywords: `AMD-DevMaster`, `Track-2`, `W7900`, `ROCm-7.2.1`, `vLLM`, `RAG`, `tool-permission`, `persistent-workspace`

## Completed

- Reviewed the supplied event screenshots and 33 group-chat screenshots.
- Separated formal rules, organizer guidance, and community experiments.
- Re-verified the official Rules, Terms and Conditions.
- Cloned the official contest repository at commit:
  - `88d4bf6fab7eb98674abd0205c94c7ef669978e5`
  - commit time: 2026-07-17 16:15:13 +0800
  - message: `update submission requirements`
- Confirmed the three-person Track 2 route and submission requirements.
- Confirmed the Radeon Cloud account is logged in and observed:
  - 5 available credits;
  - no active instance;
  - 1 credit per GPU per hour on the live page;
  - one active instance per account;
  - no SSH public key saved.
- Prepared a persistent `/workspace` layout.
- Prepared ROCm/GPU verification.
- Prepared separate Agent and vLLM environments.
- Prepared a conservative W7900 vLLM launch configuration.
- Prepared an OpenAI-compatible latency/throughput benchmark.
- Documented the distinction between model tool-call parsing and runtime permissions.
- Documented why training is not required and when post-training could become justified.

## Verification performed locally

- Official repository cloned successfully.
- Official repository working tree is clean.
- Shell scripts pass syntax checks.
- Python benchmark script compiles.
- `uv pip compile` resolved the Agent requirements for Python 3.12 (59 packages).
- The bootstrap script completed an idempotent dry run in a temporary directory.
- No API key, SSH key, or account credential was written to the workspace.

## Cloud configuration status

Radeon Cloud login and account/credit state were verified. A template form was prepared, but no GPU instance was left running and no credit was consumed during this work report.

An SSH public key was intentionally not saved because that creates persistent account access and requires a separate confirmation at the moment of action.

## Recommended next action

Create or launch the persistent Notebook template, copy this repository to `/workspace/amd-track2-agent/repo`, run the two verification scripts, and record `amd-smi`, `rocminfo`, PyTorch HIP, vLLM version, model load, and the first benchmark result.

## Update — 2026-07-22

- Reviewed four new group screenshots.
- Fetched and fast-forwarded the ignored official repository clone from
  `88d4bf6` to `96ab73d8a63fb89c5cc0ac1ef64977b04d8b8bf1`.
- Verified that the new official change adds `rc-tunnel` for one public
  HTTP/WebSocket service on newly created Notebook Pods.
- Documented the public-authentication requirement, one-port limit, localhost
  binding, unsupported SSH/TCP/UDP/database use, and recreate/reinstall rule.
- Kept the private vLLM API on `127.0.0.1` by default; only an authenticated Web
  UI may later be exposed.
- Classified the reported 100 GB PVC and instance crash as community evidence
  pending direct measurement.
- No SSH key was transmitted, no GPU instance was launched, and no public
  tunnel was created during this update.
