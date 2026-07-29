# Security hardening notes (Track 2 · PrivateLocalAgent)

## Fixed in this branch

- Path traversal in `read_file` / `parse_image` (basename + `relative_to` containment)
- Workflow / export / skill write paths sanitized (`sanitize_id`, under-base checks)
- Tool / memory / KB observations redacted for secrets & PII
- Broader exfiltration phrase blocklist
- Corrupt `session.json` no longer crashes boot
- HTTP demo defaults to `127.0.0.1`; public bind needs `PLA_ALLOW_PUBLIC=1`
- Optional `PLA_DEMO_TOKEN` (header `X-PLA-Token`) for API POSTs
- Upload size cap (`PLA_MAX_UPLOAD_MB`, default 10)
- Session IDs are full UUID hex; session map locked
- `cloudflared` download prefers verified TLS; insecure only as fallback with warning
- Config overlay restricted to `configs/`
- Workflow steps cannot call `run_skill`

## Tunnel demo (intentionally public)

```bash
export PLA_ALLOW_PUBLIC=1
export PLA_DEMO_TOKEN='choose-a-long-random-token'
python scripts/run_cloudflare_tunnel.py
```

Treat Cloudflare quick tunnels as short-lived demo only.
