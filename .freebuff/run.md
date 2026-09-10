# Run doc — MKO Universal AI Agents (Radeon-hackathon-2026-07)

A FastAPI + Uvicorn web UI serving a multi-agent chat playground with a
Stripe-backed credit system, an admin panel, a GPU compute benchmark, and
optional Qdrant RAG. Default port: **49239**.

## 0. No secrets — how state stays out of the repo

The hackathon rules forbid committing secrets. The repo handles this with two
artifacts in the project root:

- **`.gitignore`** — excludes `data/` (runtime state: users, credits, refund
  codes, webui settings, admin session tokens), `.env`/`.env.local`/
  `.env.*.local` (local overrides), `__pycache__/`, `.venv/`, `.freebuff/*.log`,
  and `*.qdrant/` (RAG vector indices). The `.freebuff/run.md` (this file) and
  `.freebuff/launch.py` (the Windows-detached launcher) ARE tracked — they are
  operator helpers, not state.
- **`.env.example`** — documents every environment variable the app reads
  (`GROQ_API_KEY`, `HF_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`,
  `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_WEBHOOK_SECRET`,
  `STRIPE_PRICE_*`, `BASE_URL`) with empty values. `cp .env.example .env.local`,
  fill it in, leave it on disk — it is gitignored.

When **no keys are configured**, the app boots in unauthenticated demo mode:

- The settings panel shows every provider as "no API key configured".
- Chat streams return a friendly `*⚠️ No <provider> API key configured. Set
  it in the Settings panel or via env var.*` mid-stream instead of a real LLM
  response. No crashes.
- `/api/stripe/create-checkout-session` returns a clean 400 explaining how to
  enable Stripe. The pricing UI still renders.
- The Admin panel accepts the default password `admin123` (the
  `ensure_admin_exists()` seed). **Change it on first login.**
- Provider-latency benchmarks gracefully mark unconfigured providers as `error: "No API key"`.

The two ways to wire up real keys after the hackathon:

1. **Env vars** — drop them in `.env.local` (or set them in your shell) and
   restart `python run.py`. Env-vars take precedence over the in-file
   `data/webui_config.json` on the next request.
2. **In-UI Settings panel** — paste them into the Settings panel and click
   Save Settings. The app writes them (gitignored) to `data/webui_config.json`.
   `webui_config.json` is inside `data/`, so it never reaches the repo.

## 1. Reproduce the artifacts a fresh checkout needs

The tracked branch only carries `README.md`, `Radeon-Cloud-User Guide/`,
`.git/`, `mko/`, `requirements.txt`, `run.py`, `tests/`, `.gitignore`,
`.env.example`, and the `.freebuff/` operator helpers (`run.md`, `launch.py`).
Everything else (`data/`, `.freebuff/*.log`) is **gitignored and runtime-only**.
A fresh checkout already has everything needed to boot — no copy step:

1. **(Gitignored) runtime files** — `data/` does not exist after a fresh
   clone. The app auto-creates it on first start:
   - `data/admin_config.json` — written by `ensure_admin_exists()` with a
     default-password hash for `admin123` and an empty `session_tokens` dict.
   - `data/webui_config.json` — written by the Settings panel only on first
     save. Until then `load_config()` returns the in-code defaults
     (`provider="groq"`, `api_keys={}`, `model="llama-3.3-70b-versatile"`).
   - `data/users.json` / `data/refund_codes.json` — written lazily by
     `get_or_create_user()` and admin refund issuance.
2. **(Optional, for RAG endpoints)** install `qdrant-client` and
   `sentence-transformers`. The `/api/rag/*` routes catch `ImportError` and
   return a clean 400, so the UI works without them — only install them if
   you intend to exercise document ingestion.
