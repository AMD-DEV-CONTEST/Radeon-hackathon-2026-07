# Radeon Cloud session 2 results

## Result

Phase 4 application integration is implemented and the real
FastAPI-to-ROCm path completed one authenticated SDXL img2img job on Radeon
Cloud. The full browser-to-cloud flow remains incomplete because no verified
temporary endpoint could be established from the supplied image.

The tested source was commit
`1074ba42df197ac78c0aa17fc5a256f943d346a4`. Exactly one
`BrandPilot-Track1` instance was used for 28 displayed minutes. The account
showed 5 credits before launch and 5 credits plus **No active instance** after
destruction.

## What passed

- Persistent workspace, cache, Python, PyTorch, HIP, and AMD device preflight.
- Source archive SHA-256 verification against the pushed commit.
- Minimal user-space install of Diffusers 0.39.0 and aiofiles 24.1.0 without
  replacing PyTorch.
- FastAPI bound only to `127.0.0.1:8000`.
- Missing bearer token returned 401; the valid in-memory token returned 200.
- API docs returned 404 while demo authentication was active.
- Status confirmed AMD Radeon, HIP, the exact model, and the exact revision.
- Lazy loading was confirmed before generation.
- One project, rights-safe product asset, style, format, and fixed seed were
  accepted by the real experimental endpoint.
- The worker loaded `StableDiffusionXLImg2ImgPipeline` and completed the job at
  step 15/15.
- The terminal API record reported output available and GPU confirmation true.
- The result persisted to the project and an approved human-review decision
  round-tripped through the API.
- Backend and tunnel processes were zero before instance destruction.

The job was created at `2026-07-25T05:18:54.498365Z` and completed at
`2026-07-25T05:23:06.741452Z`.

## Session measurements

| Field | Observed value |
|---|---|
| Session date | 2026-07-25 |
| Ready time | 2026-07-25T04:59:16.877Z |
| Destroy time | Exact timestamp was not retained locally |
| Displayed active duration | 28 minutes |
| Starting / final displayed balance | 5 / 5 credits |
| Backend startup | Passed on `127.0.0.1:8000` |
| Tunnel | Blocked; no verified endpoint established |
| Authentication | 401 unauthenticated, 200 authenticated, docs 404 |
| GPU status | AMD Radeon, HIP available |
| Project creation / upload | Passed |
| Job submission / polling | Passed through loopback API |
| API job duration | 252.243 seconds from `started_at` to `completed_at` |
| Model-load time | Captured in cloud archive; not recovered locally |
| Generation time | Captured in cloud archive; not recovered locally |
| Peak allocated / reserved VRAM | Captured in cloud archive; not recovered locally |
| Output SHA-256 | Captured in cloud archive; not recovered locally |
| Browser rendering | Not run because the tunnel was blocked |
| Human review / persistence | Approved and persisted through the API |

The cloud-side sanitized archive included the detailed timing, memory, output,
hash, logs, and GPU activity. It was created before shutdown, but the Jupyter
download remained in Chrome's isolated download store rather than the local
workspace. Values that were not separately observed are reported as
unavailable instead of being reconstructed.

## What did not pass

The image did not include the requested `rc-tunnel` command. Radeon Cloud's
current public ComfyUI template documents Cloudflare Quick Tunnel as its
fallback. The documented apt repository returned an InRelease signed by keys
that were not available in its documented keyring, while the npm wrapper
installed its launcher but did not materialize the native binary. GitHub
download also failed without a trusted certificate chain. TLS verification was
not disabled and no unrelated tunnel was substituted.

Consequently these acceptance items remain open:

- local browser connection to the cloud backend
- browser-observed live job stages
- browser-observed duplicate-submit blocking
- protected output blob rendering in the browser
- browser review followed by refresh-persistence verification

The same API behavior is covered by local automated tests, and the real
loopback cloud job passed, but those facts are not represented as browser E2E
success.

## Recommendation

Repeat only the browser edge of session 2 after Radeon Cloud supplies
`rc-tunnel` or another platform-approved, certificate-valid loopback tunnel.
Then proceed to IP-Adapter and mask/compositing preservation experiments while
measuring product shape, logo/text distortion, latency, and peak memory.

## Teardown

The temporary bearer token was never printed, committed, or written to an
evidence file. Temporary URL and process files were removed. FastAPI and all
tunnel attempts were stopped, loopback no longer responded, and the single
instance was destroyed. The final Radeon Cloud profile showed 5 credits and
**No active instance**.

See the sanitized summary in
[`evidence/radeon-session-2/`](../evidence/radeon-session-2/).
