# ROCm Inference Benchmark Template

Template status: blank benchmark record. This file contains no measured result and makes no performance claim.

Use a new copy for each materially different machine, software stack, model, prompt, model setting, or backend.

## 1. Record Metadata

- Experiment ID:
- Operator:
- Benchmark date:
- Start time:
- End time:
- Time zone:
- Host alias:
- Repository commit:
- Environment audit record:
- Raw evidence location:
- Raw evidence SHA-256:

## 2. Benchmark Environment

- CPU:
- GPU:
- GPU architecture / LLVM target:
- Memory / UMA configuration:
- OS:
- Kernel:
- ROCm:
- Driver:
- Ollama:
- Model:
- Model revision or digest:
- Quantization:
- Prompt ID:
- Prompt SHA-256:
- Prompt:
- Input token count and tokenizer:
- Maximum output tokens:
- Temperature:
- Seed, if supported:
- Thinking mode:
- Backend:
- Streaming mode:
- Context length:
- `keep_alive`:
- Warm-up procedure:
- Run count:
- Concurrency:
- Timeout:
- Network state:
- GPU metric source and sampling interval:
- Memory metric source and units:

Use only synthetic, non-confidential prompt content. If the prompt is too long to include, store a sanitized version and its checksum.

## 3. Success Criteria

- Expected output schema:
- Schema validator and version:
- Per-run success definition:
- Timeout definition:
- Allowed format-repair retries:
- Cloud fallback policy:

## 4. Run Protocol

1. Complete and link the environment audit.
2. Record the cold-start procedure separately from warm inference.
3. Run the declared warm-up procedure; exclude warm-up from measured samples.
4. Keep prompt, model, settings, backend, concurrency, and measurement sources fixed.
5. Record every attempted run, including failures and timeouts.
6. Preserve raw, non-sensitive output and metric samples.
7. Compute summary metrics only from the declared sample population.

## 5. Raw Run Record

| Run | Start time | First token latency (ms) | Total latency (ms) | Success | GPU utilization (%) | Memory usage | Output tokens | Error / evidence reference |
|---:|---|---:|---:|---|---:|---:|---:|---|
| 1 | | | | | | | | |
| 2 | | | | | | | | |
| 3 | | | | | | | | |
| 4 | | | | | | | | |
| 5 | | | | | | | | |
| 6 | | | | | | | | |
| 7 | | | | | | | | |
| 8 | | | | | | | | |
| 9 | | | | | | | | |
| 10 | | | | | | | | |

Add or remove blank rows to match the declared run count. Never delete a failed attempt from the record.

## 6. Metrics

| Metric | Result | Unit | Calculation / source |
|---|---:|---|---|
| First token latency | | ms | define event boundaries; mark unavailable for non-streaming APIs that do not expose it |
| Total latency | | ms | request dispatch to complete validated response |
| Average latency | | ms | arithmetic mean over the declared sample population |
| P95 latency | | ms | record the exact percentile method and sample count |
| Success rate | | % | successful attempts divided by all attempted measured runs |
| GPU utilization | | % | record source, sampling interval, and aggregation |
| Memory usage | | MiB or GiB | distinguish process, VRAM, system RAM, or UMA measurement |

## 7. Metric Definitions

- **First token latency**: elapsed time from request dispatch to the first response token observed by the client.
- **Total latency**: elapsed time from request dispatch to receipt and validation of the complete response.
- **Average latency**: arithmetic mean of the explicitly stated latency sample set.
- **P95 latency**: the 95th percentile computed with the named method; do not report it without the sample count.
- **Success rate**: schema-valid, policy-valid successful measured runs divided by all measured attempts.
- **GPU utilization**: utilization observed through the named measurement source, with sampling frequency and aggregation stated.
- **Memory usage**: the named memory category measured by the named source; do not present system RAM or UMA as discrete VRAM without qualification.

## 8. Results and Interpretation

### Observed facts


### Derived metrics


### Interpretation


### Limitations


## 9. Review

- [ ] No result was estimated or copied from a different environment.
- [ ] Cold-start, warm-up, and measured runs are separated.
- [ ] Failed attempts remain in the denominator.
- [ ] First token latency is not inferred when the client did not observe a first-token event.
- [ ] Average and P95 can be recomputed from preserved raw samples.
- [ ] GPU and memory metrics name their sources and units.
- [ ] The prompt and outputs contain only synthetic, non-confidential data.
- [ ] Offline or `Cloud API Calls: 0` claims have separately preserved network evidence.
- [ ] A reviewer has checked the record:

Reviewer:

Review date:
