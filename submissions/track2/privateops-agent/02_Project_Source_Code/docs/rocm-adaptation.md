# AMD Radeon GPU / ROCm Adaptation

The authoritative reproduction instructions are in `submission/radeon-cloud-runbook.md`.

Competition mode uses:

```bash
export PRIVATEOPS_PROVIDER_MODE=rocm-local
export PRIVATEOPS_MODEL_ENDPOINT=http://127.0.0.1:8000/v1/chat/completions
./scripts/run_rocm_server.sh
./scripts/run_cloud.sh
```

PrivateOps rejects non-loopback endpoints in `rocm-local` mode and reports `competition_eligible=true` only for same-instance loopback inference. The AMD shared HTTPS API sets development mode and is never core proof. The verified capture records AMD Radeon Graphics (`gfx1100`), ROCm 7.2.1, 1,511.072 ms direct latency, and 32.427 completion tokens/s. `scripts/collect_rocm_evidence.py` fails instead of inventing throughput when model usage metadata is absent.
