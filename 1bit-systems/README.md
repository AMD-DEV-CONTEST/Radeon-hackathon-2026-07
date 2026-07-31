# Track 2: 1bit.systems — Jarvis, a Fully Local Private AI Agent

**Team**: 1bit.systems (bong-water-water-bong)
**Track**: Track 2 — Development & Local Deployment of Private AI Agents

## What this is

A single C++23 binary that runs private AI agents entirely on-device on an AMD Strix
Halo machine (Ryzen AI Max+ 395) — no cloud, no API keys, no data leaving the machine.
It drives the Radeon 8060S GPU (ROCm HIP + Vulkan) and the XDNA 2 NPU together in one
process, with the NPU driver stack reverse-engineered from scratch (AMD shipped it
without public documentation).

**Jarvis**, the agent built on top of that engine, implements all 5 Track 2
capabilities — not just the required 2:

- **RAG** — local markdown knowledge base, filesystem-backed
- **Tool invocation** — model-decided tool calls (search, time, notes) with a real
  permission gate, not a stub
- **Multi-step planning** — task decomposition + per-subtask routing
- **Local multi-turn memory** — conversation history persisted per session, survives
  restarts
- **Permission / privacy control** — sensitive tools require explicit write
  permission; every call is audit-logged

## On hardware: local Strix Halo, not Radeon Cloud

This submission runs on the team's own physical AMD Strix Halo hardware (Radeon 8060S
GPU + XDNA 2 NPU), not AMD's Radeon Cloud offering. We chose local hardware
deliberately: the NPU driver itself had to be reverse-engineered against this exact
silicon (see `spec-document.md` §7 and the project's `docs/journey.md`), and the
contest's own Track 2 requirement — "core inference must run locally, no reliance on
closed-source APIs" — is the harder and more honest bar to clear on real consumer
hardware rather than a generic rented cloud GPU. Full reasoning is in
`spec-document.md`.

## Submission materials

| Deliverable | Location |
|---|---|
| Project Specification Document | [`spec-document.md`](./spec-document.md) |
| Project Source Code | https://github.com/bong-water-water-bong/1bit-systems (MIT, public, ~complete — see repo for build/run instructions in the root `README.md` and `CONTRIBUTING.md`) |
| Demo Video | [`demo-video.mp4`](./demo-video.mp4) (~2 min) — every command in it actually runs against the live server on this box; narrated with the project's own local TTS voice, not a human, since this is an automated engineering demo |
| Poster / Supplementary Materials | [`poster-and-checklist.md`](./poster-and-checklist.md) |

## Why the demo video looks the way it does

It's a real terminal session, not a scripted mockup: real `curl` calls against a
running `jarvis_server` and the production `unified_server`, real model responses,
real benchmark numbers pulled live from `1bit.systems/benchmarks.json` at record time.
While producing it we actually found and filed two live bugs in the agent
(`bong-water-water-bong/1bit-systems#1015`, `#1017`) rather than edit around them —
one scene (multi-step planning) was cut from the video because the bug made it
unreliable on camera; we'd rather show 4 working capabilities honestly than fake a
5th.

## Repository size note

This folder intentionally does **not** duplicate the full `1bit-systems` source tree
(it's a large, mature monorepo — thousands of files, submodules, and binary model
assets). The complete, buildable source is public at the link above; duplicating it
here would just be an unreviewable pile of files in this PR.
