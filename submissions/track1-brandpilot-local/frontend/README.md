# BrandPilot frontend

Next.js interface for the default mock campaign flow and the explicit
experimental Radeon workflow.

The Radeon connection panel accepts a temporary backend URL and access code at
runtime. Both remain only in `sessionStorage`; neither is compiled into the
bundle. A successful authenticated status check is required before real mode
can submit one selected style and format. The results view polls genuine job
states, displays diffusion steps only when reported, retrieves protected output
with the bearer header, shows measured metadata, and persists human review.

These behaviors are covered by local tests. The real backend completed on
Radeon Cloud loopback. Session 2b verified the official tunnel, authenticated
CORS, runtime connection diagnostics, project creation, and upload in Chrome.
Real output rendering and review persistence remain pending a completed
browser generation. Session 2c reached an active official tunnel, but its
assigned hostname did not resolve from Chrome or the Windows HTTPS client;
the frontend correctly reported a secure transport/network failure before
authentication.

Run `npm run lint`, `npm run typecheck`, `npm test`, and `npm run build`.

For local development, copy `.env.example` to `.env.local`. The normal mock
API always uses `NEXT_PUBLIC_API_BASE_URL` (default
`http://127.0.0.1:8000`); the temporary Radeon endpoint is consulted only
after Experimental Radeon is explicitly selected and connected. Product-image
bytes are stored in IndexedDB for refresh-safe draft restoration and temporary
preview object URLs are recreated per mounted file.
