# UI layout polish

## Scope

This pass corrects layout balance, control semantics, responsive behavior, and visual consistency without redesigning BrandPilot Local or changing its backend contracts. Mock remains the default mode, experimental Radeon remains opt-in, and no new inference claim is introduced.

## Corrections

- Four peer cards now use balanced two-by-two grids on desktop and tablet, then one column on mobile.
- The Creative Studio rail includes a live campaign summary. On desktop the summary remains sticky for the full form height while the longer diagnostic cards scroll normally; at tablet and mobile widths the rail returns to document flow.
- Creative style is a single-choice radio group with one default (`Luxury`). Selecting another style replaces it. Mock output formats remain multi-select; experimental mode still narrows formats to one.
- Output-format tiles now contain accessible aspect-ratio previews with visible safe-area composition instead of tiny decorative outlines.
- The Architecture product-flow heading is a full-width section header, and Project status is populated with the existing verified, blocked, and planned facts.
- Hero wrapping, navigation state, card heights, footer alignment, text contrast, color swatches, selection indicators, field grids, mode options, and tertiary button treatment were normalized.

## Responsive QA

Chrome production-build inspection covered CSS viewport widths 1440, 1280, 1024, 768, 520, 430, 390, and 360 pixels. The Overview, Creative Studio, Architecture, results, not-found, and safe error states had no horizontal document overflow. The hero headline uses three lines at the narrow inspected widths. Architecture connectors appear only in the five-column desktop flow and are removed once the layout wraps.

## Interaction QA

- Creative style changed from Luxury to Lifestyle with only Lifestyle remaining selected.
- A second mock output format was selected without clearing the first.
- The live campaign summary updated its product, style, format count, and asset state.
- An existing rights-safe local mock project rendered four equal-height result cards.
- A pending mock concept was approved and the Approved review state remained after refresh.
- Local FastAPI status changed from starting to connected with mock mode active.
- The unknown route rendered the custom 404 and an invalid project rendered the safe `Project not found` alert.
- Chrome reported no console warnings or errors during the final route inspection.

Chrome file upload automation was unavailable because the installed extension did not expose a file chooser. The upload control itself remained visible and accessible; upload validation and generation continue to be covered by the existing local test suite. No browser permission setting was changed for this pass.

## Boundaries

No Radeon Cloud instance or tunnel was launched. No GPU credit was used. No video was recorded. The official AMD submission fork and AMD PR were not modified. The screenshots under `evidence/ui-layout-polish/` contain only the local application and no runtime token, tunnel URL, account information, or private browser data.
