# Local API and product-preview fix evidence

Date: 2026-08-04

## Reproduction

With no service listening on port 8000, the Studio status checks to
`GET http://localhost:8000/health` and `GET http://localhost:8000/system-info`
failed with connection refusal. On mock submission, the first request was
`POST http://localhost:8000/projects`; `fetch` rejected with a network
`TypeError`, and the previous catch path displayed the browser's raw
`Failed to fetch` text.

The original preview created its blob URL during render with `useMemo` and
revoked that same URL during React development-mode effect cleanup. React then
reused the revoked memoized URL, leaving a broken image while the card still
said Ready.

## Verified fixes

- The normal API is consistently `http://127.0.0.1:8000`.
- Both local frontend origins pass explicit FastAPI CORS preflight tests.
- Browser network failures display the local-backend startup instruction and
  never expose raw `Failed to fetch` text.
- The status card reaches Connected with the local API and accurately leaves
  Radeon disconnected and ROCm inactive in mock mode.
- A rights-safe PNG was accepted by the loopback upload endpoint, four mock
  results were generated, one result was approved in the browser, and the
  approval survived refresh.
- The production-local build had no console errors or horizontal overflow.
- Product image validation, object-URL replacement/unmount cleanup, clean
  image-error fallback, missing-blob generation blocking, and IndexedDB
  save/load/clear wiring are covered by frontend tests.

## Browser-control boundary

The connected Chrome extension and in-app browser both declined the automated
native file chooser in this session. Therefore a new Studio uploaded-preview
screenshot and a browser-driven IndexedDB restore screenshot could not be
captured. This was a browser-control permission limitation, not an application
or API failure. The real rights-safe file was still uploaded to FastAPI, and
the persisted backend asset, mock result, review action, and refresh state were
verified in the production-local browser UI. No screenshot is presented as
proof of an unperformed browser file-picker step.

## Screenshots

- `screenshots/local-api-connected.png` — production-local Studio status with
  Local FastAPI Connected and Radeon disconnected.
- `screenshots/mock-result-approved-refresh.png` — persisted Astra Travel
  Bottle mock results after an Approved review and browser refresh.

No credentials, private URLs, account identifiers, browser profile data,
client assets, Radeon endpoints, or tokens are present. SHA-256 values are in
`screenshot-hashes.json`.
