# UI-5 Vite IPv4 Target Fix — Test Report

```powershell
cd web
npm test
npm run build
```

Cloud verification: an unauthenticated request through Vite to
`/monitor/health` returns FastAPI's `401`, proving the proxy reaches the API.
