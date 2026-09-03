# agent/ — the local optimizer-agent + cloud-escalation bridge

This is the submission's agent, in two parts:

- **`optimizer-agent/`** — the fully-local AI agent (vendored here in full, source-only, no runtime state; its own repository is private, so this directory *is* the source of record for judging). A local tool-calling brain drives the mission loop — **detect → scan ISA → find gap → fix → validate → measure** — with the brain on one GPU and benchmarks isolated on the other. It never guesses a number; it learns by measuring on real silicon. `optimizer-agent/hardware.py` maps the whole AMD-AI substrate (18 targets: GPU/CPU/NPU/APU). See `optimizer-agent/README.md` and `optimizer-agent/substrate.md`.

- **`escalation.py`** — the Gold→Platinum bridge. The local agent is autonomous for discover/build/measure; when it's *genuinely* stuck (a correctness gate it can't clear on its own), `escalation.py` packages the context and asks a Radeon-cloud model for help over an OpenAI-compatible endpoint, then re-validates the returned fix locally. Core inference stays on the local AMD GPU by default — the cloud is the exception, not the path.

The vendored copy is kept in step with upstream; edit the agent in its own repo and re-vendor, rather than editing here.
