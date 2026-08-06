## Track 2 submission: radeon-fix

**radeon-fix** is a private, CLI-driven AI code-repair agent for local git
repositories. It runs one Qwen3-14B BF16 model on an AMD Radeon GPU
(gfx1100, 51.52 GB VRAM, RadeonX Cloud) with ROCm and vLLM, and produces an
auditable patch without modifying the user's repository.

### Submission materials (folder: `Track2-radeon-fix/`)

1. **Project Specification** - `Project-Specification.pdf`
   - Application scenarios
   - Agent architecture diagram
   - Core capabilities
   - Model introduction and local deployment plan
   - Inference-speed optimization on AMD Radeon / ROCm
2. **Complete source code** - full repository with README, environment
   configuration, startup guide, and dependency list (MIT licensed).
3. **Demo video** - `demo/radeon-fix-demo.mp4` (3:38, 1920x1080): a real
   `radeon-fix` run on the AMD instance, from CLI input to generated code,
   patch output, and 7/7 passing tests, with the Radeon GPU metrics report.
4. **Supplementary material** - `Poster.pdf` / `Poster.png` (16:9).

### Highlights

- Product cell: Aider Repo Map + one focused refresh (C1R1), budget-aware
  mini-SWE controller (A1), xgrammar structured actions with Edit V2 exact
  replace (J3), and a deterministic verifier with at most one repair (V1R1).
- Fully local and private: vLLM endpoint on loopback only, no external model
  APIs, no training.
- Measured on AMD Radeon gfx1100: TTFT p50 103.97 ms, decode p50 25.66
  tokens/s, vLLM prefix caching cuts TTFT up to ~18x at 4K input and ~77x at
  16K input, xgrammar gives 100% schema-valid structured actions (189/189).
- Development gate: 5/5 non-empty patches, 5/5 applied exact replacements,
  38/38 valid J3 actions, zero integrity or API failures.
- Demo project (`examples/demo_project`): repaired in about 2 minutes 20
  seconds on the AMD instance; patch applies cleanly and all 7/7 tests pass.

All materials, descriptions, and this pull request are in English.
