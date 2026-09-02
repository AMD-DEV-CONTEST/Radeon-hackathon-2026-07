# Web Development API Proxy — Verification

- Level: S1
- Status: verified

## Verification

- `cd web && npm run build` passes.
- Vite proxy routes same-origin `/api` calls to `127.0.0.1:9000`.
- The FastAPI health endpoint is reachable in the cloud instance.