3. **Install Python dependencies** with the project's package manager. There
   is no `Pipfile`/`pyproject.toml`; the canonical manifest is
   `requirements.txt`. Use the system `pip` (Python 3.12) or, if isolation is
   required, a local venv at `.venv/`:
   ```
   python -m pip install -r requirements.txt
   ```
   Already-installed versions on this machine match: fastapi 0.115.6,
   uvicorn 0.32.1, pydantic 2.13.4, stripe 15.3.1, httpx, aiofiles,
   python-multipart.
3. **(Optional) Stripe env vars** — set `STRIPE_SECRET_KEY`,
   `STRIPE_WEBHOOK_SECRET`, `STRIPE_PUBLISHABLE_KEY`, and the per-pack
   `STRIPE_PRICE_*` env vars to enable `/api/stripe/create-checkout-session`.
   Without them the checkout endpoint returns a 400 explaining how to enable
   it; the rest of the app still works. The schema lives in `.env.example`.
4. **(Optional) LLM provider env vars** — `GROQ_API_KEY`, `HF_API_KEY`,
   `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`. Either via `.env.local` or the in-UI
   Settings panel. Env-vars win at request time.
5. **(Optional) Override the public base URL** — set `BASE_URL` (default
   `http://127.0.0.1:49239`) so Stripe success/cancel URLs are correct.

## 2. Run the server

The project's canonical launcher is `run.py` (uvicorn against
`mko.webui.server:app`, 127.0.0.1:49239). For the Freebuff preview we log to
`.freebuff/preview-*.log`, run the process detached so it outlives this
session, and reuse port 49239 if it's free:

```
python run.py > .freebuff/preview.log 2>&1 &
```

Or, for true Windows-process detachment (survives shell exit):

```
python -c "import subprocess,sys; subprocess.Popen([sys.executable,'run.py'], stdout=open('.freebuff/preview.log','wb'), stderr=subprocess.STDOUT, creationflags=0x00000008)"
```

Sanity checks:
- `curl http://127.0.0.1:49239/` returns the chat UI HTML.
- `curl http://127.0.0.1:49239/api/agents` returns the 8 agent descriptors.
- `curl http://127.0.0.1:49239/api/credits?username=demo` returns the demo
  user's credit balance.

Admin login uses the password **admin123** (the hash seeded on first start in
`ensure_admin_exists()` corresponds to that value; if `data/admin_config.json`
is missing, the app recreates it on startup). **Change it before deploying.**

### Pre-commit secret-scan

Before opening the hackathon PR, run a sweep to confirm zero leaked keys:

```
grep -rE "gsk_[A-Za-z0-9]{20,}|hf_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|whsec_[A-Za-z0-9]+" --exclude-dir=data --exclude-dir=.git .
```

If anything matches, scrub it before pushing.

## 3. Run via Docker (Hackathon delivery path)

For reviewers and judges, the canonical delivery is `docker compose up --build`.
The image is built from the root `Dockerfile` on top of
`rocm/pytorch:rocm6.2_ubuntu22.04_py3.10_pytorch_2.3.0` — ROCm 6.2 native
support for RDNA3 (RX 7000 / RX 9070) without an `HSA_OVERRIDE_GFX_VERSION`
compat hack. PyTorch is preinstalled, so `/api/benchmark/run` can call
`torch.hip.is_available()` and report a real GPU without extra wheels.

```bash
docker compose up --build
```

The compose file:
* Maps host `${MKO_PORT:-49239}` → container `49239`.
* Bind-mounts `./data` to `/app/data` so the credit ledger, user list, and
  webui settings survive `docker compose restart`.
* Reads optional `.env.local` and `.env` env-files (both gitignored) — passes
  every value through to the container process so a `cp .env.example .env.local`
  + edit + `docker compose restart` is the entire wire-up step.
* Mounts `/dev/kfd` and `/dev/dri`, adds `video` and `render` groups, and
  relaxes `SYS_PTRACE` + `seccomp` so ROCm's HSA introspection paths work.

