# AMD Radeon W7900 Cloud Runbook

This directory installs, starts, validates and benchmarks the YIJIAN demo on an AMD Radeon PRO W7900.

## Install and start

```bash
cd /workspace/gomentor
bash deploy/cloud/install_cloud_runtime.sh
bash deploy/cloud/install_katago_opencl.sh
bash deploy/cloud/start_cloud_stack.sh
```

## Validate

In another terminal:

```bash
bash deploy/cloud/smoke_test.sh
/persistent/yijian/venv/bin/python deploy/cloud/benchmark_mentor.py
bash deploy/cloud/run_cloud_acceptance.sh
```

The acceptance script checks AMD hardware and services, Python regressions, Go-rule logic, browser interaction, the local deterministic fallback and the current Qwen3.6-27B cloud coach. Results are written to persistent storage.

## Persistent storage

`/persistent/yijian` stores the `llama.cpp` build, model cache, logs and benchmark output. Project source remains in Git. Do not commit model weights, logs or secrets.

## Network boundary

The model server binds to `127.0.0.1:8082`; the workbench binds to port `8600`. Use authenticated platform forwarding or SSH tunneling for external access. Do not expose an unauthenticated model port.

## Start the main model only

```bash
bash deploy/cloud/start_qwen36_mentor.sh
```

The default model path is `/persistent/yijian/models/qwen36/Qwen3.6-27B-Q4_K_M.gguf`, served as `Yijian-Qwen3.6-27B-GoCoach`. Historical 4B experiments remain outside the current `8082` main service.
