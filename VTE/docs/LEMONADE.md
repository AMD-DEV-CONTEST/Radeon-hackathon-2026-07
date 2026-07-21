[← Back to README](../README.md)

# Integrating with Lemonade

VTE plugs into [Lemonade](https://github.com/lemonade-sdk/lemonade), AMD's local LLM server, as a native RDNA3 backend. This page documents `vte-server` (the subprocess Lemonade actually spawns), the recipe registration on the Lemonade side, and the gotchas found while wiring the two together. It complements the code, not the other way around: when something here and the code disagree, trust the code and update this page.

## Why a separate server exists

Every Lemonade backend runs as a subprocess reachable over loopback HTTP (`WrappedServer`'s contract: `load()`/`unload()`/`chat_completion()`/`completion()`, never in-process). `vte-server` ([vte/server/http_server.py](../vte/server/http_server.py)) exists to satisfy that invariant: it wraps a single `VTEModel` behind an OpenAI-compatible HTTP API, the same crash-isolation pattern `vte/core/motor.py` already uses for the desktop UI (one model per process, spoken to over IPC), just swapping `multiprocessing.Pipe` for HTTP and Flet for any HTTP client.

## API surface

| Method | Endpoint | Notes |
|--------|----------|-------|
| `GET` | `/health` | `200 {"status": "ready"}` once the model has finished loading, `503 {"status": "loading"}` before that. |
| `GET` | `/v1/models` | Lists the one loaded model, OpenAI `{"object": "list", "data": [...]}` shape. `id` is the GGUF filename stem, `created` is the load timestamp. Lets IDEs/tools (Cursor, Continue) point straight at `vte-server` without going through Lemonade. |
| `POST` | `/v1/chat/completions` | Standard OpenAI chat shape, streaming (`stream: true`, SSE) and non-streaming. |
| `POST` | `/v1/completions` | Standard OpenAI text-completion shape, non-streaming only. |

There is no authentication on any endpoint. That's fine as long as `vte-server` only ever binds to `127.0.0.1` (the default, and the only mode Lemonade uses) and is spoken to by Lemonade itself or by you directly in dev. To point an external tool at it: `base_url = "http://127.0.0.1:<port>/v1"`, `api_key = "not-needed"` (any string; nothing checks it), same convention Lemonade's own docs use for its Python examples.

## Safety fallbacks

A single `VTEModel` instance shares one HIP context, one captured decode graph, and one KV cache/arena: none of that is reentrant. `vte-server` serializes generation behind a `threading.Lock` (`_generation_lock` in `http_server.py`); a second request arriving mid-generation gets `429 {"error": {"type": "server_busy"}}` immediately instead of racing the first one against the same GPU state. On top of that: a global exception handler returns structured `500` JSON instead of leaking a traceback, malformed request bodies get a clean `400`, and `cli_main()` fails fast (clear log line, `exit(1)`) if the model load itself fails, instead of leaving Lemonade polling `/health` against a process that already died.

A parent-PID watchdog (`--parent-pid`) and SIGINT/SIGBREAK handlers both call the same `unload()` path; the watchdog exists because `TerminateProcess` on Windows delivers no catchable signal to the child, even on Lemonade's normal unload path, so it's the only thing preventing an orphaned `vte-server` holding VRAM after `lemond` dies unexpectedly.

## Downloading models: `vte pull`

There is no automatic model download built into VTE itself outside of this: `vte pull <name>` ([vte/core/downloader.py](../vte/core/downloader.py)) fetches a GGUF from the Hugging Face Hub straight into `Model/`, for the handful of checkpoints this project actually validated:

```bash
vte pull qwen2.5:1.5b-q4_k_m
vte pull granite-4.1:3b-q8_0
vte pull qwen3.5:2b-q6_k
vte list   # shows the curated names above
```

It also accepts any raw `repo_id:filename.gguf` checkpoint, the same format Lemonade's own `server_models.json` uses for its `checkpoint` field. When VTE is driven through Lemonade, this doesn't matter to the end user: Lemonade's own `ModelManager` downloads the checkpoint named in `server_models.json` before ever invoking `vte-server --gguf-path <already-downloaded-file>`. `vte pull` only matters for standalone/direct use of VTE, outside of Lemonade.

## The Lemonade-side recipe

Registering VTE as a Lemonade recipe is (on the Lemonade side, not covered by this repo) one `LEMON_BACKENDS` line in the root `CMakeLists.txt`, a `BackendDescriptor` (`VTE.h`) plus a `WrappedServer` subclass (`VTE_server.h/.cpp`) under `src/cpp/backends/VTE/`, and one entry per model in `src/cpp/resources/server_models.json`:

```json
"Qwen2.5-1.5B-Instruct-VTE": {
    "checkpoint": "Qwen/Qwen2.5-1.5B-Instruct-GGUF:qwen2.5-1.5b-instruct-q4_k_m.gguf",
    "recipe": "vte",
    "suggested": false,
    "size": 1.12,
    "recipe_options": { "ctx_size": 8192 }
}
```

VTE currently ships three such entries, one per supported architecture: `Qwen2.5-1.5B-Instruct-VTE`, `Granite-4.1-3B-VTE` (`unsloth/granite-4.1-3b-GGUF:granite-4.1-3b-Q8_0.gguf`), `Qwen3.5-2B-VTE` (`unsloth/Qwen3.5-2B-GGUF:Qwen3.5-2B-Q6_K.gguf`). All three quantizations (Q4_K_M, Q8_0, Q6_K) were validated end-to-end on real hardware: loaded via `VTEModel.from_pretrained()` and a real `generate()` call, not just downloaded.

### The `recipe_options.ctx_size` gotcha

Every one of those entries pins `"recipe_options": {"ctx_size": 8192}` deliberately. Without it, Lemonade's generic context-size auto-tune picks a value from the model's own GGUF metadata (Granite's native window is 131072, Qwen3.5's is 262144), and VTE's Split-KV (Flash-Decoding) attention scales its chunk-grid dispatch size off the *configured* context length, not the actual sequence position (see [Bugs found during development](BUGS.md)). A large auto-tuned `ctx_size` means a large dispatch grid on every decode step regardless of how short the conversation actually is: measured cost was real, ~4x more VRAM for the KV cache/activation arena and a ~15-20% tok/s regression at `ctx_size=32768` versus `8192` for the same short exchange.

The obvious place to set this default felt like the recipe itself (a `config_extra` value in the `BackendDescriptor`, so it applies to every VTE model without repeating it per entry) - that doesn't work. Lemonade's `RuntimeConfig::recipe_options()` only translates config keys a descriptor explicitly lists in its own `options` array; `ctx_size` is a *shared* option opted into via `uses_ctx_size` instead, and that function's special-cased `ctx_size` handling only ever reads the top-level global config key, never a per-recipe one. Confirmed by building and loading for real, not by reading the code: a `config_extra` entry looked correct sitting in `config.json`, but had zero effect on the resolved context size. The context size default has to live in `recipe_options` on each *model* entry (as above) until `RuntimeConfig::recipe_options()` itself is extended to accept a recipe name and read that recipe's own `uses_ctx_size` section - a real gap in Lemonade's own config system, not specific to VTE, and out of scope for this integration.

The value is still fully user-overridable: it's a default like any other `recipe_options` entry, not a hardcoded floor.

## Releasing `vte-server`

`scripts/build_vte_server_bundle.py` packages `vte-server` into a self-contained Windows bundle via PyInstaller, published as a GitHub release asset (`vte-server-<version>-windows-x64.zip`) that `VTE_server.cpp::get_install_params()` downloads by name. A naive `--collect-submodules vte` pulls in torch+transformers (541MB) despite nothing in the codebase importing either (confirmed by grep, not assumed): the script scopes collection to just `vte.core`/`vte.bridge`/`vte.compiler`/`vte.server` and excludes the confirmed-unnecessary heavy packages, bringing the bundle down to ~58MB unpacked / ~24MB compressed.

Release tags follow the plain `<major>.<minor>.<patch>` convention (`0.1.0`, `0.2.0`, no `v` prefix) - `backend_versions.json`'s `"vte": {"rocm": "<version>"}` pin on the Lemonade side has to match exactly, since it's substituted directly into the release asset filename. Always validate the frozen `.exe` against real hardware (`--gguf-path`, then `/health`, `/v1/models`, a real chat completion, and the malformed-JSON/concurrency-lock fallbacks) before publishing - the frozen bundle's dependency set differs from the dev venv, so a dev-only test isn't proof the release artifact itself works.