**Run-level env vars provisioned by the Dockerfile:**
- `MKO_HOST=0.0.0.0` — bind inside the container, not the loopback default.
- `MKO_PORT=49239`.

`run.py` reads both, so the same Python entrypoint works on Windows dev
(`MKO_HOST=127.0.0.1` default), Linux bare-metal (`MKO_HOST=0.0.0.0`), and
the container without a sed patch in the Dockerfile.

For judges — start here and only fall back to the bare-metal section above
if you can't run Docker.

## 4. CI smoke tests (`.github/workflows/ci.yml`)

The repo carries a GitHub Actions workflow that runs on every push to `main`
and on every PR. Quick map of what it does:

1. **Build** — `docker/build-push-action@v6` builds the `Dockerfile` with
   `cache-from: type=gha` and `cache-to: type=gha,mode=max` so layer reuse
   is automatic across runs.
2. **Boot** — `docker compose up -d --wait --wait-timeout 240`. `--wait`
   blocks until the container's `HEALTHCHECK CMD` returns 0, so by the time
   the next step runs, the app is healthy (not just listening).
3. **Smoke** — three HTTP-level assertions:
   - `GET /api/agents` must return HTTP 200.
   - `GET /api/credits?username=demo` must return JSON with
     `.credits` of type `number` and `.username == "demo"`, validated using
     `jq -e`.
   - `docker inspect --format='{{.State.Health.Status}}' mko-agents` must be
     `healthy`.
4. **GPU gate** — `docker compose exec -T mko python -c "import torch;
   print(int(torch.cuda.is_available()))"`. The assertion is **enforced on
   self-hosted runners** (typically labeled `amd-gpu`) and **informational
   on GitHub-hosted CPU runners** (since `False` reflects missing hardware,
   not a real defect). Toggle by pointing `runs-on:` at a different runner.
5. **Tear down** — `docker compose down -v --remove-orphans` on an
   `if: always()` step so the runner is clean whether steps pass or fail.

To run the smoke tests on an actual Radeon box, switch `runs-on: ubuntu-latest`
to `runs-on: [self-hosted, linux, amd-gpu]` (or whatever label pattern your
self-hosted runner exposes). The four HTTP assertions already pass in demo
mode; only the GPU assertion differs between runners.

Operator note: the workflow file is intentionally committed (no secrets) and
contains no `actions/checkout` of unrelated repos. The `STRIPE_*` /
`GROQ_*` / `HF_*` / `OPENAI_*` / `ANTHROPIC_*` env vars are read by compose
with `required: false` env_files, so the absence of `.env.local`/`.env` just
keeps the suite in demo mode — no need to create dummies for CI.

## 5. Security gates in CI (Hadolint + Trivy)

Two new steps in `.github/workflows/ci.yml` harden the pipeline. They produce SARIF reports and surface them as code-scanning alerts (tab: **Security → Code scanning alerts**) alongside any CodeQL findings.

### Hadolint (Dockerfile lint)

`hadolint/hadolint-action@v3.1.0` runs against the Dockerfile with:

```yaml
failure-threshold: warning
format: sarif
output-file: hadolint-results.sarif
```

A few rules worth knowing:

| Rule | Severity | What it catches |
|---|---|---|
| **DL3008** | warning | Pin versions in `apt-get install`. We pin `curl=7.81.0-1ubuntu1.20` and `ca-certificates=20230311ubuntu0.22.04.1` in the Dockerfile to satisfy this — bump via Dependabot when the base image moves forward. |
| DL3009 | info | Delete the apt-get lists after installing — the Dockerfile already does `rm -rf /var/lib/apt/lists/*`. |
| DL3015 | info | Avoid additional packages by using `--no-install-recommends` — already done. |
| DL4006 | warning | Set the SHELL option `-o pipefail` before `RUN` pipelines — not used here. |

