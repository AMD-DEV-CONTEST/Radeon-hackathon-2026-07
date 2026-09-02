#!/bin/bash
# Parallel PB driver: pool of N tools at once, EACH with a per-tool wall-clock timeout,
# streaming results as they finish. Fixes the serial-1-tool waste (box was 93% idle on
# I/O-wait TUI tests). Usage: pb_parallel_driver.sh <pilot> <results.jsonl> <jsons> <N> <timeout_s>
set -u
PILOT="$1"; RES="$2"; JD="$3"; N="${4:-6}"; TMO="${5:-1500}"
: > "$RES"; mkdir -p "$JD"
run_one() {
  local t="$1" work="/root/_p_$1"
  rm -rf "$work" && mkdir -p "$work/$t" && cp "$PILOT/$t/submission.tar.gz" "$work/$t/" 2>/dev/null
  ( cd /root/ProgramBench && timeout "$TMO" env PYTHONUTF8=1 PROGRAMBENCH_DOCKER_CPUS=1 \
      .venv/bin/programbench eval "$work" --workers 1 --force >"$work.log" 2>&1 )
  local ec=$? jp; jp=$(find "$work/$t" -name "*.eval.json" 2>/dev/null | head -1)
  if [ "$ec" = "124" ]; then echo "{\"slug\":\"$t\",\"error\":\"TIMEOUT_${TMO}s\"}" >> "$RES"
  elif [ -n "$jp" ]; then cp "$jp" "$JD/$t.eval.json"
    python3 -c "
import json;d=json.load(open('$jp'));r=d['test_results']
from collections import Counter;c=Counter(x['status'] for x in r)
tot=len(r);p=c.get('passed',0);f=c.get('failed',0)+c.get('error',0);nr=c.get('not_run',0);sk=c.get('skipped',0)
print(json.dumps({'slug':'$t','passed':p,'total':tot,'not_run':nr,'skipped':sk,'failed':f,'clean':(p==tot and f==0 and nr==0 and sk==0)}))" >> "$RES"
  else echo "{\"slug\":\"$t\",\"error\":\"no_json_ec${ec}\"}" >> "$RES"; fi
  rm -rf "$work" "$work.log"
}
export -f run_one; export PILOT RES JD TMO
ls "$PILOT" | xargs -P "$N" -I{} bash -c 'run_one "$@"' _ {}
echo '{"DONE":true}' >> "$RES"
