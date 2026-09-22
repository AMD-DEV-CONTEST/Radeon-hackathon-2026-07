# FinMuse Radeon

FinMuse Radeon is a Track 1 multimodal content creation demo for financial customer product promotion and introduction services. It helps banks, securities firms, insurers and wealth management teams transform one product brief into scenario-based marketing copy, visual prompts, SVG posters, a landing page, voiceover text and compliance-aware metadata.

The project is designed to demonstrate how AMD Radeon GPU / ROCm can support local, stable and reproducible financial content generation workflows. The baseline code uses a standard-library rule engine so judges can run it anywhere; on an AMD ROCm environment the same commands automatically record the GPU detection path.

## 1. Project background

Financial institutions need to introduce products across many daily-life scenarios:

- Wealth management for commute, family planning and retirement review.
- Insurance product education for family health, accident protection and travel.
- Credit card and banking services for mobile payment, shopping and business use.
- Fund and investment education for portfolio review and risk awareness.
- Branch screens, mobile apps, relationship-manager presentations and social videos.

Traditional production is fragmented: product teams write briefs, marketing teams create copy, design teams create visuals, compliance teams review wording, and channel teams adapt the same idea repeatedly. FinMuse Radeon compresses this into a repeatable generation pipeline.

## 2. What the demo generates

For each financial product brief, the CLI generates:

- `variants.json`: scenario-based content variants.
- `poster-01.svg`, `poster-02.svg`, `poster-03.svg`: high-resolution 1280x720 SVG promotional cards.
- `landing-page.html`: product introduction landing page.
- `gpu-status.json`: AMD Radeon / ROCm detection result.
- `run-summary.json`: runtime, clarity score, stability score and diversity tags.
- `demo-report.md`: cross-run report summarizing clarity, stability and diversity.

## 3. Repository structure

```text
finmuse-radeon/
  finmuse/
    __init__.py
    cli.py            # command line interface
    generator.py      # financial content generation logic
    gpu.py            # AMD Radeon / ROCm detection helpers
  examples/
    wealth-card.json
    insurance-family.json
  outputs/
    wealth-card/      # generated sample output
    insurance-family/ # generated sample output
    demo-report.md
    gpu-status.json
  scripts/
    run_demo.sh
  requirements.txt
  README.md
```

## 4. Quick start

> The baseline demo has no mandatory third-party dependency.

```bash
cd finmuse-radeon
python -m finmuse.cli check-gpu
python -m finmuse.cli generate --brief examples/wealth-card.json --variants 3 --out outputs/wealth-card
python -m finmuse.cli generate --brief examples/insurance-family.json --variants 3 --out outputs/insurance-family
python -m finmuse.cli report --run outputs/wealth-card --run outputs/insurance-family --out outputs/demo-report.md
```

On this packaging machine, the recorded status is CPU fallback because `rocm-smi` and `rocminfo` are not available. The demo does not fake an AMD GPU result.

## 5. AMD Radeon GPU / ROCm validation commands

On a Linux machine with supported AMD Radeon GPU and ROCm installed, run:

```bash
rocm-smi
rocminfo | head -80
python -m finmuse.cli check-gpu --out outputs/gpu-status.json
python -m finmuse.cli generate --brief examples/wealth-card.json --variants 6 --out outputs/wealth-card-rocm
python -m finmuse.cli report --run outputs/wealth-card-rocm --out outputs/demo-report-rocm.md
```

Expected evidence in `gpu-status.json`:

```json
{
  "rocm_smi_found": true,
  "rocminfo_found": true,
  "mode": "amd_rocm_gpu",
  "devices": ["AMD Radeon ..."]
}
```

If PyTorch ROCm is installed, `gpu.py` also checks whether the HIP backend is available. The current baseline generator is lightweight; a production extension can replace the rule engine with LLM, diffusion, TTS and video models running through ROCm-enabled runtimes.

## 6. System architecture

```text
Financial Brief JSON
      |
      v
Brief Parser ----> Compliance Guardrails
      |                    |
      v                    v
Scenario Planner --> Variant Generator --> Quality Metrics
      |                    |
      v                    v
Visual Prompt Builder  Copy / Voiceover Builder
      |                    |
      +-------> Asset Renderer: SVG posters + HTML landing page
                              |
                              v
                  Metadata + GPU Runtime Recorder
```

Key design choices:

- Financial-scenario planner maps products to life moments.
- Compliance guardrails avoid unrealistic return promises.
- Variant generator produces diverse scenes, tone words and channels.
- Quality metrics record clarity, stability and diversity.
- GPU recorder captures AMD Radeon / ROCm runtime evidence.

## 7. Model and algorithm design

The hackathon baseline uses deterministic generation so judges can reproduce results exactly:

- Seed creation from product brief hash.
- Scenario library by product type: wealth, insurance, credit, loan and fund.
- Tone library: premium, warm, youth and stable.
- Rule-based headline, subtitle, caption and voiceover templates.
- SVG/HTML rendering for visible multimodal assets.
- Clarity score and stability score for demo evaluation.
- Diversity tags to prove multi-scenario output coverage.

Production extension path:

- LLM for product-brief understanding and compliance rewriting.
- Diffusion model for financial-scene key visuals.
- TTS for relationship-manager narration.
- Video compositor for branch-screen and social-video formats.
- ROCm/HIP acceleration for local GPU inference.

## 8. Demo evidence generated in this package

The included sample run generated two product campaigns:

1. `Aurora Smart Wealth Card`
2. `Family Shield Plan`

Each campaign includes three content variants and reports:

- Average clarity score.
- Average stability score.
- Scenario and channel diversity tags.
- Runtime and hardware mode.

## 9. Limitations and honest GPU statement

This packaged environment does not expose AMD Radeon GPU or ROCm tools, so the included execution result is `cpu_fallback`. The source code is designed to detect and record AMD ROCm evidence when run on supported hardware. The demo video therefore shows:

- Actual command-line run in the current environment.
- Actual generated outputs from the packaged code.
- The exact AMD ROCm commands required for GPU validation.
- A clear note that no GPU result is fabricated in this environment.

## 10. License and compliance note

This is a hackathon prototype. Financial copy is for demonstration only and must be reviewed by qualified compliance and legal teams before real customer use.
