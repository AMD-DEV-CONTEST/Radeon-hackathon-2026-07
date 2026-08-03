# Performance and Validation

## Hardware and software

- AMD Radeon PRO W7900, 48 GB VRAM
- AMD ROCm 7.2.1 for `llama.cpp`
- KataGo v1.16.5 OpenCL
- Official KataGo b40 network
- Qwen3.6-27B Q4_K_M GGUF
- Python/FastAPI orchestration and SQLite persistence

## Measurements

| Test | Configuration | Result |
|---|---|---:|
| Whole-game engine sample | 33 positions, 32 visits each | 13.55 s total |
| Critical-node verification | 1 position, 128 visits | 2.63 s |
| Evidence-grounded coach acceptance | 6 constructed cases | 6/6 passed |
| Coach acceptance latency | end-to-end, six-case set | P95 9.536 s |
| Regression suite | backend + training/data | 373 tests |

The 33-position result averages approximately 0.41 seconds per analyzed position in that batch. Position complexity and runtime contention can change individual latency.

## Validation design

### Numerical authority

KataGo is the only authority for candidate ranking, win rate, score lead, visits and principal variations.

### Answer consistency

The server checks subject identity, coordinates, board regions, numerical claims and unsupported certainty. A recommended move in the upper-left cannot be described as a move in the lower center; a question about the AI move cannot silently become an explanation of the played move.

### Regression coverage

The automated suite covers board replay, SGF parsing, engine adapters, reports, jobs, teaching-context construction, answer validation, trusted KataGo artifacts, terminology and training-data hygiene.

## Reproduction commands

From `source/` on the Radeon cloud instance:

```bash
bash deploy/cloud/install_cloud_runtime.sh
bash deploy/cloud/start_cloud_stack.sh
bash deploy/cloud/smoke_test.sh
python deploy/cloud/benchmark_katago_analysis.py
python deploy/cloud/benchmark_mentor.py
bash deploy/cloud/run_cloud_acceptance.sh
```

Exact model paths are configured through environment variables. Weights, credentials and private records are intentionally excluded.

## Interpretation boundary

Passing engine and consistency checks does not make every teaching sentence objectively true. YIJIAN therefore exposes the difference between engine facts, rule facts, heuristics and language-model expression, and uses deterministic fallback when confidence is insufficient.