If hadolint flags a warning on a PR, the build fails and the warning shows up in the build log + as a code-scanning alert. Fix by either pinning as we did for `curl`/`ca-certificates`, adding a `# hadolint ignore=DLxxxx` directive, or adjusting the script.

### Trivy (image CVE scan)

`aquasecurity/trivy-action@0.24.0` scans the **built image** (the artifact of the previous `docker/build-push-action@v6` step), so the underlying `rocm/pytorch:rocm6.2_ubuntu22.04_py3.10_pytorch_2.3.0` layer and our own changes are both in scope. Flag set:

```yaml
severity: CRITICAL
exit-code: 1
ignore-unfixed: true        # don't fail on vulns without published fixes
scanners: vuln
vuln-type: os,library       # both apt packages and pip wheels
format: sarif
output: trivy-results.sarif
```

Trivy fails the build on any `CRITICAL` CVE — `HIGH`/`MEDIUM`/`LOW` show up as code-scanning alerts but don't block.

`ignore-unfixed: true` keeps noise down: if there's no upstream patch yet, we don't blackhole the build, but the alert still lands in the Security tab for triage.

### Permissions block

The workflow declares:

```yaml
permissions:
  contents: read
  security-events: write
```

`security-events: write` is the token needed for `github/codeql-action/upload-sarif@v3`. The `if: always()` flag on the upload steps means SARIF still lands even when the lint/scan itself failed — so the alerts are visible right next to the failed run, not just in the build log.

### Operator note

If hadolint or trivy flags something you've assessed as a non-issue, you can either:

1. Bump the pin in `Dockerfile` to a newer version (best — actually addresses it).
2. Add a directive: `# hadolint ignore=DL3008` on the offending `RUN` line.
3. Add a `.trivyignore` rule for trivy: `Severity: CRITICAL\nIDs: CVE-XXXX-XXXXX\nReason: ...\nExpiry: 2026-12-31`.

## 6. Slash commands (chat input)

The chat input on `index.html` accepts six slash commands (five actions plus a live /help). They are parsed
client-side by `mko/webui/static/js/slash-commands.js` (a UMD-style IIFE
that also exports `module.exports` for the Node test runner). `app.js`
intercepts Enter input: if it parses as a known command the action fires,
the input is **not** posted to `/api/chat`. If it parses as unknown, a
warning is logged and the text falls through to plain chat.

| Slash | Behaviour |
|---|---|
| `/plan <topic>`     | Switch active agent to **Planner**, seed the input with `<topic>`. Edit if you like, then press Enter to send. |
| `/research <query>` | Switch active agent to **Researcher**, seed the input with `<query>`. |
| `/summary <text>`   | Switch to **General**, seed the input with the text to summarize. |
| `/model <provider>[/<model>]` | Swap active provider (and model if given). Triggers `loadModels()` to refresh the dropdown; the bubble renders `✓ Switched model → <provider> / <model>`. |
| `/provider <name>`  | Swap active provider; model resets to default. Bubble renders `✓ Switched provider → <name>`. |
| `/help` / `/commands` | Emit a multi-line system bubble listing every command **live** from `MKOSlash.KNOWN_COMMANDS`. `/commands` is a terse alias. Rest is ignored. Help text stays in sync with code: add to KNOWN_COMMANDS + parse() + handleSlashCommand(), /help auto-includes it. |

Notes & invariants:

- **Leading slash only.** `Hello /plan foo` is treated as plain chat, not a command.
- **Case-insensitive command.** `/PLAN foo` and `/plan foo` both work; the seeded *topic* keeps the user's original case.
- **Trailing `/` stripped.** `/model groq/` → provider `groq`, default model.
- **Multi-slash model passed verbatim.** `/model a/b/c` → provider `a`, model `b/c` (model names never contain slashes in practice).
- **Quoted args verified verbatim.** `/plan "ship it"` seeds the literal `"ship it"` (no quote-stripping in v1).
- **Unknown provider.** `/provider notreal` and `/model notreal/foo` emit a `⚠️` system message listing known providers (currently `ollama, groq, huggingface, openai, anthropic`).
- **Empty slash.** `/` alone emits an `ℹ️` hint suggesting `/plan <topic>` or `/model <provider>`.

