> Chinese version: [README.md](README.md)

# Server-side Model Identity Proof (`model/`)

This section answers the most critical question in the closed loop: **did the online inference service actually load the adapter produced by training?**

## Identity chain

```text
Training side (frozen)                 Service side (runtime)
checkpoint-000119/manifest.json   ==   deployment_manifest.orig.json
  adapter_model.safetensors              adapter_model_sha256
  268,555,264 bytes                      4dcee691…f20bf   <- same hash on both sides
  sha256 4dcee691…f20bf                  + host fingerprint (hostname/boot_id/GPU unique id)
                                         + SHA-256 of the server and startup scripts
```

`served-model-manifest.json` combines this chain and the behavioral evidence into a single file and is the primary artifact for this section.

## Behavioral proof (diff proof)

The same set of 6 probes, with `temperature=0` and the same requested model name, was sent separately to the base-only service and the base+adapter service (captures are under `ab-probe/`):

| Probe | Result | Meaning |
|---|---|---|
| identity / math / tool_call | Byte-for-byte identical | The LoRA did not damage general capabilities or structured tool calling |
| tool_continuation / rdk_domain / exit0_semantics | Clearly different | The adapter weights actually participated in generation |

To reproduce this on the training machine, run `python3 ab-probe/probe.py <api_key_file> out.json` once against each service form and compare the outputs (when comparing `tool_calls`, remove the random call ID).

## Timeline and known pitfall

At 2026-08-04 16:59 UTC, the SFT deployment was created and passed every deployment gate. **At 17:54 UTC, the service was switched back to base-only, and the base service accepted the SFT model name through `--accepted-model-alias`**. From then on, sessions requesting the SFT name were actually answered by the bare base model (the response `model` field truthfully returned the base name, and `/health` reported `adapter_loaded:false`). The SFT service was restored at 2026-08-05 03:41 UTC.

The lesson is recorded in `served-model-manifest.json` under `known_footgun`: only the service's returned `model` field and `/health` indicate what was actually loaded at that moment. The user configures the `rdk-agent` provider, Base URL, model name, and API Key on the Agent side; this model package does not take over the Agent configuration.

## Adapter artifact and public download

The adapter is not stored in Git. See `SHA256SUMS` for the verification ledger.

**Public download**: [ModelScope · ming01/Qwen3-32B-Agentic-SFT-r1-v3](https://modelscope.ai/models/ming01/Qwen3-32B-Agentic-SFT-r1-v3/files) (model)
**Companion dataset**: [ModelScope · ming01/RDK-Agentic-SFT-Sanitized-v1](https://modelscope.ai/datasets/ming01/RDK-Agentic-SFT-Sanitized-v1/files) (sanitized train+validation; the historically held-out Test was released in this repository after evaluation for reproduction)

Judges need only three steps to verify it:

```bash
# 1. Download (with the ModelScope CLI or directly from the web page)
modelscope download ming01/Qwen3-32B-Agentic-SFT-r1-v3 adapter_model.safetensors --local_dir .
# 2. Verify: it must be byte-for-byte identical to the hash in the frozen training manifest
sha256sum adapter_model.safetensors
# Expected:4dcee6914e3f9c61aeb33529208bf7e63f37c4c5ae5e0e37e7f7c6b3bfff20bf  (268,555,264 bytes)
# 3. Compare with the frozen source:examples/qwen3-32b-training/evidence/checkpoint-000119/manifest.json
```

The weight hash exists in four locations: the public ModelScope repository (anonymously rechecked as Public on 2026-08-05), the original checkpoint on the training machine, the local backup at `amd-rl/model-artifacts/checkpoint-000119/`, and the frozen training manifest. In all four locations, `adapter_model.safetensors` is 268,555,264 bytes and is byte-for-byte identical under SHA-256. The public `adapter_config.json` was normalized in two ways for portable distribution: `base_model_name_or_path` was changed from the absolute path on the original training host to `unsloth/Qwen3-32B-bnb-4bit`, `revision` was changed from `null` to the pinned `7f721e74a6a8cc9ee352f7e49303a2c1705f9083`, and a final newline was added; the weight content was not changed.

## Evidence boundary

This section proves **deployment identity** (which weights were loaded) and **behavioral difference** (that the adapter took effect). It does not prove a **quality improvement**. Whether the SFT is better than the base is answered by the Test that was historically held out during evaluation and released afterward for reproduction, together with the Base/SFT A/B. That is the responsibility of the benchmark section.
