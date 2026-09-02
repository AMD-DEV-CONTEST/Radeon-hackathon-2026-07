#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PACKAGE_DIR="$ROOT_DIR/submission"
ARTIFACT_DIR="$PACKAGE_DIR/artifacts"
EVIDENCE_DIR="$PACKAGE_DIR/evidence"
SOURCE_DIR="$ROOT_DIR/docs/submission"
GENERATED_DIR="$SOURCE_DIR/generated"

mkdir -p "$ARTIFACT_DIR" "$EVIDENCE_DIR"

cp "$SOURCE_DIR/PR_BODY.en.md" "$PACKAGE_DIR/PR_BODY.md"
cp "$SOURCE_DIR/PROJECT_REPORT.en.md" "$ARTIFACT_DIR/PROJECT_SPECIFICATION.md"
cp "$SOURCE_DIR/ARCHITECTURE.en.md" "$ARTIFACT_DIR/ARCHITECTURE.md"
cp "$SOURCE_DIR/BENCHMARK_REPORT.en.md" "$ARTIFACT_DIR/BENCHMARK_REPORT.md"
cp "$SOURCE_DIR/THIRD_PARTY_NOTICES.en.md" "$ARTIFACT_DIR/THIRD_PARTY_NOTICES.md"
cp "$GENERATED_DIR/OpenAlpha-Sentinel-Project-Report.en.docx" \
  "$ARTIFACT_DIR/PROJECT_SPECIFICATION.docx"
cp "$GENERATED_DIR/OpenAlpha-Sentinel-Slides.en.pptx" \
  "$ARTIFACT_DIR/OpenAlpha-Sentinel-Slides.en.pptx"
cp "$GENERATED_DIR/ui-overview-desktop.png" "$ARTIFACT_DIR/"
cp "$GENERATED_DIR/ui-overview-mobile.png" "$ARTIFACT_DIR/"

evidence_files=(
  coverage.json
  demo-video-manifest.json
  local-evaluation.json
  rocm-benchmark-20260717T051324Z.txt
  rocm-cli-rag-20260717T050851Z.txt
  rocm-http-rag-20260717T050918Z.txt
  rocm-llama-runtime-20260717T051305Z.log
  rocm-offload-validation-20260717T152430Z.txt
  rocm-restart-trace-20260717T051301Z.txt
  rocm-test-results-20260717T050554Z.xml
  rocm-test-run-20260717T050554Z.txt
  test-results.xml
)
for file in "${evidence_files[@]}"; do
  cp "$GENERATED_DIR/$file" "$EVIDENCE_DIR/$file"
done

(
  cd "$PACKAGE_DIR"
  find . -type f ! -name SHA256SUMS -print \
    | LC_ALL=C sort \
    | while IFS= read -r file; do shasum -a 256 "$file"; done \
    | sed 's#  \./#  #' > SHA256SUMS
  shasum -a 256 -c SHA256SUMS
)

echo "Official submission package built at $PACKAGE_DIR"
