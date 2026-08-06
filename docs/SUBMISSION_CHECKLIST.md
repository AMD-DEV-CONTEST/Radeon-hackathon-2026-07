# Submission Checklist - Bunker (AMD Radeon Hackathon 2026)

Final gate before submission. Tick each box only when it passes on the target
machine (Windows dev box and, where noted, the AMD ROCm box).

## 1. Local test gates (any machine)

```bash
# Offline unit gate
pytest tests -m "not integration and not eval" -q

# Security: prompt injection + PermissionController "Deny" path
pytest tests/test_security_injection.py -v -m integration

# Negative paths: graceful degradation
pytest tests/test_negative_paths.py -v

# Performance: latency/VRAM thresholds (mocked when no GPU)
pytest tests/test_performance.py -v -m perf

# Compile pipeline smoke (offline, scripted LM)
pytest tests/test_compile_pipeline.py -v

# BDD acceptance suite
python -m behave tests/features/

# Everything, end to end
make test-all
```

- [ ] `make test-unit` - 147 tests passed, 3 env-dependent skips
- [ ] `make test-security` - injection resistance + write "Deny" path pass
- [ ] `make test-negative` - tool-denial / empty-retrieval / malformed-output pass
- [ ] `make test-perf` - TTFT < 200 ms, tok/s > 30, VRAM < 20 GB (or env-tuned)
- [ ] `make test-compile` - offline BootstrapFewShot compile + reload passes
- [ ] `make test-bdd` - 4 scenarios / 23 steps pass
- [ ] `make test-all` - full chain green

## 2. Local ROCm validation (AMD GPU box)

```bash
python scripts/validate_rocm.py
```

- [ ] Prints a non-empty `torch.version.hip`
- [ ] `torch.cuda.is_available()` is `True`
- [ ] GPU name prints (e.g. `AMD Radeon RX 7900 XTX`)
- [ ] Exit code is `0`

## 3. Local Benchmark Recording (AMD GPU box)

```bash
# Start vLLM server with your model (example)
# docker run --rm --gpus all -p 8000:8000 vllm/vllm-openai:latest --model Qwen/Qwen3-30B-A3B --quantization gptq

# Run benchmark (5 iterations, saves JSON artifact)
./scripts/benchmark.sh \
  --model Qwen/Qwen3-30B-A3B \
  --iterations 5 \
  --vllm-url http://localhost:8000 \
  --output-dir artifacts
```

- [ ] vLLM server responds to `/health`
- [ ] Benchmark completes all iterations without errors
- [ ] JSON artifact created at `artifacts/benchmark_<timestamp>.json`
- [ ] Artifact contains `summary.ttft.median_ms` and `summary.throughput.median_tok_s`
- [ ] Artifact contains `rocm_smi` output (VRAM, utilization, temperature)
- [ ] Record median TTFT and throughput in submission notes

## 4. Radeon Cloud validation (fallback path)

```powershell
$env:BUNKER_INFERENCE__BACKEND="radeon_api"
$env:BUNKER_INFERENCE__RADEON_API_KEY="<your-key>"
python -c "from src.config import get_config; from src.inference.radeon_api import RadeonCloudAPI; api = RadeonCloudAPI(api_key=get_config().inference.radeon_api_key); print('Radeon Cloud available:', api.is_available()); print(api.generate([{'role': 'user', 'content': 'Say hello in one word.'}], max_tokens=8))"
```

- [ ] `is_available()` returns `True`
- [ ] One-turn generation returns a non-empty string
- [ ] All Radeon Cloud calls use 4-bit quantization (`extra_body.quantization == "4bit"`)

## 5. App startup demo path

```bash
uvicorn src.main:app --host 0.0.0.0 --port 7860
```

- [ ] Server starts without traceback (degraded mode is fine when no GPU)
- [ ] `GET /health` returns `{"status": "ok", ...}`
- [ ] Gradio UI loads at `http://localhost:7860/` with chat + privacy dashboard
- [ ] Privacy Dashboard shows real telemetry: Local Inference % = 100 only when
      zero external and zero failed events are recorded

## 6. Demo recording checklist

Follow the 3-5 minute script in [`demo/demo_script.md`](../demo/demo_script.md).

- [ ] `python scripts/validate_rocm.py` on screen (ROCm proof)
- [ ] App boots; privacy dashboard visible (auto-refreshes every 2s)
- [ ] Ask a multi-hop grounded question; answer shows `[1] [2]`-style citations
- [ ] Ask something outside the context; pipeline says `INSUFFICIENT_CONTEXT`
- [ ] Trigger a write tool; `PermissionController` **denies by default** (the "Deny" gate)
- [ ] With `BUNKER_PRIVACY__DEMO_MODE=true`, approve a local draft/write; the
      file lands in `data/documents/`
- [ ] Show the audit log / privacy dashboard reporting real local inference %
- [ ] Run `./scripts/benchmark.sh` and show the JSON artifact in `artifacts/`
- [ ] End with `make test-all` green on screen

## 7. Architecture diagrams

- [ ] `docs/architecture.png` and `docs/agent_loop.png` are committed and render
      inline in `docs/PROJECT_SPEC.md` and `docs/ARCHITECTURE.md`

## 8. Generated artifacts policy

- [ ] `artifacts/` is gitignored (only `.gitkeep` committed)
- [ ] `make test-eval` documented as skipping until
      `python scripts/compile_bunker.py` runs against a live local model
