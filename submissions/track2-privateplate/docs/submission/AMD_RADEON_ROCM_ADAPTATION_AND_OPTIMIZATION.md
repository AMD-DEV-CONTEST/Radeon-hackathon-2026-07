# PrivatePlate: AMD Radeon GPU and ROCm Adaptation

> Track 2 judge-facing document  
> Updated: 2026-08-06  
> Claim level: project-recorded measurements within the documented experimental scope

## 1. What runs on AMD Radeon

PrivatePlate uses a self-hosted OpenAI-compatible vLLM endpoint for language and tool inference. In the judged configuration, that endpoint serves `google/gemma-4-12B-it-qat-w4a16-ct` on an AMD Radeon `gfx1100` GPU through ROCm.

A second loopback vLLM endpoint serves `BAAI/bge-small-zh-v1.5` for embedding retrieval. The application provider rejects non-loopback model URLs. A loopback endpoint can be a process on the application host or an SSH tunnel to a user-controlled Radeon node.

Contest runs used an AMD-provided Radeon cloud instance. Therefore the deployment claim is:

- model requests do not go to a third-party hosted inference API;
- vLLM is controlled by the project and bound to loopback on the Radeon node;
- the application may reach that node through a trusted SSH tunnel;
- the evidence does not require every application process to run on one physical consumer desktop.

The measured path covers text chat, tool decisions, deterministic planning, confirmation-gated writes, and embedding RAG. Image intake is implemented but not included in these measurements. Audio intake is an optional code path and was not operational in the recorded runtime because the deployed vLLM lacked the audio dependency.

## 2. Product execution path

```text
React dashboard or CLI
        |
Express API, session manager, and SSE
        |
PrivatePlate Agent orchestrator
        |
loopback OpenAI-compatible HTTP
        |
vLLM + Gemma 4 12B QAT on AMD Radeon
        |
9 model-visible read, compute, or preview tools
        |
deterministic Domain validation and SQLite
        |
explicit confirmation
        |
local write or local simulated caregiver inbox
```

The model-visible tool inventory is defined in `packages/agent-runtime/src/model/tool-definitions.ts`:

1. `get_day_context`
2. `get_inventory`
3. `find_dish_candidates`
4. `finalize_meal_plan`
5. `retrieve_local_knowledge`
6. `preview_caregiver_task`
7. `preview_meal_completion`
8. `preview_inventory_change`
9. `preview_member_memory_change`

The model has no commit tool. It may produce a typed preview, but a separate trusted confirmation route performs any write. Confirmed caregiver tasks are stored in a local simulated inbox; no SMS, email, or other external delivery provider is integrated.

## 3. Recorded Radeon environment

| Item | Recorded value |
| --- | --- |
| Host identifier | `u-13448-88ef42ae` |
| GPU architecture | AMD Radeon `gfx1100`, card model `0x744b` |
| ROCm / HIP | HIP `7.2.53211` |
| PyTorch | `2.11.0+gitd0c8b1f` |
| vLLM | `0.25.1+rocm723` |
| Attention backend | `TRITON_ATTN` |
| Chat model | `google/gemma-4-12B-it-qat-w4a16-ct` |
| Model revision | `1d2c2d7f2466070e69d6fb3fd5ce9a7d75f2f6ee` |
| Quantization | QAT W4A16, `compressed-tensors` |
| Tool and reasoning parser | `gemma4` / `gemma4` |
| Chat template | `gemma4-vllm-tool.jinja` |
| Embedding model | `BAAI/bge-small-zh-v1.5` on port `8001` |
| Chat endpoint | `http://127.0.0.1:8000/v1` |

The repository pins and installation plan are stored under `scripts/c0/stage-b/`.

## 4. Serving configuration

The recorded final chat configuration is equivalent to:

```bash
vllm serve <gemma-4-12B-it-qat-w4a16-ct snapshot> \
  --host 127.0.0.1 \
  --port 8000 \
  --tensor-parallel-size 1 \
  --max-model-len 16384 \
  --kv-cache-memory-bytes 12884901888 \
  --attention-backend TRITON_ATTN \
  --enforce-eager \
  --enable-auto-tool-choice \
  --tool-call-parser gemma4 \
  --reasoning-parser gemma4 \
  --quantization compressed-tensors \
  --chat-template <gemma4-vllm-tool.jinja> \
  --enable-prefix-caching
```

