# Track 2 Development Environment

- **Remote access/device last verified:** 2026-07-24
- **Contract/config updated:** 2026-07-24
- **Qwen2.5-14B E1-A3 milestone status:** **ACCEPTED IN PR #7 REVIEW**
- **Engineering packet history:** append-only **PASS_REVIEW_PENDING** record for exact clean commit
  `520910183783c9bec8a0810a34b49dcc7856f360`; see
  `evidence/milestones/e1-a3-real-w7900/20260725T121500Z/`

The fixed model manifest and serving configuration below have a reproducible
engineering pass for model load, structured proposal, Runtime allow/deny and
terminal/restart behavior on the current W7900. The quality owner accepted that
E1-A3 scope during PR #7 review; the original packet remains append-only and
therefore still records its pre-review decision. This acceptance is neither the
E2 Serving Reference S1 nor the formal E8 product performance Baseline.

## Recommended architecture

```text
Web UI / CLI
    |
FastAPI application
    |
Agent runtime (LangGraph + explicit policy layer)
    |-- state and checkpointing
    |-- RAG
    |-- tool registry
    |-- argument validation
    |-- allow/deny policy
    |-- approval gates
    |-- timeout, retry, trace and evaluation
    |
OpenAI-compatible client
    |
vLLM inference server
    |
ROCm
    |
Radeon PRO W7900 48 GiB
```

Keep the inference environment and Agent application environment separate. vLLM bundles a validated PyTorch/ROCm stack and should not be mixed casually with unrelated application packages.

`RAG` in this diagram is phase-gated application behavior, not a single generic
search call. M1-M4 may retrieve only current-source spans and prior versions of
the same asset. Cross-asset summary discovery waits for the post-M4
`KnowledgeCardReady` decision; detailed historical retrieval waits for explicit
user confirmation of the relation. vLLM does not own or enforce these gates—the
Agent Runtime does.

## What vLLM is

vLLM is an inference engine and model-serving runtime, not a model. It loads an open model onto the GPU, manages KV cache and request scheduling, and exposes an OpenAI-compatible HTTP API.

The Agent application sends chat requests to vLLM. The Agent runtime still owns the workflow, state, tools, permissions, retries, and user approvals.

## Tool calling versus tool permission

These are separate layers.

`--enable-auto-tool-choice` and `--tool-call-parser` configure vLLM to let a compatible model produce and parse structured tool-call output. They affect the model/API protocol.

They do not grant the model permission to run anything.

The Agent runtime must still:

- register only approved tools;
- validate JSON arguments;
- apply per-user and per-task allowlists;
- deny filesystem, network, database, or export actions by default where appropriate;
- request human approval for sensitive actions;
- enforce timeouts, resource limits, and sandboxing;
- record an audit trail.

The safe sequence is:

```text
model proposes tool call
-> runtime validates schema
-> runtime checks identity and policy
-> optional human approval
-> runtime executes tool
-> sanitized result returns to model
```

## Model acquisition and starting choice

Use official model repositories from Hugging Face or ModelScope and check the model license before submission. Store caches under `/workspace`, for example:

```bash
export HF_HOME=/workspace/amd-track2-agent/cache/huggingface
```

Recommended E1-A3 candidate input profile (**NOT VERIFIED**):

```text
Qwen/Qwen2.5-14B-Instruct
BF16
vLLM
8K context
Hermes tool-call parser
```

Why:

- 14B BF16 weights are roughly 28 GiB, leaving room on a 48 GiB W7900 for KV cache and runtime overhead.
- Qwen2.5 has a documented Hermes-style tool template in vLLM.
- It is large enough for a credible private Agent while being simpler than 30B–80B experiments.

Exploratory alternative after the fixed Qwen2.5 profile is verified:

```text
Qwen/Qwen3-14B
```

Qwen describes Qwen3-14B as an Apache-2.0 model with strong agent and tool-use
capabilities. Test its exact vLLM tool-call template/parser combination before
considering it for a later serving reference or the E8 Baseline.

