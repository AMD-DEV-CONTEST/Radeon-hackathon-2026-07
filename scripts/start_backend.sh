#!/bin/bash
set -e
cd "$(dirname "$0")/../backend"

source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate e2e

python -m uvicorn main:app --host 0.0.0.0 --port 8000