# UI-5 Operations Proxy Fix — Test Report

```powershell
cd web
npm test
npm run build
```

Manual cloud verification: admin login loads `/monitor/health` and
`/admin/backup` through Vite port 5173, then displays System operations.
