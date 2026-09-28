# License and rights review

This is an engineering rights inventory, not legal advice or commercial
clearance. No final application-source license has been selected.

| Material | Current basis | Submission treatment | Remaining action |
|---|---|---|---|
| BrandPilot application source | Original team work | Public source in development and official submission repositories | Select and add an OSI license only after owner approval and compatibility review |
| SDXL base 1.0 model | Stability AI CreativeML Open RAIL++-M terms apply to the model | Model ID/revision only; no weights are redistributed | Review intended production/commercial use against current model terms |
| PyTorch, FastAPI, Next.js, Diffusers, Pillow, and other dependencies | Their upstream package licenses | Dependencies declared by manifests/requirements; no dependency source bundled | Generate final SBOM/license report before production distribution |
| Rights-safe example product image | Team-created synthetic demonstration asset | Included at `examples/browser-test-product.png`; used in screenshots/evidence | Keep provenance statement with submission |
| Generated Radeon output | Created from the rights-safe example during the verified run | Included as technical evidence with parameters/hash | Treat as prototype output; do not claim trademark or packaging fidelity |
| UI screenshots | Captured from the original BrandPilot interface using the example asset | Included as PNG evidence | Continue sanitization and hash verification |
| Icons | Original inline SVG icon system in `frontend/components/icons.tsx` | Source included; no third-party icon binary bundle | Retain source attribution if third-party shapes are introduced later |
| Fonts | Browser/system fonts only; no font binaries committed | CSS fallbacks and available system fonts | Do not bundle proprietary font files without a license |
| Presentation/Profile assets | Original layouts plus repository screenshots/evidence | PPTX/PDF/source content included | Confirm exported metadata contains no private details |
| Demo audio/music | No music included | Narration-only recording package | Add music only with documented compatible license |

## Submission rights rules

- Use only self-created or rights-cleared inputs.
- Do not add client/customer assets, competitor UI captures, browser-profile
  data, account identifiers, private correspondence, or private infrastructure
  information.
- Do not commit model weights, Hugging Face caches, font binaries, or raw
  environment dumps.
- Keep model/source commercial clearance explicitly unresolved.
- The hackathon Rules grant AMD broad rights in submitted entry materials;
  team members should review those terms before final submission.
