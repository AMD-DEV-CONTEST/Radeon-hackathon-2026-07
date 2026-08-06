# Verification Evidence - 2026-08-05

## Scope

This record distinguishes repository tests, read-only RDK X5 evidence, client model configuration, and evidence that still requires the participant-controlled Radeon Cloud server.

## Development-host verification

### TypeScript

Commands:

```sh
cd rdk-agent
npm run check
npm test
```

Result:

```text
TypeScript check: passed
tests: 134
pass: 134
fail: 0
```

### Rust

Commands:

```sh
cd rdk-sophon
cargo test --workspace
cargo clippy --workspace -- -D warnings
cargo build --release --workspace
```

Result:

```text
tests: 62
pass: 62
fail: 0
clippy with -D warnings: passed
release workspace build: passed
```

The socket-based end-to-end tests require permission to bind local TCP/Unix sockets. They passed when re-run in an environment that permits loopback binding.

Formatting boundary:

```text
cargo fmt --all -- --check: follow-up required
```

The command reported existing formatting differences. The evidence does not describe the complete `scripts/full_test.sh` pipeline as green.

## Read-only RDK X5 evidence

Commands:

```sh
sophonctl --board x5 --timeout 5 ping
sophonctl --board x5 --timeout 5 state
sophonctl --board x5 --timeout 5 plugins list
```

Sanitized result:

```text
ping: pong=true
board timestamp: 2026-08-05T11:02:17Z
CPU: 8 usage entries; reported core frequency 1500 MHz
memory: 7,424,344,064 bytes total; 3,550,343,168 bytes used
thermal-ddr: 55.113 C
thermal-cpu: 54.38 C
plugin: servo - MagicBox servo posture control
```

MAC addresses and private infrastructure details are intentionally omitted.

## Client model configuration

The private Pi runtime selects:

```text
provider: amd
model: Qwen3-Next-80B-A3B-Instruct
API: OpenAI-compatible Chat Completions
```

The endpoint and literal local API key are not copied into the repository.

## AMD server evidence boundary

Not yet independently captured for the submission:

- AMD Radeon GPU model.
- ROCm/HIP version.
- vLLM version and launch command.
- Model revision and precision/quantization.
- Client TTFT and decode throughput.
- Server utilization, VRAM, and profiler evidence.

The benchmark script and evidence procedure are included so these items can be added without changing the methodology.
