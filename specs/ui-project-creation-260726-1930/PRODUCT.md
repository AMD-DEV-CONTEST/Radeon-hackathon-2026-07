# Project Creation in the Web Workbench

## Goal

Allow an authenticated user to create an isolated project from the React
workbench, removing the previous requirement to call the API from a terminal.

## User flow

1. Select **Create project** on the workbench.
2. Enter a lowercase project ID, name, and optional description.
3. Submit once; the API creates the project and adds the creator as project
   administrator.
4. The new project becomes selected and can receive files and task lists.

The backend remains authoritative for identifier validation and authorization.
