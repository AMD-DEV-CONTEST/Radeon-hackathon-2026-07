# Technical Specification — Phase J runtime queue integration

- Level: S2
- Status: implemented

## Design

1. `TaskQueue` now uses thread-safe bounded semaphores because controlled runs execute synchronous tools in worker threads with independent event loops.
2. `LLMClient.generate_text(..., project_id=...)` routes chat completion calls through `enqueue_llm`.
3. The Phase C report workflow supplies its project ID to the LLM client.
4. `LLMEmbedder` routes synchronous indexing/query embeddings through `enqueue_embedding`; `ProjectIndex` supplies its project ID.
5. Queue acquisition polls cancellation and respects the configured wait timeout.

## Verification

- `python -m pytest tests/test_queue_runtime_integration.py -q`
- `python -m pytest tests/test_llm_client.py tests/test_project_report_workflow.py tests/test_phase_j.py -q`
- `python scripts/validate_specs.py --strict`

## Cloud follow-up

Run the same project/report workload on the ROCm instance after it is available. Capture VRAM, tokens/s, embedding throughput, queue wait time, and error rate before claiming AMD performance gains.
