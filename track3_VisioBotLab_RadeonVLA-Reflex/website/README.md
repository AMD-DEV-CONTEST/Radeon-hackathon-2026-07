# RadeonVLA-Reflex showcase site

Static, bilingual project site for RadeonVLA-Reflex. It uses Vite and native
TypeScript with no runtime framework, analytics, remote fonts, or CDN dependencies.
Node.js 20.19 or newer is required.

## Run locally

```bash
npm install
npm run dev
```

Open the URL printed by Vite. English is the default language; the header toggle stores
the visitor's choice locally.

## Validate and build

```bash
npm run check
npm run preview -- --host 127.0.0.1
```

The production build is written to `dist/`. `vite.config.ts` uses a relative asset base,
so the same build can be hosted at a repository subpath such as GitHub Pages.

## Content and evidence policy

All bilingual copy, verified metrics, task rows, and external URLs live in
`src/content.ts`. Published content follows these rules:

- only publish numbers present in immutable evaluation artifacts;
- publish policy metrics only after held-out evaluation passes;
- distinguish a target (for example 1,000 demonstrations) from a completed result;
- update Dataset Card, Model Card, technical report, and this site from the same run;
- keep the simulation-only limitation visible.

The project-owned hero concept is bundled from
`src/assets/radeonvla-reflex-hero-v2.png`. System architecture diagrams (EN/ZH) live under
`src/assets/architecture-*.jpg` and mirror `../docs/figures/`. Keep the software and
simulation credits in `../THIRD_PARTY_NOTICES.md` when editing the footer.

Public deploy: GitHub Pages workflow
`.github/workflows/radeonvla-reflex-pages.yml` builds this folder on the submission
branch. Live URL: https://zzw-rgb.github.io/Radeon-hackathon-2026-07/

## Dataset collection previews

Three short H.264 excerpts under `public/videos/` come from completed baseline dataset
episodes 000, 047, and 158. They are world-camera previews of scripted expert data
collection, selected across different appearance-randomization domains. Posters use WebP;
videos use H.264, `yuv420p`, and fast-start for browser compatibility.

Their UI scope is limited to collection-path validation. Held-out policy success,
interruption handling, and recovery performance belong to the policy evaluation suite.

## Policy evaluation video

The evaluation-status panel is replaced after all three policy runs pass:

1. export a 3+ minute narrated H.264 MP4 with `yuv420p` and fast-start;
2. create a lightweight WebP poster and WebVTT captions;
3. host the large MP4 outside the contest Git repository;
4. add a native `<video controls preload="metadata">` element with poster, captions,
   and a direct-download fallback;
5. test playback without autoplay in current Chromium, Firefox, and Safari.

Stitched AV1 dataset videos and the compact H.264 excerpts remain collection artifacts.
The release policy video is a separate H.264 export with captions, synchronized runtime
telemetry, and direct-download fallback.
