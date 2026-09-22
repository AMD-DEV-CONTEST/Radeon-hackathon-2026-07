#!/usr/bin/env bash
set -euo pipefail
python -m finmuse.cli check-gpu
python -m finmuse.cli generate --brief examples/wealth-card.json --variants 3 --out outputs/wealth-card
python -m finmuse.cli generate --brief examples/insurance-family.json --variants 3 --out outputs/insurance-family
python -m finmuse.cli report --run outputs/wealth-card --run outputs/insurance-family --out outputs/demo-report.md
