# Pull Request Template

Use this text when opening the submission PR against the upstream repository.
The registered Luma team name is 炉火 (Luhuo).

---

## PR title

Track 2, 炉火, RadeonPilot

## PR body

### Project

**RadeonPilot** — a multi-agent console that performs the full inference-operations
loop on a single AMD Radeon GPU: diagnose the ROCm environment, deploy the local
model endpoint, benchmark it, locate bottlenecks, and propose validated
optimizations. Every agent generation is served by the Radeon itself.

All materials are in English and live under `radeonpilot/` in this PR.

### Track 2 deliverables in this PR

1. **Project Specification Document**
   - `radeonpilot/docs/PROJECT_SPECIFICATION.md` (+ `PROJECT_SPECIFICATION.pdf`)
   - Covers application scenarios, agent architecture diagram, core capabilities,
     model introduction & local deployment plan, and inference-speed optimization
     on the AMD Radeon GPU.
2. **Project Source Code**
   - Complete repository under `radeonpilot/`
   - `radeonpilot/README.md` with environment configuration, startup guide, and
     dependency list
   - Step-by-step judge-facing reproduction: `radeonpilot/docs/REPRODUCE.md`
3. **Demo Video**
   - Script and shot list: `radeonpilot/docs/DEMO_SCRIPT.md`
   - Video link: `radeonpilot/submission/links.json`
4. **Supplementary Material**
   - Poster: `radeonpilot/docs/POSTER.pdf`

### Measured evidence

Benchmark JSON captured on the organiser-provided Radeon Cloud instance
(gfx1100, 48 GB, ROCm 7.2.1) is committed under `radeonpilot/benchmarks/results/`.
Each record contains raw samples, the prompt hash, VRAM peak, and amd-smi device
attestation. No numbers are fabricated.

### Quick start

```bash
cd radeonpilot
bash scripts/setup_server.sh        # on the Radeon instance
bash scripts/start_endpoint.sh      # local ROCm endpoint
bash scripts/run_bridge.sh          # Pi multi-agent bridge
RADEONPILOT_MODE=pi bash scripts/run_app.sh   # Gradio console
```

See `radeonpilot/docs/REPRODUCE.md` for checkpoints and troubleshooting.
