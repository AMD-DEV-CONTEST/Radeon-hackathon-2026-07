# RDK Agent Reproducibility Guide

This guide separates development-host verification, read-only RDK X5 checks, full deployment, private AMD inference, and physical-action acceptance. Evaluators can run the first two sections without moving the robot.

## 1. Repository layout

```text
rdk-sophon/
├── rdk-agent/       TypeScript multi-agent TUI and delivery tooling
├── rdk-sophon/      Rust device platform and sophonctl
└── submission/en/   Official English Track 2 materials and evidence
```

## 2. Development-host prerequisites

- Node.js 22.19 or newer
- npm
- Rust toolchain with Cargo
- Podman and a pre-pulled `docker.io/library/python:3.12-slim` image for Robot Development Mode
- macOS or Linux for local development

Install dependencies:

```sh
git clone https://github.com/cowhorseming/rdk-sophon.git
cd rdk-sophon/rdk-agent
npm ci
```

The Rust workspace uses `Cargo.lock`; Cargo resolves the pinned dependency graph during the first build.

## 3. Safe local verification

### 3.1 TypeScript

```sh
cd rdk-agent
npm run check
npm test
```

Expected evidence for the submitted snapshot: TypeScript check succeeds and 134 tests pass.

### 3.2 Rust

```sh
cd ../rdk-sophon
cargo test --workspace
cargo clippy --workspace -- -D warnings
cargo build --release --workspace
```

Expected evidence for the submitted snapshot: 62 tests pass, Clippy succeeds with warnings denied, and the release workspace builds.

The repository's `scripts/full_test.sh` pipeline was not recorded as a single run for this snapshot. Its constituent check, Clippy, test, and release-build stages were run separately and passed. A separate `cargo fmt --all -- --check` reported existing formatting differences; formatting is not part of `full_test.sh`.

Some Rust end-to-end tests bind local TCP or Unix sockets. Run them in an environment that permits loopback socket binding.

## 4. Inspect the TUI without moving hardware

```sh
cd ../rdk-agent
npm start -- --workspace "$PWD/config/templates/magicbox-servo"
```

Use only inspection commands:

```text
/modes
/mode robot-development
/skills
/workspace
```

Do not submit an imperative robot request while performing a safe UI inspection. Robot Application Mode treats an imperative request as authorization for one mapped action.

## 5. Configure the RDK X5 client

Create `~/.rdk-sophon/config.toml` on the development host:

```toml
[default]
host = "192.0.2.10:7777" # Documentation-only address; replace with the board address.
timeout = 30

[boards.x5]
host = "192.0.2.10:7777" # Documentation-only address; replace with the board address.
timeout = 30
```

Adjust the address to match the board. Then run only read-only checks:

```sh
sophonctl --board x5 ping
sophonctl --board x5 state
sophonctl --board x5 plugins list
```

The submitted evidence captured `pong: true`, a live state snapshot, and the `servo` plugin on 2026-08-05.

## 6. Deploy the complete stack

RDK X5 prerequisites:

- Ubuntu aarch64 with `systemd`
- Root access for installation
- SSH host alias `x5-root`, or a replacement supplied to the script
- Python 3 and device permissions required by the MagicBox runtime

From the repository root:

```sh
export RDK_BOARD_IP=192.0.2.10 # Documentation-only example; replace with the board IP.
./rdk-agent/deploy/install-rdk-agent-stack.sh \
  --ssh-host x5-root \
  --board-address "$RDK_BOARD_IP:7777"
```

This deploys board binaries and configuration, the servo plugin/runtime, the development-host `sophonctl`, and the RDK Agent application/configuration. It performs read-only integration checks after installation.

## 7. Configure private AMD Radeon inference

Use a participant-controlled Radeon Cloud instance with a compatible ROCm stack and a dedicated OpenAI-compatible vLLM service. The service must listen on `0.0.0.0:8000` when using the competition's dedicated Model API routing.

Example service shape:

```sh
export MODEL_PATH_OR_ID=/path/to/model-or-hub-id
vllm serve "$MODEL_PATH_OR_ID" \
  --served-model-name Qwen3-Next-80B-A3B-Instruct \
  --host 0.0.0.0 \
  --port 8000
```

Copy the sanitized client configuration:

```sh
mkdir -p ~/.pi/agent
cp submission/en/config/pi-models.amd-rocm.example.json ~/.pi/agent/models.json
```

Set the real private base URL in the copied file. Keep the API key out of the repository:

```sh
read -r -s RDK_AMD_MODEL_API_KEY
export RDK_AMD_MODEL_API_KEY
```

Select the model in `~/.pi/agent/settings.json`:

```json
{
  "defaultProvider": "amd",
  "defaultModel": "Qwen3-Next-80B-A3B-Instruct"
}
```

Do not publish the live endpoint or key. Redact secrets and user-specific tunnel names from screenshots and logs.

## 8. Capture server-side AMD evidence

Run equivalent commands inside the participant-controlled Radeon instance and save redacted output:

```sh
rocminfo
rocm-smi --showproductname --showdriverversion --showmeminfo vram
python3 -c 'import torch; print(torch.__version__); print(torch.version.hip); print(torch.cuda.get_device_name(0))'
python3 -c 'import vllm; print(vllm.__version__)'
curl http://127.0.0.1:8000/v1/models
```

Also record the exact vLLM launch command, model revision, precision or quantization setting, container digest if used, and warm-up policy.

## 9. Run the client benchmark

The benchmark reads the Pi model configuration but never emits the API key:

```sh
node submission/en/scripts/benchmark-openai-compatible.mjs \
  --provider amd \
  --runs 10 \
  --output submission/en/evidence/amd-endpoint-benchmark.json
```

Run the same prompt set against the baseline and tuned configuration. Report p50 and p95, not only the fastest request. This client-side result includes network/tunnel overhead and must be interpreted alongside server-side profiler and utilization evidence.

## 10. Run Robot Development Mode

Start the TUI:

```sh
rdk-agent
```

Then:

```text
/mode robot-development
/develop Create a new action that waves the left side once.
```

Observe the five delivery nodes. The final two acceptance stages may move real hardware. Keep the robot clear of people and obstacles and be prepared to abort.

## 11. Run Robot Application Mode

After the Skill is installed:

```text
/mode robot-application
Wave the left side once.
```

An imperative request authorizes one mapped action. A successful command path does not by itself prove that the physical motion was correct; record a human observation separately.

## 12. Expected outputs

- Test reports for the TypeScript and Rust workspaces.
- TUI stage progress and tool/Skill events.
- An action-package release with deterministic metadata and hashes.
- Board deployment receipt and installed Skill.
- `sophonctl` state and plugin output.
- One CLI and one natural-language acceptance invocation.
- Redacted Radeon/ROCm/vLLM environment evidence and benchmark JSON.

## 13. Troubleshooting boundaries

- If Rust E2E tests fail with `Operation not permitted` while binding `127.0.0.1`, run them outside a restricted sandbox.
- If HTTP or WebSocket adapters are used, explicitly pass `/run/probe-daemon/probe.sock` until their source defaults are aligned with daemon configuration.
- If a real servo action fails, verify GPIO permissions for the unprivileged `probe` service user.
- If the model is unavailable, verify provider/model selection, the private endpoint, and API-key environment variable without printing the key.
