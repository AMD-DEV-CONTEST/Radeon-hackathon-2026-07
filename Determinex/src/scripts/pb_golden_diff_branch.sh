#!/bin/bash
# Per-branch golden differ: ONE branch env (consistent input/golden + its conftest with run()),
# build reimpl, run pytest -vv -> reliable assertion diffs. No cross-branch fixture mismatch.
set +e
mkdir -p /workspace && cp -r /branch/* /workspace/ 2>/dev/null && cp -r /src/* /workspace/ 2>/dev/null
cd /workspace; chmod -R u+w /workspace 2>/dev/null; rm -f executable
bash compile.sh >/tmp/c 2>&1 && echo BUILD_OK || { echo BUILDFAIL; tail -6 /tmp/c; exit 1; }
pip3 install -q pytest-timeout pytest-rerunfailures 2>/dev/null
TD=$(find /workspace -type d -name tests | head -1); echo "tests: $TD"
cd "$(dirname "$TD")"
python3 -m pytest "$TD" -o addopts="" -p no:cacheprovider -q 2>&1 | grep -E "passed|failed|error" | tail -2
echo "=== FAILED tests + assertion diffs ==="
python3 -m pytest "$TD" -o addopts="" -p no:cacheprovider -rA -vv 2>&1 | grep -E "FAILED|AssertionError|assert |where |^E |Remove|tbody|<td|<div" | head -30
