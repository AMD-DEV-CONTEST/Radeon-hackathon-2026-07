# QuakeSense — AMD AI DevMaster Hackathon 2026, Track 2

> [!IMPORTANT]
> ▶️ **[Watch the final QuakeSense demo online on Bilibili](https://www.bilibili.com/video/BV1MbuH6KE18/)**
> 
> The high-quality submitted MP4 remains available in [demo/](demo/).

QuakeSense is a locally deployed agentic AI system for auditable, city-scale earthquake evacuation experiments. Local language-model leaders observe jurisdiction state, keep compact memory, emit grammar-constrained actions, and change destination allocation while the physical simulator enforces road throughput, shelter capacity, and population conservation.

**Participant:** Bian Chunlin (`bcl200n`)

**Track:** Track 2 — Development & Local Deployment of Private AI Agents

**Application:** QuakeSense

## Official deliverables

| Requirement | Submission artifact |
|---|---|
| Project specification | [`docs/QuakeSense_Project_Specification_EN.md`](docs/QuakeSense_Project_Specification_EN.md) |
| Complete public-safe source | [`source/`](source/) |
| Environment, startup, dependencies | [`source/README.md`](source/README.md), [`source/requirements.txt`](source/requirements.txt) |
| Demo video | [`demo/QuakeSense_Agentic_AI_AMD_Track2_Demo_EN.mp4`](demo/QuakeSense_Agentic_AI_AMD_Track2_Demo_EN.mp4) |
| Supplementary presentation | [`docs/QuakeSense_AMD_Track2_Deck_EN.pptx`](docs/QuakeSense_AMD_Track2_Deck_EN.pptx) |
| Seven-city animated evidence | [`public_demo/`](public_demo/) |
| Radeon/ROCm evidence map | [`evidence/README.md`](evidence/README.md) |
| Online demo playback | [Watch the final QuakeSense demo on Bilibili](https://www.bilibili.com/video/BV1MbuH6KE18/) |

## Public demonstration

The editable presentation ([`docs/QuakeSense_AMD_Track2_Deck_EN.pptx`](docs/QuakeSense_AMD_Track2_Deck_EN.pptx)) consists of **39 slides** covering **10 city evacuation scenarios** with animated GIFs and detailed map analysis.

The `public_demo/` interactive viewer contains seven overseas city scenarios: Los Angeles, Naples, Wellington, L'Aquila, Noto, Kumamoto, and Kathmandu. They use a common animated evidence interface so reviewers can compare the complete evacuation process rather than isolated static charts.

```bash
python -m http.server 8765 --directory submissions/track2-quakesense/public_demo
```

Open `http://127.0.0.1:8765/web/viewer.html?city=los_angeles&frame=18`.

## Validation

```bash
cd submissions/track2-quakesense/source
python -m pytest tests claude/tests -q
cd ..
python tools/verify_submission.py .
```

## Evidence boundary

The public payloads are synthetic, capacity-constrained scenarios. They are not observed individual trajectories, forecasts, or official emergency plans. Private city inputs, personal data, credentials, model weights, large rasters, generated caches, and unpublished run outputs are intentionally excluded. The included source is the complete public-safe implementation needed to inspect the mechanisms, agent logic, tests, and animated review surface.

## AMD acknowledgment

We gratefully acknowledge AMD for cloud computing resources used for large-scale preparation, simulation, rendering, and validation. Local inference and performance evidence were produced on AMD Radeon through ROCm. This acknowledgment does not imply AMD endorsement of the methods, scenarios, results, or conclusions.