### Tests

Two test suites pin the grammar:

- `tests/test_slash_commands.mjs` — run with `node --test tests/test_slash_commands.mjs`.
  Exercises the **actual** parser file (no Python mirror). ~25 cases cover
  each command, trailing/multi-slash variants, case-insensitivity, slash
  mid-sentence, quoted args, the formatConfirmation helper, and the
  `KNOWN_PROVIDERS` / `KNOWN_AGENTS` constants.
- `tests/test_run_smoke.py` — run with `python -m unittest tests.test_run_smoke`.
  A cheap layout pin: slash-commands.js exists, the Node test exists, the
  `<script src="/static/js/slash-commands.js">` tag is loaded **before**
  `app.js`, app.js references `MKOSlash` / `handleSlashCommand` /
  `appendSystemMessage` and calls `MKOSlash.parse`, and `.freebuff/run.md`
  mentions every one of the five commands.

Both run with no extra dependency on Python (uses `unittest` from stdlib,
no `pytest`) and no JS framework (uses Node 18+'s built-in `node:test`).


### Slash-command autocomplete

When the user types `/` in the chat input a dropdown opens listing every command from `window.MKOSlash.KNOWN_COMMANDS`. Navigation:

- ↑ / ↓  — move highlight (clamped at ends, no loop)
- Tab    — autocomplete the highlight (or first row if no highlight)
- Enter  — autocomplete (NEVER auto-sends while the dropdown is open)
- Shift+Enter — passes through (normal textarea newline)
- Escape — close & refocus input
- Click outside the dropdown — close
- Completion writes `/cmd` + a single trailing space (uniform cheap behavior). The trailing space in turn triggers `getSuggestions()` to return null and so the dropdown self-closes.

### Agent DAG canvas (MoE routing)

When the assistant stream contains a `moe_debug` event, the chat
bubble prepends an inline-SVG graph above the existing expert
cards. Gate at top; each expert node spaced below; edges
labeled with weight; deterministic DJB2-hashed palette so the
same provider always maps to the same color across renders.

Pure pieces (`moe-graph.js`, exposed on `window.MKOGraph`):

- `computeMoEGraphLayout(debugData)` — returns `null` for empty details,
  otherwise `{ width, height, expertCount, nodes[], edges[] }`. Gate
  placed at top center; experts distributed evenly below; N=1
  case places the single expert directly under the gate on the
  same X column.
- `renderMoEGraphSVG(layout)` — pure SVG string with `<title>`,
  `<desc>`, `<defs>` (arrow marker), one `<g class="mko-dag-edge">`
  per edge with a weight label, and one `<g class="mko-dag-node">`
  per node (circle + label + sublabel).
- `colorForProvider(name)` / `formatWeight(w)` — exported for
  forward-compatible use (e.g., colored badges elsewhere).

DOM glue (`app.js`): `renderMoEDAG(bubble, debugData)` queries
`bubble.querySelectorAll('.moe-debug-body')`, forEach, and
prepends a `.moe-dag-wrap` block at the top of each body. The
existing `🔀 MoE Debug` header toggle collapses the whole panel.

Pure helper: `MKOSlash.getSuggestions(text)` returns `null` when no popup, `[]` when no match, or an array of `KNOWN_COMMANDS` rows for direct rendering. The implementation lives in `mko/webui/static/js/slash-commands.js`; the DOM wiring is in `mko/webui/static/js/app.js`'s `wireSlashSuggest()` plus the `.mko-suggest*` rules in `mko/webui/static/css/styles.css`. Tests pin the helper in `tests/test_slash_commands.mjs` and the wiring in `tests/test_run_smoke.py` (`SlashSuggestTests`).
