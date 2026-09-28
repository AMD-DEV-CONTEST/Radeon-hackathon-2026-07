# Radeon Cloud session 3 results

## Outcome

The final bounded official-tunnel retry was blocked by the same Radeon Cloud
public DNS failure seen in Session 2c. A fresh
`BrandPilot-Track1-Tunnel` Notebook reached ready state, exposed the expected
AMD Radeon/HIP runtime, installed `rc-tunnel 0.3.0` from the official platform
installer, and passed the authenticated FastAPI loopback startup checks.

The assigned public hostname did not resolve from Windows Python, Windows
PowerShell, or Chrome. One controlled official-tunnel stop/start produced the
same result. The final checks at the five-minute deadline still classified the
failure as `dns_resolution_failed`, so TCP 443, verified TLS, HTTPS,
authentication through the public edge, CORS, and browser generation could not
be attempted.

SDXL was not downloaded or loaded, no generation job was submitted, and no
browser output was produced. The official tunnel and backend were stopped,
port 8000 was confirmed closed with a direct loopback socket test, the
temporary token was unset, and the single instance was destroyed. Radeon Cloud
then displayed **No active instance**. The fallback submission path is active.

## Session record

| Field | Verified result |
|---|---|
| Date | 2026-08-03 |
| Template | `BrandPilot-Track1-Tunnel` |
| Container | AMD OneClick Base ROCm 7.2.1, Python 3.12 |
| Deployment | Notebook/JupyterLab, profile-only, SSH disabled |
| Persistent storage | PVC mounted at the approved persistent workspace |
| Instances launched | Exactly one |
| Starting displayed credits | 5 |
| Final displayed credits | 5 |
| Launch time | 2026-08-03 17:16:58 PKT / 12:16:58 UTC |
| Ready time | 2026-08-03 17:17:55 PKT / 12:17:55 UTC |
| Destroy/no-active confirmation | 2026-08-03 17:31:33 PKT / 12:31:33 UTC |
| Launch-to-destroy duration | 14 minutes 35 seconds |
| Ready-to-destroy duration | 13 minutes 38 seconds |
| Official installer | Present and executable |
| Identity prerequisites | Present |
| `rc-tunnel` | 0.3.0 |
| Controlled tunnel restarts | One |
| Support response | None received before the final retry |

## Runtime verification

| Field | Verified value |
|---|---|
| Python | 3.12.3 |
| PyTorch | 2.9.1+gitff65f5b |
| HIP/ROCm | 7.2.53211-e1a6bc5663 |
| GPU | AMD Radeon Graphics |
| Reported memory | 48.0 GiB |
| Reported compute units | 48 |
| Radeon through `torch.cuda` | Available |
| Diffusers | 0.39.0 |
| Transformers | 4.57.6 |
| Accelerate | 1.13.0 |
| Safetensors | 0.7.0 |
| PyTorch replaced | No |

The pod could not clone GitHub because certificate verification failed. TLS
verification was not disabled. Instead, local `main` commit
`44b131b640fad674548ecec907c7e628d1873399` was archived, hashed, uploaded
through JupyterLab, hashed again, and extracted only after SHA-256 matched.

## DNS gate

Official tunnel activation was confirmed at approximately 17:24:06 PKT. The
prepared Python and PowerShell diagnostics and Chrome produced these sanitized
results:

| Check | Result |
|---|---|
| Public DNS | Failed: hostname did not resolve |
| TCP 443 | Not attempted because DNS failed |
| Certificate validation | Not attempted because DNS failed |
| HTTPS | Not attempted because DNS failed |
| Unauthenticated public 401 | Not reachable |
| Authenticated public status | Not reachable |
| Public CORS | Not reachable |
| Chrome navigation | Failed before service reachability |
| TLS verification disabled | No |
| DNS/hosts/proxy/VPN change | No |

The initial diagnostic failed at 17:24:50 PKT, a repeat failed at 17:26:06,
the one permitted official restart failed at 17:26:50, another observation
failed at 17:27:57, and the final Python/PowerShell checks failed at
17:29:06–17:29:07.

## Generation result

| Item | Result |
|---|---|
| Model loaded | No |
| Model downloaded | No |
| Job submitted | No |
| Duplicate rejection | Not reached |
| 15/15 progress | Not reached |
| Protected output | Not produced |
| Browser rendering | Not reached |
| Human review | Not reached |
| Refresh persistence | Not reached |
| Model-load time | Not available |
| Generation time | Not available |
| Peak allocated/reserved VRAM | Not available |
| Output SHA-256 | Not available |

No browser-to-Radeon generation success is claimed.

## Shutdown and evidence

The stop script reported the official tunnel stopped, loopback backend stopped,
and temporary runtime state cleared. A separate Python socket check confirmed
`127.0.0.1:8000` was closed, and the tunnel process was absent. The temporary
token was unset in the pod and is excluded from repository evidence.

Sanitized evidence is under `evidence/radeon-session-3/`. It includes both DNS
implementations, Chrome classifications, safe runtime/session summaries, and
cropped before/after no-active-instance screenshots. The full hostname, token,
raw terminal images, private logs, account identifiers, and instance identifier
remain outside Git.

## Final boundary

Verified claims remain limited to local application behavior, controlled AMD
Radeon SDXL image-to-image inference from earlier sessions, authenticated
FastAPI loopback inference, official tunnel installation/activation, and the
responsive review-first interface. Full browser-to-Radeon generation,
continuous hosting, production readiness, IP-Adapter preservation, exact
logo/text preservation, and commercial clearance remain unverified.
