# Poster Frontend

Poster is an AI Visual Studio for bands, live performances, talks, and events. It separates GPU-generated key visuals from verified information layers, so titles, dates, venues, original logos, and QR codes remain accurate and publishable.

## Stack

- React 18, Vite 6, and TypeScript
- React Router and Framer Motion
- Plain CSS with design tokens and container-responsive poster composition
- Lucide icons and `html-to-image`
- LocalStorage persistence for projects, language preferences, and task recovery
- Playwright for browser-based end-to-end validation

## Start and verify

From the `frontend` directory:

```bash
npm install
npm run dev
npm run lint
npm run build
```

The development server normally uses `http://127.0.0.1:5173`. The repository launcher can expose the demo at `http://127.0.0.1:4173`.

Configure the backend through an environment variable. Never hard-code a temporary Cloudflare Tunnel URL in source code:

```text
VITE_API_BASE_URL=https://your-stageposter-backend.example.com
```

## Routes

- `/` — immersive brand experience, scene entrances, workflow, and generated gallery
- `/create` — four-step manual workflow plus the real conversational AI assistant
- `/create?project=:id` — resume a persisted project
- `/generate/:id` — real W7900 generation status, partial candidates, candidate selection, and cancellation
- `/result/:id` — adaptive release compositor, editing, quality review, ROCm evidence, lightbox, and PNG export

## Implemented product flow

Two real creation modes reach a downloadable result:

1. **Manual workflow:** form → `POST /api/posters` → live polling → partial candidates → candidate selection → adaptive information composition → PNG.
2. **AI-assisted workflow:** assets → `/api/ai/sessions` → brief completion → plan confirmation → three candidates → selection → VLM final review → adaptive information composition → PNG.

The frontend uses backend `availableActions` as the authority for messaging, plan confirmation, selection, finalization, retry, cancellation, and download. It does not infer actions from guessed states.

### Assets and references

- Separate optional upload slots for people, venues, logos, QR codes, and reference posters
- Local preview, type and size validation, replacement, removal, success, and error states
- Backend upload and processing evidence, including transparent-logo checks
- Reference conditioning evidence (`actuallyUsed`, `usedInStage`, and `reference_control`)
- Hidden internal reference strategy: users see the reference, status, and result—not ControlNet parameters, masks, or template IDs
- Original logos remain deterministic frontend layers and are never redrawn by the image model

### Adaptive release compositor

The backend generates a text-free key visual. The frontend consumes root-level `visualAnalysis` data to:

- protect detected subjects;
- place copy inside prioritized text-safe zones;
- clamp every layout to hard poster boundaries;
- select a visual treatment from palette, texture, contrast, and typography hints;
- reduce and reflow long titles;
- render verified title, tagline, lineup, date, venue, ticket data, logos, and QR code;
- export an exact 1024 × 1536 PNG without another GPU pass.

English poster copy and Chinese poster copy are independent from the site-interface language. Both preferences persist across reloads and routes.

### Competition evidence

The result experience displays backend evidence without inventing unavailable values:

- full generation stage, completed candidate count, elapsed time, and ETA;
- candidate variant, palette, composition, camera, material, seed, attempt, failure, and retry state;
- visual-analysis safe zones, protected subjects, contrast, OCR/model-text evidence, and actual image metadata;
- quality score, requirement match, composition, typography, readability, visual quality, brand consistency, hard failures, issues, suggestions, rounds, and decision;
- GPU model and VRAM, ROCm when provided, ComfyUI workflow version, VLM model, inference/review/total duration, peak VRAM, and token counts;
- capability health and honest unavailable reasons for background removal and identity-similarity metrics.

`completed_with_warnings` is presented as a usable best result with review advice, not as a generic failure. A review decision such as `REGENERATE` is never mislabeled as accepted merely because its numeric score is high.

## Real browser acceptance evidence

The current release was validated in Chromium with four browser scenarios. Evidence is saved outside the repository in `C:\Users\ASUS\Documents\Poster\e2e-evidence`:

1. **AI reference concert:** transparent NATP logo + real reference poster, conversational brief, three W7900 candidates, `reference_control`, candidate selection, two review rounds, 88/100 best result, ROCm evidence, bilingual copy, and PNG export.
2. **Manual talk:** complete manual form, English key visual, three real W7900 candidates, selection, adaptive layout, and PNG export.
3. **Responsive bilingual UI:** 390 px mobile landing/create flow, persisted English interface, and no horizontal overflow; 1280 px desktop navigation was also verified.
4. **Opaque logo degradation:** JPEG logo upload, backend transparency inspection, explicit rectangular-background warning, asset preservation, and no console errors.

The two exported acceptance files were independently verified as 1024 × 1536 PNG images. Browser console checks returned zero errors after the fixes.

## Current backend boundary

- The deployed real GPU workflow is currently `metal-gothic-v1`. The three UI presets are prompt-level visual directions, not three separate model pipelines.
- Background removal and person identity-similarity measurement are not available; the UI reports the backend reason instead of claiming support.
- ROCm version, precision, or peak-VRAM fields display “Not provided” when the backend does not return them.
- The local “AI recommend style” button is still a transparent Mock rule; the conversational assistant is backed by the real API.
- P1 teaser generation is planned and opt-in only. It is not implemented in this release.
- P2 VJ visuals are disabled and marked as a later release.
- No Go API keys, model credentials, or temporary tunnel URLs are embedded in the frontend.
