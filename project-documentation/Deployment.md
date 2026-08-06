# FastAgentFactory Deployment and Acceptance Guide

This guide describes the reproducible deployment used for the submission. FastAgentFactory supports two equivalent topologies:

- **Local:** the Web stack, Agent runtime, and AMD ROCm inference node run on one Linux host.
- **SSH:** the Web stack and Agent runtime run on a control host; AMD inference services run on a separate host and are reached through SSH tunnels.

Both modes use the same inference control API, model profiles, Official/AMD switching, MTP, capacity estimation, QPS benchmark, and operator analysis.

## 1. Expected Result

| Component | Default endpoint or path |
| --- | --- |
| Web frontend | `http://127.0.0.1:3000` |
| Web backend | `http://127.0.0.1:8000` |
| Chat API | inference host `127.0.0.1:8003` |
| Embedding API | inference host `127.0.0.1:8002` |
| Inference control and telemetry | inference host `127.0.0.1:8004` |
| Image generation API | inference host `127.0.0.1:8005` |
| Official llama.cpp source | `vendor/llama.cpp-official` |
| AMD llama.cpp source | `vendor/llama.cpp-amd` |
| Shared dispatch tracing | `vendor/llama.cpp-common` |
| stable-diffusion.cpp source | `vendor/stable-diffusion.cpp` |
| Default remote models | `/root/models` |
| Default remote runtime state | `/root/.fastagentfactory` |

All inference-node paths can be overridden in the root `.env`. Use persistent storage when the hosting platform provides it.

## 2. Prerequisites

### 2.1 Control Host

Required commands:

```bash
git --version
ssh -V
python3 --version
uv --version
node --version
npm --version
```

Minimum environment:

- Python 3.11+
- Node.js 18+
- OpenSSH
- An SSH key or ssh-agent identity for split-host deployment
- Free local ports `3000`, `8000`, `18002`, `18003`, `18004`, and `18005` when image generation is enabled

On Windows, invoke `.\deploy.ps1 <command>` directly from PowerShell. WSL and
Git Bash are not required. The Web stack, Agent runtime, and SSH tunnel run
natively on Windows, and linked workspaces use paths such as
`C:\Users\<username>\Documents` without copying the source files.

```powershell
Copy-Item .env.example .env
Set-ExecutionPolicy -Scope Process Bypass
.\deploy.ps1 up
```

SSH deployment prefers `rsync` when it is available. On Windows without
`rsync`, the same deployment core uses SCP and compressed archives while
preserving the controlled remote-directory replacement boundary. Local Linux
ROCm deployment still requires `rsync`.

AgentPackage sessions use a supervised Native Runtime and do not require Docker. Session workspaces, runtime state, tool outputs, and dependency environments remain logically isolated.

### 2.2 AMD ROCm Inference Host

- Linux with an AMD GPU and working `/dev/kfd`
- ROCm user-space runtime and compiler tools
- PyTorch HIP compatible with the host ROCm version
- CMake, Ninja, a C/C++ compiler, curl, and CA certificates
- Enough disk space for model weights, two llama.cpp builds, stable-diffusion.cpp, logs, and benchmark state
- SSH key login when `DEPLOY_TARGET=ssh`

The deployment process may install missing user-space build dependencies when configured. It does not install or replace the host GPU driver.

> **Server image tip:** When creating a RadeonCloud/AMD cloud inference server, select `ROCm vLLM-dev (Navi) (vllm-dev:rocm7.2.1_navi_ubuntu22.04_py3.10_pytorch_2.9_vllm_0.16.0)`. This image is the baseline for the project's remote ROCm inference node. If you choose another image, first verify ROCm, PyTorch HIP, `/dev/kfd`, and Python ABI compatibility.

## 3. Get the Source

```bash
git clone https://github.com/LiuYan-89937/FastAgentFactory.git
cd FastAgentFactory
cp .env.example .env
```