Two settings are especially important:

- `max_model_len=16384` supports the production Agent prompt, tool schemas, and household context.
- `--enable-prefix-caching` accelerates repeated Agent prefixes and is measured in Section 6.1.

The embedding server receives a deliberately small GPU-memory allocation so it can coexist with the quantized chat model. The helper scripts and pins are in `scripts/c0/stage-b/` and `scripts/rag/`.

## 5. Agent quality on Radeon

### 5.1 Diagnostic result

The latest project-recorded diagnostic re-run is `sealed-suite-diag-16k-20260804T161006Z-brfix`:

| Column | Result | Project threshold | Gate |
| --- | ---: | ---: | --- |
| Model | 21/21, 100% | 85% | PASS |
| Product | 17/21, 81% | 95% | FAIL |
| Safety | 21/21, 100% | 100% | PASS |
| All three | 17/21 | Not applicable | Not a full pass |

Also recorded:

- 83/83 real tool calls;
- zero infrastructure failures;
- zero runtime failures;
- four remaining Product failures attributed to Domain or evaluation-integration issues;
- `mealReasonableness` 7/10;
- `multiTurnObjectRecognition` 1/3;
- `confirmationAndIdempotency` 3/3.

This is a diagnostic regression run. It is not a blind formal score and it is not an official Track 2 benchmark. The suite's `finalConclusion` is `FAIL` because Product 17/21 is below the project's own 95% threshold.

Evidence: `benchmarks/c0/stage-b/sealed-suite-diag-16k-20260804T161006Z-brfix/` (`summary.json`, `case-results.jsonl`, per-case `result.json`, `transcript.jsonl`; per-case SQLite omitted by gitignore).

### 5.2 Formal blind-run boundary

An earlier frozen blind run at commit `d78e5fcda26331b3a8647a20751d6aa2d68e2297` with `max_model_len=8192` reports Model 3/21, Product 4/21, and Safety 4/21. Most failures in that run were affected by the serving context limit.

After the sealed cases were inspected and the implementation was tuned against them, later runs became diagnostic regression evidence rather than blind evidence. The submission must not merge those two categories.

### 5.3 Known remaining product gaps

Four current Product failures:

| Case | Recorded cause |
| --- | --- |
| `ppb-005` | A low-fat pinned main dish plus the small synthetic catalogue cannot satisfy a member's fat floor; revision candidates also omit some active-plan dishes |
| `ppb-006` | A single global `mealPortionScale` cannot satisfy opposing member constraints, and a repeated-failed-selection guard did not activate |
| `ppb-008` | The explicit one-pot exception path ends in `no_valid_final_plan` |
| `ppb-021` | The citation evaluator still extracts retired `kc-*` identifiers while the live corpus uses document paths and `doc-*` identifiers |

These are not hidden as successful cases. The diagnostic suite remains below its Product gate.

## 6. Measured inference-speed optimizations

The numbers in this section are project-recorded controlled A/B summaries. Each experiment changed one primary variable on the same Radeon card and model artifact, with a quality check alongside latency.

### 6.1 vLLM prefix caching

Agent calls repeatedly send a stable prefix containing system instructions, nine tool schemas, and household context. Prefix caching reuses KV state for that repeated prefix.

The recorded experiment used a separate vLLM process for each arm, 10 measured serial requests per arm, and one uncounted primer.

| Metric | A: cache off | B: cache on | Change |
| --- | ---: | ---: | ---: |
| TTFT p50 | 2248.31 ms | 1151.58 ms | **-48.78%** |
| TTFT p90 | 2250.15 ms | 1158.74 ms | -48.50% |
| E2E p50 | 3124.85 ms | 2030.96 ms | -35.01% |
| Output tokens/s p50 | 46.42 | 46.62 | +0.43% |
| Prompt tokens p50 | 3267 | 3267 | 0% |

The project record notes a valid-decision rate of 1.0 in both arms. The result shape is consistent with a prefill optimization: time to first token falls substantially while output-token generation speed stays nearly unchanged.

Recorded run identifier: `prefix-caching-ab-retry-20260803T071404Z`.

### 6.2 Trusted terminal presenter

After a terminal Domain tool succeeds, the verified result already contains the selected dishes, nutrition totals, shopping gap, or confirmation preview. The baseline asks the model for another final rewrite. The optimized arm renders a closing message from the model-submitted semantic fields and the Domain-verified payload.

