# Evidence packet: `e1a3-remote-20260724T093311Z-f7ebbbc`

## Outcome and scope

- Engineering/user outcome: recovered secure public-key SSH to the current
  Radeon Cloud replacement pod and recorded a sanitized device/ROCm snapshot.
- Explicit non-goals: no repository restore, PyTorch/vLLM install, model
  download, Tool Call, Agent Runtime, benchmark, public tunnel or E1 promotion.
- Commit / Issue / PR: tested source `f7ebbbc`; Issue #5; PR #9.
- AC / L1 / L2: AC-11/18/19; E1-A3; Local inference, Evidence discipline and
  Security boundary. These ACs remain unverified as complete product criteria.

## Reproduction

- Fixture or approved sanitized scenario: current Radeon Cloud replacement
  pod, access/device sub-gate only.
- Environment/model/profile: Ubuntu 24.04; 16-core CPU quota; approximately
  55 GiB memory quota; 98 GiB `/workspace`; one gfx1100/96-CU/49136-MB GDDR6
  GPU; ROCm 7.2.1. The proposed 14B BF16 model was not installed or run.
- Commands and exit status: OpenSSH installation, `sshd -t`, public-key SSH,
  cgroup/workspace inspection and AMD SMI checks passed. PyTorch/vLLM presence
  checks correctly reported both absent.

## Observed results

- Terminal state: `CONDITIONAL`.
- Product/artifact/UI evidence: none; this packet does not claim product
  behavior.
- Measurements: SSH public-key authentication PASS; GPU/ROCm identity PASS;
  workspace checkout ABSENT; PyTorch HIP and vLLM NOT VERIFIED.
- Failures, retries, and recovery: the prior instance disappeared and its data
  was not present on the replacement volume. OpenSSH was installed after
  explicit approval and configured for key-only access.
- Unverified areas: project/environment restore, PyTorch HIP, model snapshot,
  vLLM, structured response, Tool Call, Runtime decisions, application trace,
  performance and optional-bonus claims.

## Decision and history

- Result class: `CONDITIONAL` — remote development and device inspection are
  ready, but E1-A3 is still blocked on the model/service/Agent evidence.
- Known risks and conditional owner/deadline: the quality/integration owner must
  require the full current-pod E1-A3 trace before any local-inference claim.
- Rollback/known-good profile: stop `sshd` if remote access is no longer needed;
  keep all other services loopback-only and do not publish a tunnel.
- Supersedes/prior packet: complements, but does not replace,
  `e1-contract-20260724T084655Z-14a43a4`.
- Raw/large evidence location and checksum: none. No endpoint, credential,
  private data, host identifier, GPU serial or unrestricted raw log is stored.
