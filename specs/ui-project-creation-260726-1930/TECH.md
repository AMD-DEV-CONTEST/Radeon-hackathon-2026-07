# Project Creation in the Web Workbench

- Level: S2
- Status: implemented

The UI calls existing `POST /api/projects` through `ApiClient.createProject`.
It does not create directories, write databases, or assign permissions in the
browser. On success it reloads the accessible-project list and selects the
returned project.
