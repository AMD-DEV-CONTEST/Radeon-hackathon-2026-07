# Track 2, Saad Kaicar, costbench

**Cost governance for on-prem AI agents, priced in measured joules.**

| | |
|:--|:--|
| Repository | https://github.com/Artkill24/costbench |
| Demo video (4:00) | https://youtu.be/7yQZLJPVTDE |
| Specification | [SPECIFICATION.md](SPECIFICATION.md) |
| Poster | [poster.pdf](poster.pdf) |
| Hardware | AMD Radeon PRO W7900 (gfx1100), Radeon Cloud |
| Stack | ROCm 7.2.1 · llama.cpp HIP · Qwen2.5-Coder 7B / 14B Q4_K_M |
| License | MIT |

## Submission checklist

- **Project Specification Document** — [SPECIFICATION.md](SPECIFICATION.md):
  application scenarios, agent architecture diagram, core capabilities,
  model & local deployment plan, inference-speed optimisation on Radeon.
- **Project Source Code** — https://github.com/Artkill24/costbench, with a
  README covering environment configuration, startup guide and dependency list.
- **Demo Video (4:00)** — https://youtu.be/7yQZLJPVTDE — live execution on the
  W7900, command line to final result.
- **Supplementary Material** — [poster.pdf](poster.pdf), A3.

## What it is

An agent reads files, plans across steps, answers — then reports what the task
cost:

3 steps · 194 tokens · 404.2 J · EUR 0.000028 · 0 bytes left the network


Every figure comes from a tokens-per-joule curve measured on this GPU, not a
price list, and the zero is verified against a local audit ledger.

## Measured results

| | Qwen2.5-Coder-7B Q4_K_M | Qwen2.5-Coder-14B Q4_K_M |
|:--|---:|---:|
| Peak sustained throughput | 696.3 tok/s | 411.6 tok/s |
| Single-stream throughput | 103.1 tok/s | 57.3 tok/s |
| Throughput gain from batching | 6.75x | 7.19x |
| Energy efficiency gain | 8.70x | 8.80x |
| Time to first token | 25 ms | 56 ms |

**Batching buys 8.7x energy efficiency, and the factor is model-independent.**
**Absolute efficiency scales inversely with model size** — the 14B/7B
tokens-per-joule ratio is 0.53 / 0.52 / 0.54 at concurrency 1 / 4 / 16, the
signature of a memory-bandwidth-bound decode. **Power draw is not monotonic in
batch size**: both models peak at concurrency 4 and draw less power at 16 while
doing ~6.8x the work.

The honest trade-off: **-88% energy per token, 7.8x time to first token.**

All figures are `measured` and reproducible from
[proofs/](https://github.com/Artkill24/costbench/tree/main/proofs). Four
measurement bugs are documented rather than hidden, and one benchmark run was
rejected as invalid — kept with its post-mortem in
[rejected/](https://github.com/Artkill24/costbench/tree/main/rejected).
