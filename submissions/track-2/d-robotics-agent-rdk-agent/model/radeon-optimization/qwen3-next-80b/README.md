# Qwen3-Next-80B on a Single Radeon GPU

This is an independent Radeon/ROCm deployment-optimization case study. It is
not the Qwen3-32B SFT model used by the main Agent demo, and it was not the
teacher that generated the released training data.

We deployed the official pre-quantized
`Qwen3-Next-80B-A3B-Instruct-Q4_K_M.gguf` with a ROCm/HIP build of
`llama.cpp`, then compared two serving configurations on one `gfx1100` Radeon
GPU. The optimization changed only KV-cache precision and GPU offload depth.

## Recorded result

| Metric | Q8 KV / 45 layers | Q4 KV / 47 layers | Change |
|---|---:|---:|---:|
| 2,332-token prefill | 1,271.45 tok/s | 1,397.39 tok/s | +9.9% |
| 64-token decode | 37.19 tok/s | 49.82 tok/s | +34.0% |
| TTFT median | 2,021.26 ms | 1,808.76 ms | -10.5% |
| Mean wall latency | 3,727.88 ms | 3,084.19 ms | -17.3% |

Both configurations used the same Q4_K_M weights, 262,144-token configured
context, Flash Attention, 32 inference/batch threads, one parallel slot and the
same request shape. Each arm had one warm-up followed by five measured runs.

The optimized service also passed these narrow canaries:

- OpenAI-compatible structured `message.tool_calls`;
- JSON tool arguments and `role=tool` continuation;
- one 42,028-token needle retrieval.

## Verify the saved comparison

No GPU, network access or third-party package is needed:

```bash
python3 verify_results.py
```

The command recomputes the wall-time, prefill and decode means from all ten
saved measurements and checks every published delta. TTFT has only the two
saved medians, so its delta can be checked but its median cannot be rebuilt
from per-run samples.

## Reproduce the optimized service

Prerequisites:

- Linux with a ROCm-supported Radeon GPU; the recorded host used `gfx1100`,
  ROCm 7.2.1 and 51,522,830,336 bytes of VRAM;
- a ROCm/HIP `llama-server` binary built for the GPU;
- the official Q4_K_M model file from
  [Qwen/Qwen3-Next-80B-A3B-Instruct-GGUF](https://huggingface.co/Qwen/Qwen3-Next-80B-A3B-Instruct-GGUF).

The recorded model artifact has:

```text
file:   Qwen3-Next-80B-A3B-Instruct-Q4_K_M.gguf
bytes:  48,410,988,384
sha256: d103b2733ec1012a52d01edda66b7e5c24ae50508c9f99f5297ea459ef3c061a
```

`serve.sh` checks the exact byte length without re-hashing a 48 GB file on
every start. After downloading the model, verify the published SHA-256 once if
you need exact artifact identity.

Create a host-local API key and start the service. Port `8010` is used below
to avoid colliding with the main 32B service; the historical run used port
`8000`.

```bash
umask 077
openssl rand -hex 32 > /workspace/qwen80b-api-key

MODEL=/workspace/models/Qwen3-Next-80B-A3B-Instruct-Q4_K_M.gguf \
LLAMA_SERVER=/workspace/llama.cpp/build/bin/llama-server \
API_KEY_FILE=/workspace/qwen80b-api-key \
STATE_DIR=/workspace/qwen80b-state \
PORT=8010 \
bash serve.sh

curl -fsS http://127.0.0.1:8010/health
```

`serve.sh` reproduces the optimized parameters but is intentionally safer than
the historical launcher: it is path/port configurable and never kills a
different `llama-server` process. It writes only its PID and log under the
explicit `STATE_DIR`. If startup fails, it stops only the process it created and
removes the stale PID file; the log remains for diagnosis.

For a fresh `llama.cpp` build, pin and record a source revision and use:

```bash
cmake -S llama.cpp -B llama.cpp/build \
  -DGGML_HIP=ON \
  -DAMDGPU_TARGETS=gfx1100 \
  -DGGML_NATIVE=OFF \
  -DLLAMA_CURL=OFF \
  -DCMAKE_BUILD_TYPE=Release
cmake --build llama.cpp/build -j 12 --target llama-server
```

The historical A/B binary reports `version: 0 (unknown)` and is identified by
its binary SHA-256 in `results/ab-20260730.json`; it cannot be honestly mapped
back to a Git commit. A newly built binary therefore requires a fresh
performance measurement rather than inheriting the historical numbers.

## Evidence boundary

This folder preserves a five-run configuration-selection A/B, not a full
statistical benchmark. The exact historical request generator, baseline server
log and per-run TTFT samples were not archived. The optimized-arm server
timings were rechecked on the Radeon host and match the preserved JSON, but
`verify_results.py` verifies saved evidence rather than rerunning inference.

The 42K canary does not prove quality across the full configured 262K context,
and Q4 KV was not compared with Q8 KV across the final Agent task suite. These
limits are intentional and should remain visible in any presentation.

## Files

- `serve.sh`: safe launcher for the optimized Q4-KV/47-layer configuration.
- `verify_results.py`: standard-library-only arithmetic and experiment-contract check.
- `results/ab-20260730.json`: byte-identical copy of the host-side result.

The remote service and the model, runtime, launcher and result identities were
read-only rechecked on 2026-08-06. No credential or public endpoint is included
in this package.
