#!/bin/sh
set -eu

rm -rf dist
mkdir -p dist/data dist/icons dist/content-packs
cp index.html app.js app-reliability.js learning-core.js remote-update.js styles.css manifest.json service-worker.js dist/
cp data/*.json dist/data/
cp content-packs/library-catalog.json dist/content-packs/
cp icons/* dist/icons/

# Audio and video stay remote/streamed; no bundled commercial assets.

echo "Mobile web bundle created in dist/"
