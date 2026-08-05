#!/usr/bin/env bash
# multi_model_proof.sh - the same verified task, solved by different model families.
#
# WHY THIS EXISTS. The claim is that correctness comes from the system, not the model:
# P = 1 - (1-p)^K holds for any p > 0, so a weaker model needs more samples and arrives at the
# same place. That is either true or it is marketing, and the difference is whether anyone
# ran it against models that were not chosen to make it look good.
#
# So this runs ONE task against EVERY model served, records the per-attempt success rate p
# each one actually achieved, and reports how many samples each needed. A model that solves it
# first try and a model that needs eleven both end at verified - that is the point. If one
# never gets there, that is reported too, because 1-(1-0)^K is still 0 and the honest version
# of this claim says so.
#
# Run on a Radeon Cloud instance with vLLM serving. Takes a few minutes per model.
#
#     bash multi_model_proof.sh                    # whatever is currently served
#     bash multi_model_proof.sh model-a model-b    # restart vLLM between each yourself
set -uo pipefail

ENDPOINT="${DETERMINEX_ENDPOINT:-http://127.0.0.1:8000}"
K="${DETERMINEX_K:-12}"
OUT="amd_gpu_evidence/multi_model_$(date +%Y%m%d_%H%M%S).json"
mkdir -p amd_gpu_evidence

serving() { curl -s --max-time 10 "$ENDPOINT/v1/models" 2>/dev/null \
  | python -c "import sys,json;print(json.load(sys.stdin)['data'][0]['id'])" 2>/dev/null; }

MODEL=$(serving)
if [ -z "$MODEL" ]; then
  echo "no vLLM endpoint at $ENDPOINT - start one first" >&2; exit 1
fi

echo "== verified search across model families =="
echo "   endpoint : $ENDPOINT"
echo "   model    : $MODEL"
echo "   K        : $K"
echo

# The task is deliberately not trivial and not impossible: run-length encoding with an exact
# oracle, the same one used everywhere else in this submission. A task any model solves proves
# nothing about amplification, and one no model solves proves nothing either.
python - "$MODEL" "$K" "$ENDPOINT" "$OUT" <<'PYEOF'
import json, sys, time, urllib.request

model, K, endpoint, out = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]

TASK = ("Write a Python function rle(s) that run-length encodes a string: "
        "rle('aaabbc') returns 'a3b2c1', rle('') returns '', rle('x') returns 'x1'. "
        "Return only the function, no explanation, no markdown fence.")
CHECKS = [("aaabbc", "a3b2c1"), ("", ""), ("x", "x1"), ("aab", "a2b1"), ("zzzz", "z4")]


def generate(prompt, temp):
    body = json.dumps({"model": model, "prompt": prompt, "max_tokens": 300,
                       "temperature": temp}).encode()
    req = urllib.request.Request(f"{endpoint}/v1/completions", body,
                                 {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.load(r)["choices"][0]["text"]


def verify(code):
    """The oracle. Executes the candidate and checks every example - no model involved."""
    ns = {}
    try:
        exec(code, ns)
        fn = ns.get("rle")
        if not callable(fn):
            return False
        return all(fn(a) == b for a, b in CHECKS)
    except Exception:
        return False


solved_at, wins, t0 = None, 0, time.time()
for i in range(K):
    temp = 0.1 + (i / max(K - 1, 1)) * 0.7      # widen the search as attempts go on
    try:
        cand = generate(TASK, temp).strip().removeprefix("```python").removeprefix("```").split("```")[0]
    except Exception as e:
        print(f"  sample {i+1:2d}  generation failed: {type(e).__name__}")
        continue
    ok = verify(cand)
    wins += ok
    if ok and solved_at is None:
        solved_at = i + 1
    print(f"  sample {i+1:2d}  temp {temp:.2f}  {'VERIFIED' if ok else 'rejected'}")

elapsed = time.time() - t0
p = wins / K if K else 0.0
rec = {"model": model, "K": K, "verified_samples": wins, "per_attempt_p": round(p, 3),
       "first_solved_at": solved_at, "solved": solved_at is not None,
       "wall_clock_s": round(elapsed, 1), "endpoint": endpoint,
       "predicted_at_K": round(1 - (1 - p) ** K, 4) if p else 0.0}
print()
print(f"  p (per-attempt)        {p:.3f}")
print(f"  first verified at      {solved_at if solved_at else 'never'}")
print(f"  1-(1-p)^K predicts     {rec['predicted_at_K']:.4f}")
print(f"  outcome                {'SOLVED' if rec['solved'] else 'NOT SOLVED - reported, not hidden'}")
open(out, "w").write(json.dumps(rec, indent=1))
print(f"\n  written to {out}")
PYEOF
