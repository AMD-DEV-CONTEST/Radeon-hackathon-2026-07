# Studio draft persistence evidence

Date: 2026-08-05

This evidence records the final local mock-workflow validation for the versioned Creative Studio draft. The test used the requested Astra Travel Bottle brief, Luxury style, Instagram Square and Instagram Portrait formats, and the existing rights-safe IndexedDB product asset.

## Verified behavior

- All requested form values survived a browser refresh.
- Campaign Summary restored `Astra Travel Bottle`, `Luxury`, `2` formats, `Ready` asset, and `Mock` mode.
- All requested form values, summary values, and the product image survived navigation to Overview and back.
- One mock generation created exactly one new backend project and returned four concepts.
- The Luxury concept was approved, and the approval and all four results survived a results-page refresh.
- Returning to Creative Studio after generation restored the full brief, summary, and IndexedDB image.
- Reset workspace cleared the Studio draft, project references, and IndexedDB asset; a subsequent refresh remained clean.
- No `Failed to fetch` message appeared and the tested desktop viewport had no horizontal overflow.

Backend project count was 5 before generation and 6 after generation, results refresh, route return, reset, and reset refresh. No duplicate project was created.

## Screenshot index

1. `screenshots/01-completed-form-before-refresh.png`
2. `screenshots/02-completed-form-after-refresh.png`
3. `screenshots/03-campaign-summary-after-refresh.png`
4. `screenshots/04-form-after-route-return.png`
5. `screenshots/05-generated-results-after-refresh.png`
6. `screenshots/06-approved-result-after-refresh.png`
7. `screenshots/07-reset-workspace-clean-state.png`

SHA-256 values are recorded in `screenshot-hashes.json`.

## Evidence limitations

- The native operating-system file chooser was not directly automated. The validated, recoverable IndexedDB asset was used for the persistence path; existing upload and IndexedDB tests cover the code path.
- Exact browser zoom automation was not available. Responsive viewport QA from the preceding UI validation remains applicable; this pass confirmed the normal desktop view and no horizontal overflow without claiming independently measured zoom levels.
- Chrome injected the `cz-shortcut-listen` body attribute before React hydration. Development mode reported that extension-only attribute mismatch and displayed the development issue badge; no application exception, fetch failure, or layout overflow occurred. The production build passed.
