# Radeon session 3 evidence

This directory contains sanitized evidence from the final bounded official
Radeon tunnel retry.

- Exactly one Radeon Cloud instance is allowed.
- Only the official Radeon Cloud `rc-tunnel` may be used.
- Public DNS, TCP 443, verified TLS, HTTPS, authentication, and explicit CORS
  must pass before SDXL is loaded.
- Unresolved DNS has a hard stop five minutes after tunnel activation.
- Browser-to-Radeon success requires a completed protected output rendered in
  Chrome; loopback or tunnel activation alone is not success.
- The full temporary hostname must never be committed.
- Tokens, private URLs, account/instance identifiers, internal hostnames, raw
  diagnostics, and private logs must never be committed.
- Model weights, Hugging Face caches, client assets, and browser-profile data
  are excluded.

Private session material belongs only in
a private directory outside Git. Sanitized screenshots go
in `screenshots/`; any verified, rights-safe generated output goes in
`outputs/` only after direct authenticated retrieval and secret review.
