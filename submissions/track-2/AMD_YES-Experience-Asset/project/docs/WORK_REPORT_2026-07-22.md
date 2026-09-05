# Work Report — 2026-07-22

Timestamp: 2026-07-22T05:05:00+10:00
Keywords: `AMD-DevMaster`, `Track-2`, `W7900-48GiB`, `ROCm-7.2.1`,
`vLLM-ROCm`, `Responses-API`, `Persistent-PVC`, `SSH`, `VS-Code-Remote`,
`Codex`, `Claude-Code`, `GitHub-private`, `three-person-team`

## Outcome

The initial development environment is operational end to end:

```text
Mac Codex / VS Code / terminal
  -> SSH alias amd-radeon
Radeon Cloud Ubuntu pod
  -> persistent /workspace/amd-track2-agent
  -> private GitHub working copy
  -> Codex CLI / Claude Code / Agent Python environment
  -> vLLM ROCm environment
  -> ROCm 7.2.1
  -> one Radeon PRO W7900, 48 GiB VRAM
```

Real ROCm inference was proven with a small public Qwen smoke model. Both
`/v1/chat/completions` and `/v1/responses` returned HTTP 200, and a three-run
smoke benchmark averaged 0.1590 seconds for 64 output tokens (roughly
380–417 output tokens/s). This number validates the stack only; it is not a
performance claim for the recommended 14B contest model.

The instance is intentionally still running. It consumes one contest credit
per GPU hour until the user destroys it from Radeon Cloud.

## Verified server allocation

The Radeon Cloud product is a complete Linux pod with a GPU, not a bare GPU.
The pod sees a large host, but cgroup quotas are the effective limits:

| Resource | Observed value | Effective interpretation |
|---|---:|---|
| GPU | 1 × AMD Radeon Graphics / W7900 board | `gfx1100`, 96 CUs |
| VRAM | 49,136 MB | 47.98 GiB GDDR6, 384-bit |
| Host CPU visible | 128 logical CPUs | 2 × EPYC 9334, 2 NUMA nodes |
| `cpu.max` | `1600000 100000` | 16 CPU cores of quota |
| Host RAM visible | 503 GiB | not the pod's usable quota |
| `memory.max` | 59,055,800,320 bytes | 55 GiB effective pod limit |
| `/workspace` | 97.9 GiB ext4 PVC | about 79–80 GiB free after setup |
| Root filesystem | 3.5 TiB overlay | non-persistent; do not rely on it |
| OS | Ubuntu 24.04.4 LTS | kernel 6.8.0-79 |
| ROCm | 7.2.1 | AMD SMI 26.2.2, amdgpu 6.16.13 |

`free -h` and `lscpu` expose host topology; deployment choices must use the
cgroup values above. The GPU's 48 GiB VRAM is separate from the 55 GiB CPU RAM
limit.

## Completed work

### Cloud and SSH

- Saved only the Mac Ed25519 public key to Radeon Cloud. The private key never
  left the Mac.
- With explicit approval, installed `openssh-server`, created `/run/sshd`, and
  started `/usr/sbin/sshd` in the existing pod.
- Verified non-interactive SSH as `root` to instance `u-9570-f63594ab`.
- Configured local SSH alias `amd-radeon` with the live host, port, key, and
  keepalive settings.
- Verified the prerequisites used by VS Code Remote SSH: Bash, tar, curl,
  writable home, SSH command execution, and the persistent project path.
- Added an idempotent `scripts/ensure_sshd.sh` recovery helper because the
  package lives in the non-persistent system layer and may be absent after a
  pod rebuild.

### Persistent development environment

- Source and environments live under `/workspace/amd-track2-agent`.
- Repository checkout: `/workspace/amd-track2-agent/repo`.
- Agent Python venv: `/workspace/amd-track2-agent/venvs/agent`.
- Inference venv: `/workspace/amd-track2-agent/venvs/vllm`.
- Model/cache/log paths also live under `/workspace`.
- Installed and verified Node 22.17.1, npm 10.9.2, GitHub CLI 2.45.0,
  Codex CLI 0.144.6, and Claude Code 2.1.216.
- No Codex, Claude, or GitHub account login was performed on the shared pod.

### ROCm and vLLM

- Verified `/dev/kfd`, `/dev/dri`, `rocminfo`, `amd-smi`, and a real PyTorch
  tensor operation on the GPU.
- Installed PyTorch `2.11.0+gitd0c8b1f` with HIP `7.2.53211`.
- Installed the explicit vLLM ROCm wheel
  `0.23.1rc1.dev1327+gf25953cc5.rocm723`.
- Fixed a reproducibility bug where a highest-version index strategy selected
  PyPI's CUDA `vLLM 0.25.1` instead of the ROCm nightly wheel.
- Removed only CUDA-only optional packages left by that incorrect isolated
  install; no base ROCm package or user data was changed.
