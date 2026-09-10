# Radeon-hackathon-2026-07
🏆 **AMD AI DevMaster Hackathon 2026 Winners**
[Three Tracks, One GPU: Lessons from the AMD DevMaster Hackathon](https://www.amd.com/en/developer/resources/technical-articles/2026/lessons-from-the-amd-devmaster-hackathon.html)

## how to apply and use AMD Radeon GPU
see [README](https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07/blob/main/Radeon-Cloud-User%20Guide/README.md)

## Track 3 starter demo: robot simulation on AMD Radeon GPU

New to robotics, or want to learn how to run robot simulation on AMD GPUs? This reference demo is a quick, hands-on starting point for Track 3 participants — an end-to-end pipeline where a Franka Panda arm picks fruit off a table and places it in a bowl, built on the **Genesis** physics engine and **LeRobot**, running on an AMD Radeon (ROCm) GPU.

▶️ **Demo repo & videos:** https://github.com/wangxunx/franka_fruit_pick_demo

What you'll learn:
- Set up a robot simulation environment on an AMD Radeon GPU (ROCm), using the prebuilt ROCm PyTorch wheels
- Build a scene and run physics simulation with **Genesis**
- Record data, apply domain randomization, and train a visuomotor policy with **LeRobot**
- Go end-to-end — from a scripted pick-and-place to a trained, closed-loop policy, with evaluation videos

> Note: this is a learning reference to show how to run simulation and training on an AMD GPU with `genesis-world` + `lerobot`; the trained model's success rate is not guaranteed.

## Reproducibility & Docker Deployment

[![CI](https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07/actions/workflows/ci.yml/badge.svg)](https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07/actions/workflows/ci.yml)

This project ships as a single-command Docker deployment targeting AMD ROCm — no secrets are tracked in this repository, the app boots in **unauthenticated demo mode** if no API keys are configured, and the full operator / hackathon-internal doc lives in [`.freebuff/run.md`](./.freebuff/run.md).

### 1. 🚀 One-command bring-up

Prerequisites on the host: a working AMD ROCm install (`/dev/kfd` and `/dev/dri` should both exist and be writable). Then:

```bash
docker compose up --build
```

The app comes up at <http://localhost:49239/>. Verify it:

```bash
curl -fsS http://localhost:49239/api/agents   # returns the 8 agent descriptors
curl -fsS http://localhost:49239/api/credits?username=demo   # returns {"credits": 0, ...}
```

In demo mode (no API keys configured):
* The chat stream emits a `*⚠️ No <provider> API key configured…*` mid-stream instead of a real LLM response.
* Stripe `/api/stripe/create-checkout-session` returns a clean 400 explaining how to enable it; the Pricing UI still renders.
* The Admin panel accepts the **default password `admin123`** — **change it on first login**.

### 2. 🔐 Wiring secrets (for full functionality)

```bash
cp .env.example .env.local          # gitignored — secrets stay here
docker compose restart              # picks up the new env
```

…or paste keys into the in-UI **Settings panel** (persisted to the git-ignored `data/webui_config.json` — no leak path).

### 3. 🖥️ Verifying AMD Radeon passthrough

```bash
docker compose exec mko python -c "import torch; print(f'GPU Available: {torch.cuda.is_available()} | HIP: {torch.version.hip}')"
```

Working result: `GPU Available: True | HIP: 6.2.xxxx…`. If `False` shows up, the GPU device passthrough didn't reach the container — verify `ls /dev/kfd /dev/dri` on the host and that your user is in the `video` and `render` groups.

### 4. 🛠️ Manual / bare-metal path (without Docker)

The same app runs without Docker:

```bash
python -m pip install -r requirements.txt
python run.py            # listens on MKO_HOST:MKO_PORT, defaults 127.0.0.1:49239
```

MKO_HOST and MKO_PORT env vars override the bind address and port. See [`.freebuff/run.md`](./.freebuff/run.md) for the full operator doc — including the run-when-Server-isn't-running-on-Linux notes, the pre-commit secret-scan grep, and the post-hackathon wiring guide.

### 5. ✅ Continuous integration (CI)

### 7. 🔀 Agent DAG canvas (in-app)

When a chat response carries a `moe_debug` event (the MoE agent's
router telemetry), the assistant bubble prepends an inline-SVG Agent
DAG canvas above the existing expert cards: gate at top, each expert
node spaced below, edges labeled with weight. Decorative chrome
(`.moe-dag-wrap`) reuses existing CSS variables. Collapsible alongside
the rest of the panel via the existing 🔀 MoE Debug header.

Pure layout + SVG renderer live in `mko/webui/static/js/moe-graph.js`
(UMD-exported `window.MKOGraph`); `app.js`'s `renderMoEDAG(bubble, debugData)`
is the only DOM glue. Tests: `tests/test_moe_graph.mjs` exercises the
layout + renderer; `tests/test_run_smoke.py`'s `MoEDagTests` pins
the wiring end-to-end.


A GitHub Actions workflow at [`.github/workflows/ci.yml`](./.github/workflows/ci.yml) runs on every push to `main` and on every PR. It combines **two security gates** (Hadolint + Trivy → SARIF → GitHub code-scanning alerts) with the **runtime smoke suite**. The canonical step list lives in [`.freebuff/run.md` Section 5](./.freebuff/run.md#5-security-gates-in-ci-hadolint--trivy); the at-a-glance view is:

1. **Checkout** — `actions/checkout@v4`.
2. **Security gate #1 — Dockerfile lint** — `hadolint/hadolint-action@v3.1.0`, `failure-threshold: warning` (this is what catches unpinned `apt-get install` lines like **DL3008**). SARIF → `github/codeql-action/upload-sarif@v3`.
3. **Buildx + Build** — `docker/setup-buildx-action@v3` + `docker/build-push-action@v6` with `cache-from: type=gha`, `cache-to: type=gha,mode=max`.
4. **Security gate #2 — image CVE scan** — `aquasecurity/trivy-action@0.24.0` against `mko-universal-ai-agents:test`, `severity: CRITICAL`, `exit-code: 1`, `ignore-unfixed: true`. SARIF → upload-sarif.
5. **Boot** — `docker compose up -d --wait --wait-timeout 240`. `--wait` blocks until the container's `HEALTHCHECK` passes.
6. **Smoke /api/agents** — `curl --connect-timeout 5 --max-time 15` → HTTP 200 required.
7. **Smoke /api/credits?username=demo** — JSON shape (`jq -e '.credits|number'`, `jq -e '.username=="demo"'`).
8. **Healthcheck audit** — `docker inspect … .State.Health.Status` = `healthy`.
9. **GPU gate** — `docker compose exec -T mko python -c "import torch; print(int(torch.cuda.is_available()))"`. **Hard fail on `*self-hosted*` runners; informational on GitHub-hosted CPU runners.**
10. **Tear down (always)** — `docker compose down -v --remove-orphans` on `if: always()`.

The workflow declares `permissions: { contents: read, security-events: write }` so SARIF actually lands. Surfaced alerts appear under **Security → Code scanning alerts**, with both Hadolint (Dockerfile-level) and Trivy (image-level) findings inline-annotated on the PR diff. Trigger a free-form rebuild from the Actions tab via **Run workflow**. GPU enforcement is one knob flip: change `runs-on: ubuntu-latest` → `runs-on: [self-hosted, linux, amd-gpu]` and the assertion becomes a hard failure.

> Fork badge note: the URL above encodes `AMD-DEV-CONTEST/Radeon-hackathon-2026-07`. If you fork to a personal namespace, update the badge in `README.md` to match.
>
> Apt-pin caveat: Hadolint DL3008 forces `curl` and `ca-certificates` to be pinned in the Dockerfile (currently `7.81.0-1ubuntu1.20` and `20230311ubuntu0.22.04.1`). If the rocm/pytorch base image's apt cache ships them as wrong/missing, the build aborts with `E: Version '…' not found`. Override per line with `# hadolint ignore=DL3008`, or move the override to a project-level `.hadolint.yaml`. See `.freebuff/run.md` Section 5 for the full table.

### 6. ⌨️ Slash commands (in-app)

Type `/` in the chat input — an autocomplete dropdown lists every command. Use ↑/↓ to navigate, Tab or Enter to autocomplete the highlighted row, Escape to dismiss. Completion is uniform: clicking `/plan` writes `/plan_` (trailing space) so the cursor lands ready for the topic.

### 7. 📜 Slash commands (in-app)

The chat input on `index.html` accepts six slash commands, parsed **client-side** in `mko/webui/static/js/slash-commands.js` (a UMD module that also exports `module.exports` for the Node test runner). `app.js` intercepts Enter; unknown commands fall through to plain chat with a warning bubble.

| Slash                                | Behaviour                                                                 |
|---|---|
| `/plan <topic>`                    | Switch agent → **Planner**; seed the input.                                |
| `/research <query>`                | Switch agent → **Researcher**; seed the input.                              |
| `/summary <text>`                  | Switch agent → **General**; seed the input.                                |
| `/model <provider>[/<model>]` | Swap provider (and model); bubble emits `✓ Switched model → …`; refreshes dropdown. Trailing slashes collapse. |
| `/provider <name>`                 | Swap provider; model resets to default. Bubble emits `✓ Switched provider → …`. |
| `/help` / `/commands`                     | Emit a **multi-line** system bubble listing every command live from `MKOSlash.KNOWN_COMMANDS`. `/commands` is a terse alias. Help text stays in sync with code: add the row to `KNOWN_COMMANDS` + a `parse()` branch + an `app.js` `case` and `/help` auto-includes it. |

→ Canonical grammar, edge cases, override rules: [`.freebuff/run.md` § 6](./.freebuff/run.md#6-slash-commands-chat-input).

Tests: `node --test tests/test_slash_commands.mjs` + `python -m unittest tests.test_run_smoke`.

## when you submit
**pls fork this repo and open a pull request including the stuff that is mentioned in Rules&conditions of luma page. the title of pull request should be like "Track x, Team name, your application name"**

> [!IMPORTANT]
> Team name was an optional field on the Luma registration form. If you did not fill in a team name when you registered, please use your own name instead, so the title of the pull request should be like **"Track x, Your name, your application name"**.

> [!NOTE]
> All submission materials, project descriptions, and Pull Requests should be submitted in English.

## Submission Requirements

### Track 1: Development of Multimodal Content Creation Tools

1. **Project Profile Document (PDF)**
   - Project background
   - Target users & application scenarios
   - System architecture
   - Model & algorithm introduction
   - Adaptation description for AMD Radeon GPU / ROCm
2. **Project Source Code**
   - Complete source code repository
   - README file including environment configuration, startup guide and dependency list
3. **Demo Video**
   - Recommended duration: 3–5 minutes
   - Demonstrate the actual operation process
   - The actual execution performance on an AMD Radeon GPU, from command line/GUI to the final result (clarity, stability and diversity of outputs)
4. **Supplementary Materials (Choose One)**
   - PPT / Poster (highlight creative scenarios, practical value of the tool)

### Track 2: Development & Local Deployment of Private AI Agents

1. **Project Specification Document**
   - Application scenarios
   - Agent architecture diagram
   - Introduction to core capabilities
   - Model introduction & local deployment plan
   - Optimization description for inference speed on AMD Radeon GPU
2. **Project Source Code**
   - Complete source code repository
   - README file including environment configuration, startup guide and dependency list
3. **Demo Video**
   - Recommended duration: 3–5 minutes
   - Demonstrate the actual operation process
   - The actual execution performance on an AMD Radeon GPU, from command line/GUI to the final result (fluidity and functional completeness)
4. **Supplementary Materials (Choose One)**
   - PPT / Poster

### Track 3: Physical AI Challenge – Robotics Simulation and Application Design based on AMD Radeon GPUs and ROCm

1. **Technical Report** (should include, but is not limited to):
   - Definition and description of the target application
   - Overall system architecture and solution design
   - Description of the datasets used for training and/or evaluation
   - Explanation of how AMD Radeon GPUs are utilized during training, inference, and other relevant stages
   - Description of the innovations, key technical contributions, and important aspects of the project
   - Description of the final deliverables and output forms of the project
   - Any additional information that participants believe highlights the strengths or unique aspects of their work
   - Introduction of team members and their respective contributions
2. **Project Source Code**
   - Dedicated source code repositories
   - A Docker image containing the complete source code and all required components for running the project would be preferable
3. **Reproducibility Instruction README** — a detailed README document containing:
   - Environment setup instructions
   - Execution and usage instructions
   - Dependency specifications
   - Step-by-step reproduction procedures
   - Following the provided instructions should allow evaluators to reproduce the submitted results
4. **Demonstration Video** (Recommended Length 3~5 minutes)
   - The video should demonstrate the complete workflow of the project, including command-line and/or GUI operations, execution procedures, and results
5. **Supplementary materials** in other formats may be submitted to demonstrate the value of the proposed technical solution.
