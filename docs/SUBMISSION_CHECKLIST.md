# Submission Checklist — Bunker (AMD Radeon Hackathon 2026)

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

- [ ] `make test-unit` — 117 tests passed, 1 env-dependent skip
- [ ] `make test-security` — injection resistance + write "Deny" path pass
- [ ] `make test-negative` — tool-denial / empty-retrieval / malformed-output pass
- [ ] `make test-perf` — TTFT < 200 ms, tok/s > 30, VRAM < 20 GB (or env-tuned)
- [ ] `make test-compile` — offline BootstrapFewShot compile + reload passes
- [ ] `make test-bdd` — 4 scenarios / 23 steps pass
- [ ] `make test-all` — full chain green

## 2. Local ROCm validation (AMD GPU box)

```bash
python scripts/validate_rocm.py
```

- [ ] Prints a non-empty `torch.version.hip`
- [ ] `torch.cuda.is_available()` is `True`
- [ ] GPU name prints (e.g. `AMD Radeon RX 7900 XTX`)
- [ ] Exit code is `0`

## 3. Radeon Cloud validation (fallback path)

```powershell
$env:BUNKER_INFERENCE__BACKEND="radeon_api"
$env:BUNKER_INFERENCE__RADEON_API_KEY="<your-key>"
python -c "from src.config import get_config; from src.inference.radeon_api import RadeonCloudAPI; api = RadeonCloudAPI(api_key=get_config().inference.radeon_api_key); print('Radeon Cloud available:', api.is_available()); print(api.generate([{'role': 'user', 'content': 'Say hello in one word.'}], max_tokens=8))"
```

- [ ] `is_available()` returns `True`
- [ ] One-turn generation returns a non-empty string
- [ ] All Radeon Cloud calls use 4-bit quantization (`extra_body.quantization == "4bit"`)

## 4. App startup demo path

```bash
uvicorn src.main:app --host 0.0.0.0 --port 7860
```

- [ ] Server starts without traceback (degraded mode is fine when no GPU)
- [ ] `GET /health` returns `{"status": "ok", ...}`
- [ ] Gradio UI loads at `http://localhost:7860/` with chat + privacy dashboard
- [ ] Privacy Dashboard reports 100% local inference

## 5. Demo recording checklist

- [ ] `python scripts/validate_rocm.py` on screen (ROCm proof)
- [ ] App boots; privacy dashboard visible
- [ ] Ask a multi-hop grounded question; answer shows `[1] [2]`-style citations
- [ ] Ask something outside the context; pipeline says `INSUFFICIENT_CONTEXT`
- [ ] Trigger a write tool; PermissionController shows the "Deny" gate
- [ ] Show the audit log / data-flow monitor at 100% local
- [ ] End with `make test-all` green on screen

## 6. Generated artifacts policy

- [ ] `artifacts/` is gitignored (only `.gitkeep` committed)
- [ ] `make test-eval` documented as skipping until
      `python scripts/compile_bunker.py` runs against a live local model
