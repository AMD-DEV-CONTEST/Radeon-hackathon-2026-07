# Third-party notices

Xenix Radeon Edition depends on and interoperates with third-party software,
models, and services. Those materials remain governed by their own licenses;
the Xenix copyright notice does not replace or restrict those terms.

- Python dependencies and resolved versions are declared in
  [pyproject.toml](pyproject.toml) and [pdm.lock](pdm.lock).
- Radeon runtime and model artifacts are not relicensed by this repository.
  Their source, pinned revision, digest, and SPDX license identifier are recorded
  in `src/xenix/resources/amd/manifests/`.
- The native Knowledge OCR runtime has component-specific notices in
  [native/knowledge_ocr/THIRD_PARTY_NOTICES.txt](native/knowledge_ocr/THIRD_PARTY_NOTICES.txt).
- A file with its own SPDX identifier or license metadata is governed by that
  file-specific declaration instead of the repository copyright notice.

Redistributors are responsible for preserving the applicable third-party
notices and satisfying the license terms of every component they distribute.