Runtime secrets, host addresses, and deployment overrides belong in `.env`, the only user-edited configuration file excluded from Git. `deploy/defaults.env` is an internal defaults table.

## 4. Configure the Inference Target

### 4.1 Configure SSH Key Authentication from Scratch

SSH deployment requires non-interactive key authentication from the control
host. The deployment controller uses `BatchMode=yes` and never reads an SSH
login password. Use the cloud console, an existing administrator connection, or
temporary password access only to install the public key initially.

Generate a dedicated key on Windows PowerShell:

```powershell
$KeyPath = Join-Path $HOME ".ssh\id_ed25519_fastagentfactory"
New-Item -ItemType Directory -Force (Split-Path $KeyPath) | Out-Null
ssh-keygen -t ed25519 -a 64 -f $KeyPath -C "fastagentfactory-control"
Get-Content "$KeyPath.pub"
```

Generate it on macOS/Linux:

```bash
KEY_PATH="$HOME/.ssh/id_ed25519_fastagentfactory"
mkdir -p "$(dirname "$KEY_PATH")"
chmod 700 "$(dirname "$KEY_PATH")"
ssh-keygen -t ed25519 -a 64 -f "$KEY_PATH" -C "fastagentfactory-control"
cat "${KEY_PATH}.pub"
```

Never upload, commit, or copy the private key to the inference host. Only the
single-line `.pub` value belongs on the server. If the key has a passphrase,
load it into ssh-agent before deployment because automated commands cannot
prompt for that passphrase.

From the cloud console, inspect the SSH server:

```bash
command -v sshd || true
ps -p 1 -o comm=
ps -ef | grep '[s]shd' || true
```

Install OpenSSH on Ubuntu/Debian when it is absent:

```bash
sudo apt-get update
sudo apt-get install -y openssh-server
```

On a systemd host:

```bash
sudo /usr/sbin/sshd -t
sudo systemctl enable --now ssh
sudo systemctl status ssh --no-pager
```

In a container or hosted workspace without systemd as PID 1:

```bash
sudo mkdir -p /run/sshd
sudo /usr/sbin/sshd -t
sudo /usr/sbin/sshd
ps -ef | grep '[s]shd'
```

If `ss` is installed, confirm the internal listener:

```bash
ss -lntp | grep sshd
```

Open the external SSH port in the cloud security group or port mapping.
`SSH_PORT` is the public port reached by the control host; it may map to port
`22` inside a container.

Log in as the same account that will be placed in `SSH_USER`, replace
`PUBLIC_KEY` with the complete public-key line, and install it:

```bash
PUBLIC_KEY='ssh-ed25519 AAAA... fastagentfactory-control'
install -d -m 700 "$HOME/.ssh"
touch "$HOME/.ssh/authorized_keys"
grep -qxF "$PUBLIC_KEY" "$HOME/.ssh/authorized_keys" \
  || printf '%s\n' "$PUBLIC_KEY" >> "$HOME/.ssh/authorized_keys"
chmod 600 "$HOME/.ssh/authorized_keys"
chown -R "$(id -u):$(id -g)" "$HOME/.ssh"
```

Keep the existing console open while validating a new connection.

Windows PowerShell:

```powershell
ssh -i $KeyPath -p <external-port> <SSH_USER>@<SSH_HOST> "printf 'ssh-key-ok\n'"
```

macOS/Linux:

```bash
ssh -i "$KEY_PATH" -p <external-port> <SSH_USER>@<SSH_HOST> \
  "printf 'ssh-key-ok\n'"
```

Verify the server Host Key before accepting it. A successful command prints
only `ssh-key-ok`; add `-vvv` to the same command to diagnose identity selection
or authentication failures.

Load a passphrase-protected key into ssh-agent:

```powershell
# Windows; enabling the service initially may require an elevated PowerShell
Get-Service ssh-agent | Set-Service -StartupType Manual
Start-Service ssh-agent
ssh-add $KeyPath
```

