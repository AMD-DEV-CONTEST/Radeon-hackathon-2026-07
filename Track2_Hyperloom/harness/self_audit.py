#!/usr/bin/env python3
"""
self_audit.py — can OUR agent find the flaws in OUR submission?

Three Claude subagents audited this submission and found real defects. The
obvious question is why the agent we are submitting did not do that job. This
runs the experiment.

Design follows our own doctrine (bakeoff/, 2026-07-30): the model supplies
judgement, the HARNESS owns the reference and the scoring. Specifically:

  * The claim list is fixed here, not chosen by the model.
  * Ground truth is fixed here, from defects independently verified by hand
    (Magpie #70 is an issue not a PR; the file says 91.6 not 90.5; the ISA
    census contradicts "unexploited"; serve.py did not gate per-metric).
  * The model gets ONE tool, grep over the repo. It cannot fabricate a file.
  * Scoring is mechanical. The model's own confidence is ignored entirely, and
    any file:line it cites is checked for existence before its verdict counts.

A wrong verdict is a finding, not a failure of the experiment.
"""
import json, re, subprocess, sys, urllib.request
from pathlib import Path

URL   = "http://localhost:13305/v1/chat/completions"
BRAIN = "agentworld"
REPO  = Path("/tmp/pr-submit/Track2_Hyperloom")

# (claim, ground truth, why) — verdict is what a correct auditor should return.
CLAIMS = [
 ("Prefill int4 2:4-sparse SWMMAC reaches 3.669x vs int8 WMMA at K=8192.",
  "BACKED",   "benchmarks/README.md records 3.669x on that shape"),
 ("The crossover table's 8B numbers (1965 -> 2014 at ubatch 64) come from a real run.",
  "BACKED",   "benchmarks/crossover-results.txt holds them verbatim"),
 ("AMD-AGI/Magpie#70 was filed upstream WITH A FIX.",
  "UNBACKED", "it is an open ISSUE, not a PR and not a fix"),
 ("Prefill measured 90.5 TOP/s against 25.0 TOP/s for int8.",
  "UNBACKED", "the only file with the figure says 91.6, not 90.5"),
 ("v_dot8_i32_iu4, v_dot2_f32_f16 and v_dot4_f32_fp8 are genuinely unexploited.",
  "UNBACKED", "the repo's own ISA census counts 4, 125666 and 110 uses"),
 ("The serving section's 18.42x at 256 streams is reproducible from this repo.",
  "UNBACKED", "continuous batching needs the fork's server; no artifact was present"),
 # NOTE: this claim was UNBACKED when the audit that produced this list was run --
 # serve.py computed one boolean over all output. It was FIXED before this script
 # ran, so the correct answer against the tree as it now stands is BACKED. The
 # first run of this experiment scored the model WRONG here using the stale truth;
 # the model was right. Recording that, because a harness that owns the reference
 # is only as good as the reference, and this one was briefly out of date.
 ("The harness refuses to show a throughput number until a gate NAMING that metric passes.",
  "BACKED",   "serve.py now parses a per-line verdict and pairs it with that metric"),
 ("The decode iu4 kernel is correctness-gated against a CPU reference before timing.",
  "BACKED",   "decode_mmvq_iu4.hip runs the gate first and prints max_rel_err per shape"),
]

TOOLS = [{"type":"function","function":{
    "name":"grep_repo",
    "description":("Search the submission for a regular expression. Returns matching "
                   "file:line:text, up to 40 lines. This is the ONLY way to see the "
                   "repository — you cannot open files directly, so cite what this returns."),
    "parameters":{"type":"object","properties":{
        "pattern":{"type":"string","description":"regex, e.g. '3\\\\.669|TOP/s'"}},
        "required":["pattern"]}}}]

