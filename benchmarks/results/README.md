# Reviewed Benchmark Results

Commit final Radeon benchmark summaries here only after completing the review steps in
`benchmarks/README.md`.

Expected files:

```text
llama_cpp_w7900_cold.json
llama_cpp_w7900_cold.md
llama_cpp_w7900_optimized.json
llama_cpp_w7900_optimized.md
```

The reviewed 2026-08-05 capture contains five optimized warm runs after one warmup and one separate
cold reference run. It reports 87.09 ms median first generated delta, 83.42 tok/s median decode
throughput, 11.92 s median end-to-end latency, and 100% valid structured JSON for the warm capture.
The final-content hash is identical across all six captured runs.

Do not add fabricated placeholder numbers. Results must be generated on the active production
Radeon host, reviewed for secrets and personal data, and interpreted according to the protocol.
