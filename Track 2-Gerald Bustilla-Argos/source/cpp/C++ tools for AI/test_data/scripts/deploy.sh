#!/bin/bash
# Deployment script for AI search tool
set -e

echo "Building AI search tool..."
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release

echo "Deploying..."
cp build/aisearch /usr/local/bin/
echo "Deployment complete!"
