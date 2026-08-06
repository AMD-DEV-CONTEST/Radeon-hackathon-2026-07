#!/bin/bash
# run_clean_readme.sh — execute README shell commands in a clean shell and record results (Todo 11/F4).
#
# Reads README.md, extracts fenced bash code blocks, and executes each command
# with `bash -c` in an isolated environment. The result JSON records every
# command with its exit status. Exit 0 when all commands pass.
#
# Usage:
#   bash scripts/run_clean_readme.sh --out <result.json>
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --out) OUT="$2"; shift 2;;
    *) echo "unknown arg: $1" >&2; exit 2;;
  esac
done
[ -n "$OUT" ] || { echo "run_clean_readme: --out required" >&2; exit 2; }

# extract commands from README bash fenced blocks (lines starting with '```bash')
CMDS_FILE="$(mktemp)"
/opt/venv/bin/python - "$CMDS_FILE" <<'PY'
import re, sys
text = open("/persistent/learning-companion/README.md", encoding="utf-8").read()
blocks = re.findall(r"```bash\n(.*?)```", text, re.S)
cmds = []
for b in blocks:
    for line in b.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Only DETERMINISTIC OFFLINE verification commands are walked: validators,
        # tests, compile checks, contract audit, and the one-command smoke. Anything
        # requiring live models (downloads, vLLM startup, bench, qwen3 experiment,
        # gated reset) or pure env setup is excluded so the walk is reproducible in
        # a clean shell without network/GPU services.
        if re.match(r"^(python|python3|/opt/venv/bin/python|bash|npm|npx)\s+(scripts/|web/|--prefix|-m unittest|-m compileall)", line):
            # drop lines that clearly need a live model/network/service
            if re.search(r"huggingface_cli|start_vllm|qwen3_experiment|bench\.py|uvicorn|download|reset ", line):
                continue
            cmds.append(line)
open(sys.argv[1], "w").write("\n".join(cmds) + "\n")
PY

results="[]"
while IFS= read -r cmd; do
  [ -n "$cmd" ] || continue
  if timeout 240 bash -c "$cmd" >/dev/null 2>&1; then
    results="$(/opt/venv/bin/python -c "
import json, sys
r = json.loads(sys.argv[1]); r.append({'cmd': sys.argv[2], 'ok': True}); print(json.dumps(r))
" "$results" "$cmd")"
  else
    results="$(/opt/venv/bin/python -c "
import json, sys
r = json.loads(sys.argv[1]); r.append({'cmd': sys.argv[2], 'ok': False, 'error': 'nonzero'})
print(json.dumps(r))
" "$results" "$cmd")"
  fi
done < "$CMDS_FILE"
rm -f "$CMDS_FILE"

mkdir -p "$(dirname "$OUT")"
printf '{"clean_readme_schema_version":1,"commands":%s,"created_at":"%s"}\n' \
  "$results" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$OUT"
FAILS="$(/opt/venv/bin/python -c "
import json, sys
r = json.load(open(sys.argv[1]))
print(sum(1 for c in r['commands'] if not c.get('ok')))
" "$OUT")"
echo "CLEAN_README_RUN: total=$(/opt/venv/bin/python -c "import json; print(len(json.load(open('$OUT'))['commands']))") failures=$FAILS -> $OUT"
[ "$FAILS" = "0" ]