The optimization does not remove the model from interpretation, multi-turn context, tool choice, dish selection, or `selectionReason` generation. It removes only a redundant terminal restatement after the result is already determined.

| Metric | A: model finalization | B: trusted presenter | Change |
| --- | ---: | ---: | ---: |
| Target E2E p50 | 16882.65 ms | 4763.24 ms | **-71.79%** |
| Target E2E p90 | 40133.17 ms | 25308.79 ms | -36.94% |
| Target model calls | 34 | 21 | -38.24% |
| Prompt tokens | 152,409 | 99,053 | -35.01% |
| Completion tokens | 4,871 | 1,802 | -63.01% |

| Scenario | A p50 | B p50 | Change |
| --- | ---: | ---: | ---: |
| Basic planning | 38601.97 ms | 19289.46 ms | -50.03% |
| Meal completion | 11036.15 ms | 1981.89 ms | -82.04% |
| RAG caregiver preview | 16882.65 ms | 4763.24 ms | -71.79% |

The recorded small quality check moved from 7/9 to 9/9 with no new errors.

Recorded run identifier: `terminal-finalization-ab-20260803T094112Z-05`.

### 6.3 Supporting design choices

The following choices reduce memory pressure or avoid unnecessary model work, but they are not presented as separate A/B results:

1. The QAT W4A16 artifact reduces model memory compared with an unquantized 12B checkpoint.
2. The Agent loop bounds model requests, tool steps, and planning retries.
3. Provider responses are constrained to one tool call at a time.
4. Typed tool schemas keep deterministic arithmetic and permission checks out of free-form generation.
5. The embedding service receives a capped GPU-memory allocation.

## 7. Evidence availability

This branch contains:

- the application and evaluation source code;
- environment pins and serving scripts;
- diagnostic evidence under `benchmarks/c0/stage-b/sealed-suite-diag-16k-20260804T161006Z-brfix/`;
- A/B evidence under `benchmarks/prefix-caching-ab-retry-20260803T071404Z/results/` and `benchmarks/terminal-finalization-ab-20260803T094112Z-05/results/`;
- this methodology and optimization summary.

Per-case SQLite databases are omitted by gitignore. Numerical results should still be read as project-recorded measurements within the documented experiment, not as an official leaderboard score.

## 8. Reproduction outline

1. Provision a compatible AMD Radeon ROCm environment.
2. Install the pinned vLLM runtime according to `scripts/c0/stage-b/install-plan.json` and `00-install-runtime.sh`.
3. Start the Gemma chat endpoint on loopback port `8000` with the configuration in Section 4.
4. Start the BGE embedding endpoint on loopback port `8001`.
5. Configure the application environment:

```bash
export PRIVATEPLATE_RAG_MODE=vllm
export PRIVATEPLATE_VLLM_BASE_URL=http://127.0.0.1:8000/v1
export PRIVATEPLATE_MODEL_ACTIVE=google/gemma-4-12B-it-qat-w4a16-ct
export PRIVATEPLATE_EMBEDDING_BASE_URL=http://127.0.0.1:8001/v1
export PRIVATEPLATE_EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
```

6. Start `npm run dev:server` and `npm run dev:web`.
7. Check `GET /api/runtime/status` for `modelReady=true` and `rag.mode=vllm_embedding`.
8. Run the desired diagnostic or A/B script while preserving environment, commit, request, result, and integrity metadata.

Offline tests and hash retrieval do not replace this Radeon reproduction path.

## 9. Claim summary

| Claim | Allowed wording |
| --- | --- |
| Deployment | Self-hosted vLLM inference on an AMD Radeon node through ROCm; no third-party hosted model API |
| Tools | Nine model-visible read, compute, or preview tools; no commit tool |
| Caregiver action | Confirmed local simulated inbox write, not external delivery |
| Diagnostic quality | Model 21/21 · Product **17/21** · Safety 21/21; overall internal gate **FAIL**; not blind |
| Prefix caching | Project-recorded TTFT p50 reduction of 48.78% in the described A/B |
| Terminal presenter | Project-recorded target E2E p50 reduction of 71.79% in the described A/B; small quality check 7/9 to 9/9 |
| Media | Image code exists; audio optional and unavailable in recorded runtime; neither belongs to the performance claim |
| Evidence scope | Diagnostic and A/B summaries committed under `benchmarks/`; per-case SQLite omitted |

