# Browser-to-Radeon retry after official DNS resolution

## Entry gate

Do not launch until an official support response or non-billable official
diagnostic satisfies one of the gates in
[radeon-tunnel-dns-support.md](radeon-tunnel-dns-support.md). Record the
resolution safely before spending GPU credits.

The retry is limited to one instance, one generation, and 30 minutes.

## Runbook

1. Confirm the official support resolution and verify no active instance.
2. Launch `BrandPilot-Track1-Tunnel`.
3. Verify the Persistent PVC and run `scripts/bootstrap_radeon_runtime.sh`.
4. Start the authenticated backend on `127.0.0.1:8000`.
5. Start only the official `rc-tunnel`.
6. Before loading the model, run the Windows DNS diagnostics.
7. Require DNS resolution and valid certificate-verified HTTPS.
8. Require unauthenticated public status to return HTTP 401.
9. Require authenticated status and localhost CORS preflight to succeed.
10. Only then start the local frontend and connect through Chrome.
11. Create one project and upload one rights-safe repository image.
12. Submit one SDXL job and verify the active-job duplicate is rejected.
13. Verify genuine stages and diffusion progress reach 15/15.
14. Retrieve and render the protected output with measured metadata.
15. Approve the output, refresh, and confirm result/review persistence.
16. Download allowlisted evidence directly to Windows and verify hashes.
17. Disconnect, stop polling, stop the tunnel/backend, and clear runtime values.
18. Destroy the instance and confirm no active instance.

## Hard stop

If DNS does not resolve within five minutes after official tunnel activation,
save private and sanitized diagnostics, stop the tunnel/backend, destroy the
instance without loading the model, and update the support request. Do not try
a third-party transport or a second instance.
