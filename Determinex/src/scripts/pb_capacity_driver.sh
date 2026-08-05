#!/bin/bash
# Canonical PB capacity driver — never stalls silently.
#  * per-tool HARD wall-clock timeout (a hung tool like argc's recursion is killed, batch continues)
#  * STREAMS each result to results.jsonl the instant it completes (live visibility)
#  * disk-guard prune between tools
# Usage: pb_capacity_driver.sh <pilot_dir> <results.jsonl> <jsons_dir> [per_tool_timeout_s]
set -u
PILOT="$1"; RES="$2"; JD="$3"; TMO="${4:-1200}"
: > "$RES"; mkdir -p "$JD"
for t in $(ls "$PILOT"); do
  # disk discipline
  used=$(df / | awk 'NR==2{gsub(/%/,"",$5);print $5}')
  [ "$used" -ge 85 ] && { docker image prune -af >/dev/null 2>&1; docker builder prune -af >/dev/null 2>&1; }
  rm -rf /root/_one && mkdir -p /root/_one && cp -r "$PILOT/$t" "/root/_one/$t"
  # hard wall-clock timeout around the single-tool eval
  ( cd /root/ProgramBench && timeout "$TMO" env PYTHONUTF8=1 PROGRAMBENCH_DOCKER_CPUS=3 \
      .venv/bin/programbench eval /root/_one --workers 1 --force >/root/_one.log 2>&1 )
  ec=$?
  # kill any container left from a timeout/hang
  docker ps -q | xargs -r docker kill >/dev/null 2>&1
  jp=$(find /root/_one/$t -name "*.eval.json" 2>/dev/null | head -1)
  if [ "$ec" = "124" ]; then
    echo "{\"slug\":\"$t\",\"error\":\"TIMEOUT_${TMO}s\"}" >> "$RES"
  elif [ -n "$jp" ]; then
    cp "$jp" "$JD/$t.eval.json"
    python3 -c "
import json;d=json.load(open('$jp'));r=d['test_results']
from collections import Counter;c=Counter(x['status'] for x in r)
tot=len(r);p=c.get('passed',0);f=c.get('failed',0)+c.get('error',0);nr=c.get('not_run',0);sk=c.get('skipped',0)
print(json.dumps({'slug':'$t','passed':p,'total':tot,'not_run':nr,'skipped':sk,'failed':f,'clean':(p==tot and f==0 and nr==0 and sk==0)}))" >> "$RES"
  else
    echo "{\"slug\":\"$t\",\"error\":\"no_json_ec${ec}\"}" >> "$RES"
  fi
  rm -rf /root/_one
done
echo '{"DONE":true}' >> "$RES"
