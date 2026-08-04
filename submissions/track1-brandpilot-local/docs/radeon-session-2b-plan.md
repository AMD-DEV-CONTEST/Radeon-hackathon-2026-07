# Radeon Cloud session 2b plan

## Narrow objective

Complete only the missing Chrome browser edge of the disabled-by-default
experimental Radeon workflow. Phase 4 already verified project creation,
upload, one SDXL job, protected output creation, persistence, and review through
authenticated FastAPI on cloud loopback. It did not establish an approved
browser transport.

No model, prompt, worker, or default-mode redesign is planned. This session
does not add IP-Adapter, ControlNet, LoRA, training, video, batching, multiple
models, or permanent hosting.

## Official tunnel gate

Use a new profile-only Notebook template and a fresh pod. Before model loading,
run:

```bash
scripts/check_rc_tunnel_prerequisites.sh \
  --port 8000 \
  --output /workspace/brandpilot-radeon-session-2b/rc-tunnel-prerequisites.json
```

The check records only booleans and harmless version information. The required
platform installer is `/var/run/secrets/frp-self-service/install`. Do not
manufacture identity state, create FRP keys, edit rc-tunnel state, or copy
state from another pod.

When the installer and identity prerequisites are available, run the official
installer and use only `$HOME/.local/bin/rc-tunnel`. There is no Cloudflare,
ngrok, unsigned-binary, TLS-bypass, Jupyter, SSH, or shell exposure fallback.

If a fresh compatible pod still lacks the prerequisites, save the sanitised
check, destroy the instance promptly, and send the prepared question to the
official AMD hackathon support channel. Do not launch another instance in this
task.

Use this message without adding account, instance, endpoint, or environment
details:

> Hi AMD AI DevMaster Hackathon team,
>
> I created a new Radeon Cloud Notebook template using the AMD OneClick Base
> ROCm 7.2.1 image with Persistent PVC. The newly launched Notebook does not
> provide `/var/run/secrets/frp-self-service/install`, and the official
> rc-tunnel identity prerequisites are unavailable.
>
> The Radeon Cloud User Guide states that newly created compatible Notebook
> pods should use this installer for HTTP/WebSocket tunnel access. Could you
> confirm whether rc-tunnel provisioning is enabled for my account/template or
> provide the currently approved method for exposing a loopback FastAPI service
> during hackathon testing?
>
> I have not disabled TLS verification, created platform keys, exposed
> JupyterLab, or used an unapproved third-party tunnel.
>
> Project: BrandPilot Local
> Track: Track 1 — Multimodal AI

Record only the official channel name and UTC timestamp. Do not keep a GPU
instance active while waiting for a reply.

## Evidence retrieval

Critical evidence is downloaded directly from the authenticated API to Windows,
not through Chrome's download store:

```powershell
$env:BRANDPILOT_DEMO_TOKEN = '<temporary value held only in this shell>'
python scripts\download_remote_evidence.py `
  --base-url '<temporary HTTPS endpoint>' `
  --job-id '<completed job UUID>' `
  --output-dir evidence\radeon-session-2b
```

The downloader verifies TLS, reads the token only from the environment,
allowlists metadata, uses fixed safe filenames, downloads the protected image,
calculates local SHA-256 hashes, and removes the token environment value in its
own process. The invoking shell must immediately run:

```powershell
Remove-Item Env:BRANDPILOT_DEMO_TOKEN
```

It never downloads raw logs, environment dumps, caches, weights, tunnel state,
account data, or internal paths.

## Credit and shutdown controls

- Use exactly one `BrandPilot-Track1-Tunnel` instance.
- Intended maximum: 40 minutes; target: 25–35 minutes.
- Spend no more than eight minutes on tunnel provisioning.
- Stop immediately when official prerequisites remain unavailable.
- Begin shutdown preparation at minute 32.
- Stop rc-tunnel by minute 35.
- Destroy by minute 38.
- Verify no active instance by minute 40.
- Do not document while the instance remains active.

## Success criteria

1. Official rc-tunnel installs or is already available.
2. An unauthenticated tunnel request returns 401.
3. Authenticated status succeeds with the exact GPU/model/revision.
4. Local Chrome connects through the runtime panel.
5. The browser creates a project and uploads the rights-safe example.
6. One real generation completes with genuine stages and step 15/15.
7. The browser confirms duplicate submission is rejected.
8. The protected output and measured metadata display in Chrome.
9. A human-review action persists across refresh.
10. Evidence downloads directly into the Windows repository and hashes verify.
11. Frontend polling disconnects, rc-tunnel and FastAPI stop, and the temporary
    token is removed.
12. The instance is destroyed and Radeon Cloud shows no active instance.

## Failure criteria

The session is blocked when the new pod lacks the official installer or
identity, the official tunnel cannot start within eight minutes, TLS cannot be
verified, authenticated CORS cannot be made explicit, or safe shutdown would
be threatened. A loopback-only API result does not count as browser E2E.
