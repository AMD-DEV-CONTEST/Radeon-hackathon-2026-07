# Product specification

- Change ID: role-based-workbench-visibility-260802-1900
- Status: implemented

## Problem

Guest users could see write controls such as project creation, uploads, task import, task transition, and report generation. The API rejected protected writes, but the interface did not communicate read-only access clearly.

## Acceptance criteria

- Guests see an explicit read-only status for an assigned project.
- Guests cannot see project creation, file upload, task import, task transition, or report-generation controls.
- Only configured system administrators can create projects in production.
- Existing API authorization remains the enforcement boundary.
