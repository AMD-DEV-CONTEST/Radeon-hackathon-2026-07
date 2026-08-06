# Live Science Phase 1

Phase 1 uses a memoryless Codex Agent to complete in one run:

```text
Understand → necessary completion → brief planning → code → render → check → fix
```

The input can be a concept, a rough process, or a detailed process. The output is a programmatic
video with in-frame subtitles, the source code, and a standalone SRT subtitle track.

## Directory

```text
phase1/
├── AGENTS.md
├── PHASE1_PROMPT.md
├── REQUEST.example.md
├── run_phase1.sh
├── package.json
├── tools/
│   ├── render_video.mjs
│   ├── export_bridge.mjs
│   ├── validate_outputs.py
│   └── validate_bridge.py
├── examples/
│   ├── concept.md
│   ├── outline.md
│   └── detailed_process.md
└── runs/
```

One run only produces:

```text
runs/<run-id>/
├── REQUEST.md
├── brief.md
├── app/
├── subtitles.srt
├── video.mp4
├── poster.png
├── bridge/
│   ├── manifest.json
│   ├── contact_sheet.png
│   ├── presentation/
│   ├── clean/
│   └── overlay/
└── agent-final.txt
```

The `programmatic` route only requires `bridge/manifest.json`; the image directories and
`contact_sheet.png` are not necessarily generated.

## Environment

Requires:

- Codex CLI
- Node.js 18+
- FFmpeg and ffprobe
- Playwright Chromium

Install the rendering dependencies once under `phase1`:

```bash
npm install
npx playwright install chromium
```

## Usage

Copy and edit the request:

```bash
cp REQUEST.example.md REQUEST.md
./run_phase1.sh REQUEST.md
```

You can also run the examples:

```bash
./run_phase1.sh examples/concept.md karst-concept
./run_phase1.sh examples/outline.md karst-outline
./run_phase1.sh examples/detailed_process.md karst-detailed
```

The second argument is an optional run id. When omitted, a timestamp is used automatically.

The script uses `codex exec --ephemeral --sandbox workspace-write`. The model and reasoning
effort inherit from your Codex configuration by default, so it will not override the model you
have already chosen.

## Design principles

Phase 1 fixes only a "narrow-waist interface":

- the input file;
- `renderFrame(t, options)`;
- the required output files;
- the renderer and validators.

Content scope, number of scenes, duration, number of objects, and the specific animation approach
are decided by the Agent based on teaching needs.

## Bridge route

- `programmatic`: programmatic visuals best serve the teaching, and realistic keyframe assets are
  not required.
- `realizable`: every key moment exports presentation, clean, and overlay assets.
- `hybrid`: only key moments marked realizable export the three asset sets.

Manually re-export and validate the Bridge:

```bash
node tools/export_bridge.mjs \
  --app runs/<run-id>/app/index.html \
  --output runs/<run-id>/bridge

python3 tools/validate_bridge.py runs/<run-id>
```

The Phase 1 Agent is responsible for defining the key teaching moments. The exporter does not
re-select keyframes or design storyboards; it only realizes the moments already defined by the
web page as assets for the downstream image and video realization stages. Subtitles continue to be
managed by `subtitles.srt` and do not enter the overlay.