```bash
# macOS/Linux
eval "$(ssh-agent -s)"
ssh-add "$KEY_PATH"
```

If Windows OpenSSH rejects broad private-key permissions:

```powershell
icacls $KeyPath /inheritance:r /grant:r "$($env:USERNAME):(R)"
```

Use a native Windows path with forward slashes:

```dotenv
DEPLOY_TARGET=ssh
SSH_HOST=<SSH_HOST>
SSH_PORT=<SSH_PORT>
SSH_USER=root
SSH_KEY=C:/Users/<username>/.ssh/id_ed25519_fastagentfactory
```

On macOS/Linux:

```dotenv
DEPLOY_TARGET=ssh
SSH_HOST=<SSH_HOST>
SSH_PORT=<SSH_PORT>
SSH_USER=root
SSH_KEY=~/.ssh/id_ed25519_fastagentfactory
```

Leave `SSH_KEY=` empty only when ssh-agent or OpenSSH configuration already
selects the correct identity. Run a read-only diagnostic before deployment:

```powershell
.\deploy.ps1 doctor
.\deploy.ps1 up
```

```bash
./deploy.sh doctor
./deploy.sh up
```

### 4.2 Remote AMD GPU

```dotenv
DEPLOY_TARGET=ssh
SSH_HOST=<AMD-Inference-Host>
SSH_PORT=<SSH-Port>
SSH_USER=root
SSH_KEY=
```

`SSH_KEY` may be an absolute private-key path. Leave it empty when OpenSSH or ssh-agent already selects the correct identity.

Validate login before deployment:

```bash
ssh root@<AMD-Inference-Host> -p <SSH-Port>
```

### 4.3 Local AMD GPU

```dotenv
DEPLOY_TARGET=local
SSH_HOST=
SSH_PORT=22
SSH_USER=
SSH_KEY=
```

Set all `REMOTE_*_ROOT` and `REMOTE_*_DIR` values to writable absolute paths on the local Linux host. The names are retained for compatibility but refer to the inference node in both modes.

### 4.4 Important Configuration Groups

- Target and paths: `DEPLOY_TARGET`, `SSH_*`, `REMOTE_PROJECT_ROOT`, `REMOTE_STATE_ROOT`, `REMOTE_MODEL_ROOT`
- llama.cpp builds: source roots, build type, active implementation, GPU architecture
- Chat model: GGUF URL, SHA256, context, slots, KV cache, Flash Attention, GPU layers
- YaRN: native context, extension support, and maximum context
- MTP: enabled flag, draft-token limit, acceptance probability, backend sampling
- Embedding: model id, provider, device, dimensions
- Image generation: FLUX GGUF, VAE, CLIP-L, T5XXL, eager loading, and residency policy
- Web Search MCP: built and registered from `.agentfactory/mcp/web_search` with the bundled Hackson test configuration

Do not commit filled deployment configuration.

## 5. One-command Deployment

```bash
./deploy.sh up
```

The workflow is idempotent and performs these stages:

1. Validate local/SSH target configuration and connectivity.
2. Validate bundled Official and AMD llama.cpp source trees.
3. Inspect the AMD GPU, `/dev/kfd`, ROCm, compiler, PyTorch HIP, disk, and CA trust chain.
4. Install only missing permitted user-space dependencies.
5. Synchronize the minimal inference runtime and bundled native sources.
6. Build Official and AMD `llama-server`/`llama-bench` independently.
7. Build `sd-server` from the complete bundled stable-diffusion.cpp source.
8. Resume model downloads and verify configured file size/SHA256.
9. Create or reconcile Chat, Embedding, and Image profiles.
10. Start inference control, Chat, Embedding, and configured Image services.
11. Wait for real readiness, including model runtime metadata and MTP slot state when enabled.
12. Generate local endpoint settings and the resource encryption key.
13. Prepare Python, frontend, and Native Agent runtime dependencies from `uv.lock` and `package-lock.json`, then type-check and build the production frontend.
14. Start the backend and wait for `http://127.0.0.1:8000/health`; start Vite Preview with explicit `--host 127.0.0.1 --port 3000 --strictPort` arguments and wait for `http://127.0.0.1:3000/`, unless `--no-web` was selected.

