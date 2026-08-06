# AMD AI DevMaster Hackathon — Track 2 Workspace

This workspace is the preparation package for a three-person Track 2 team building a private, locally deployed AI Agent on AMD Radeon PRO W7900 (48 GiB) and ROCm.

## Judge quick start

The complete local product path was tested at exact implementation
`c9ec07489d17a2abb74bac66a23ade2c775c1b06` and merged through PR #52. The
sanitized W7900 result is under
`evidence/milestones/e8-a0-w7900/20260806T122806Z/` on `main`. Before judging,
use the final repository commit that contains that implementation plus the
submission materials and final launcher; record that exact commit in the demo.

The judge-facing submission package is indexed at
[`docs/submission/e9/FINAL_SUBMISSION_INDEX.md`](docs/submission/e9/FINAL_SUBMISSION_INDEX.md).
The Project Specification, English PPT and supporting submission documents are
ready; the Demo video and publication-time links remain separate.

### 1. Prepare the persistent workspace

```bash
cd /workspace
git clone https://github.com/kinnyuww/amd-devmaster-track2-agent \
  amd-track2-agent/repo
cd amd-track2-agent/repo
export FINAL_SUBMISSION_COMMIT=c4d14bf042ad53baa9b726a0e11fbd9ffd37e5fd
git checkout "$FINAL_SUBMISSION_COMMIT"
bash scripts/bootstrap_workspace.sh
bash scripts/verify_remote_dev.sh
bash scripts/verify_rocm_env.sh
bash scripts/install_agent_env.sh
bash scripts/install_vllm_rocm721.sh
```

Python application dependencies are pinned in `pyproject.toml` and
`requirements-agent.txt`. Frontend dependencies are locked in
`web/package-lock.json`. vLLM remains in its separate ROCm environment and is
installed through `scripts/install_vllm_rocm721.sh`.

The commit above is the current reproducible `main` snapshot containing the
accepted product path and final P1/S0 launcher before the E9 documentation PR
is integrated. The exact W7900 product evidence remains bound to `c9ec074`.

### 2. Start the verified local model

The verified profile uses `Qwen/Qwen3.5-9B` revision
`460979c3d11864dd16408d860ac930a360a2fac2`, BF16, no quantization, vLLM
0.26.0, ROCm/HIP 7.2 and a 20K maximum context on Radeon PRO W7900. The
selected P1 launcher and its S0 rollback are merged through PR #58:

```bash
export MODEL_PATH=/workspace/amd-track2-agent/models/Qwen3.5-9B-460979c3d118
export SERVING_PROFILE=P1-prefix-cache
bash scripts/serve_final_vllm.sh
```

If P1 cannot start, set `SERVING_PROFILE=S0`; no other application or model
setting changes. The launcher verifies the immutable model manifest and refuses
a non-loopback bind.

### 3. Start the Agent API

From a second terminal:

```bash
cd /workspace/amd-track2-agent/repo
source /workspace/amd-track2-agent/venvs/agent/bin/activate
export EXPERIENCE_ASSET_DB=/workspace/amd-track2-agent/data/experience_asset.sqlite3
export EXPERIENCE_WORKFLOW_DB=/workspace/amd-track2-agent/data/experience_asset.workflow.sqlite3
export CODE_COMMIT="$(git rev-parse HEAD)"
export OPENAI_BASE_URL=http://127.0.0.1:8000/v1
export SERVED_MODEL_NAME=Qwen3.5-9B
export GPU_VIABILITY=VERIFIED
uvicorn app.experience_asset.api.main:app --host 127.0.0.1 --port 8080
```

### 4. Start the Web UI

From a third terminal:

```bash
cd /workspace/amd-track2-agent/repo/web
npm ci
VITE_PROXY_TARGET=http://127.0.0.1:8080 \
  npm run dev -- --host 127.0.0.1 --port 5173
```

Open `http://127.0.0.1:5173/?view=m1&source=live`. The visible workflow is
M1 Experience Brief -> M2 Critical Moment Map -> M3 Decision and Evidence
Ledger -> M4 Insight and Boundary Map -> M5 Route Readiness Matrix -> private
preview and approved HTML/Markdown/JSON export. Managed export files remain
under `/workspace/amd-track2-agent/data/exports`.

For the public judging path, use the synthetic scenario represented by
`web/e2e/m4.spec.ts::live M4 insight and boundary map journey` and follow the
visible milestone navigation. The accepted flow generates M1-M4, opens
canonical evidence, applies an upstream correction, invalidates and regenerates
downstream work, then selects `PRIVATE_SELF` at M5 and produces private HTML,
Markdown and JSON deliverables.

The exact accepted implementation completed this live browser journey in
approximately 2.0 minutes with S0 and 109.21 seconds with P1. Each profile was
observed once and both passed; this is a bounded integration check, not a
generalized performance claim. The P1 log showed 0.0% cache hit, and Stage 2
peak VRAM was not measured.

The services bind to loopback by default. Do not expose them publicly without
the documented authentication and publication review.

## Start here

