# Radeon Cloud session 2 evidence

This directory contains a sanitized record of the 2026-07-25 integration run.
The source under test was commit
`1074ba42df197ac78c0aa17fc5a256f943d346a4`.

## Confirmed outcome

- Exactly one `BrandPilot-Track1` instance was used.
- The instance became ready at `2026-07-25T04:59:16.877Z`.
- FastAPI ran on loopback with bearer authentication and experimental ROCm
  mode enabled.
- An unauthenticated status request returned HTTP 401 and an authenticated
  request returned HTTP 200.
- API documentation was unavailable while demo authentication was enabled.
- The model was not loaded before the first generation request.
- One rights-safe project and image were submitted to the real endpoint.
- The job completed at `2026-07-25T05:23:06.741452Z`.
- The API reported step 15/15, output available, and GPU confirmation true.
- The generated result was persisted and an approved human-review decision
  round-tripped through the project API.
- Backend and tunnel processes were stopped before instance destruction.
- Radeon Cloud showed 5 credits and **No active instance** after destruction.

## Runtime facts

- GPU: AMD Radeon Graphics
- GPU memory reported by PyTorch: 51,522,830,336 bytes
- Python: 3.12.3
- PyTorch: 2.9.1+gitff65f5b
- HIP: 7.2.53211-e1a6bc5663
- Diffusers: 0.39.0
- Transformers: 4.57.6
- Accelerate: 1.13.0
- Model: `stabilityai/stable-diffusion-xl-base-1.0`
- Revision: `462165984030d82259a11f4367a4eed129e94a7b`
- Pipeline: `StableDiffusionXLImg2ImgPipeline`

## Important limitation

The full browser-to-cloud acceptance flow was not completed. Radeon Cloud did
not provide `rc-tunnel` in this image. The current public ComfyUI template
documents a Cloudflare Quick Tunnel fallback, but the Cloudflare package
repository advertised signing keys that were not available from its documented
keyring, and its npm wrapper did not materialize the binary. TLS verification
was never disabled. The real integration was therefore validated from
loopback FastAPI through ROCm, while browser connection, protected output
rendering, browser duplicate-submit behavior, and refresh persistence remain
open.

The larger cloud-side sanitized archive was created before shutdown, but the
browser download remained inside Chrome's isolated download store and was not
available to the local workspace. This record includes only facts directly
confirmed through the authenticated API and Radeon Cloud UI.
