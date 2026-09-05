# Xenix Knowledge OCR runtime

This subtree builds Xenix's optional Windows x64 OCR component over the pinned
official PaddleOCR C++ pipeline and Paddle Inference runtime. It is a release input,
not part of the desktop application's Python environment.

Run `pdm run build-knowledge-ocr` from a Developer PowerShell with the pinned MSVC
toolchain available. The build verifies every downloaded byte, applies the reviewed
compatibility patch, executes the real stdio protocol checks, and writes the
normalized archive plus `runtime_catalog.json` under `dist/knowledge-ocr/`. The
archive name includes its complete SHA-256, so rebuilt runtime bytes never collide
with an earlier immutable object that has the same logical runtime ID. The fixed
Xenix OCR pipeline configuration is compiled into the worker; the archive contains
only the worker, its dependency closure, and model assets. Build verification runs
the extracted worker without the PaddleOCR checkout and from a foreign working
directory, and rejects real builder paths in released binaries.

The application downloads only that Xenix-built archive from its configured release
origin. It never installs Python, pip, Paddle packages, or models on an end-user
machine.
