# PrivatePlate Prefix Caching A/B

- status: **ADOPTABLE_CANDIDATE**
- measured samples: A=10, B=10

## Primary latency

| Metric | A OFF | B ON | Change B vs A |
| --- | ---: | ---: | ---: |
| TTFT p50 (ms) | 2248.309641 | 1151.579739000008 | -48.78% |
| TTFT p90 (ms) | 2250.1479980000004 | 1158.7407919999969 | -48.50% |
| E2E p50 (ms) | 3124.846927000006 | 2030.9634950000036 | -35.01% |

## Cache evidence

- B prefix-cache queries delta: 35934
- B prefix-cache hits delta: 19840
- B cached prompt-token delta: 0
- metric names: vllm:external_prefix_cache_hits_created{engine="0",model_name="google/gemma-4-12B-it-qat-w4a16-ct"}, vllm:external_prefix_cache_hits_total{engine="0",model_name="google/gemma-4-12B-it-qat-w4a16-ct"}, vllm:external_prefix_cache_queries_created{engine="0",model_name="google/gemma-4-12B-it-qat-w4a16-ct"}, vllm:external_prefix_cache_queries_total{engine="0",model_name="google/gemma-4-12B-it-qat-w4a16-ct"}, vllm:prefix_cache_hits_created{engine="0",model_name="google/gemma-4-12B-it-qat-w4a16-ct"}, vllm:prefix_cache_hits_total{engine="0",model_name="google/gemma-4-12B-it-qat-w4a16-ct"}, vllm:prefix_cache_queries_created{engine="0",model_name="google/gemma-4-12B-it-qat-w4a16-ct"}, vllm:prefix_cache_queries_total{engine="0",model_name="google/gemma-4-12B-it-qat-w4a16-ct"}
- actual hit evidence: yes

## Quality and limits

- quality not lower: yes
- new B errors: none
- Timing uses streaming replay of the real production request shape; the measured requests do not execute Domain tools.
- There are 10 measured serial requests per arm plus one uncounted primer; this is not a statistical performance characterization.
- TTFT is the primary signal. Output tokens/s is reported but is not used as a prefix-cache failure criterion.
- A separate vLLM process is started for each arm; process-local prefix cache is not shared across arms.

Conclusion: B is adoptable only when quality is not lower, B adds no errors, prefix cache metrics show activity, and TTFT p50 improves.
