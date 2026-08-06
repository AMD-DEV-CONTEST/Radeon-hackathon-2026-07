# Credit 2 Radeon Run Findings

Credit 2 established a reproducible AMD Radeon/ROCm inference and evidence path for
Radeon Story Studio. The uploaded results archive has SHA-256
`6a610023ad1746f537f4d5f4f89007080e4269579dcaa9f95f40edee73bf5908`.

## Technical result

Technical acceptance passed on one `gfx1100` AMD Radeon GPU using PyTorch
`2.9.1+rocm7.2.1`, HIP `7.2.53211`, and the immutable SDXL Turbo revision
`71153311d3dbb46851df1931d3ca6e939de83304`. Eight candidate images were
produced with recorded hashes. The measured candidate phase took 10.504696 seconds,
with a 0.368234-second median and 45.693848 candidates per minute. Peak allocated
GPU memory was 10,451,900,416 bytes.

The initial sealed payload failed because it eagerly converted only the VAE to FP32.
That caused a Half-input/float-bias mismatch. The recovery run removed that premature
conversion, preserved the original and patched hashes, reused the cached model, and
passed output verification. The canonical source now keeps the VAE in its loaded dtype
and lets Diffusers coordinate any decode-time upcast.

## Editorial result

Editorial acceptance failed closed. `notice-hazard.lineage-01` clearly depicts the
damaged cable. The second hazard candidate appears intact. Neither reaction candidate
communicates stopping or stepping back, and neither final candidate includes an adult.
Consequently, no complete single-lineage storyboard is eligible for finalization.

This is expected behavior: technical execution does not override safety, semantic, or
continuity review. The reviewed decisions are recorded in
`evidence/sdxl/credit-2-reviewed-decisions.json`.
