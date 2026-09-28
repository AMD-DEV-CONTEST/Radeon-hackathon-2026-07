# Official Radeon tunnel DNS support

## Status

The final bounded browser-to-Radeon retry reproduced the public DNS failure
after successful official `rc-tunnel` activation. The fallback submission path
is active, and no additional paid Radeon Cloud instance may be launched for
this submission merely to see whether the hostname works now.

A new bounded session may begin only after at least one of these conditions:

1. AMD support confirms the DNS issue is resolved.
2. AMD support assigns a working replacement hostname.
3. AMD support provides an approved alternative public transport.
4. AMD updates the official Radeon Cloud tunnel documentation.
5. A non-billable official diagnostic confirms public DNS provisioning works.

Cloudflare Quick Tunnels, ngrok, third-party FRP clients, manual FRPS
configuration, edited `rc-tunnel` state, manufactured platform identity, and
TLS bypasses remain prohibited.

## Sanitized support packet

| Field | Value |
|---|---|
| Project | BrandPilot Local |
| Hackathon | AMD AI DevMaster Hackathon |
| Track | Track 1 — Multimodal AI |
| Template | `BrandPilot-Track1-Tunnel` |
| Container | AMD OneClick Base ROCm 7.2.1, Python 3.12 |
| Deployment | Notebook/JupyterLab |
| Storage | Persistent PVC |
| Visibility | Profile-only |
| SSH | Disabled |

Verified official-tunnel facts:

- The official installer was present and executable.
- Platform identity prerequisites were present.
- `rc-tunnel 0.3.0` installed successfully.
- The tunnel reported active and its process reported running.
- FastAPI bound only to `127.0.0.1:8000`.
- Local unauthenticated status returned HTTP 401.
- Local authenticated status succeeded.
- The assigned public hostname failed DNS resolution in Chrome and Windows.
- One controlled official-tunnel stop/start reproduced the DNS failure.
- TLS certificate verification remained enabled.
- No third-party tunnel was used.
- The instance was destroyed and no active instance remained.

Session timing:

- Launch: 2026-07-25 16:19:21 PKT
- Ready: 2026-07-25 16:19:42 PKT
- Destroyed/no-active confirmation: 2026-07-25 16:47:07 PKT
- Launch-to-destroy duration: approximately 27 minutes 46 seconds

The full hostname must never be added to this document. A future private
support packet may use:

`<FULL_ASSIGNED_HOSTNAME_TO_SEND_PRIVATELY>`

## Support action

| Field | Value |
|---|---|
| Sent | 2026-07-25 18:42:35 PKT |
| Official channel | AMD AI DevMaster Hackathon Luma — Contact the Host |
| Visibility | Private host message |
| Full hostname shared | No; the ephemeral value was deliberately not retained after shutdown |
| Safe reference | Luma confirmed: “Your message is on its way to the host!” |
| Status | Awaiting response |
| Immediate response | Submission confirmation only |

The private request asks the host to correlate the authenticated Session 2c
timing or provide a non-billable approved way to retrieve or replace the
hostname. It also asks whether public DNS/FRPS registration completed, whether
propagation or regional DNS was involved, and which approved alternative is
available.

Private correspondence is stored outside the repository. Do not copy full
message threads, private ticket links, account data, hostnames, tokens, or
authentication material into Git.

## Final bounded retry — Session 3

No support response arrived before 2026-08-03. One final authorized instance
used the same compatible profile-only Notebook template with Persistent PVC.
The official installer and identity prerequisites were present, `rc-tunnel
0.3.0` installed and activated, and authenticated FastAPI passed on loopback.

The first Windows Python and PowerShell checks and Chrome all failed public DNS.
One controlled official tunnel stop/start was performed. The restarted endpoint
also failed DNS. The final checks at 17:29:06–17:29:07 PKT, five minutes after
activation, remained `dns_resolution_failed`; therefore TCP 443, TLS, HTTPS,
public authentication, CORS, model loading, and generation were not attempted.

Session 3 timing:

- Launch: 2026-08-03 17:16:58 PKT
- Ready: 2026-08-03 17:17:55 PKT
- Destroyed/no-active confirmation: 2026-08-03 17:31:33 PKT
- Launch-to-destroy duration: 14 minutes 35 seconds
- Starting/final displayed balance: 5 credits / 5 credits

The official tunnel and backend stopped, port 8000 was confirmed closed, the
single instance was destroyed, and no active instance remained. No model was
downloaded or loaded, no generation ran, no unofficial tunnel was used, and no
TLS or DNS bypass was attempted. The full hostname remains outside Git.
