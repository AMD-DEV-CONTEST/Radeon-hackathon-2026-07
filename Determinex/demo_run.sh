#!/usr/bin/env bash
# Determinex - AMD Radeon demo. One command, ~4 minutes.
#
# Run in the JupyterLab Terminal of a Radeon Cloud NOTEBOOK instance, with vLLM already
# serving on 127.0.0.1:8000. Do NOT pass --enforce-eager: it disables HIP graph capture and
# measured ~8 tok/s vs ~32 tok/s on identical hardware.
#
# The task is deliberate. We measured per-attempt success rate p for two models on this GPU
# (192 independent draws each, every candidate verified):
#
#     task                 7B          32B        regime
#     rle              192/192     192/192       saturated - K adds nothing
#     gron 5-check       1/192     181/192       model solves it; K trims the tail
#     gron 6-check       0/192      94/192       p=0.49 - THE PRODUCTIVE MIDDLE
#
# So this demo runs gron 6-check. At p=0.49 the model fails about half its attempts, which
# is exactly what makes the oracle visible: you watch candidates get REJECTED and then one
# pass. A task the model always solves would show the machinery doing nothing.
set -u
P=4
say(){ printf '\n\033[1;36m============================================================\033[0m\n'; printf '\033[1;36m  %s\033[0m\n' "$1"; printf '\033[1;36m============================================================\033[0m\n'; sleep $P; }

MODEL=$(curl -s http://127.0.0.1:8000/v1/models 2>/dev/null \
        | /opt/venv/bin/python -c "import sys,json;print(json.load(sys.stdin)['data'][0]['id'])" 2>/dev/null)
MODEL="${MODEL:-Qwen/Qwen2.5-Coder-7B-Instruct}"

say "1/6  THE HARDWARE - this is an AMD Radeon GPU"
rocm-smi; sleep $P

say "2/6  $MODEL SERVED ON THE RADEON GPU (vLLM + ROCm)"
curl -s http://127.0.0.1:8000/v1/models | head -c 300; echo; sleep $P

say "3/6  WHAT DOES THE 6th CANDIDATE COST ON THIS GPU?"
/opt/venv/bin/python - <<PYEOF
import json, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
URL="http://127.0.0.1:8000/v1/chat/completions"; M="$MODEL"
P="Write a Rust bounded LRU cache with get/put/len using only std. Code only."
def one(i,n=512):
    b=json.dumps({"model":M,"max_tokens":n,"temperature":0.2+0.1*(i%4),
                  "messages":[{"role":"user","content":P}]}).encode()
    r=urllib.request.Request(URL,data=b,headers={"Content-Type":"application/json"})
    t=time.monotonic()
    with urllib.request.urlopen(r,timeout=600) as f: d=json.loads(f.read())
    return time.monotonic()-t, d["usage"]["completion_tokens"]
el,tok=one(0); single=tok/el
print("  single stream : %d tok in %.2fs = %.1f tok/s"%(tok,el,single))
t0=time.monotonic()
with ThreadPoolExecutor(max_workers=6) as ex: rs=list(ex.map(one,range(6)))
w=time.monotonic()-t0; tot=sum(t for _,t in rs)
print("  K=6 concurrent: %d tok in %.2fs = %.1f tok/s aggregate"%(tot,w,tot/w))
print("")
print("  >>> %.2fx THROUGHPUT for %.2fx WALL CLOCK"%(tot/w/single,w/el))
print("  >>> measured knee on this GPU is K=32: 25.8x tokens for 1.21x wall clock")
PYEOF
sleep $P

say "4/6  GPU UNDER LOAD - the Radeon is doing the work"
rocm-smi; sleep $P

# p=0.49 means roughly half of first attempts fail, so a run either shows candidates being
# rejected before one passes, or passes quickly. Both are the system working; neither is
# promised here, because promising the dramatic one would be a claim the measurement does
# not support.
say "5/6  IDEA -> SOUND ORACLE -> VERIFIED PROGRAM (nothing trusts the model)"
cd /workspace/Determinex || exit 1
cat > /tmp/idea.md <<'IEOF'
# Flatten JSON into assignment lines

Write a function `gron(s)` that takes a JSON string and returns discrete assignment
statements, one per line, in the style of the `gron` command-line tool.

Every container is declared before its members. Strings are quoted, numbers are not.
Array elements use bracket indices. The root is always named `json`.

Examples:
- gron('{"a":1}') returns "json = {};\njson.a = 1;"
- gron('{"s":"hi"}') returns "json = {};\njson.s = \"hi\";"
- gron('{"a":{"b":2}}') returns "json = {};\njson.a = {};\njson.a.b = 2;"
- gron('{"a":[10,20]}') returns "json = {};\njson.a = [];\njson.a[0] = 10;\njson.a[1] = 20;"
- gron('{}') returns "json = {};"
- gron('{"n":null,"t":true}') returns "json = {};\njson.n = null;\njson.t = true;"
IEOF

DETERMINEX_VLLM_BASE_URL=http://127.0.0.1:8000/v1 \
DETERMINEX_VLLM_MODEL="$MODEL" \
DETERMINEX_VS_MAX_CONCURRENCY=8 \
/opt/venv/bin/python scripts/determinex_build_from_idea.py \
  --idea /tmp/idea.md --provider vllm --lang python --k 8
sleep $P

say "6/6  WHAT JUST HAPPENED"
cat <<'EEOF'
  The oracle was SYNTHESIZED from the idea, then VALIDATED to actually run.
  The model on the Radeon GPU proposed candidates - and got several WRONG.
  Only a program that PASSES every synthesized check is returned.

  Measured on this GPU: this model solves this task 94/192 times alone (p=0.49).
  Sampling K candidates against a sound oracle:

      K=1   48.96%        K=4   93.21%   (1.01x wall clock)
      K=8   99.54%        K=16  ~100%    (1.11x wall clock)

  A model that fails more than half the time becomes near-certain for 4% more time.
  No LLM judged anything. No score came from a model.

  Determinex  .  github.com/DarthCeltic/Determinex  .  AGPL-3.0-or-later
EEOF
