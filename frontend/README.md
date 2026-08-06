# ClaimCourt frontend

This React client talks only to the ClaimCourt local API. Document contents and
model requests stay on the selected machine; no Gemini key or hosted model is
required.

## Run locally

Prerequisites: Node.js and the Python runtime used by the repository.

1. Install dependencies: `npm install`
2. Start the local API from the repository root: `python api.py --port 8503`
3. In a second terminal start Vite: `npm run dev`
4. Open the URL printed by Vite (normally `http://127.0.0.1:5173`).

The Vite development server proxies `/api` to `http://127.0.0.1:8503`.
For a single-process production preview, run `npm run build` and then
`npm run start`.
