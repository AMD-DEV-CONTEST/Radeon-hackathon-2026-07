# Contribution Guide & PR Submission Process (Fork & PR Guide)

> Per the competition requirements: fork the designated GitHub repository subdirectory and submit the work via Pull Request for official review.

---

## Part 1: Fork & PR Submission Process

### Step 1: Fork the official repository

1. Log in to GitHub and visit the competition-specified official repository
2. Click the **Fork** button in the upper right corner to fork the repository into your personal account
3. After confirming the fork, your repository URL will look like: `https://github.com/<your-username>/<official-repo-name>`

### Step 2: Clone your Fork

```bash
git clone https://github.com/<your-username>/<official-repo-name>.git
cd <official-repo-name>
```

### Step 3: Add the upstream repository (to sync official updates)

```bash
git remote add upstream https://github.com/<official-org>/<official-repo-name>.git
git fetch upstream
```

### Step 4: Create a submission branch

```bash
# Create a submission branch from main
git checkout main
git pull upstream main
git checkout -b track2-insurance-rag-agent
```

### Step 5: Add the project files

Copy all files under the `insurance-rag-agent/` directory into the corresponding subdirectory of the repository:

```bash
# Assuming the official repository requires placement under the track2/ subdirectory
mkdir -p track2/insurance-rag-agent
cp -r insurance-rag-agent/* track2/insurance-rag-agent/

# Confirm the files have been copied
ls -la track2/insurance-rag-agent/
```

### Step 6: Check the pre-commit checklist

Before committing, ensure the following files are all included:

| Check item | File path | Status |
|--------|----------|------|
| README.md | `track2/insurance-rag-agent/README.md` | Included |
| Project specification document | `track2/insurance-rag-agent/docs/SPECIFICATION.md` | Included |
| Architecture diagram document | `track2/insurance-rag-agent/docs/ARCHITECTURE.md` | Included |
| Deployment plan | `track2/insurance-rag-agent/docs/DEPLOYMENT.md` | Included |
| GPU environment evidence | `track2/insurance-rag-agent/docs/GPU_ENVIRONMENT.md` | Included |
| ROCm optimization notes | `track2/insurance-rag-agent/docs/ROCm_OPTIMIZATION.md` | Included |
| Reproduction guide | `track2/insurance-rag-agent/docs/REPRODUCTION.md` | Included |
| Complete source code | `track2/insurance-rag-agent/src/` | Included |
| Configuration files | `track2/insurance-rag-agent/configs/` | Included |
| Startup scripts | `track2/insurance-rag-agent/scripts/` | Included |
| Demo samples | `track2/insurance-rag-agent/demo/` | Included |
| Dependency list | `track2/insurance-rag-agent/requirements.txt` | Included |
| Key template | `track2/insurance-rag-agent/.env.example` | Included |
| License | `track2/insurance-rag-agent/LICENSE` | Included |

### Step 7: Confirm .gitignore

Ensure the following sensitive files are not committed:

```gitignore
# .gitignore
.env
models/
.agently/
__pycache__/
*.pyc
docs/benchmarks/logs/
*.log
```

> The `.env` file contains API keys and must **never be committed**. Only the `.env.example` template should be kept in the repository.

### Step 8: Commit and push

```bash
git add .
git commit -m "feat: add Insurance RAG Agent for Track 2

- Agently 4.1.4.1 framework with 5-step business flow
- FAISS RAG + Workspace persistence + layered memory
- vLLM on ROCm with INT4 quantization optimization
- Full documentation: spec, architecture, deployment, optimization, reproduction
- Demo samples and benchmark scripts"

git push origin track2-insurance-rag-agent
```

### Step 9: Create a Pull Request

1. Open your Fork repository on GitHub
2. Click the **Compare & pull request** button
3. Select the branch: `track2-insurance-rag-agent` → `official-repo:main`
4. Fill in the PR title and description (template below)
5. Click **Create pull request**

