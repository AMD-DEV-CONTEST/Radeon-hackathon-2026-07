# PolicyCut — Internal Contracts (single source of truth)

All implementation agents MUST follow this document exactly. Python 3.10+. All code, comments, UI text in **English**.

## 0. Global principles

- FastAPI backend, vanilla HTML/CSS/JS frontend, no build step, no database, no Redis.
- All persistence: atomic JSON (`write tmp → os.replace`) under `data/projects/<project_id>/`.
- Heavy ML deps (torch, transformers, sam2, presidio) are imported **lazily inside functions** and each wrapped in try/except so the app + unit tests run on machines without them (CPU/macOS dev). A missing model = a recorded "fallback", never a crash.
- Device selection: `policycut.core.device.get_device()` returns `"cuda"` if `torch.cuda.is_available()` else `"cpu"`. Env var `POLICYCUT_REQUIRE_ROCM=1` (or `--require-rocm`) makes core model stages raise `RuntimeError` instead of falling back to CPU.
- All timestamps in media domain: **float seconds**. All API/JSON times: float seconds. Frame index = `round(t * fps)`.
- IDs: `p_` + 10 hex chars for projects, `e_` + 10 hex for events, `j_` + 10 hex for jobs, `t_` + 10 hex for tracks. Use `uuid.uuid4().hex[:10]`.
- Logging: standard `logging` module, logger name = module `__name__`. Pipeline stage logs also appended to `data/projects/<id>/logs/pipeline.jsonl` (one JSON per line: `{"ts": iso, "stage": str, "level": str, "msg": str, "extra": {}}`).
- No PII plaintext in `audit.json`, no absolute host paths in any export artifact.

## 1. Directory layout (repo)

```
policycut/                      # project root (this folder)
├── README.md
├── LICENSE                     # MIT
├── THIRD_PARTY_NOTICES.md
├── pyproject.toml
├── requirements-rocm.txt
├── run.py                      # uvicorn entry: python run.py [--host 0.0.0.0 --port 8000 --require-rocm]
├── policycut/
│   ├── __init__.py             # __version__ = "1.0.0"
│   ├── config.py               # Settings dataclass (see §2)
│   ├── api/                    # FastAPI app + routers
│   │   ├── __init__.py
│   │   ├── app.py              # create_app() -> FastAPI; mounts /api/v1 routers + static web
│   │   ├── projects.py
│   │   ├── jobs.py
│   │   ├── events.py
│   │   ├── artifacts.py
│   │   └── system.py
│   ├── core/
│   │   ├── __init__.py
│   │   ├── device.py           # get_device(), device_info() dict, require_rocm check, vram_peak helpers
│   │   ├── ids.py              # new_id(prefix)
│   │   ├── storage.py          # ProjectStore (see §5)
│   │   ├── models.py           # Pydantic models: Project, RedactionEvent, Job, ... (see §4)
│   │   └── queue.py            # JobQueue: single worker thread; submit(job_fn) (see §6)
│   ├── policy/
│   │   ├── __init__.py
│   │   ├── schema.py           # PolicySpec pydantic models (see §3)
│   │   ├── parser.py           # parse_policy(text) -> PolicySpec  (Qwen w/ retry → keyword fallback)
│   │   └── keyword_parser.py   # deterministic fallback parser incl. negation handling
│   ├── vision/
│   │   ├── __init__.py
│   │   ├── detector.py         # GroundingDINO + YuNet keyframe detection -> list[Detection]
│   │   ├── tracker.py          # build_tracks(detections, video_info, policy) -> list[Track]; SAM2 optional, box-interpolation fallback
│   │   ├── sam2_tracker.py     # SAM2 video propagation wrapper (optional import)
│   │   └── masks.py            # mask post-processing: fill holes, dilate, feather, union with padded box
│   ├── audio/
│   │   ├── __init__.py
│   │   ├── transcribe.py       # whisper (transformers pipeline) -> Transcript with word timestamps
│   │   ├── pii.py              # detect_pii(transcript, policy) -> list[AudioEventDraft]; regex + spoken-form + optional presidio
│   │   └── spoken.py           # normalization of spoken digits/emails ("zero one two"→"012", "dot"/"at")
│   ├── media/
│   │   ├── __init__.py
│   │   ├── probe.py            # ffprobe wrapper -> MediaInfo
│   │   ├── normalize.py        # normalize_video(): CFR, ≤1080p, proxy ≤1280, thumbnail, asr wav
│   │   └── render.py           # final render: visual effects on frames (OpenCV) + audio effects + mux + srt
│   ├── review/
│   │   ├── __init__.py
│   │   └── overlay.py          # build review overlay MP4 (boxes drawn, no redaction)
│   ├── audit/
│   │   ├── __init__.py
│   │   └── builder.py          # build audit.json + zip
│   ├── pipeline.py             # run_analysis(project_id, store, progress_cb), run_render(...)
│   └── web/
│       ├── __init__.py
│       └── static/
│           ├── index.html      # Projects home
│           ├── project.html    # New Project / upload+policy  (?id=)
│           ├── processing.html # progress (?id=&job=)
│           ├── review.html     # Review Workspace (?id=)
│           ├── export.html     # Export page (?id=)
│           ├── css/app.css
│           └── js/{api.js, index.js, project.js, processing.js, review.js, export.js}
├── schemas/{policy.schema.json, events.schema.json, audit.schema.json}
├── scripts/{download_models.py, preflight.py, benchmark.py, make_fixtures.py}
├── tests/...
└── docs/...
```