Avoid beginning with 70B/80B. Even quantized weights, KV cache, and runtime overhead make a 48 GiB single-card deployment tight; CPU offload can be much slower and adds failure modes.

## Do we need training or post-training?

No. Training from scratch is unnecessary and unrealistic for this contest.

Do not fine-tune first. Build an evaluation set and a complete local Agent workflow first. Consider LoRA/SFT or distillation only if measured failures remain after:

- better tool schemas;
- prompt and context design;
- deterministic routing;
- RAG quality improvements;
- output validation and retry;
- model comparison.

Fine-tuning is justified only when there is a repeatable error category, a clean
training set, a held-out evaluation set, and enough time to document the gain.
Quantization or distillation can support measured AMD optimization evidence.
The current optional-bonus wording also mentions use of the Radeon Cloud model
API, so self-hosted vLLM quantization alone must not be presented as guaranteed
bonus eligibility without written organizer clarification. Before E8,
quantization is limited to a compatibility probe or exploratory serving
experiment; a formal quantized Candidate follows the accepted E8 Baseline.

## What “ROCm optimization” means

It does not mean that the team must write GPU kernels.

For this project it means proving that the core inference runs on the W7900 through ROCm, then measuring and improving it:

1. Environment evidence:
   - `amd-smi`;
   - `rocminfo`;
   - PyTorch reports HIP and the GPU name;
   - vLLM starts on the GPU.
2. Inference tuning:
   - model size and dtype;
   - context-length budget;
   - `gpu-memory-utilization`;
   - KV cache usage;
   - `max-num-seqs`;
   - batching and concurrency;
   - prompt length and output caps;
   - warmup.
3. Agent runtime tuning:
   - fewer unnecessary model calls;
   - parallel independent tools;
   - context trimming;
   - caching;
   - node-level retry rather than restarting the whole task.
4. Evidence:
   - time to first token;
   - output tokens per second;
   - end-to-end task latency;
   - peak VRAM;
   - success rate;
   - tool-call accuracy;
   - comparison of a baseline and an optimized configuration.

The current vLLM documentation lists ROCm support and prebuilt wheels. The
historically verified 2026-07-22 environment used the explicit wheel
`0.23.1rc1.dev1327+gf25953cc5.rocm723`, PyTorch
`2.11.0+gitd0c8b1f`, and HIP `7.2.53211` on the host ROCm 7.2.1 stack. The
installer now reads an immutable commit URL and full SHA-256 from
`config/runtime/vllm-rocm721-known-good.env`; it never discovers the newest
nightly. It records a complete environment freeze for review. The dependency
lock becomes canonical only after the current pod passes the 14B load and
tool-call gates. Its quantization matrix does not give AMD support to every
CUDA-oriented AWQ/GPTQ/FP8 path. Verify one exact method on this W7900 before
claiming a later quantized result. Before E8 it is only a compatibility probe;
the first formal quantized Candidate is evaluated after Baseline v1 exists.

## Radeon Cloud setup

Account state observed on 2026-07-22:

- 5 credits were available before launch;
- one active W7900 instance is charged at 1 credit per GPU per hour;
- live page states 1 credit per GPU per hour;
- one active instance per account;
- the development template was changed from Local SSD to Persistent (PVC);
- SSH access remains enabled on the template;
- the local Ed25519 public key is saved; its private key remains on the Mac;
- the selected AMD OneClick Base image is
  `rocm7.2.1-py3.12-v20260416`;
- the base image did not include `/usr/sbin/sshd`; `openssh-server` was
  installed after explicit approval and non-interactive SSH now passes;
- the system/root layer is non-persistent, so a rebuilt pod may need
  `bash scripts/ensure_sshd.sh` from Jupyter before SSH works again;
- the pod exposes 128 host logical CPUs but `cpu.max` gives 16 CPU cores of
  effective quota;
