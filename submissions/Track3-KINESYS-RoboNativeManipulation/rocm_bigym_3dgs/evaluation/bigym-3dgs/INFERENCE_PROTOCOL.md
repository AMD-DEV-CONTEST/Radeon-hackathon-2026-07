# External inference HTTP contract v2

The evaluator contains an HTTP client and contract probe, but no model runtime,
checkpoint downloader or inference server. Start a compatible service outside
this branch and set `INFERENCE_BASE_URL` to its base URL.

The previous reference provider implementation is preserved on the
[`interence`](https://github.com/eust-w/amd-bigym-3dgs-rocm/tree/interence)
branch.

## Health

`GET /health` must return HTTP 200 and JSON with:

```json
{
  "status": "ok",
  "protocol_version": 2,
  "policy_identity": {
    "provider": "provider-name",
    "model_id": "model-name-or-path",
    "model_revision": "immutable-revision",
    "adapter_source_sha256": "64-lowercase-hex-characters"
  }
}
```

The four identity fields are required and must remain unchanged for an episode.
A service may add checkpoint identifiers and backend metadata, but the evaluator
does not require provider-specific fields.

## Action request

`POST /process_frame` uses `multipart/form-data` with:

- `text`: task instruction;
- `states`: JSON array containing 16 finite numbers;
- `request_id`: caller-generated unique string;
- three PNG files using the repeated field name `image`, ordered as `head`, `left_wrist`,
  `right_wrist`.

The response must echo `request_id` and contain a finite `10 x 16` action chunk:

```json
{
  "request_id": "episode-000000-chunk-000001",
  "response": [[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]],
  "timing_ms": {
    "image_decode": 0.0,
    "policy_infer": 0.0,
    "total_before_serialize": 0.0,
    "serialization_first_pass": 0.0,
    "server_total_before_final_serialize": 0.0
  }
}
```

The example abbreviates the action horizon; a real response must have exactly
10 rows and 16 finite values per row. Timing values must be finite and
non-negative.

## Probe

After starting the external service, verify one real request before evaluation:

```bash
export INFERENCE_BASE_URL=http://127.0.0.1:7891
./evaluation/bigym-3dgs/bin/probe_inference.sh
```

The probe writes a machine-readable receipt. It proves protocol compatibility,
not BiGym task success or visual quality.

## Two-model evaluation

The simulator can evaluate OpenPI and OpenDM without embedding either runtime.
Start both external providers, set `OPENPI_INFERENCE_BASE_URL` and
`OPENDM_INFERENCE_BASE_URL`, then run:

```bash
./evaluation/bigym-3dgs/bin/run_model_matrix.sh \
  --manifest evaluation/bigym-3dgs/model-matrix.example.json \
  --mode smoke \
  --output-root /workspace/results/two-model-smoke
```

The matrix runner validates and freezes both provider identities, invokes the
same simulator-side evaluator sequentially, and writes
`model-matrix-summary.json`. It contains no model loader, checkpoint downloader
or inference implementation.
