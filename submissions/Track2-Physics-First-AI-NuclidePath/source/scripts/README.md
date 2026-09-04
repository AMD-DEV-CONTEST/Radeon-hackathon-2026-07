# NuclidePath scripts

Every script here is reproducible tooling: benchmarks that produce the evidence
under `artifacts/`, generators that produce the submission package, and gates
that CI enforces. Nothing in `submission/` or `docs/assets/` is hand-authored.

## Editorial and submission artifacts

These generate the judged package. Run them in this order after changing the
underlying Markdown, because the contact sheets are rendered from the deck and
specification PDFs:

| Script | Produces | Notes |
|---|---|---|
| `generate_deck.js` | `submission/NuclidePath_Track2_Deck.pptx` | Node + `pptxgenjs`; the ten Track 2 slides and their stat tiles are declared inline |
| `generate_spec_pdf.js` | `submission/NuclidePath_Project_Specification.pdf` | Renders `docs/SPECIFICATION.md` through headless Chromium (Playwright) |
| `generate_spec_pdf_fallback.py` | same PDF | ReportLab fallback for environments without Chromium; keep its cover stats in step with `generate_spec_pdf.js` |
| `generate_contact_sheets.py` | `docs/assets/{deck,spec,video}-contact.png` | Visual-QA grids of the deck slides, specification pages and video cards; needs `pdftoppm` and Pillow |
| `generate_current_video_assets.py` | `private-deliverables/current-video-assets/slide-*.png` | The six cards used by the current demo video |
| `generate_demo_video.py` | narrated demo video master (MP4) | Assembles cards, narration and timing; subprocesses use argv lists, never a shell |
| `generate_video_subtitles.py` | `private-deliverables/*.srt` | Proportional paragraph-level captions derived from `docs/VIDEO_NARRATION.md` |
| `split_pptx_for_qa.py` | one-slide PPTX files | Stdlib-only splitter for per-slide visual review |

The deck PDF (`submission/NuclidePath_Track2_Deck.pdf`) is converted from the
generated PPTX with LibreOffice Impress:

```bash
soffice --headless --convert-to pdf --outdir submission submission/NuclidePath_Track2_Deck.pptx
```

After regenerating any artifact, refresh its SHA-256 and byte size in
`submission/ARTIFACT_MANIFEST.json` — the manifest is the integrity record for
all twenty-two tracked artifacts.

## Benchmarks and AMD evidence

Each writes into a dated directory under `artifacts/`. They are the only source
of the performance numbers quoted in the documentation, and every quoted figure
must name the snapshot it came from.

| Script | Purpose |
|---|---|
| `amd_preflight.sh` | Records the AMD/ROCm environment (`rocminfo`, `gpu-smi`) before a run |
| `check_amd_environment.sh` | Verifies ROCm/torch visibility and device sanity |
| `amd_validation_run.sh` | Orchestrates a full AMD validation run into `artifacts/*/validation-current/` |
| `amd_torch_benchmark.py` | PyTorch/ROCm micro-benchmark |
| `amd_transport_benchmark.py` | FP64/FP32 transport benchmark |
| `benchmark_amd_platform.py` | Device-resident GCS to transport to receptor platform benchmark |
| `benchmark_primary_gcs.py` | Exact batched primary Bradbury GCS benchmark |
| `benchmark_phase_b.py` | Dependency-light Phase B benchmark and parity smoke run |

## Gates and environment

| Script | Purpose |
|---|---|
| `check_workflow_security.py` | Enforces the exact workflow security policy; run by CI and reproducible locally |
| `update_ci_lock.sh` | Regenerates or checks the hash-locked `requirements/ci.txt` (`--check` in CI) |
| `install_phreeqc_3_9_0.sh` | Installs the pinned PHREEQC 3.9.0 build used for trusted manual qualification |

`install_phreeqc_3_9_0.sh` supports the manual, trusted qualification workflow
only. Do not run the PHREEQC workflow automatically, from a feature branch, or
from an untrusted ref — see [CI and runner trust boundary](../docs/CI_SECURITY.md).
