# sdcpp-webui

A lightweight Vue + Vite web UI for `stable-diffusion.cpp` servers that expose the native `sdcpp` API.

It is designed for two use cases:

- run as a standalone frontend during local development
- build into a single HTML file that can be embedded into `sd-server`

## What It Does

`sdcpp-webui` talks directly to the native server endpoints:

- `GET /sdcpp/v1/capabilities`
- `POST /sdcpp/v1/img_gen`
- `POST /sdcpp/v1/vid_gen`
- `GET /sdcpp/v1/jobs/:id`
- `POST /sdcpp/v1/jobs/:id/cancel`

The current UI supports:

- image generation and video generation mode switching
- prompt and negative prompt editing
- width, height, seed, batch count, video frames, and fps
- sampler and scheduler selection
- guidance controls, including the video high-noise stage
- conditioning controls such as `clip_skip`, `strength`, `control_strength`, `moe_boundary`, and `vace_strength`
- LoRA selection from server capabilities
- init image, end image, mask image, control image, control frames, and reference images
- VAE tiling controls
- cache controls
- job polling, cancellation, image preview, and video or animated WebP preview

## Requirements

- Node.js `>= 20`
- `pnpm` `>= 10`
- a running `stable-diffusion.cpp` server with the `sdcpp` API enabled

## Development

Install dependencies:

```bash
pnpm install
```

Start the dev server:

```bash
pnpm dev
```

Then open the Vite URL shown in the terminal.

The UI lets you set the backend base URL in the Settings tab.  
If left empty, requests go to the current origin.

## Production Build

Build a production bundle:

```bash
pnpm build
```

This project uses `vite-plugin-singlefile`, so the output is emitted as a self-contained `dist/index.html`.

Preview the production build locally:

```bash
pnpm preview
```

## Embedding Into `sd-server`

If you want to ship the UI inside `stable-diffusion.cpp`, first build the frontend:

```bash
pnpm build
```

Then generate the C header:

```bash
pnpm build:header
```

That produces:

```text
dist/gen_index_html.h
```

The generated header contains the built HTML as a byte array, which can be compiled into the server binary.

## Type Checking

Run:

```bash
pnpm type-check
```

## Project Layout

```text
src/
  components/   reusable UI pieces
  lib/          API, form mapping, image helpers, settings helpers
  App.vue       main application shell
  main.ts       app entry
  styles.css    global styles
scripts/
  build_gen_index_html.js
```

## Notes

- This UI is intentionally thin. Most selectable options come from the server's `capabilities` response.
- It assumes the backend handles CORS correctly if the frontend is served from a different origin.
- It is scoped to the native `sdcpp` API, not the OpenAI-compatible routes and not the A1111-compatible `sdapi` routes.

## License

MIT License
