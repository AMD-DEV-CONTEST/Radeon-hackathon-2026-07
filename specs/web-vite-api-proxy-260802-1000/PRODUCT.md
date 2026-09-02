# Web Development API Proxy

## Goal

Make the development workbench reach the local FastAPI service through the
same-origin `/api` path when accessed through an SSH-forwarded Vite server.

## Acceptance criteria

- A browser opened at the Vite workbench can load authenticated project data.
- API requests remain same-origin to the browser and are proxied only inside
  the cloud instance to `127.0.0.1:9000`.