### PR Title Template

```
[Track 2] Insurance RAG Agent — Agently + vLLM ROCm Local Deployment
```

### PR Description Template

```markdown
## Project Information

- **Track**: Track 2: Private AI Agents
- **Project Name**: Insurance RAG Agent
- **Tech Stack**: Agently 4.1.4.1 + vLLM (ROCm) + FAISS + BGE-M3
- **Platform**: AMD Radeon GPU + ROCm 6.5+

## Core Capabilities (5/5)

- [x] Local knowledge retrieval (RAG) — FAISS ANN + Workspace packaging
- [x] Tool invocation — file_tools / doc_tools / data_query
- [x] Multi-step task planning — TriggerFlow five-step orchestration + reflection validation
- [x] Local multi-turn memory — Session short-term + Namespace long-term
- [x] Permission control & privacy protection — directory whitelist + scope filtering + audit log

## Documentation List

- [x] README.md — quick start + environment setup + startup guide
- [x] docs/SPECIFICATION.md — project specification document
- [x] docs/ARCHITECTURE.md — Agent architecture diagram
- [x] docs/DEPLOYMENT.md — model & local deployment plan
- [x] docs/ROCm_OPTIMIZATION.md — ROCm inference optimization notes
- [x] docs/REPRODUCTION.md — offline reproduction guide
- [x] demo/demo_script.md — Demo recording script

## Reproduction Method

```bash
bash scripts/setup_rocm.sh          # environment installation
bash scripts/download_models.sh     # model download
python scripts/build_index.py       # index building
python scripts/start_agent.py       # start the Agent
```

## GPU Evidence

- GPU: AMD Radeon Graphics (gfx1100, RDNA 3)
- VRAM: 48 GB
- ROCm: 6.16.13 (HSA Runtime 1.18)
- CPU: 2× AMD EPYC 9334 (64 cores)
- Platform: Radeon Cloud remote container
- Inference backend: vLLM 0.6.x (ROCm)
- Optimization comparison: C0 baseline (FP16) vs C4 large-VRAM specialization (FP16 + 16 concurrency) → 3.7x tok/s improvement
- Environment evidence: docs/GPU_ENVIRONMENT.md
```

---

## Part 2: Branch Management

### Branch Naming Convention

```
track2-<project-name>     # main submission branch
track2-<project-name>-dev # development branch (optional)
```

### Syncing official updates

```bash
# Fetch upstream updates
git fetch upstream
git checkout main
git merge upstream/main
git push origin main

# Merge the updates into the submission branch
git checkout track2-insurance-rag-agent
git rebase main  # or git merge main
```

---

## Part 3: Commit Conventions

### Commit Message Format

```
<type>: <description>

[optional body]
```

**Type values**:

| Type | Description |
|------|------|
| `feat` | New feature |
| `fix` | Bug fix |
| `docs` | Documentation update |
| `refactor` | Code refactoring |
| `perf` | Performance optimization |
| `test` | Test-related |
| `chore` | Build/tooling changes |

**Examples**:

```
feat: add FAISS indexer with IndexFlatIP support
fix: resolve Session resize handler edge case
docs: add ROCm optimization comparison table
perf: enable prefix caching for vLLM C3 config
```

---

## Part 4: Coding Conventions

### Python Code

- Python 3.11+, with type hints
- Follow PEP 8 style
- Use `from __future__ import annotations` to support `str | None` syntax
- Module-level docstrings explaining responsibilities
- Function docstrings explaining Args and Returns

### Configuration Files

- TOML format, key-value pairs assigned with `=`
- Add comments to each section explaining its purpose
- Sensitive information (API keys) is referenced via `auth_env` environment variables, never hardcoded

### Documentation

- Markdown format
- Chinese as the primary language, technical terms kept in English
- Prefer tables over long paragraphs
- Annotate the language of code blocks
- Use Mermaid diagrams for architecture visualization