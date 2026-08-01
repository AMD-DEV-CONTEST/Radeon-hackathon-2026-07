#!/usr/bin/env bash
# Determinex - AMD Radeon demo. One command, ~4 minutes.
#
# Verified working 2026-07-31 on a Radeon Cloud NOTEBOOK instance (ROCm 7.2.1,
# vLLM 0.16.1, Qwen2.5-Coder-7B-Instruct):
#   single stream 31.9 tok/s | K=6 concurrent 179.0 tok/s | 5.61x for 1.07x wall
#   idea -> synthesized 4-check oracle -> SOLVED on sample 1
#
# Assumes vLLM is ALREADY serving on 127.0.0.1:8000 and the repo is cloned to
# /workspace/Determinex. Start vLLM without --enforce-eager: eager mode disables
# HIP graph capture and measured ~8 tok/s vs ~32 tok/s on identical hardware.
set -u
P=4
say(){ printf '\n\033[1;36m============================================================\033[0m\n'; printf '\033[1;36m  %s\033[0m\n' "$1"; printf '\033[1;36m============================================================\033[0m\n'; sleep $P; }

say "1/6  THE HARDWARE - this is an AMD Radeon GPU"
rocm-smi; sleep $P

say "2/6  Qwen2.5-Coder-7B SERVED ON THE RADEON GPU (vLLM + ROCm)"
curl -s http://127.0.0.1:8000/v1/models | head -c 300; echo; sleep $P

say "3/6  THE THESIS - what does the 6th candidate cost on this GPU?"
/opt/venv/bin/python - <<'PYEOF'
import json, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
URL="http://127.0.0.1:8000/v1/chat/completions"
P="Write a Rust bounded LRU cache with get/put/len using only std. Code only."
def one(i,n=512):
    b=json.dumps({"model":"Qwen/Qwen2.5-Coder-7B-Instruct","max_tokens":n,
                  "temperature":0.2+0.1*(i%4),
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
print("  >>> six verified-search candidates cost ~8% more time than one")
print("  >>> P(correct)=1-(1-p)^K is nearly free here: p=0.3,K=6 -> 88.2% not 30%")
PYEOF
sleep $P

say "4/6  GPU UNDER LOAD - the Radeon is doing the work"
rocm-smi; sleep $P

say "5/6  IDEA -> SOUND ORACLE -> VERIFIED PROGRAM (nothing trusts the model)"
cd /workspace/Determinex || exit 1
cat > /tmp/idea.md <<'IEOF'
# Run-length encoding

Write a function `rle(s)` that run-length encodes a string.
Each run of one repeated character becomes the run length followed by the character.

Examples:
- rle("aaabbc") returns "3a2b1c"
- rle("a") returns "1a"
- rle("") returns ""
- rle("abc") returns "1a1b1c"
IEOF
DETERMINEX_VLLM_BASE_URL=http://127.0.0.1:8000/v1 \
DETERMINEX_VLLM_MODEL=Qwen/Qwen2.5-Coder-7B-Instruct \
/opt/venv/bin/python scripts/determinex_build_from_idea.py \
  --idea /tmp/idea.md --provider vllm --lang python --k 6
sleep $P

say "6/6  WHAT JUST HAPPENED"
cat <<'EEOF'
  The oracle was SYNTHESIZED from the idea, then VALIDATED to actually run.
  The 7B model on the Radeon GPU proposed candidates.
  Only a program that PASSES every synthesized check is returned.

  No LLM judged anything. No score came from a model.

  Determinex  .  github.com/DarthCeltic/Determinex  .  AGPL-3.0-or-later
EEOF
