# Current Iteration — Remote Coding-Agent Environment

Last updated: 2026-07-22 AEST

## Requirement

Prepare a final Radeon Cloud development environment that can be used through
VS Code Remote SSH with Codex, the Codex CLI, or Claude Code. The environment
must keep project data under persistent storage, expose the W7900 through ROCm,
avoid committing credentials, and remain reproducible for the three-person
Track 2 team.

Requirement status: APPROVED
Engineering status: COMPLETE

## Engineering Proposal

Route: PROJECT

Why:

- The work spans the local repository, Radeon Cloud infrastructure, persistent
  storage, SSH access, GPU runtime verification, and several coding-agent
  clients.
- Launching a live instance has an operating cost of 1 credit per GPU hour.
- Saving an SSH public key creates persistent remote access.

Affected areas:

- Radeon Cloud development template, storage mode, and SSH access;
- `/workspace/amd-track2-agent` directory contract;
- remote bootstrap, health-check, and agent-install scripts;
- VS Code Remote SSH workspace configuration;
- Codex CLI and Claude Code prerequisites and non-secret configuration;
- a bounded DeepSeek-V4-Flash development helper with no tool access;
- a private GitHub repository as the durable team source of truth;
- environment documentation and handoff evidence.

Proposed checkpoints:

1. Consolidate the cloud design around one Notebook development template using
   AMD OneClick Base, Persistent PVC, and SSH access.
2. Add repository-managed bootstrap scripts and editor configuration for a
   direct-on-host `/workspace` workflow.
3. Save the existing local SSH public key to Radeon Cloud after action-time
   confirmation.
4. Optionally launch one W7900 instance, inspect its actual CPU/RAM/disk/ROCm
   allocation, bootstrap the workspace, and verify SSH plus VS Code readiness.
5. Verify the AMD V4 Flash endpoint and define a safe handoff boundary. The
   worker is now deferred by the user until a Responses-compatible key/service
   is available.
6. Create and push the private GitHub repository.
7. Record exact commands and verification evidence.

Test and runtime verification:

- shell syntax and idempotency checks locally;
- secret and path-safety checks;
- `amd-smi`, `rocminfo`, `/dev/kfd`, PyTorch HIP, Node, Git, Python and disk
  checks on the remote instance;
- SSH connection and a non-interactive remote command;
- VS Code Remote SSH prerequisites;
- Codex CLI and Claude Code command availability without storing login tokens;
- vLLM installation, real GPU tensor execution, a small model load, Chat
  Completions, Responses, and a short benchmark are required acceptance
  evidence.

Material technical decisions:

1. Use a direct host workflow under `/workspace`, not nested Podman/devcontainers.
   This is the recommended route because ROCm device access is simpler and the
   contest pod is already containerized.
2. Keep application and vLLM Python environments separate.
3. Do not store Codex/OpenAI, Anthropic, GitHub, Hugging Face, or SSH private
   credentials in the repository or persistent shell files.
4. Prefer end-to-end verification on one live W7900 instance, with the known
   cost of 1 credit per running hour.

Risks and rollback:

- Incorrect storage selection could lose non-persistent files. Roll back by
  recreating the template with Persistent PVC before development.
- A running instance consumes credits. Stop verification promptly and destroy
  it after separate action-time confirmation.
- Agent CLI versions can change. Pin install channels where supported and
  record observed versions.
- Template edits are reversible. Duplicate template deletion is deliberately
  excluded until separately approved.

Explicit non-goals:

- no production deployment;
- no public repository or automatic Pull Request;
- no model fine-tuning;
- no storage of login tokens or private SSH keys;
- no deletion of cloud templates without a separate confirmation.

## Approval

Approved by the user on 2026-07-21:

- Proposal B: direct `/workspace` architecture;
- launch one live W7900 instance for end-to-end verification;
- spend up to one credit-hour for the verification run.
- create and upload the initial project to a private GitHub repository.

Execution order requested by the user:

1. verify SSH connectivity first;
2. inspect actual device, CPU, RAM, disk and ROCm parameters;
3. only then install and configure the coding-agent environment.

## Evidence

- Live Radeon Cloud page observed 2026-07-22: 5 credits initially, one active
  instance per account, 1 credit per GPU hour.
- Four templates currently exist; the development template uses AMD OneClick
  Base, has SSH enabled, and was changed successfully to Persistent (PVC).
- The local Ed25519 public key is saved in Radeon Cloud Profile; no private key
  was transmitted.
- Added repository contracts and reproducible scripts for VS Code Remote SSH,
  Codex CLI, Claude Code, remote verification, and the team pre-stop Git gate.
- Instance `u-9570-f63594ab` was launched from AMD OneClick Base
  `rocm7.2.1-py3.12-v20260416` with one W7900 allocation. Initial SSH failed
  because the image omitted `/usr/sbin/sshd`; the approved
  `openssh-server` bootstrap resolved it.
- Processed the official `rc-tunnel` update at commit `96ab73d8`; kept the
  private inference endpoint local and documented an optional authenticated
  public Web UI path. No tunnel was created. Direct `df` measurement showed a
  97.9 GiB PVC.
- AMD DeepSeek-V4-Flash `/chat/completions` returned the exact smoke-test
  response. Codex CLI 0.144.2 attempted `/responses`, received HTTP 404, and
  rejected a Chat Completions wire override. The user subsequently deferred
  this worker entirely until a Responses-compatible service is available.
- After approval, installed and started `openssh-server`; `ssh amd-radeon`
  passes non-interactively.
- Measured the effective allocation: 16 CPU cores by cgroup quota, 55 GiB RAM
  by cgroup limit, a 97.9 GiB `/workspace` PVC, and one 47.98 GiB W7900.
- Installed persistent Node, GitHub CLI, Codex CLI, Claude Code, Agent Python,
  PyTorch/HIP, and the explicit vLLM ROCm wheel.
- Verified vLLM on the W7900 with a public 0.5B smoke model. `/health`,
  `/v1/chat/completions`, and `/v1/responses` all passed; the benchmark and
  install manifest are saved under `/workspace/amd-track2-agent/logs`.
- Stopped the smoke inference server after verification. The cloud instance
  remains running for continued development and continues consuming credits.