- Verified vLLM detects `RocmPlatform`, starts on the W7900, loads a public
  `Qwen/Qwen2.5-0.5B-Instruct` smoke model, allocates about 10.0 GiB VRAM at a
  conservative 20% setting, and exposes both OpenAI-compatible APIs.
- Stopped the smoke service after testing; GPU VRAM returned to about 26 MB
  used. The cloud pod itself remains active.

### GitHub and team safety

- Private repository:
  `https://github.com/kinnyuww/amd-devmaster-track2-agent`.
- `main` is pushed and the remote cloud checkout is synchronized.
- Added a three-person branch/worktree workflow, pre-stop checkpoint gate,
  pull-request template, and lightweight GitHub Actions static checks.
- Corrected two legacy whitespace findings from the first workflow run; the
  `quality` workflow passed on environment checkpoint `b8450be`.
- GitHub is the durable source-code truth; the PVC is a fast working disk and
  model cache, not the only backup.
- Other team members still need to provide their GitHub usernames before they
  can be added as collaborators.

## Sensitive or externally visible actions

The following actions changed external or security-relevant state and are
recorded explicitly:

1. Created and pushed a private GitHub repository under `kinnyuww`.
2. Saved one SSH public key to the Radeon Cloud profile.
3. Installed and started `openssh-server` after the user's explicit approval.
4. Used an HF-compatible China mirror, without a token, to download the public
   0.5B smoke model because `huggingface.co` was unreachable from this pod.
   Final contest model provenance and license must be recorded separately;
   ModelScope or a reviewed local transfer is preferred for the final model.
5. Kept the paid W7900 instance running so development can continue.

Actions deliberately not performed:

- no public `rc-tunnel` and no externally exposed vLLM/admin endpoint;
- no deletion/destruction of the instance or templates;
- no GitHub/Codex/Claude login token copied from the Mac;
- no model API key stored, transmitted to the pod, or committed;
- no DeepSeek-V4-Flash worker configured after the user deferred it;
- no model training or fine-tuning.

## Important technical conclusions

### vLLM and tool calling

vLLM is the GPU inference server. `--enable-auto-tool-choice` and a parser such
as `hermes` help a compatible model emit structured tool-call data. They do not
grant permission to execute a tool. Tool allowlists, argument validation,
identity, approvals, timeouts, sandboxing, and audit records remain the Agent
runtime's responsibility.

### Model choice and training

The recommended first contest baseline remains Qwen2.5-14B-Instruct BF16 with
an 8K context. It should fit the 48 GiB W7900 more safely than 70B/80B
experiments. Training from scratch is not required. LoRA/SFT or distillation is
considered only after the complete Agent and evaluation set expose a repeatable
failure category.

### ROCm optimization

The team does not need to write custom HIP kernels. The first optimization
layer is reproducible ROCm execution plus measured choices for model/dtype,
context, KV cache, concurrency, batching, warmup, prompt length, and output
caps. Application-runtime optimization is separate: reduce unnecessary model
calls, trim context, parallelize independent tools, cache, and retry only the
failed node.

### Public tunnel

The official `rc-tunnel` is for an authenticated judge-facing Web UI. It
publishes one localhost HTTP/WebSocket port. It is not needed for SSH, VS Code,
or development, and the raw vLLM API must remain private.

## Verification evidence

```text
SSH command execution                  PASS
Remote OS/CPU/cgroup/RAM/PVC inventory PASS
/dev/kfd, /dev/dri, amd-smi, rocminfo  PASS
PyTorch HIP GPU tensor                 PASS
vLLM distribution contains .rocm      PASS
vLLM platform = RocmPlatform           PASS
vLLM /health                           HTTP 200
vLLM /v1/chat/completions              HTTP 200
vLLM /v1/responses                     HTTP 200
3 × 64-token smoke benchmark           0.1590 s mean
GPU after service shutdown             about 26 MB used
Remote coding-agent availability       PASS
Shell syntax / Python compilation      PASS
Git whitespace and secret checks       PASS
GitHub Actions quality                  PASS on b8450be
```

Evidence files on the pod:

```text
/workspace/amd-track2-agent/logs/vllm-install-manifest.txt
/workspace/amd-track2-agent/logs/vllm-smoke.log
/workspace/amd-track2-agent/logs/vllm-smoke-benchmark.json
```

## Next human actions

1. Add the two teammate GitHub usernames as collaborators.
2. Sign in interactively only when needed:
   `codex login --device-auth`, `claude`, or
   `gh auth login --web --git-protocol https`.
3. Select the product scenario and create the first task branch.
4. Run the 14B baseline only after checking free `/workspace` space and saving
   a clean Git checkpoint.
5. Destroy the W7900 instance from Radeon Cloud when the work session ends.
6. Rotate the AMD Model API key shown in the earlier screenshot before any
   future DeepSeek worker experiment.
