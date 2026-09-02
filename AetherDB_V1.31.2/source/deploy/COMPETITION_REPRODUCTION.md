# AetherDB V1.31.2 Competition ROCm Reproduction

This profile is for a Linux competition host with an AMD GPU. It is separate
from Docker Core and does not weaken the ordinary ROCm/CUDA/CPU compatibility
paths.

Authoritative upstream references:

- AMD ROCm container device mapping: <https://rocm.docs.amd.com/projects/install-on-linux/en/docs-7.2.3/how-to/docker.html>
- AMD validated PyTorch image family: <https://rocm.docs.amd.com/projects/install-on-linux/en/develop/install/3rd-party/pytorch-install.html>
- AMD SMI fixed CLI commands: <https://rocm.docs.amd.com/projects/amdsmi/en/latest/how-to/amdsmi-cli-tool.html>
- Pinned base image details: <https://hub.docker.com/r/rocm/pytorch/tags>

## 1. Frozen Image

`deploy/docker/Dockerfile.rocm` uses:

```text
rocm/pytorch:rocm7.2.4_ubuntu22.04_py3.10_pytorch_release_2.9.1
@sha256:9c9592175fece788d6c0b86059012f49b568dc95c98c13879dfdf89c30342559
```

The application image used by Compose must also be supplied as a final
`name@sha256:<64 hex>` reference. A tag, including an application version tag,
is not sufficient evidence.

A reproducible registry workflow is:

```bash
docker buildx build \
  --platform linux/amd64 \
  --file deploy/docker/Dockerfile.rocm \
  --tag REGISTRY/AETHERDB_REPOSITORY:1.31.2-rocm7.2.4 \
  --push .

docker buildx imagetools inspect \
  REGISTRY/AETHERDB_REPOSITORY:1.31.2-rocm7.2.4
```

Record the returned manifest digest in a private copy of
`deploy/docker/.env.competition.example`. Do not put registry credentials,
API keys or private model locations in that file.

## 2. Linux Host Prerequisites

- Linux `amd64` host with a compatible AMD kernel driver.
- `/dev/kfd` and at least one `/dev/dri/renderD*` node.
- Docker Engine and Compose.
- Host `video` and `render` group GIDs.
- Enough private disk space for the approximately 9.5 GB compressed base image,
  the AetherDB image, dependencies and separately installed model packages.

Resolve group IDs on the target host:

```bash
getent group video
getent group render
```

Put only the numeric GIDs in the private competition env file. The Compose
profile maps `/dev/kfd` and `/dev/dri`, adds those groups, drops all Linux
capabilities, sets no-new-privileges, uses the AMD-recommended unconfined
seccomp profile for ROCm memory mapping, and exposes only a dynamic loopback
host port.

## 3. Start

```bash
cp deploy/docker/.env.competition.example deploy/docker/.env.competition

docker compose \
  --env-file deploy/docker/.env.competition \
  --file deploy/docker/docker-compose.competition.yaml \
  up
```

Startup is fail-closed. Before runtime initialization creates local keys, the
container verifies:

1. Linux, `/dev/kfd`, render nodes, `rocminfo`, and `amd-smi`.
2. PyTorch reports a HIP runtime and at least one device through its CUDA API.
3. A real float32 GPU matrix multiplication matches a CPU reference.
4. The final image reference and the pinned ROCm base use full digests.

The bounded report is written to the private runtime volume at:

```text
/var/lib/aetherdb/evidence/rocm/competition-probe.json
```

It stores hashes, versions, device fingerprints, timings and memory counters.
It does not store tool output, API keys, prompts, user data, model weights or
filesystem payloads.

## 4. Model-Level Verification

Platform verification is not model verification. Install the trusted package,
start its isolated Worker, and invoke the existing admin-only Worker probe.
The Resource Scheduler records `VERIFIED_ROCM` only when:

- the package version and manifest digest match;
- the current server-detected device fingerprint matches;
- the Worker effective backend is exactly `rocm_migraphx` or `rocm_pytorch`;
- the model performs its real probe operation and returns valid bounded output.

After the Worker probe, re-run the competition verifier inside the container:

```bash
python /opt/aetherdb/scripts/verify_rocm.py \
  --require-package aetherdb.bge-m3
```

Add another `--require-package` for every model required by the demonstration.
`competition_ready=true` is impossible when no model package was requested or
when a required package lacks current Worker evidence.

## 5. Fail-Closed Rules

The competition profile freezes:

```text
AETHERDB_EXECUTION_MODE=competition
REQUIRE_ROCM=true
ALLOW_SILENT_FALLBACK=false
ALLOW_UNVERIFIED_MODEL=false
```

An admin API request cannot disable the environment competition lock. Explicit
CPU or CUDA model execution is also blocked while `REQUIRE_ROCM=true`.
Ordinary non-competition deployments retain ROCm, CUDA and CPU compatibility.

Never copy the runtime volume, evidence file, local API key file, user database
or model directory into Git or a release image.

## 6. Acceptance Checklist

- Final application image is addressed by a full digest.
- Platform report says `platform_verified=true`.
- Every demonstrated native model has current `worker:` `VERIFIED_ROCM`
  evidence.
- BGE-M3 returns 1024-dimensional normalized multilingual embeddings.
- BGE-VL and image generation are accepted independently if demonstrated.
- No CPU fallback occurs.
- Resource Scheduler leases match actual device and measured VRAM.
- Multiple Workers run together only after sufficient resources and
  coexistence evidence; serial execution is a profile, not an architecture
  limit.
- Dynamic loopback port works while 8000 is unavailable.
- Secret scan, route auth, full tests and staged diff checks pass.

This repository host has no Docker Engine or ROCm device, so it cannot satisfy
the Linux hardware items above. Those results must be collected on the actual
competition host.
