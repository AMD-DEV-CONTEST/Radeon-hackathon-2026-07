# UI-5 Admin Operations Visibility Fix — Test Report

```powershell
cd web
npm test
npm run build
```

Expected browser evidence: after administrator login, the operations card is
visible before the materials, tasks, risks, collaboration, and integration
cards. A non-administrator still does not see it.
