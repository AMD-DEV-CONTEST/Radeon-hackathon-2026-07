# Architecture

BrandPilot Local separates the user experience, validated persistence, and
inference. Mock mode remains the default. An opt-in experimental namespace can
connect the browser to the validated Radeon pipeline without changing mock
behavior.

```mermaid
flowchart LR
  U["User"] --> F["Next.js frontend<br/>Mock by default"]
  F --> B["FastAPI backend"]
  B --> V["Asset validation"]
  V --> Q["Single-job experimental worker"]
  Q --> P["Validated SDXL img2img"]
  P --> I["AMD Radeon through PyTorch/HIP"]
  I --> O["Campaign output"]
  O --> H["Human review"]
```

The browser never accesses filesystem storage directly. FastAPI validates
media type, file signature, size, and image decoding, then assigns a UUID
filename inside a project-specific directory. JSON persistence sits behind a
service boundary.

The inference contract covers analysis, creative concepts, visual generation,
campaign copy, metrics, and health. Mock mode returns disclosures and no device
data. The experimental worker is disabled unless configured, lazy-loads the
exact validated model, refuses CPU/mock fallback, and records measured metadata.
Temporary tunnel use is demo-only and bearer-authenticated.

Session 2 verified the authenticated FastAPI worker through the real Radeon
pipeline on loopback. Session 2b verified the official `rc-tunnel` browser
edge, TLS, authenticated CORS, and Chrome connection diagnostics. Its browser
generation did not complete; a failed-load pipeline recovery bug was found and
fixed. Session 2c verified fresh-pod runtime restoration, the unchanged
PyTorch/HIP stack, authenticated loopback startup, and official tunnel
activation. The official public hostname did not resolve from the Windows
browser host, so no Session 2c public authentication, CORS, or generation claim
is made.

See [fastapi-rocm-integration.md](fastapi-rocm-integration.md) for the job API,
worker, browser runtime connection, and security boundaries.
See [radeon-session-2-results.md](radeon-session-2-results.md) for the observed
loopback validation boundary and
[radeon-session-2b-results.md](radeon-session-2b-results.md) for the browser
edge result, and [radeon-session-2c-results.md](radeon-session-2c-results.md)
for the final completion attempt.
