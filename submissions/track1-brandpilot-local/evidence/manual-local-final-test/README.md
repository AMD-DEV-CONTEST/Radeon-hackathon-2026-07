# Manual local final test

Date: 2026-08-05

Branch: `fix-local-api-and-image-preview`

## Local services

- The first launcher attempt exposed a quoting defect in its Python dependency
  probe. The probe was corrected to invoke the virtual-environment interpreter
  directly, and its focused test and PowerShell parse then passed.
- The corrected `scripts/start-local.ps1` started the frontend at
  `http://localhost:3000` and FastAPI at `http://127.0.0.1:8000`.
- `GET /health` returned HTTP 200 with service `brandpilot-backend` in `mock`
  mode. Swagger UI rendered at `/docs`.

## Product image and Studio

- Chrome restored a real, previously approved `s-l400.jpg` draft from IndexedDB.
- The visible preview reported JPEG, 0.02 MB, loaded completely with a natural
  width of 400 pixels, and displayed no broken-image fallback or raw alt text.
- The workspace and Campaign Summary both reported the asset as Ready.
- A reload and a return from the results page restored the same image safely.
- The browser-control file chooser did not become available in either Chrome or
  the in-app browser. Replace and Remove were therefore not exercised because
  removing the only recoverable draft would have made safe restoration
  impossible. No screenshot claims otherwise.

The exact Astra Travel Bottle brief was entered. Before generation, Campaign
Summary showed Astra Travel Bottle, Luxury, two formats, Ready, and Mock.

## Mock generation and review

- The browser completed the local create/upload/generate sequence and navigated
  to project `6c239e13-5d82-4b0f-9317-65b5c21c6aa2`.
- Launcher access logs recorded `POST /projects` as 201, the asset upload as
  201, mock generation as 200, protected asset retrieval as 200, and the
  review submission as 200. All used the local FastAPI service.
- The local project endpoint returned HTTP 200 and four clearly disclosed mock
  results. The page showed the two requested formats and no Radeon claim.
- The Luxury concept was approved. Its approved state and all four results
  remained present after a browser refresh.
- Project campaign data persisted in FastAPI and on the refreshed results page.
- Studio form fields themselves are not persisted: returning to `/studio`
  restored the image but reset Product to Not named and Formats to one. This is
  a confirmed readiness gap against the requested Studio refresh behavior.

## Attached rail and responsive behavior

At requested viewport widths 1440, 1280, 1024, 768, and 520, DOM measurements
confirmed:

- no Campaign Summary/Radeon Connection overlap;
- `position: static` and `transform: none` on Campaign Summary;
- no drag handle and no Reset position action;
- `scrollWidth` equaled `clientWidth`;
- the 768 and 520 layouts stacked the summary before the Radeon card.

Browser zoom shortcuts did not change the controlled Chrome zoom level, so
80%, 125%, and 150% were not independently proven as browser zoom states.
Responsive widths spanning their effective CSS ranges passed, but this is
recorded as a manual-coverage limitation.

## Outage and console

With only FastAPI stopped, the Studio remained usable, the restored preview
stayed complete, and the status changed to Local API unavailable with the safe
instruction to start FastAPI on port 8000. Raw `Failed to fetch` and Radeon
outage wording were absent. Restarting FastAPI returned the card to Local API
online and Connected.

The clean in-app browser reported no warnings or errors. Chrome reported an
extension-injected hydration mismatch (`cz-shortcut-listen`) and a closed
extension message channel; neither appeared in the clean browser. Next.js also
reported its development-only smooth-scroll advisory. No application request,
CORS, preview, or rendering error was observed.

## Screenshots

The `screenshots` directory contains sanitized page-only evidence for the
connected Studio, restored preview, completed brief, mock results, approved
review, review after refresh, responsive rail/mobile stack, and backend outage.
No browser tabs, account data, tokens, tunnel URLs, notifications, or private
filesystem paths are visible.

## Readiness conclusion

PR #15 is not yet fully ready to merge against this test specification because
Studio form/Campaign Summary state does not survive refresh and exact browser
zoom coverage remains unproven. The API, preview restoration, mock generation,
review persistence, responsive rail, and outage behavior otherwise passed.
