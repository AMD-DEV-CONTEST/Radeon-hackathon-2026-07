# Project Creation in the Web Workbench — Test Report

```powershell
cd web
npm test
npm run build
```

The API-client test verifies a JSON POST to `/api/projects` with the supplied
project identifier. Backend project creation and creator membership remain
covered by existing project API tests.