Validated model files are reused on later runs. Partial downloads resume instead of restarting.

By default, the FLUX image profile is enabled and active. Deployment waits for Chat, Embedding, and FLUX to report `ready`; FLUX uses eager loading and a 1024×1024 default generation size. Set `IMAGE_ENABLED=0` only when the image runtime should remain disabled.

Open `http://localhost:3000` after readiness completes.

The frontend port is not Vite's default preview port. `./deploy.sh up` owns the Web lifecycle and reports `Application ready` only after the backend and frontend probes both succeed. A log showing `http://127.0.0.1:4173/` indicates an outdated deployment controller or a direct preview invocation, not a valid FastAgentFactory startup.

## 6. Acceptance Checks

### 6.1 Environment

```bash
./deploy.sh doctor
./deploy.sh status
```

Confirm:

- AMD GPU and expected `gfx` architecture are visible.
- `/dev/kfd` is accessible.
- ROCm compiler/runtime and PyTorch HIP probes succeed.
- Official and AMD build metadata are present.
- Model directories have sufficient free space.

### 6.2 Services

For SSH mode, local forwarded endpoints should respond:

```bash
curl --fail http://127.0.0.1:18004/health
curl --fail http://127.0.0.1:18003/health
curl --fail http://127.0.0.1:18002/health
curl --fail http://127.0.0.1:18005/v1/models  # when IMAGE_ENABLED=1
```

For local mode, use the configured direct loopback ports.

Readiness is not inferred only from an open port. The control node verifies the loaded model, implementation metadata, slot configuration, and required MTP state.

### 6.3 Web

Verify both control-host endpoints before UI acceptance:

```bash
curl --fail http://127.0.0.1:8000/health
curl --fail http://127.0.0.1:3000/
```

The terminal should print `Backend is ready`, `Frontend is ready`, and `Application ready` in that order. The preview process must report `http://127.0.0.1:3000/`; port `4173` is not accepted by the deployment readiness probe.

Verify from the UI:

- Model profiles and live inference configuration are visible.
- The active Official/AMD implementation is reported.
- A normal chat request streams promptly.
- A published Agent initializes and can call its declared tools.
- Collaboration starts isolated workers and reports task progress.
- Workspaces and artifacts remain session-isolated.
- Benchmark pages show real runtime parameters and GPU telemetry.

## 7. Service Lifecycle

| Command | Purpose |
| --- | --- |
| `./deploy.sh up` | Deploy and run the full stack |
| `./deploy.sh up --no-web` | Deploy inference only |
| `./deploy.sh bootstrap` | Prepare models and inference without Web |
| `./deploy.sh doctor` | Inspect prerequisites and GPU environment |
| `./deploy.sh status` | Display model and service state |
| `./deploy.sh logs` | Read recent inference-node logs |
| `./deploy.sh restart` | Restart inference services and wait for readiness |
| `./deploy.sh down` | Stop inference and release VRAM |
| `./deploy.sh models` | Resume downloads and reconcile profiles |
| `./deploy.sh sync` | Synchronize runtime and native sources |
| `./deploy.sh build-llama [official\|amd\|all]` | Incrementally build implementations |
| `./deploy.sh switch-llama <official\|amd>` | Switch implementation with the same profile |
| `./deploy.sh rollback-llama` | Restore the previous active implementation |
| `./deploy.sh build-sd` | Build the image-generation server |

`./deploy.sh up` is the only public startup entrypoint. It reconciles the deployment idempotently and then starts the Web stack.

## 8. Updating the Project

Pull or copy the new source on the control host, then run:

```bash
./deploy.sh sync
./deploy.sh build-llama all
./deploy.sh restart
```

