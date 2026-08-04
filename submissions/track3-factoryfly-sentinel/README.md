# FactoryFly Sentinel

**Human-Guided Physical AI for Active Factory Inspection**

- **Track:** Track 3 — Physical AI Challenge
- **Participant:** Jaewon Lee
- **Team:** Solo participant
- **Application:** FactoryFly Sentinel
- **Version:** v7.3.13

## Project Summary

FactoryFly Sentinel converts repeated human-operated drone inspections into
localized visual-change evidence, routes geometrically uncertain observations
to targeted reinspection, and produces a self-contained evidence report for
human review.

The system builds persistent spatial memory from a baseline flight using
COLMAP, localizes a later inspection in the same coordinate system, refines
comparable views with SIFT, RANSAC, and homography, and runs DINOv2 ViT-S/14
semantic-change inference on an AMD Radeon GPU through PyTorch and ROCm.

## Submission Materials

### Source Code and Reproducibility README

- Repository:  
  https://github.com/lee2017-bit/factoryfly-sentinel

- Reproducibility instructions:  
  https://github.com/lee2017-bit/factoryfly-sentinel/blob/main/README.md

### Release and Evaluation Assets

- Release page:  
  https://github.com/lee2017-bit/factoryfly-sentinel/releases/tag/v7.3.13

- Public privacy-redacted sample dataset:  
  https://github.com/lee2017-bit/factoryfly-sentinel/releases/download/v7.3.13/FactoryFly_Sample_Data_v1.zip

- Demonstration video:  
  https://github.com/lee2017-bit/factoryfly-sentinel/releases/download/v7.3.13/FactoryFly_Sentinel_Demo_4m03s.mp4

- Technical report:  
  https://github.com/lee2017-bit/factoryfly-sentinel/releases/download/v7.3.13/FactoryFly_Sentinel_Technical_Report.pdf

### Result Inspection

- Self-contained HTML evidence report:  
  https://github.com/lee2017-bit/factoryfly-sentinel/blob/main/expected_results/final_change_report.html

## AMD Radeon GPU and ROCm Usage

The core semantic-change perception stage runs on an AMD Radeon GPU in Radeon
Cloud. DINOv2 ViT-S/14 feature inference and semantic comparison execute using
PyTorch with ROCm. Geometry processing, COLMAP localization, workflow
orchestration, evidence triage, and report generation run on the local
workstation.

The clean Radeon Cloud environment verification reported:

```text
ROCM_OK
GPU_OK
DINOV2_OK
```

## Demonstrated Workflow

1. Baseline registration
2. Persistent 3D spatial memory
3. Inspection registration
4. Spatial localization
5. Localization review
6. Geometric pair refinement
7. Geometry-ready evidence selection
8. AMD Radeon DINOv2 analysis
9. Semantic-change result review
10. Evidence triage
11. Targeted reinspection mission
12. Reinspection analysis
13. Self-contained final evidence report

## Data and Privacy Disclosure

All demonstration data were collected by the participant in a private indoor
environment. No employer data, employer code, confidential factory information,
or proprietary company assets are included.

The publicly released sample videos are privacy-redacted derivatives. Exact
dataset-dependent numerical results may therefore differ from the original
demonstration shown in the technical report and video.

The original DJI flight record is not distributed because it may contain
location, device, or personal identifiers. FactoryFly Sentinel v7.3.13 does not
parse telemetry or use it for visual localization.

## Scope Boundary

FactoryFly Sentinel reports localized visual changes and evidence quality. It
does not determine whether an observation is a defect, a safety issue, or an
acceptable operational condition. Final operational disposition remains a human
review decision.
