Document ID: RP-KB-004
Revision: 1.0
Classification: competition-public

# Benchmark Evidence Protocol

RadeonPilot ships no invented throughput claims. The Performance Lab only loads
result JSON that passes the evidence validator.

## Required fields per record

- profile: baseline | optimized | quantized
- engine: vllm | llama.cpp
- model and revision or GGUF filename
- endpoint base url (must be loopback)
- prompts: the fixed evaluation prompt list hash
- samples: raw per-request TTFT, latency, completion tokens
- aggregate: mean and p95 TTFT, mean tokens-per-second
- vram_peak_bytes observed during the run
- attestation: amd-smi process evidence for the endpoint PID
- captured_at timestamp and host

## Measurement procedure

1. Warm the endpoint with one throwaway request so JIT/compile cost is excluded.
2. Run each prompt at least five times; record every sample.
3. Keep the prompt set and max_tokens identical across baseline and optimized runs.
4. Capture VRAM with `rocm-smi --showmeminfo vram` during the run.
5. Re-run the quantized profile only if the frozen quality gate passes.

## Integrity rules

- Never edit samples after capture. Re-measure instead.
- The Performance Lab rejects records missing attestation or the prompt hash.
- Demo-mode numbers are labelled synthetic and never mixed into measured results.