- the pod exposes 503 GiB host RAM but `memory.max` gives 55 GiB of effective
  RAM;
- `/workspace` is a 97.9 GiB ext4 PVC; the replacement volume had roughly
  93 GiB free because the prior checkout, environments and model cache were
  absent.

Revalidation on 2026-07-24 found that the previous instance had disappeared
while the Profile briefly showed a stale `Ready` state. Launching the same
Persistent template created a Ready replacement pod, but `/workspace`
contained only `lost+found`; the prior repository, environments, logs and
model cache were not attached. Therefore:

- treat `/workspace` as durable only within the currently attached volume, not
  as a proven cross-instance backup;
- GitHub remains the source of truth for every source/document change, and
  work must be committed and pushed before risky tests or leaving the pod;
- retain a reproducible inventory for model snapshots and large evidence, and
  copy irreplaceable final evidence to approved external storage;
- expect every replacement pod to require `openssh-server`, repository
  restoration, environment bootstrap and model verification again; and
- do not claim PVC cross-instance persistence unless a future controlled
  destroy/relaunch test proves the exact same data and volume identity return.

### Current replacement-pod verification (2026-07-24)

The following facts were observed through non-interactive public-key SSH and
may be used as the **remote access/device sub-gate only**:

| Check | Observed result |
|---|---|
| SSH | `openssh-server` `1:9.6p1-3ubuntu13.18`; `sshd -t` and public-key login pass; password login remains disabled |
| OS | Ubuntu 24.04, kernel `6.8.0-79-generic` |
| CPU quota | `cpu.max=1600000 100000`, equivalent to 16 cores; host cpuset remains `0-127` |
| Memory quota | `memory.max=59055800320`, approximately 55 GiB |
| Persistent path | `/workspace`, 98 GiB total and 93 GiB available at verification time |
| GPU | One `gfx1100` device, 96 compute units, 49136 MB GDDR6 |
| AMD stack | ROCm `7.2.1`, `amdgpu` `6.16.13`, AMD SMI `26.2.2` |
| Project/runtime | `/workspace/amd-track2-agent/repo` absent; system Python has no `torch`; `vllm` absent |

This does **not** pass E1-A3. The project checkout, persistent environments,
frozen model snapshot, PyTorch HIP path, vLLM service, structured response,
Tool Call proposal and Runtime allow/deny trace must still be rebuilt and
verified on this exact pod. No IP address, host identifier, device serial,
credential or key fingerprint belongs in repository evidence.

Create a Notebook template with:

```text
Title: AMD Track2 Private Agent Dev
Container: AMD OneClick Base (ROCm 7.2.1, Python 3.12)
Deploy type: Notebook
Storage: Persistent (PVC)
SSH: enabled; public key saved
```

Use JupyterLab for the first bootstrap. Saving an SSH public key creates
persistent remote access; only a public key belongs in the cloud profile.

Inside the instance:

```bash
cd /workspace
git clone <team-repository-url> amd-track2-agent/repo
cd amd-track2-agent/repo
bash scripts/bootstrap_workspace.sh
bash scripts/verify_rocm_env.sh
```

If vLLM is not already present, install it in its own environment:

```bash
bash scripts/install_vllm_rocm721.sh
```

Download the approved model to the persistent model path with the exact
ModelScope revision (using a reviewed `modelscope` CLI installation), then
verify all 19 files before serving:

```bash
modelscope download \
  --model Qwen/Qwen2.5-14B-Instruct \
  --revision 3957bf39753cf01f98f6560295c4811c2b5df001 \
  --local_dir /workspace/amd-track2-agent/models/Qwen2.5-14B-Instruct-3957bf39753c

python3 scripts/verify_model_snapshot.py \
  --manifest config/models/qwen2.5-14b-instruct.modelscope.json \
  --model-dir /workspace/amd-track2-agent/models/Qwen2.5-14B-Instruct-3957bf39753c
```

