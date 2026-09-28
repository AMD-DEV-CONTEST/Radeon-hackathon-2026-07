# Private official-support message template

Use only in a private official AMD/event ticket, direct moderator message,
Contact the Host form, or official support email. Do not post the full assigned
hostname in a public or broadly visible channel.

## Subject

Radeon Cloud rc-tunnel hostname does not resolve after successful activation

## Message

Hello AMD AI DevMaster Hackathon / Radeon Cloud support team,

I am participating in Track 1 with the project BrandPilot Local.

I created a fresh profile-only Radeon Cloud Notebook using
`BrandPilot-Track1-Tunnel`, the AMD OneClick Base ROCm 7.2.1 image,
Notebook/JupyterLab, Persistent PVC, and SSH disabled.

The official installer and platform identity prerequisites were present.
`rc-tunnel 0.3.0` installed successfully, `expose --port 8000` reported active,
and tunnel status reported the process running. FastAPI bound only to
`127.0.0.1:8000`; local unauthenticated status returned HTTP 401 and local
authenticated status succeeded.

The automatically assigned public hostname did not resolve from either Chrome
or Windows. DNS still failed after one controlled stop/start of the official
tunnel.

The full assigned hostname is:

`<FULL_ASSIGNED_HOSTNAME_TO_SEND_PRIVATELY>`

Session timing:

- Launch: 2026-07-25 16:19:21 PKT
- Ready: 2026-07-25 16:19:42 PKT
- Destroyed/no-active confirmation: 2026-07-25 16:47:07 PKT

TLS certificate verification remained enabled. I did not edit tunnel state,
create platform keys, expose JupyterLab, or use a third-party tunnel.

Could you please verify:

1. Whether the assigned hostname was registered in public DNS.
2. Whether FRPS/domain registration completed successfully.
3. Whether propagation delay or regional DNS could explain the result.
4. Whether a replacement domain should be assigned.
5. Which approved alternative is available when the official hostname does not
   resolve.

I can provide a sanitized diagnostic report and, when available, the full
hostname privately.

Thank you.