- [Team coding-Agent specification entry point](spec/README.md)
- [Proportional development and review standard](spec/DEVELOPMENT_STANDARD.md)
- [Engineering evidence retention contract](spec/EVIDENCE_RETENTION.md)
- [Competition and group summary](docs/COMPETITION_AND_GROUP_SUMMARY.md)
- [Approved Experience Asset P0 requirement](docs/kinnyu/CURRENT_ITERATION.md)
- [Approved L3 engineering execution plan](docs/kinnyu/L3_ENGINEERING_PLAN.md)
- [E2–E8 milestone-owner pipeline proposal](docs/kinnyu/E2_E8_PIPELINE_EXECUTION_PLAN.md)
- [Selected Track 2 Agent architecture](docs/team-alignment/AGENT_ARCHITECTURE.md)
- [Master competition task board, readiness and three-member checklist](docs/COMPETITION_READINESS_CHECKLIST.md)
- [Official Track 2 requirements, project-plan coverage and gap audit](docs/COMPETITION_REQUIREMENT_COVERAGE.md)
- [Team and AI-Agent discovery package](docs/team-alignment/README.md)
- [Visual product and system blueprint](docs/team-alignment/PRODUCT_BLUEPRINT.md)
- [Track 2 benchmark and ROCm optimization plan](docs/team-alignment/BENCHMARK_PLAN.md)
- [Active team quality contract](docs/team-alignment/TEAM_QUALITY_CONTRACT.md)
- [Public engineering evidence index](evidence/README.md)
- [Executable public QA framework](qa/README.md)
- [Quality-owner runbook](qa/QUALITY_OWNER_RUNBOOK.md)
- [Development environment guide](docs/DEVELOPMENT_ENVIRONMENT.md)
- [Prepared E3/M2 W7900 execution handoff](docs/E3_M2_W7900_HANDOFF.md)
- [Three-person Git and persistence workflow](docs/TEAM_GIT_WORKFLOW.md)
- [Primary/DeepSeek worker handoff](docs/REMOTE_AGENT_HANDOFF.md)
- [Optional authenticated public demo tunnel](docs/PUBLIC_DEMO_TUNNEL.md)
- [Latest work report](docs/WORK_REPORT_2026-07-22.md)
- [Initial research report](docs/WORK_REPORT_2026-07-21.md)
- [Official contest repository](https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07)
- [Official Radeon Cloud guide](https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07/tree/main/Radeon-Cloud-User%20Guide)

## Prepared commands for Radeon Cloud

Run everything under `/workspace`; other paths may disappear when the pod is rebuilt.

```bash
cd /workspace
git clone <team-repository-url> amd-track2-agent/repo
cd amd-track2-agent/repo
bash scripts/bootstrap_workspace.sh
bash scripts/verify_remote_dev.sh
bash scripts/verify_rocm_env.sh
```

If a newly rebuilt pod has SSH enabled in its template but the base image omits
the server, run `bash scripts/ensure_sshd.sh` once from the Radeon Cloud
terminal, then retry the `amd-radeon` SSH alias from the Mac.

Install the remote coding agents and the two Python environments only when
needed:

```bash
bash scripts/install_coding_agents.sh
source scripts/activate_remote_env.sh
bash scripts/install_agent_env.sh
bash scripts/install_vllm_rocm721.sh
```

The optional DeepSeek development worker is currently deferred. The existing
AMD shared endpoint exposes Chat Completions, while the installed Codex CLI
uses Responses. Keep the helper unused until the team obtains and reviews a
Responses-compatible service; never store its key in this repository.

If a future approved bounded text-only test is needed, the helper remains:

```bash
read -rsp "AMD model API key: " AMD_MODEL_API_KEY
echo
export AMD_MODEL_API_KEY
python3 scripts/deepseek_worker.py "Summarize this benchmark output: ..."
```

Before the first 14B run, download the exact ModelScope revision and verify the
local snapshot as documented in `docs/DEVELOPMENT_ENVIRONMENT.md`. The default
server wrapper refuses to start the 14B candidate input profile if any listed
file is missing or has the wrong SHA-256.

Start the frozen BF16 candidate input profile. Its inputs and E1-A3 viability
evidence were accepted during PR #7 review, but this remains an engineering
profile rather than the formal E8 performance Baseline:

```bash
bash scripts/serve_vllm.sh
```

From a second terminal, verify that Qwen/vLLM can produce a structured tool
proposal. This does not authorize tool execution; the application Runtime owns
that decision.

```bash
python3 scripts/verify_vllm_tool_call.py --model Qwen2.5-14B-Instruct
```

Validate the full ROCm/API path with a small public smoke model before a large
download:

```bash
# Set HF_ENDPOINT only when using a reviewed compatible endpoint, or pass a
# local MODEL_ID path downloaded from an approved source.
MODEL_ID=Qwen/Qwen2.5-0.5B-Instruct bash scripts/smoke_vllm_server.sh
```

The vLLM endpoint binds to `127.0.0.1` by default. If a public judge-facing
demo is needed, expose an authenticated Web UI through the official
`rc-tunnel`; do not expose vLLM itself.

From a second terminal:

```bash
python scripts/benchmark_openai_api.py \
  --base-url http://127.0.0.1:8000/v1 \
  --model Qwen2.5-14B-Instruct
```

## Repository layout

```text
.
├── spec/                         # Stable teammate/coding-Agent alignment entry
├── docs/                         # Decisions, official facts, setup, work report
├── config/codex/                 # No-secret local vLLM provider/profile example
├── config/models/                # Frozen model source/revision/file manifests
├── config/runtime/               # Frozen known-good runtime wheel identities
├── official/                     # Read-only clone of the official AMD contest repo
├── scripts/                      # Idempotent cloud setup and verification helpers
├── .vscode/                      # Remote interpreter, PATH and extension recommendations
├── AGENTS.md                     # Shared Codex/coding-agent repository rules
├── CLAUDE.md                     # Claude Code project context
├── requirements-agent.txt        # Agent application environment
└── .env.example                  # Non-secret runtime configuration template
```

Do not commit API keys, model tokens, private data, or SSH private keys.
Coding agents must not commit or push unless the user explicitly asks after
reviewing the diff.
