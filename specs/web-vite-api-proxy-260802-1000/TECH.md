# Web Development API Proxy — Technical Notes

- Level: S1
- Status: implemented

## Change

Configure Vite's development server to proxy `/api` to the loopback-only
FastAPI service at `127.0.0.1:9000`. Production artifacts are unchanged.

## Risk and rollback

Low risk. This affects only the Vite development server. Revert the config
block to restore the previous behavior.
