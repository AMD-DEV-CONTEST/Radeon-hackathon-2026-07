# Radeon Cloud Reproduction Runbook

## Verified state and current reproduction

The first complete run was captured from instance `u-15477-db2e6f27`: AMD Radeon Graphics (`gfx1100`), ROCm 7.2.1, Qwen2.5-7B-Instruct, same-instance vLLM, direct latency 1,511.072 ms, throughput 32.427 tokens/s, and complete Agent latency 18,384.639 ms. That runtime was destroyed after capture. On 2026-08-04 the profile was launched again and independently reproduced the same runtime boundary with a 1,513.115 ms / 32.384 tokens/s machine benchmark, a real Chinese Agent response, 101 passing cloud tests, and the 27-artifact validator. The new evidence is kept separately under `evidence/rocm-retest-20260804/`; do not overwrite the primary evidence by hand.

## 1. Request and create the Radeon Cloud environment

Register with the competition organizer using the same email used for the event. After access is granted, sign in to Radeon Cloud, open **Profile**, and add a template from the competition-provided ROCm image. Attach a persistent PVC so the repository, model cache, and captured evidence survive instance restarts. Launch the instance and use its Jupyter terminal; enable SSH only when it materially helps the recording workflow.

Keep the application and the vLLM model server in the same Radeon instance. Destroy the instance after evidence capture so credits stop accruing.

This is the competition **Local ROCm** profile: PrivateOps and vLLM share a **same-instance loopback** connection. The console can also retain a separate Remote model profile for development, but switching profiles never changes the provenance of captured Radeon evidence.

## 2. Upload the prepared source archive (before the final fork)

Upload `privateops-track2-final.zip` with JupyterLab's file browser into the persistent workspace, open a terminal, and run:

```bash
mkdir -p "$HOME/privateops-agent"
python3 -m zipfile -e privateops-track2-final.zip "$HOME/privateops-agent"
cd "$HOME/privateops-agent"
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/verify_submission.py
```

The prepared archive excludes `.git`, `.venv`, `.env`, `data/state`, runtime logs, credentials, caches, and nested archives. Keep it in the persistent workspace so an instance restart does not remove the source or downloaded model cache.

### Alternative after the final competition fork exists

Set `FORK_URL` to the URL of the account owner's competition fork, then run:

```bash
git clone "$FORK_URL" privateops-agent
cd privateops-agent
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 -m unittest discover -s tests -v
```

Use only the fork created for the final competition pull request. Until that fork exists, use the archive path above; do not clone an unrelated repository.

## 3. Confirm AMD and ROCm

```bash
rocminfo | sed -n '1,100p'
rocm-smi --showproductname --showmeminfo vram
hipcc --version
/opt/venv/bin/python -c "import torch; print(torch.__version__); print(torch.version.hip); print(torch.cuda.get_device_name(0)); print(torch.cuda.is_available())"
```

Stop if the device is not an AMD Radeon GPU or PyTorch cannot see the ROCm device.

## 4. Start the open model locally with vLLM

```bash
chmod +x scripts/*.sh
export PATH="$PWD/.venv/bin:/opt/venv/bin:$PATH"
./scripts/run_rocm_server.sh
```

The shared competition profile is intentionally explicit:

- model: `Qwen/Qwen2.5-7B-Instruct`
- host: `127.0.0.1` only
- port: `8000`
- maximum context: `8192`
- GPU memory utilization: `0.85`

The script checks for both `rocminfo` and `vllm` before launch. If the selected ROCm image does not include vLLM, install the ROCm-compatible vLLM build specified by the image documentation before continuing. Do not replace the loopback host with a hosted inference API.

In another terminal:

```bash
curl --fail http://127.0.0.1:8000/v1/models
```

The endpoint remains on loopback. Shared public APIs do not provide core inference.

## 5. Start PrivateOps in competition mode

```bash
export PATH="$PWD/.venv/bin:/opt/venv/bin:$PATH"
./scripts/run_cloud.sh
```

Verify:

```bash
curl --fail http://127.0.0.1:8765/api/status | python3 -m json.tool
```

The response must show `provider_mode` as `rocm-local`, `provider` as `openai-compatible-rocm`, `agent_framework` as `LangChain Core`, `core_inference_location` as `same-instance loopback`, and `competition_eligible` as `true`. In the inference panel, select **Local ROCm**; the loopback endpoint and Qwen model are prefilled and the API key is optional.

## 6. Capture benchmark evidence

```bash
./scripts/run_rocm_benchmark.sh | tee submission/radeon-benchmark-run-new.json
curl --fail http://127.0.0.1:8765/api/benchmarks/export.csv > submission/radeon-benchmark-runs-new.csv
```

Show the measured result in the UI for the video. Keep new evidence separate from the verified source bundle until it has been reviewed; never edit latency or throughput by hand.

## 7. Expose the UI for review or recording

Use the platform-provided `rc-tunnel` only after confirming the app works on loopback:

```bash
curl --fail http://127.0.0.1:8765/api/health
/var/run/secrets/frp-self-service/install
"$HOME/.local/bin/rc-tunnel" expose --port 8765
```

The tunnel URL is public. PrivateOps tools remain workspace-confined, but do not expose real secrets or personal files during the demo.

## 8. Final evidence checks

```bash
python3 scripts/verify_submission.py
python3 -m unittest discover -s tests -v
python3 scripts/stability_check.py
curl --fail http://127.0.0.1:8765/api/audit/export > submission/radeon-audit-export.json
```

Record the video only after these checks pass.

## 9. Required recording proof

Keep the following in one continuous 3-5 minute recording: the Radeon Cloud instance, `rocminfo`/HIP output, the vLLM models endpoint, the PrivateOps **Local ROCm** selection plus runtime provider/location, the project-readiness multi-turn flow from `example-prompts.md`, permission and audit panels, and the benchmark recorded by `collect_rocm_evidence.py`. The Windows whole-computer collectors are a separate local extension; do not pretend that the Linux cloud instance inspected a Windows laptop. Do not type or overlay performance numbers that were not produced by the script.

## Official references

- Competition repository and submission rules: <https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07/blob/main/README.md>
- Radeon Cloud user guide: <https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07/blob/main/Radeon-Cloud-User%20Guide/README.md>
- vLLM quick start and ROCm installation: <https://docs.vllm.ai/en/latest/getting_started/quickstart/>
- Qwen2.5-7B-Instruct model card and license: <https://huggingface.co/Qwen/Qwen2.5-7B-Instruct>
