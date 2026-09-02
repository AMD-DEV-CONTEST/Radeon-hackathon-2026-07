# Phase D Minimal Workbench

- Level: S2
- Status: implemented

## Design

- Add project list and project-scoped upload endpoints. Uploads accept only
  supported document formats and write basename-only files below `source/`.
- A task upload is renamed to the approved `tasks.csv` or `tasks.xlsx` name;
  replacing an existing file is rejected.
- Add run-artifact endpoints that resolve only artifact paths recorded on that
  run. Structured evaluation data is stored as a controlled JSON artifact.
- The Gradio page communicates only with the FastAPI API through HTTP.

## Risks and rollback

- Runs are synchronous in this MVP, so a long model response holds the UI
  request until completion.
- Rollback removes the UI and new API routes without changing the controlled
  RAG runner's permitted tool set.

## Verification

- API tests cover project listing, safe upload rejection, artifact download,
  and structured evaluation access.
- UI construction test verifies the workbench can be built without a cloud
  model connection.