Use `./deploy.sh models` when model manifests or profile definitions changed. Re-running `./deploy.sh up` remains safe and performs the complete reconciliation.

## 9. llama.cpp Operator Development

Official and AMD implementations are built into separate directories and never overwrite each other. The switch command unloads the current model, atomically activates the selected binary, reloads the same profile, and rolls back on failure.

Normal performance tests keep HIP Graph enabled. Operator analysis temporarily disables graph replay so host dispatch records can be matched with rocprof kernel events. Profiler timing is used only for attribution; user-facing throughput comes from normal HTTP service runs.

Kernel catalogs describe stable kernel ids, labels, purpose text, supported architectures, quantization types, and shape constraints. Dispatch metrics distinguish eligibility, selection, actual launch, and fallback.

MTP uses the model's retained NextN layers through `--spec-type draft-mtp`. The service becomes ready only when every slot reports speculative decoding as active; unsupported models fail explicitly rather than silently falling back.

## 10. Replacing an SSH Inference Host

1. Install the required SSH public key on the new host.
2. Update `SSH_HOST`, `SSH_PORT`, and any persistent-path overrides in `.env`.
3. Run `./deploy.sh up`.

The script synchronizes source and runtime files again. Existing validated models are reused only when the configured storage path already contains them.

## 11. Troubleshooting

### SSH Login Fails

```bash
ssh -vvv root@<host> -p <port>
```

Verify the host, port, server public key installation, private-key permissions, and ssh-agent identity.

Some hosted workspaces are containers without systemd as PID 1. In that case,
`systemctl status ssh` failing does not mean OpenSSH is absent. Validate and
start sshd directly:

```bash
/usr/sbin/sshd -t
ps -ef | grep '[s]shd'
mkdir -p /run/sshd
/usr/sbin/sshd
```

Install the public key in the remote user's `~/.ssh/authorized_keys`. Keep the
private key on the control host and select it through `SSH_KEY` or ssh-agent.

### SSH Channel Connection Refused

SSH is connected but a remote inference service is not listening. Check:

```bash
./deploy.sh status
./deploy.sh logs
```

### Read Timeout

Distinguish model loading from a dead service. Inspect control-node state and logs; do not increase timeouts until the loading stage and GPU activity are understood.

### Interrupted Model Download

Run:

```bash
./deploy.sh models
```

The downloader resumes from the partial size and accepts the file only after configured validation succeeds. A tiny error response cannot pass as a model file.

### Model Load Fails or VRAM Is Insufficient

Inspect context size, slots, KV cache types, GPU layers, YaRN scaling, MTP, image residency, and current VRAM use. Capacity is calculated per slot; increasing total context without adjusting compression and VRAM estimation is not valid.

### Native Agent Runtime Initialization Fails

Check Python, uv, package dependency declarations, and session-workspace permissions, then rerun `./deploy.sh up`. The AgentPackage runtime does not require Docker.

### Frontend Preview Starts on 4173 or Never Becomes Ready

The deployment supervisor probes `http://127.0.0.1:3000/` and starts Vite with an explicit strict port. If the log reports `4173`, verify that the checkout contains the current `deploy/web_runtime.py` and that startup was performed through `./deploy.sh up`, not `npm run preview`.

When frontend dependency declarations or the lockfile changed, rebuild the local installation from the committed lock before retrying:

```bash
cd web_frontend/frontend
npm ci
cd ../..
./deploy.sh up
```

The committed toolchain keeps TypeScript on the Vue type-checker's compatible 5.3 patch line. Do not regenerate the lockfile with an unrelated TypeScript major/minor upgrade during deployment.

## 12. Static Checks

```bash
python3 -m compileall agent_factory web_frontend/backend deploy
python3 -m compileall -q deploy
bash -n deploy.sh deploy/start_web.sh deploy/remote_runtime.sh
cd web_frontend/frontend && npm run type-check
```

These checks validate syntax and types only. Final acceptance must use the actual AMD ROCm runtime and Web workflow.
