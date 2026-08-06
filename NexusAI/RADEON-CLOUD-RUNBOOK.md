# NexusAI Radeon Cloud Runbook
You have 5 credits and usage costs 1 credit per GPU per hour. Launch only after v0.8 is pushed.

## Template
- NexusAI-GPU
- AMD OneClick Base
- ROCm 7.2.1 / Python 3.12 image observed
- Persistent PVC

## After launch
```bash
rocminfo | head -50
rocm-smi
python --version
python -c "import torch; print(torch.__version__); print(torch.version.hip); print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'Not detected')"
```

Get code:
```bash
git clone https://github.com/Ghanasyam20/NexusAI.git
cd NexusAI
```
or `git pull`.

Do NOT blindly reinstall PyTorch. Preserve the image's ROCm-compatible build.

```bash
pip install -r requirements-gpu.txt
export PYTHONPATH="$PWD:$PWD/apps/api"
python scripts/check_radeon_environment.py
export NEXUS_EMBEDDING_PROVIDER=rocm
python scripts/benchmark_embeddings.py
python -m pytest -q
```

Save evidence:
```bash
git add benchmarks/radeon_embedding_benchmark.json
git commit -m "bench(radeon): add ROCm embedding benchmark results"
git push
```

Then destroy the instance from Profile -> Active Instance so credits stop being consumed.
