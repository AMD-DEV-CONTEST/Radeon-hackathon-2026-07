# Radeon Cloud session 2c plan

## Narrow objective

Session 2c is limited to completing the browser edge that Session 2b could not
finish: one authenticated Chrome-to-official-tunnel-to-loopback-FastAPI SDXL
img2img generation, followed by protected rendering, human review, refresh
recovery, direct evidence retrieval, and shutdown.

Mock remains the default. Experimental Radeon mode remains opt-in and disabled
by default. This session does not add IP-Adapter, ControlNet, LoRA, training,
video, batch generation, multiple models, permanent hosting, or product-identity
preservation claims.

## Why Session 2b was incomplete

The fresh Radeon pod lacked the transient Diffusers runtime. After those pinned
packages were restored, the retry exposed a worker defect: a pipeline whose
first model load failed remained cached. PR #5 fixed the premature cache
assignment and documented the incomplete browser result path. Session 2c adds a
repeatable bootstrap and stronger retry/restart coverage before another launch.

## Prepared controls

- `scripts/bootstrap_radeon_runtime.sh` checks the existing PyTorch/HIP stack,
  exact inference packages, AMD device, memory class, imports, and the repository
  environment checker. It never installs or replaces PyTorch.
- `scripts/start_radeon_demo.sh` binds FastAPI only to `127.0.0.1:8000`, verifies
  authentication and unloaded model state, then uses only official
  `rc-tunnel 0.3.0`.
- `scripts/stop_radeon_demo.sh` stops the official tunnel and only its recorded
  Uvicorn process.
- `scripts/download_remote_evidence.py` retrieves allowlisted evidence directly
  to Windows over verified HTTPS and removes its process token environment
  variable.
- Active persisted jobs from a prior process are marked interrupted on startup;
  completed/failed results and human-review state are preserved.

## Runtime and credit boundary

Exactly one `BrandPilot-Track1-Tunnel` instance may be launched. The target is
25–30 minutes and the hard limit is 38 minutes. Bootstrap gets at most eight
minutes; the tunnel gets at most five. Shutdown begins by minute 32, services
stop by minute 34, destruction occurs by minute 36, and no-active-instance
confirmation is required by minute 38.

No standalone or optional second generation will run. If bootstrap or the
official tunnel remains unavailable, the instance will be destroyed without a
fallback tunnel or second launch.

## Success criteria

1. Fresh-pod dependencies pass the exact bootstrap.
2. Official `rc-tunnel` starts.
3. Chrome authenticates and displays Radeon/HIP status.
4. A project and rights-safe repository example upload succeed.
5. One Luxury, Instagram Square SDXL job progresses genuinely to 15/15.
6. A duplicate submission is rejected while the job is active.
7. The protected output downloads and renders in Chrome with measured metadata.
8. Approved review persists.
9. Refresh restores the completed result and review without resubmitting.
10. Direct Windows evidence retrieval succeeds and output hashes match.
11. Tunnel/backend stop, the instance is destroyed, and no active instance
    remains.

No success will be claimed unless every applicable item passes.

## Failure and escalation

Bootstrap failure after eight minutes, official tunnel failure after five
minutes, missing exact cached model revision, unsafe TLS behavior, or the hard
session deadline ends the attempt. Evidence will be sanitised, services stopped,
and the single instance destroyed.

If official platform provisioning is absent, the existing official AMD
hackathon support route may be updated with harmless technical details only.
Tokens, URLs, account/instance identities, internal hosts, logs, caches, and
private repository data will not be sent.

## Shutdown procedure

1. Complete direct Windows evidence retrieval and hash verification.
2. Stop browser polling and disconnect the frontend.
3. Run `scripts/stop_radeon_demo.sh`.
4. Confirm tunnel stopped and loopback port closed.
5. Unset the token and remove temporary runtime state.
6. Destroy the instance in Radeon Cloud.
7. Confirm no active instance and record the final displayed balance.