The manifest records ModelScope commit
`3957bf39753cf01f98f6560295c4811c2b5df001`, the corresponding official
Hugging Face revision, Apache-2.0 license, file sizes and per-file SHA-256.
Metadata is not treated as proof: the verifier hashes the downloaded local
files and fails closed.

Then start the frozen BF16 candidate input profile. This command does not by
itself satisfy a model gate. The exact-commit E1-A3 evidence was later accepted
in PR #7 review; a future Serving Reference, Baseline or Candidate still
requires its own exact-commit packet and quality-owner decision:

```bash
bash scripts/serve_vllm.sh
```

After health passes, prove the model can produce a structured but inert tool
proposal. Runtime authorization remains a separate application test:

```bash
python3 scripts/verify_vllm_tool_call.py --model Qwen2.5-14B-Instruct
```

For a safe end-to-end smoke test, use the small public model and stop it
automatically afterward:

```bash
# huggingface.co is currently unreachable from this cloud region. Prefer a
# reviewed ModelScope/local download. If an approved HF-compatible endpoint is
# used for the smoke model, set it only for this shell.
export HF_ENDPOINT=https://<reviewed-hf-compatible-endpoint>
export HF_HUB_DISABLE_XET=1
bash scripts/smoke_vllm_server.sh
```

The smoke script validates `/health`, Chat Completions, Responses, and a short
benchmark, then stops the server. On 2026-07-22 the test passed using
`Qwen/Qwen2.5-0.5B-Instruct`; snapshot verification is deliberately disabled
for this disposable smoke run, so it is not submission evidence. The 14B
candidate input profile must pass the frozen snapshot, current-pod model-load,
ROCm identity, and tool-call checks above before it becomes an E2 Serving
Reference.

The Notebook development route binds vLLM privately by default:

```text
host = 127.0.0.1
port = 8000
```

The repository's private vLLM wrapper rejects non-loopback binds. A separate
dedicated model-API deployment would need its own explicit authentication,
authorization and exposure review; it is not part of the P0 Notebook route.

## Optional public Web UI tunnel

Official repository commit `96ab73d8a63fb89c5cc0ac1ef64977b04d8b8bf1`
added a built-in `rc-tunnel` flow on 2026-07-21. It can expose one
localhost-bound HTTP/WebSocket port from a newly created Notebook Pod through a
platform-assigned public HTTPS domain.

This does not replace SSH and cannot expose SSH, TCP, UDP, or database ports.
For this project it is reserved for an authenticated judge-facing Web UI. The
private vLLM endpoint remains on `127.0.0.1:8000` and must not be tunneled.

See `docs/PUBLIC_DEMO_TUNNEL.md` for the publication gate and security
checklist. `rc-tunnel expose` is an external publication action and must not be
run automatically by a coding agent.

## VS Code Remote SSH, Codex, and Claude Code

Radeon Cloud provides a complete Linux pod, not a bare GPU device. The W7900 is
attached to that pod together with CPU, RAM, root filesystem, networking, and a
persistent volume at `/workspace`. On this instance the effective quotas are
16 CPU cores, 55 GiB RAM, one 47.98 GiB W7900, and a 97.9 GiB PVC. `lscpu` and
`free -h` show the larger host, so use the cgroup values reported by
`scripts/verify_remote_dev.sh` when sizing workloads.

The final workflow is:

```text
local VS Code / terminal
    -> SSH
Radeon Cloud Linux pod
    -> /workspace/amd-track2-agent/repo
    -> Codex CLI or Claude Code
    -> Agent application and vLLM
    -> ROCm
    -> Radeon PRO W7900
```

After SSH and hardware verification:

```bash
cd /workspace/amd-track2-agent/repo
bash scripts/install_coding_agents.sh
source scripts/activate_remote_env.sh
```

