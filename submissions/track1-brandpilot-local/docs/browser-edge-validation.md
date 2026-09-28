# Browser edge validation

## Preserved boundaries

- Mock remains the default.
- Experimental ROCm remains opt-in and disabled unless configured.
- Demo routes require bearer authentication.
- FastAPI binds to loopback.
- One GPU job runs at a time.
- Model loading is lazy and the pipeline may be reused.
- CPU and mock fallback are refused.
- The exact SDXL model and revision remain fixed.
- Runtime endpoint and token values remain only in `sessionStorage`.
- The access code stays masked and clears on disconnect.
- Normal local startup does not require Torch, Diffusers, ROCm, or a GPU.

## Connection diagnostics

The runtime panel records safe stages for backend reachability, authentication,
Radeon, ROCm, model/revision verification, and readiness. HTTP authentication,
disabled-mode, GPU, and model failures are classified directly. A browser
transport failure is checked with a no-CORS reachability probe: a reachable
opaque response indicates CORS, an offline browser indicates network
unavailability, and a remaining HTTPS failure is described as a
TLS/certificate or secure-transport failure. No access code, URL, stack trace,
internal path, or tunnel configuration is included in the message.

Authenticated CORS is allowlist-only. The backend permits configured local
origins and the `Authorization`, `Content-Type`, and `Accept` headers with
`GET`, `POST`, `PATCH`, and `OPTIONS`. Wildcard origins are refused in
authenticated demo mode.

## Refresh and polling

The results route reloads the project and current job identifiers from the
current tab session. It polls only while the job is non-terminal. Clearing the
runtime connection dispatches an in-tab event that stops polling immediately.
Refreshing may reuse the current tab's runtime connection but never places the
token into a visible input.

Protected assets and outputs use authenticated fetch. The browser creates an
object URL only for the returned blob and revokes it during cleanup.

During an active job, a validation control submits the same project once more.
The expected response is HTTP 409 from the single-job worker. Acceptance
requires the UI to report the rejection; an accepted duplicate is a failure.

## Browser QA checklist

- Desktop and mobile layout remain readable.
- Console contains no token, internal URL, stack trace, or unhandled exception.
- Preflight permits the local origin and rejects an unknown origin.
- Connection stages reach **Ready for generation**.
- Project creation and upload succeed once.
- Genuine job stages and reported diffusion steps render.
- Duplicate validation reports HTTP 409 behavior.
- Protected output and measured metadata render.
- Review becomes approved, rejected, or needs changes.
- Refresh reloads the same persisted result and review state.
- Disconnect clears runtime values, stops polling, and returns status to mock.

Results belong in [radeon-session-2b-results.md](radeon-session-2b-results.md)
after the instance is destroyed.

## Session 2b observed result

The fresh template, official installer, `rc-tunnel 0.3.0`, TLS,
authentication, CORS, Chrome connection diagnostics, project creation, and
rights-safe upload passed. Two jobs failed before diffusion: first because the
fresh pod lacked Diffusers, then because the failed pipeline object had been
cached. The worker recovery bug is fixed and covered by a regression test.

The hard shutdown checkpoint was reached before a third attempt. Duplicate
protection, 15-step progress, output rendering, review, and result refresh
persistence remain open. The tunnel and backend were stopped and the only
instance was destroyed.

## Session 2c observed result

The fresh-pod bootstrap passed after pinning the Pydantic native runtime
dependency explicitly. PyTorch `2.9.1+gitff65f5b`, HIP/ROCm
`7.2.53211-e1a6bc5663`, the AMD Radeon device, the exact cached SDXL revision,
the authenticated loopback API, and official `rc-tunnel 0.3.0` were verified.
The tunnel reported active, but its assigned public hostname returned a DNS
name-resolution failure from both Chrome and the Windows HTTPS client. One
controlled official-tunnel restart produced the same result.

TLS verification was never disabled, and no fallback tunnel was used. Because
the public edge could not be reached, public authentication and CORS, project
creation, upload, generation, duplicate rejection, output rendering, review,
refresh persistence, and direct job evidence retrieval were not attempted in
Session 2c. The tunnel and loopback API were stopped, port 8000 was closed, the
single instance was destroyed, and the profile confirmed no active instance.
See [radeon-session-2c-results.md](radeon-session-2c-results.md).
