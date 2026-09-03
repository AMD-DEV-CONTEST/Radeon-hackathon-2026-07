# Rocky tuning workbench — container

A reproducible, hostable image that vendors the **exact verified** ROCm 7.14 stack
(TheRock pip SDK `7.14.0a20260611` + torch `2.13.0a0` + triton + the hyperloom ISA toolkit).
Clone Rocky anywhere with an AMD GPU and get the toolchain that produced the verified
numbers — no host `hipcc` / `ldconfig` archaeology.

## Two decoupled layers
- **Kernel (host):** `amdgpu-dkms` stays on the host. The image ships **no** kernel driver.
- **Userspace (image):** the whole `qat714` env is vendored via **conda-pack**.

At runtime the host `/dev/kfd` + `/dev/dri` are passed in for GPU work (bench only).

## Why conda-pack, not a pip wheelhouse
`7.14.0a20260611` is a **dated nightly** and has already **rotated off TheRock's pip index**
— it can no longer be `pip download`ed (verified: pip resolves only a `0.1.0` placeholder).
So a wheelhouse is impossible. `conda-pack` snapshots the *installed* env into a relocatable
tarball; `conda-unpack` fixes the prefixes at build time. That reproduces the verified stack
**exactly and hermetically** — the right shape for an image you host and others reuse.

## Storage discipline (important on this box)
`rpool` (`/home`) is **~98% full** and hosts the Docker overlay. So **everything** —
the env tarball and podman's image storage — goes on **aipool** (`/aipool/rocky-build/`,
123 G free). The wrapper runs `podman --root /aipool/rocky-build/podman-root`. Do **not**
`docker build` the ROCm image on rpool; it will fill the root pool.

## Quick start
```bash
./container/build-in-container.sh pack     # conda-pack qat714 -> aipool (+ context symlink)
./container/build-in-container.sh image    # build rocky-workbench (podman --root on aipool)
./container/build-in-container.sh llama    # compile the llama.cpp fork inside it (GPU-safe)
```

## Build here, bench on host (the important discipline)
Compiling needs **no** GPU, so `... llama` runs without device passthrough and can't touch
GPU0/GPU1 — safe to run alongside anything.

**Benchmarking t/s must run on the host**, where:
- `ensure_bench_ready()` controls perf-level via host `/sys/class/drm/card*/device/...`, and
- the GPU0 (compute, `04:00.0`) / GPU1 (display+serve, `8a:00.0`) split is verified.

If you ever bench **inside** a passthrough container, run `./build-in-container.sh verify`
first and confirm `rocminfo` **device 0 BDF == `04:00.0`**. Container device enumeration can
renumber; if `HIP_VISIBLE_DEVICES=0` lands on the display card you get a gfx-ring timeout that
**kills Xorg** (the T149 failure). Build-in-container / bench-on-host avoids this entirely.

## Publishing (hosted reuse)
```bash
REGISTRY=<host>/<ns> ./container/build-in-container.sh publish
```
Tag scheme: `rocm<ver>` so the SDK pin is legible in the tag. Record the pushed **digest**
in the repo so `hardware.detect()` -> image selection can pin by digest, not floating tag.