The script installs checksum-verified portable Node.js and, when direct GitHub
Release TLS works, a checksum-verified GitHub CLI under `/workspace`. If the
cloud network presents an untrusted GitHub certificate, it uses Ubuntu's signed
`gh` package instead of bypassing TLS. It also installs the official Codex CLI
into persistent storage and invokes the official Claude Code native installer.
It does not sign in or write authentication material to the repository.

If the cloud region redirects the Claude native installer to an unavailable
page, the script detects the HTML response and installs Anthropic's official
`@anthropic-ai/claude-code` npm package into the persistent npm prefix.

Versions verified on the prior pod before its replacement (historical only;
they are not yet restored on the current empty `/workspace`):

```text
Node.js       22.17.1
npm           10.9.2
GitHub CLI    2.45.0 (Ubuntu signed package fallback)
Codex CLI     0.144.6
Claude Code   2.1.216
```

Use device authentication for a headless Codex session:

```bash
codex login --device-auth
```

Claude Code signs in when `claude` is first run. Its credentials and Codex
credentials remain outside the repository. VS Code Server and authentication
files under the home directory may need to be recreated after a pod rebuild.

The current vLLM server exposes a working Responses endpoint, so a future
Codex profile can target a compatible local model through a custom provider.
Do not treat the 0.5B smoke model as a coding agent; first validate the chosen
14B/30B model's instruction following and tool use. The AMD shared
DeepSeek-V4-Flash endpoint is deferred because its current API provides Chat
Completions rather than the Responses protocol used by this Codex CLI.

A no-secret provider/profile example is kept at
`config/codex/local-vllm-config.toml.example`. It must be merged into the
remote user's `~/.codex/config.toml`; Codex intentionally does not accept
custom provider definitions from an untrusted project-local config. Start with
the `radeon-readonly` profile. Use `radeon-workspace` only for a bounded task
branch after the model passes tool-use evaluation.

For an explicitly approved push from the pod, use an ephemeral browser login:

```bash
gh auth login --web --git-protocol https
```

Do not copy the Mac's GitHub token into the pod. Log out before handing the
shared pod to another team member.

Repository guidance is shared through `AGENTS.md`; Claude-specific context is
in `CLAUDE.md`. VS Code interpreter, cache exclusions, PATH, and extension
recommendations are in `.vscode/`.

## Credit and persistence discipline

- Keep all code, caches, models, benchmarks, and data under `/workspace`.
- The PVC was measured directly as 97.9 GiB ext4; keep model downloads and
  benchmark artifacts within its current free-space budget.
- Treat the persistent volume as a working disk, not as a backup.
- Commit and push after every reviewed, meaningful checkpoint.
- Run `bash scripts/pre_stop_checkpoint.sh` before destroying the pod.
- Destroy the instance when work ends; a running instance consumes credits.
- Do not rely on old group messages saying credits were not deducted. The live account page is the current source of truth.
- Never store SSH private keys, API keys, or confidential data in Git.
- Coding agents may create small, tested local commits on task branches when
  instructed. Push task branches at named checkpoints and record the commit;
  never let an agent bypass review or push directly to protected `main`.

## Two-week optimization plan

1. Use the accepted E1/T06 packet as the known-good model/runtime input; do
   not relabel it as an E2 Serving Reference or E8 Baseline.
2. Continue bounded Issue #15 E2/M1 implementation from accepted
   `main@b053f66`; do not expand into M2–M5 before the sequential gates.
3. Establish the E2 Serving Reference S1 and E2 Vertical Slice V1; measure
   model-only and end-to-end performance separately.
4. Expand the approved representative task set only as required by the next
   milestone gates.
5. Tune context, concurrency, tool scheduling, cache, and retries only after a
   reproducible reference exists.
6. Before E8, limit quantization work to Q0 compatibility probes; establish the
   formal E8 Baseline v1 before evaluating quantized Candidate Q1.
7. Record all commands, versions, and result tables for the English submission.
