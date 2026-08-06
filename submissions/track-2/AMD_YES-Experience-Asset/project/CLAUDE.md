# Claude Code Project Context

Follow `AGENTS.md` as the shared repository contract.
Use `spec/README.md` as the stable project-specification entry point and
complete `spec/AGENT_ALIGNMENT.md` before proposing or changing work.

Project-specific priorities:

- This is a three-person AMD AI DevMaster Hackathon Track 2 repository.
- Core model inference must run locally on the Radeon Cloud W7900 through ROCm.
- `/workspace` is the only cloud path considered persistent.
- Use `/workspace/amd-track2-agent/repo` for the integration checkout.
- Keep Agent and vLLM Python environments separate.
- Treat model tool calls as untrusted proposals; the runtime enforces tool
  registration, validation, permission, approval, timeout, and audit.
- Treat the AMD DeepSeek shared API as a bounded development helper only. Do
  not send it private data and do not use it as the submission's core model.
- Keep vLLM and development services on `127.0.0.1`. Never run
  `rc-tunnel expose` without explicit human approval after authentication is
  verified; expose an authenticated Web UI, never the raw inference API.
- Never put authentication files, tokens, SSH keys, private datasets, model
  weights, caches, or generated benchmark artifacts in Git.
- Do not commit, push, merge, rebase, force-push, or open a Pull Request unless
  the user explicitly asks in the current task.

Before claiming completion, run the checks listed in `AGENTS.md` and summarize
what was actually verified.
