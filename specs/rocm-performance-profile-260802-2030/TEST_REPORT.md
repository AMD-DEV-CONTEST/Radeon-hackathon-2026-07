# Test report

- Level: S1
- Status: implemented

## Automated verification

- `python -m pytest tests/test_config.py tests/test_llm_client.py tests/test_task_reports.py tests/test_phase_j.py -q` — passed: 151 tests.
- `python scripts/benchmark.py --help` — passed.
- `cd web && npm run build` — passed.
- `python scripts/validate_specs.py --strict` — passed: 0 validation errors.

## Cloud baseline evidence

- Chat model: Qwen3.6 35B Q4, `n_ctx=32768` on port 8000.
- Embedding model: the same Qwen GGUF, `n_ctx=4096` on port 8080.
- ROCm SMI reported 48,944 MB used of 49,136 MB total VRAM before the profile restart.
- API logs recorded task model calls falling back after model-generation failures under the prior 15-second application timeout.

## Cloud benchmark comparison

The same 128-token chat request and 50-text embedding batch were run before
and after reducing the chat server context window to 16K. The embedding server
was left unchanged.

| Metric | Baseline (32K) | Optimized (16K) | Change |
| --- | ---: | ---: | ---: |
| Chat generation throughput | 66.9 tok/s | 70.0 tok/s | +4.6% |
| Chat end-to-end time | 1,911.9 ms | 1,827.5 ms | -4.4% |
| Embedding throughput | 22.0 texts/s | 23.8 texts/s | +8.2% |
| Used VRAM | 46,670.4 MB | 45,851.2 MB | -819.2 MB |

- The optimized branch was started independently on API port 9001 with
  `LLM_TIMEOUT_SECONDS=90` and `LLM_MAX_TOKENS=384`; `/health` confirmed the
  model service was reachable.
- The production-facing API remains on port 9000. The 16K chat-server setting
  is appropriate for the normal concise project-report flow; use 32K again
  only when a long-context task demonstrably requires it.
