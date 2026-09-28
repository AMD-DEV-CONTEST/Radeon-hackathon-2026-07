# Radeon Cloud session 3 plan

## Objective and boundary

Session 3 is the final bounded attempt to complete BrandPilot Local's missing
browser-to-Radeon edge. It may launch exactly one
`BrandPilot-Track1-Tunnel` Notebook instance and may use only the official
Radeon Cloud `rc-tunnel` transport.

The success path is local Chrome to the official verified HTTPS endpoint,
authenticated loopback FastAPI, one serialized SDXL image-to-image job on AMD
Radeon through ROCm, protected result rendering, human approval, and refresh
persistence. A completed browser-rendered output is required before the
browser E2E may be called verified.

The fallback path activates immediately when the official hostname still does
not pass DNS, TCP 443, verified TLS, HTTPS, authentication, and explicit CORS.
Cloudflare, ngrok, LocalTunnel, third-party FRP, reverse SSH, VPN/DNS/hosts-file
changes, and TLS bypasses are prohibited.

## Pre-launch gate

Before cloud launch:

- synchronize clean `main` and create `final-radeon-e2e-retry`;
- pass frontend lint, type checking, 14 tests, and production build;
- pass 68 backend, inference, and script tests plus Python compilation;
- pass shell syntax checks for bootstrap, start, and stop scripts;
- verify mock is default and experimental Radeon is opt-in;
- verify connection values remain only in `sessionStorage`;
- verify authentication, loopback binding, one-job serialization, safe failed
  model-load recovery, interrupted-job recovery, and result/review persistence;
- create the repository evidence structure and the private session directory
  outside Git.

## Single-instance controls

- Confirm Radeon Cloud shows no active instance before launch.
- Launch only `BrandPilot-Track1-Tunnel`.
- Record local and UTC launch, ready, and destruction timestamps plus displayed
  starting and final credit balances.
- Target 25–30 minutes and never exceed 38 minutes.
- Do not launch a second instance under any outcome.
- Stop the backend and tunnel, close port 8000, destroy the instance, and
  verify no active instance before documentation continues.

## Runtime and official tunnel gate

The fresh pod must retain its existing ROCm PyTorch. Bootstrap may install only
the pinned missing non-Torch packages. The model remains pinned to
`stabilityai/stable-diffusion-xl-base-1.0` at revision
`462165984030d82259a11f4367a4eed129e94a7b`, and must not load before the DNS
gate passes.

FastAPI binds only to `127.0.0.1:8000`. Local unauthenticated experimental
status must return 401 and authenticated status must report AMD Radeon, HIP,
the exact model/revision, and lazy unloaded state.

The platform installer and identity prerequisites must exist without being
manufactured. Use `rc-tunnel 0.3.0` to expose only port 8000. Store the full
temporary hostname, token, raw diagnostics, and private logs only under
a private directory outside the repository.

## Five-minute DNS gate

Immediately after tunnel activation, diagnose the private hostname from
Windows and Chrome. Within no more than five minutes, all of the following
must pass:

1. Public DNS resolves.
2. TCP port 443 is reachable.
3. TLS certificate validation succeeds.
4. HTTPS reaches FastAPI.
5. An unauthenticated request returns 401.
6. An authenticated status request succeeds.
7. CORS explicitly permits the local frontend origin.

At most one controlled official tunnel stop/start is permitted. During this
gate SDXL must remain unloaded and no job may be submitted. If any item remains
blocked, stop and destroy the instance immediately and activate the honest
submission fallback.

## Success criteria

When the DNS gate passes, create one project from a rights-safe non-client
image and submit one Luxury, 768 × 768 job with 15 steps, strength 0.35,
guidance 6.5, and seed 20260725. Verify genuine stages, 15/15 progress, one
duplicate rejection, protected rendering, measured metadata, human approval,
refresh persistence, direct sanitized evidence retrieval, disconnect cleanup,
and final destruction.

## Failure criteria

Public DNS or verified HTTPS failing after five minutes is a platform blocker.
No model load, generation, output, timing, VRAM, or browser-E2E success may be
claimed. Preserve only sanitized reports in Git, keep private data outside the
repository, document that the official tunnel was used without workarounds,
destroy the instance, and prepare the fallback submission package.