## 2. Config (`policycut/config.py`)

```python
@dataclass
class Settings:
    data_dir: Path            # default Path("data"); env POLICYCUT_DATA_DIR
    require_rocm: bool        # env POLICYCUT_REQUIRE_ROCM == "1"
    max_video_seconds: float = 60.0
    max_height: int = 1080
    proxy_long_edge: int = 1280
    dino_model: str = "IDEA-Research/grounding-dino-tiny"
    qwen_model: str = "Qwen/Qwen3-4B-Instruct-2507"
    whisper_model: str = "openai/whisper-large-v3-turbo"
    sam2_model: str = "facebook/sam2.1-hiera-small"
    dino_interval_s: float = 0.5
    yunet_interval_s: float = 0.25
    box_threshold: float = 0.25
    text_threshold: float = 0.20
    nms_iou: float = 0.50
settings = Settings()  # module-level singleton, get_settings() returns it
```

## 3. PolicySpec (policy/schema.py) — matches schemas/policy.schema.json

```python
VisualCategory = Literal["face", "license_plate", "id_document", "screen"]
AudioCategory  = Literal["phone", "email", "address"]
VisualActionType = Literal["blur", "pixelate", "solid"]
AudioActionType  = Literal["mute", "beep"]

class VisualAction(BaseModel):
    type: VisualActionType = "pixelate"
    strength: int = Field(65, ge=1, le=100)

class AudioAction(BaseModel):
    type: AudioActionType = "mute"

class VisualTarget(BaseModel):
    category: VisualCategory
    prompts: list[str]                  # detection phrases for DINO
    action: VisualAction

class AudioTarget(BaseModel):
    category: AudioCategory
    action: AudioAction
    padding_before_ms: int = 150
    padding_after_ms: int = 250

class PolicySpec(BaseModel):
    schema_version: str = "1.0"
    language: str = "en"
    visual_targets: list[VisualTarget]
    audio_targets: list[AudioTarget]
    unsupported_terms: list[str] = []
    review_required: bool = True
```

Default DINO prompts per category:
- face: ["human face"]  (YuNet also always runs when face is targeted)
- license_plate: ["license plate", "vehicle registration plate"]
- id_document: ["identity card", "passport", "driver's license"]
- screen: ["computer monitor", "laptop screen", "smartphone screen", "tablet screen"]

`parse_policy(text: str, use_llm: bool = True) -> tuple[PolicySpec, str]` returns (spec, source) where source ∈ {"llm", "llm_repaired", "keyword_fallback"}. Keyword parser MUST handle negation: "do not blur screens", "don't pixelate faces", "except faces" → remove that target. Unknown nouns like "tattoos" → `unsupported_terms`.

## 4. Core models (core/models.py) — Pydantic

