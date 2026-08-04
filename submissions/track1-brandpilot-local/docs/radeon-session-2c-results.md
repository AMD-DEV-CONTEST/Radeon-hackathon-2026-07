# Radeon Cloud session 2c results

## Outcome

Session 2c completed the fresh-pod runtime and loopback preparation but was
blocked at the official public tunnel edge. Official `rc-tunnel 0.3.0` reported
active; its assigned hostname did not resolve from either Chrome or the Windows
HTTPS client. No third-party tunnel or TLS bypass was used. The single instance
was destroyed within the bounded session and the profile confirmed no active
instance.

| Item | Result |
|---|---|
| Date | 2026-07-25 |
| Template | `BrandPilot-Track1-Tunnel` |
| Container | AMD OneClick Base ROCm 7.2.1, Python 3.12 |
| Storage | Persistent PVC at `/workspace` |
| Starting displayed balance | 5 |
| Final displayed balance | 5 |
| Launch time | 16:19:21 PKT |
| Ready time | 16:19:42 PKT |
| Destroy/no-active confirmation | 16:47:07 PKT |
| Launch-to-destroy duration | 27 minutes 46 seconds |
| Ready-to-destroy duration | 27 minutes 25 seconds |
| Official installer and identity | Available |
| Official tunnel | `rc-tunnel 0.3.0`; active locally, public DNS blocked |
| Final service state | Tunnel stopped, backend stopped, port 8000 closed |

## Verified on Radeon Cloud

- Persistent storage and the exact cached model revision were present.
- A local archive of pre-launch commit `28b809bdd72a7976fb7923697dc0e96ef9bd52db`
  was transferred because Git TLS validation failed. Local and remote SHA-256
  matched:
  `83d57e6b6011ace5f77c441077f73917a609cd99d569f694ab0a4006c5b601cc`.
- The official installer completed and `rc-tunnel version` returned `0.3.0`.
- The exact non-Torch runtime was restored into persistent storage. An explicit
  `pydantic-core==2.33.2` pin was required to match Pydantic 2.11.7.
- PyTorch remained `2.9.1+gitff65f5b`; it was not replaced.
- HIP/ROCm remained `7.2.53211-e1a6bc5663`.
- AMD Radeon Graphics and the 48 GiB memory class were detected.
- FastAPI bound only to `127.0.0.1:8000`.
- Unauthenticated loopback status returned 401 and authenticated loopback
  status succeeded.
- Experimental mode, GPU/HIP status, exact model ID and revision, and lazy
  unloaded model state were confirmed before tunnel activation.
- Official tunnel activation and stop both succeeded.

## Browser and public-edge result

The local frontend opened in Chrome and attempted the runtime connection. The
assigned official hostname failed DNS resolution. A separate Windows HTTPS
request reported the same name-resolution failure, including after one
controlled official-tunnel restart. Because the public endpoint was never
reachable, certificate negotiation, public authentication, preflight/CORS, and
protected fetches could not be exercised in this session.

The frontend surfaced a network/secure-transport failure and did not falsely
report connection readiness. The only console observation was an
extension-owned hydration attribute (`cz-shortcut-listen`), not an application
secret or failure.

## Not reached

The following remain **blocked**, not failed application behaviors:

- public authenticated status and CORS
- browser project creation and rights-safe upload
- job submission and duplicate-submit rejection
- model loading, 15-step diffusion progress, and generation
- protected result retrieval and image rendering
- measured model-load, generation, and total-job timing
- measured peak allocated and reserved VRAM
- generated-output SHA-256
- human-review persistence
- refresh restoration
- direct Windows job-evidence retrieval

No fake or placeholder generation values were recorded.

## Fixes retained from the attempt

- The bootstrap now pins and verifies `pydantic-core==2.33.2`.
- The start script invokes the bootstrap through `bash`, allowing a verified
  archive extracted without executable permission metadata to start safely.
- The Uvicorn log is created and restricted before process launch, avoiding a
  harmless permission race.
- Script tests cover both changes.

## Evidence and sanitisation

The only retained screenshot is
`evidence/radeon-session-2c/screenshots/10-no-active-instance.png`. It is cropped
to the no-active-instance message and contains no account, instance, tunnel, or
browser-profile identifier. Its SHA-256 is
`9d57b875344c7e663a56559edf9f1d6dacba67fa85f01c9a1312a0264baee93a`.

No token, tunnel URL, internal hostname, environment dump, raw log, cache,
weight, client asset, or browser state is retained. Temporary runtime values
were unset or removed before shutdown.

## Verified boundary

- **Verified through Chrome:** local frontend loaded; connection attempt
  correctly remained unready when the official hostname did not resolve.
- **Verified through API only:** authenticated and unauthenticated loopback
  behavior.
- **Verified on Radeon Cloud:** runtime bootstrap, Radeon/HIP status, exact
  cached revision, official installer/tunnel lifecycle, and clean shutdown.
- **Tested locally with mocks:** frontend transport, polling, protected blob,
  refresh, duplicate-submit, and worker recovery coverage.
- **Blocked:** the public official-tunnel path and all downstream browser
  generation steps.

Mock remains the default, experimental Radeon mode remains disabled by default,
and this result does not establish production readiness, permanent hosting,
IP-Adapter preservation, logo or packaging-text preservation, or commercial
clearance.
