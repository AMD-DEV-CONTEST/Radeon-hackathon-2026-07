# Test report

- Level: S1
- Status: implemented

## Automated verification

- `python -m pytest tests/test_phase_j.py -q` — passed.
- `cd web && npm run test` — passed: 92 tests.
- `cd web && npm run build` — pending before PR submission.
- `python scripts/validate_specs.py --strict` — pending before PR submission.

## Cloud evidence

- `rocm-smi --showproductname --showmeminfo vram --showuse --showtemp --json` returned `VRAM Total Memory (B)`, `VRAM Total Used Memory (B)`, utilization, and temperature fields on the Radeon cloud instance.
- `GET http://127.0.0.1:8000/health` returned `status: ok`.
- `GET http://127.0.0.1:8000/v1/models` returned model id `qwen3.6-office-agent` and `meta.n_ctx: 32768`.
