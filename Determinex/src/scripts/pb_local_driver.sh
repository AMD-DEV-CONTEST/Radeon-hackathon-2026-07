#!/bin/bash
# LOCAL bounded PB driver (Git Bash + Docker Desktop). Abuses local but won't slag:
# N=2 parallel, 1 cpu each (leaves 10 free), aggressive prune (Docker Desktop disk is small),
# per-tool timeout, streaming. Usage: pb_local_driver.sh <pilot> <results.jsonl> <jsons> <N> <tmo>
set -u
PB="T:/Dev/ProgramBench"
PILOT="$1"; RES="$2"; JD="$3"; N="${4:-2}"; TMO="${5:-900}"
: > "$RES"; mkdir -p "$JD"
run_one() {
  local t="$1" work="C:/tmp/_loc_$1"
  rm -rf "$work" && mkdir -p "$work/$t" && cp "$PILOT/$t/submission.tar.gz" "$work/$t/" 2>/dev/null
  ( cd "$PB" && timeout "$TMO" env PYTHONUTF8=1 PROGRAMBENCH_DOCKER_CPUS=1 \
      .venv/Scripts/programbench.exe eval "$work" --workers 1 --force >"$work.log" 2>&1 )
  local ec=$? jp; jp=$(find "$work/$t" -name "*.eval.json" 2>/dev/null | head -1)
  if [ "$ec" = "124" ]; then echo "{\"slug\":\"$t\",\"error\":\"TIMEOUT_${TMO}s\"}" >> "$RES"
  elif [ -n "$jp" ]; then cp "$jp" "$JD/$t.eval.json"
    python "$PB/../../Dev/Determinex/scripts/_one_count.py" "$jp" "$t" >> "$RES" 2>/dev/null || \
    python -c "
import json,sys;d=json.load(open(sys.argv[1]));r=d['test_results']
from collections import Counter;c=Counter(x['status'] for x in r)
tot=len(r);p=c.get('passed',0);f=c.get('failed',0)+c.get('error',0);nr=c.get('not_run',0);sk=c.get('skipped',0)
print(json.dumps({'slug':sys.argv[2],'passed':p,'total':tot,'not_run':nr,'skipped':sk,'failed':f,'clean':(p==tot and f==0 and nr==0 and sk==0)}))" "$jp" "$t" >> "$RES"
  else echo "{\"slug\":\"$t\",\"error\":\"no_json_ec${ec}\"}" >> "$RES"; fi
  # aggressive prune (Docker Desktop disk is small) + cleanup
  docker image prune -af >/dev/null 2>&1; rm -rf "$work" "$work.log"
}
export -f run_one; export PB PILOT RES JD TMO
ls "$PILOT" | xargs -P "$N" -I{} bash -c 'run_one "$@"' _ {}
echo '{"DONE":true}' >> "$RES"