```python
ProjectStatus = Literal["draft","analyzing","review_ready","rendering","complete","error"]

class MediaInfo(BaseModel):
    filename: str; duration_s: float; width: int; height: int; fps: float
    codec: str; has_audio: bool; audio_codec: str | None = None
    size_bytes: int; rotation: int = 0

class Project(BaseModel):
    id: str; name: str; status: ProjectStatus = "draft"
    created_at: str; updated_at: str          # ISO 8601 UTC
    media: MediaInfo | None = None
    policy_text: str = ""
    revision: int = 0                          # bumped on every event mutation
    exports_stale: bool = False
    error: str | None = None

EventKind   = Literal["visual","audio"]
EventSource = Literal["auto","manual"]
EventStatus = Literal["pending","confirmed","ignored"]

class BoxKeyframe(BaseModel):
    t: float                                   # seconds
    x: float; y: float; w: float; h: float     # normalized 0..1 relative to output video

class RedactionEvent(BaseModel):
    id: str
    kind: EventKind
    category: str                              # VisualCategory | AudioCategory | "manual"
    status: EventStatus = "pending"
    source: EventSource = "auto"
    start_s: float; end_s: float
    action: dict                               # {"type": "pixelate","strength":65} or {"type":"beep"}
    confidence: float = 1.0
    track_id: str | None = None                # visual only; masks stored in analysis/masks/<track_id>.npz
    boxes: list[BoxKeyframe] = []              # visual: per-keyframe boxes (interpolate linearly between)
    text_preview: str = ""                     # audio only: REDACTED-safe label like "PHONE (…last 2 digits hidden)" — never raw PII
    warnings: list[str] = []                   # e.g. "low_confidence","rect_fallback","segment_level_timestamps"
    manual_fixed_region: bool = False

class Job(BaseModel):
    id: str; project_id: str
    type: Literal["analysis","render"]
    status: Literal["queued","running","done","error","cancelled","server_restarted"]
    stage: str = ""                            # see §7 stages
    progress: float = 0.0                      # 0..1
    message: str = ""
    created_at: str; started_at: str | None = None; finished_at: str | None = None
    error: str | None = None
    metrics: dict = {}                         # stage -> {"wall_s":..,"peak_vram_mb":..,"frames":..,"fps":..,"precision":..}
```

## 5. Storage (core/storage.py)

```python
class ProjectStore:
    def __init__(self, data_dir: Path): ...
    # all writes atomic: tmp file + os.replace; all reads tolerate missing files
    def list_projects(self) -> list[Project]
    def create_project(self, name: str) -> Project
    def get_project(self, pid) -> Project | None
    def save_project(self, project) -> None
    def delete_project(self, pid) -> None                    # shutil.rmtree
    def project_dir(self, pid) -> Path
    def path(self, pid, *parts) -> Path                      # project_dir/parts, mkdir parents of file
    def load_events(self, pid) -> list[RedactionEvent]
    def save_events(self, pid, events) -> None
    def load_policy(self, pid) -> PolicySpec | None
    def save_policy(self, pid, spec) -> None
    def load_jobs(self, pid) -> list[Job]                    # jobs.json in project dir
    def save_job(self, job) -> None                          # also maintains data/jobs_index.json {job_id: project_id}
    def get_job(self, job_id) -> Job | None
    def append_review_history(self, pid, entry: dict) -> None  # review_history.jsonl
```

On-disk per project: `project.json`, `policy.json`, `events.json`, `jobs.json`,
`review_history.jsonl`, `source/original.<ext>`, `working/{normalized.mp4, asr.wav, review_overlay.mp4, thumbnail.jpg}`,
`analysis/{transcript.private.json, audio_events.json, tracks.json, masks/*.npz}`,
`exports/{redacted.mp4, redacted.srt, audit.json, policycut_export.zip}`, `logs/pipeline.jsonl`.

## 6. Job queue (core/queue.py)

Single global `JobQueue` (created in api/app.py, stored on `app.state`). One worker thread, `queue.Queue`. `submit(job: Job, fn: Callable[[Job, ProgressCallback], None])`. Progress callback signature: `cb(stage: str, progress: float, message: str = "", metrics: dict | None = None)` — updates job (throttled save ≥0.3s apart) and pushes SSE. Cancellation: `queue.cancel(job_id)` sets a `threading.Event`; pipeline checks `cancel_event.is_set()` between chunks. SSE: each job has an in-memory `list[asyncio.Queue]` of subscribers; REST polling of `GET /jobs/{id}` is the fallback. On startup, any job stored as queued/running → status `server_restarted`.

## 7. Pipeline stages (pipeline.py)

Analysis stages in order (stage names are exact strings):
`NORMALIZING, PARSING_POLICY, TRANSCRIBING, DETECTING_PII, DETECTING_VISUAL, TRACKING, BUILDING_PREVIEW, REVIEW_READY`
(policy already parsed at project setup; PARSING_POLICY just validates/loads it. Video-only projects skip TRANSCRIBING/DETECTING_PII with a log line.)
Render job stages: `RENDERING, MUXING, AUDITING, COMPLETE`.