SYSTEM = ("You are auditing a technical submission for claims the repository does not "
          "support. For each claim, search the repo and answer strictly:\n"
          "VERDICT: BACKED or UNBACKED\n"
          "EVIDENCE: a file:line you actually saw in grep output, or NONE\n"
          "WHY: one sentence.\n"
          "BACKED means a file in this repo demonstrates the claim. UNBACKED means it "
          "does not, or the repo contradicts it. Never cite a file you did not see in "
          "grep output. If grep shows nothing, that is evidence of UNBACKED, not a "
          "reason to guess.")

def grep(pattern):
    try:
        r = subprocess.run(["grep","-rnE",pattern,"--include=*.md","--include=*.py",
                            "--include=*.hip","--include=*.sh","--include=*.txt","."],
                           cwd=REPO, capture_output=True, text=True, timeout=60)
        out = (r.stdout or "").strip().splitlines()
        return "\n".join(out[:40]) if out else "(no matches)"
    except Exception as e:
        return f"(grep error: {e})"

def ask(msgs):
    body = {"model":BRAIN,"messages":msgs,"tools":TOOLS,"temperature":0.1,"max_tokens":24000}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(),
                                 headers={"Content-Type":"application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=900).read())["choices"][0]["message"]

def audit_one(claim):
    msgs = [{"role":"system","content":SYSTEM},
            {"role":"user","content":f"Claim to audit:\n\n{claim}"}]
    cited = []
    # 4 rounds was too few: the model was still investigating when we cut it off,
    # and we recorded that as a NO-VERDICT failure. It answers correctly with room.
    for _ in range(10):
        m = ask(msgs)
        msgs.append({k:v for k,v in m.items() if k in ("role","content","tool_calls")})
        tcs = m.get("tool_calls") or []
        if not tcs:
            return (m.get("content") or ""), cited
        for tc in tcs:
            try: a = json.loads(tc["function"]["arguments"] or "{}")
            except Exception: a = {}
            res = grep(a.get("pattern","")) if tc["function"]["name"]=="grep_repo" else "(unknown tool)"
            cited.extend(re.findall(r"^([^\s:]+):(\d+):", res, re.M))
            msgs.append({"role":"tool","tool_call_id":tc.get("id","0"),"content":res})
    return (m.get("content") or ""), cited

def main():
    rows, correct, fabricated = [], 0, 0
    for i,(claim, truth, why) in enumerate(CLAIMS, 1):
        print(f"\n[{i}/{len(CLAIMS)}] {claim[:72]}")
        try:
            answer, seen = audit_one(claim)
        except Exception as e:
            print(f"    ERROR {e}"); rows.append((claim,truth,"ERROR",False)); continue
        v = re.search(r"VERDICT:\s*(BACKED|UNBACKED)", answer.upper())
        got = v.group(1) if v else "NO-VERDICT"
        # Harness owns the check: any cited file:line must have actually appeared.
        ev = re.search(r"EVIDENCE:\s*([^\s,]+):(\d+)", answer)
        fab = False
        if ev and (ev.group(1).lstrip("./"), ev.group(2)) not in \
                  {(f.lstrip("./"), l) for f,l in seen}:
            fab = True; fabricated += 1
        ok = (got == truth)
        correct += ok
        print(f"    model: {got:<10} truth: {truth:<10} {'OK' if ok else 'WRONG'}"
              f"{'   [CITED A LINE IT NEVER SAW]' if fab else ''}")
        rows.append((claim, truth, got, ok))
    print("\n" + "="*72)
    print(f"  correct verdicts : {correct}/{len(CLAIMS)}")
    print(f"  fabricated cites : {fabricated}")
    print(f"  defects caught   : {sum(1 for c,t,g,o in rows if t=='UNBACKED' and o)}"
          f"/{sum(1 for _,t,_,_ in rows if t=='UNBACKED')}")
    print(f"  false alarms     : {sum(1 for c,t,g,o in rows if t=='BACKED' and not o)}"
          f"/{sum(1 for _,t,_,_ in rows if t=='BACKED')}")
    Path("/tmp/self_audit_result.json").write_text(json.dumps(
        [{"claim":c,"truth":t,"model":g,"correct":o} for c,t,g,o in rows], indent=1))

if __name__ == "__main__":
    main()
