# Radeon Credit 1 Findings

Credit 1 established that the designated Radeon Cloud environment can execute
AAHJ image inference locally through ROCm. It also exposed why technical success
must not be confused with editorial acceptance for child-safety content.

## Verified runtime

- AMD Radeon GPU, architecture `gfx1100`
- 51,522,830,336 bytes of reported VRAM
- PyTorch `2.9.1+rocm7.2.1.gitff65f5bc`
- HIP `7.2.53211-e1a6bc5663`
- A real tensor operation completed on `cuda:0`, PyTorch's ROCm device API
- SDXL attention reported the AOTriton backend

The evidence archive is not committed because it contains generated media. Its
SHA-256 is recorded in
`evidence/sdxl/credit-1-evidence-summary.json`.

## Performance observations

The initial one-image smoke run included model download, model load, first-use
compilation, and one inference. It is evidence of end-to-end feasibility, not a
warm throughput benchmark.

The four-image calibration run separated the first candidate from subsequent
warm candidates:

- first candidate: 13.927649 seconds
- subsequent candidates: 1.186100, 1.254271, and 1.187068 seconds
- four-candidate total: 17.555087 seconds

The modular three-panel run completed measured generation in 7.487091 seconds.
These numbers remain observational until Story Studio v2 reruns a sealed
warm-up plus measured benchmark with actual component dtype evidence.

## Editorial failure that changed the design

All four calibration candidates were rejected. Long prompts combined a child,
an adult, a damaged cable, distance, body position, and several negated actions
inside one generated frame. The model produced unsafe or contradictory scenes.
The repository retains only hashes and rejection reasons in
`evidence/sdxl/rejected-calibration-summary.json`; the rejected images
are not submission artwork.

The corrected architectural rule is **constraint-aware scene decomposition**:

1. Generate a character reference.
2. Generate the hazard alone, with no person or hand.
3. Generate the child's safe reaction as a separate reference-conditioned scene.
4. Generate the child telling an adult as another reference-conditioned scene.
5. Require technical, safety, semantic, and continuity acceptance before final
   assembly.

## Dtype evidence correction

The modular experiment passed `dtype=` to `StableDiffusionXLPipeline`, and the
console warned that this argument was ignored. Therefore its report field is an
intention, not proof of FP16 execution.

Story Studio v2 uses `torch_dtype=` when loading the model and records the
actual dtype of the UNet, both text encoders when present, and the VAE. The
VAE remains in its loaded dtype during ordinary inference. Diffusers may
coordinate a decode-time upcast when the selected pipeline requires it; AAHJ
records the observed component dtypes instead of forcing a partial VAE
conversion.
Technical acceptance fails when the requested core dtype is not verified. A
manifest field by itself is never runtime proof.

## Resource shutdown

The Radeon Cloud profile was captured with `No active instance` after the
artifacts had been downloaded. No further GPU run should begin until the next
package, review template, and benchmark acceptance criteria are prepared
locally.
