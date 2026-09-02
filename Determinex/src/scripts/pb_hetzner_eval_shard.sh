#!/usr/bin/env bash
# Run a ProgramBench native-eval shard on a Linux worker.
#
# Expected layout:
#   shard/
#     manifest.json
#     runs/pb_<tool>_native_v1/<slug>/submission.tar.gz
#     run.sh
#
# The local workstation must gate/apply returned eval JSONs. This script only
# runs official evals and writes logs/results into the shard directory.
set -euo pipefail

SHARD_DIR="${1:-$(pwd)}"
WORKERS="${WORKERS:-4}"
PROGRAMBENCH_ROOT="${PROGRAMBENCH_ROOT:-/root/ProgramBench}"
export PATH="/root/.local/bin:$PATH"
UV_BIN="${UV_BIN:-uv}"
PROGRAMBENCH_DOCKER_CPUS="${PROGRAMBENCH_DOCKER_CPUS:-2}"
PROGRAMBENCH_DOCKER_RUN_TIMEOUT="${PROGRAMBENCH_DOCKER_RUN_TIMEOUT:-900}"

cd "$SHARD_DIR"
mkdir -p logs results

if [ ! -f manifest.json ]; then
  echo "manifest.json missing in $SHARD_DIR" >&2
  exit 2
fi

python3 - <<'PY' > .jobs.tsv
import json
from pathlib import Path
m = json.loads(Path("manifest.json").read_text(encoding="utf-8"))
for item in m["items"]:
    print(item["slug"] + "\t" + item["remote_run_root"])
PY

run_one() {
  local slug="$1"
  local rel_run="$2"
  local safe
  safe="$(echo "$slug" | tr '/:;.' '____')"
  local out="logs/${safe}.out.log"
  local err="logs/${safe}.err.log"
  local abs_run="$SHARD_DIR/$rel_run"

  if [ -f "$abs_run/$slug/$slug.eval.json" ]; then
    echo "SKIP existing $slug"
    return 0
  fi

  echo "START $slug"
  (
    cd "$PROGRAMBENCH_ROOT"
    PYTHONUTF8=1 PYTHONIOENCODING=utf-8 "$UV_BIN" run programbench eval "$abs_run" --filter "$slug" --force
  ) >"$SHARD_DIR/$out" 2>"$SHARD_DIR/$err" || true

  if [ -f "$abs_run/$slug/$slug.eval.json" ]; then
    cp "$abs_run/$slug/$slug.eval.json" "$SHARD_DIR/results/$slug.eval.json"
    echo "DONE $slug"
  else
    echo "NO_EVAL $slug"
  fi
}

export -f run_one
export SHARD_DIR PROGRAMBENCH_ROOT UV_BIN PROGRAMBENCH_DOCKER_CPUS PROGRAMBENCH_DOCKER_RUN_TIMEOUT

if command -v parallel >/dev/null 2>&1; then
  parallel -j "$WORKERS" --colsep '\t' run_one {1} {2} :::: .jobs.tsv
else
  # xargs fallback; input is tab-delimited slug/run_root.
  xargs -P "$WORKERS" -n 2 bash -c 'run_one "$0" "$1"' < .jobs.tsv
fi

python3 - <<'PY'
import json
from pathlib import Path
m = json.loads(Path("manifest.json").read_text(encoding="utf-8"))
done = sorted(p.name for p in Path("results").glob("*.eval.json"))
logs = sorted(p.name for p in Path("logs").glob("*.err.log"))
summary = {
    "items": len(m["items"]),
    "eval_json": len(done),
    "missing_eval": [
        item["slug"] for item in m["items"]
        if not Path("results", item["slug"] + ".eval.json").exists()
    ],
    "err_logs": logs,
}
Path("results/summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
print(json.dumps(summary, indent=2))
PY