`run_analysis(project_id, store, settings, progress_cb, cancel_event)`:
1. NORMALIZING — media.normalize.normalize_video()
2. TRANSCRIBING — audio.transcribe (if has_audio and audio_targets)
3. DETECTING_PII — audio.pii → audio RedactionEvents
4. DETECTING_VISUAL — vision.detector on proxy keyframes
5. TRACKING — vision.tracker → tracks.json + masks/*.npz + visual RedactionEvents
6. BUILDING_PREVIEW — review.overlay (boxes burned into working/review_overlay.mp4)
7. events.json written, project.status = review_ready

Each stage wrapped with timing + VRAM metrics (see §12) into job.metrics + audit data at `analysis/stage_metrics.json`.

`run_render(...)`: requires all auto events confirmed/ignored. Applies confirmed events only:
- Visual: for each output frame, for each active visual event: mask from npz if present (resized), else box (interpolated between BoxKeyframes, expanded by 8px, feathered). Effect priority when overlapping: solid > pixelate > blur.
- Audio: extract full-rate audio, apply mute/beep with 10ms fades, mute wins overlaps; write back.
- Mux with libx264, aac, yuv420p, faststart, `-map_metadata -1`. ffprobe-validate → atomic replace into exports/.
- Write redacted.srt (transcript segments with redacted spans replaced by `[REDACTED: PHONE|EMAIL|ADDRESS|MANUAL]`), audit.json (§11), zip.
- On any event mutation after render: project.exports_stale = True.

## 8. API (all under /api/v1) — JSON bodies, snake_case

```
GET  /health                    -> {"status":"ok","version":...}
GET  /system                    -> {"gpu": device_info(), "models": {...ready flags}, "ffmpeg": bool}
GET  /projects                  -> {"projects":[Project...]}
POST /projects {name}           -> Project (201)
GET  /projects/{id}             -> Project
PATCH /projects/{id} {name}     -> Project
DELETE /projects/{id}           -> 204
POST /projects/{id}/source      multipart file -> Project (validates ffprobe, ≤60s, sets media, generates thumbnail working/thumbnail.jpg immediately)
GET  /projects/{id}/media       -> MediaInfo
POST /projects/{id}/policy/parse {text} -> {"spec": PolicySpec, "source": "llm|llm_repaired|keyword_fallback"}
PUT  /projects/{id}/policy {spec} -> saved PolicySpec (validated)
POST /projects/{id}/jobs/analysis -> Job (409 if busy)
POST /projects/{id}/jobs/render   -> Job (409 if pending auto events exist or busy)
GET  /jobs/{job_id}             -> Job
POST /jobs/{job_id}/cancel      -> Job
GET  /jobs/{job_id}/events      -> SSE stream: event: progress, data: Job JSON; final event: done
GET  /projects/{id}/events      -> {"events":[...], "revision": int}
POST /projects/{id}/events {event fields, expected_revision} -> event (manual add; kind/category/start/end/action + boxes for visual)
PATCH /projects/{id}/events/{eid} {changes..., expected_revision} -> event; 409 on revision mismatch
DELETE /projects/{id}/events/{eid}?expected_revision= -> 204 (manual events only; auto events get status=ignored instead)
POST /projects/{id}/review/confirm-all {expected_revision} -> {"confirmed": n, "revision": int}
POST /projects/{id}/review/complete -> project (marks review done; render allowed)
GET  /projects/{id}/preview/original   -> FileResponse working/normalized.mp4 (Range supported by Starlette FileResponse)
GET  /projects/{id}/preview/overlay    -> FileResponse working/review_overlay.mp4
GET  /projects/{id}/thumbnail          -> FileResponse working/thumbnail.jpg
GET  /projects/{id}/artifacts/{kind}   -> kind ∈ video|srt|audit|zip from exports/
```
Static frontend mounted at `/` (StaticFiles html=True). Every event mutation bumps `project.revision`, appends review_history, sets exports_stale.

## 9. Frontend behavior (vanilla JS)

- `js/api.js`: tiny fetch wrapper `API.get/post/patch/del`, `API.sse(url, onMsg)`.
- index.html: project cards (thumbnail, name, status chip, duration, updated), New Project button, delete w/ confirm dialog, system bar (GPU name, ROCm ok, "Local processing only" badge).
- project.html: upload (drag-drop + file input, progress via XHR), ffprobe info table, `<video>` preview of original upload, policy textarea + 2 example buttons, "Interpret Policy" → renders parsed targets as editable rows (category ✓, action select, strength slider; unsupported terms in red "Unsupported target"), "Start Analysis" → POST jobs/analysis → processing.html.
- processing.html: stage list with current highlighted, overall progress bar, per-stage metrics (frames, fps, elapsed, ETA, GPU name, precision, peak VRAM), SSE with auto-reconnect + 2s polling fallback, Cancel + Retry buttons. On done → review.html.
- review.html (most important):
  - center `<video>` (src = preview/overlay or preview/original, toggle button swaps src keeping currentTime)
  - canvas overlay above video: draws boxes of visual events at currentTime (interpolated), highlights selected event; click-drag on canvas in "Add region" mode creates manual rect event (fixed region, label "Manual fixed region")
  - left: event list grouped visual/audio with filter (all/pending/confirmed/ignored), badge counts
  - right: property panel for selected event (status buttons Confirm/Ignore, start/end number inputs, category select, action select, strength, "play ±2s" button, "jump to lowest confidence" for visual)
  - bottom: two-track timeline (canvas): visual track + audio track, zoom slider, click → seek + select; drag event edges to retime (snap to 1/fps for visual); colors: pending amber, confirmed green, ignored gray
  - top bar: pending count, save state ("Saved"/"Saving…"), Confirm All Remaining, Complete Review → export.html
  - keyboard: space play/pause, ,/. frame step, [ ] prev/next event
  - transport: play/pause, frame ±1 (step = 1/fps), rate 0.5/1.0, prev/next event, timecode input
- export.html: pre-render summary (counts by status/kind, output res, est. time), Render button → job SSE progress → final `<video>` player of redacted.mp4 + download buttons (MP4/SRT/audit/ZIP) + SHA-256s + processing time + peak VRAM + realtime factor; "Stale" banner if exports_stale.

## 10. Vision & audio algorithm notes

- Detection runs on the proxy video at keyframe times (dino_interval 0.5s; YuNet 0.25s when face targeted). Detection = `Detection(t, category, box_norm, score, source)`. NMS per category IoU 0.5.
- Tracker: greedy association across keyframes per category by IoU>0.3 (fallback center distance < 0.15). Track = keyframe boxes; linear interpolation between; extend 1 interval before first/after last sighting. Gap > 1.5s splits track. If SAM2 available: refine each track's chunk with mask propagation → masks saved as packed bool arrays npz `{t: mask}` at proxy resolution downsampled 2x; else warnings=["rect_fallback"].
- Every track → one visual RedactionEvent (start, end, boxes=keyframes, confidence=min score).
- Audio PII: normalize spoken forms (spoken.py), regex on both raw text and normalized string with char→word-timestamp mapping; presidio optional extra recall for addresses. Merge events with gap <200ms; pad 150/250ms. Missing word timestamps → whole segment + warnings=["segment_level_timestamps"], confidence=0.4.
- Beep: 1kHz sine at −12dBFS; mute: zeros; 10ms linear fades both ends.

## 11. audit.json (audit/builder.py) — schema in schemas/audit.schema.json

Top-level keys: `schema_version, generated_at, input:{sha256,duration_s,resolution}, output:{sha256,duration_s,resolution}, policy (PolicySpec dump), models:[{stage,model_id,precision,device}], environment:{gpu_name,rocm_version,torch_version,python}, stage_metrics:{stage:{wall_s,peak_vram_mb,frames,effective_fps,precision,fallbacks[]}}, events:[{id,kind,category,start_s,end_s,action,source,status,warnings}] (no text_preview), counts:{auto,manual,confirmed,ignored}, review_history_count, warnings:[...]`. NO raw transcript, NO PII text, NO absolute paths.

## 12. Metrics helper (core/device.py)

```python
def stage_metrics(stage_name): # context manager
    # torch.cuda.synchronize() + reset_peak_memory_stats() before, synchronize + max_memory_allocated after (guarded by availability)
    # yields dict to fill: frames, precision; sets wall_s, peak_vram_mb
def device_info() -> dict  # {"available":bool,"name":str,"torch_version":str,"hip_version":str|None,"rocm":bool}
```

## 13. Testing

- Unit tests must run WITHOUT torch/ffmpeg installed (pure-python modules: keyword parser incl. negation, spoken normalization, PII regex, mask math with numpy, storage, models, audit builder with fake data).
- API tests: fastapi TestClient, temp data dir, fake tiny "video" bypass — `POST /source` with monkeypatched probe for speed.
- `scripts/make_fixtures.py`: generates 3 synthetic test videos with OpenCV+ffmpeg (street/interview/office analogs: moving rectangles with face-like drawings, fake plate text, fake ID card, screen-like rectangles) + gTTS-free synthetic audio: generate spoken PII via `say` (mac) or espeak (linux) if available else tone placeholder; all PII fake.
```
