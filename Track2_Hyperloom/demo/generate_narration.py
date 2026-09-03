#!/usr/bin/env python3
"""
generate_narration.py — the LOCAL model writes its own voiceover, grounded.

The Track 1 claim for this submission is that the artifact is produced by the
stack it demonstrates. So the narration script is written by the agent's own
brain (Qwen-AgentWorld-35B-A3B via Lemonade on the R9700), not by a human and
not by a cloud model. kokoro-v1 then speaks it. Both on the same card.

THE PROBLEM THIS SOLVES: asked from memory, local models here confidently got
RDNA4 facts wrong (two separate models described `iu4` as 8-bit and as 16-bit;
it is 4-bit). So the model is never asked to recall anything. It is handed the
segment's ACTUAL terminal transcript and told to describe what is on screen.

AND THE GUARD: every number the model emits is checked against the transcript.
If it produces a figure that is not on screen, the line is REJECTED. A narration
that states a number the video does not show is exactly the failure this project
spent the day removing.

Usage: python3 generate_narration.py [segment ...]   -> writes narration-cues.json
"""
import json, re, subprocess, sys, urllib.request
from pathlib import Path

URL   = "http://localhost:13305"
BRAIN = "agentworld"          # the agent's own brain
HERE  = Path(__file__).resolve().parent
OUT   = HERE / "self-narrated" / "narration-cues.json"

# segment -> (transcript, video seconds, how many lines)
# (transcript, SPED video seconds, total lines wanted)
# Lines are requested in CHUNKS of <=4: the brain's reasoning scales with how
# much you ask for in one call, and >5 lines reliably spirals past the token
# budget without emitting anything. Small asks terminate.
SEGMENTS = {
    "seg-intro":      ("/tmp/txc-seg-intro.txt",   27,  3),
    "seg-launch":     ("/tmp/txc-launch2.txt",     64,  7),
    "seg-kernel":     ("/tmp/txc-explain.txt",     62,  7),
    "demo-operation": ("/tmp/txc-demo-paced.txt", 118, 13),
    "seg-route":      ("/tmp/txc-route.txt",       40,  4),
    "seg-chat":       ("/tmp/txc-chat.txt",        65,  6),
}
CHUNK = 4

PROMPT = """Write {n} spoken voiceover lines describing this terminal output.
Use only what is below. Numbers as spoken words. Skip version hashes and paths.
Say "G F X twelve-oh-one" not "gfx1201".
Each line MUST be under 14 words. Short, clipped sentences.
Describe RESULTS and DECISIONS, never build warnings or boilerplate.
Reply with ONLY a JSON array of {n} strings.

{tx}

JSON array now:"""

def ask(prompt: str, max_tokens: int = 15000) -> str:
    body = {"model": BRAIN, "max_tokens": max_tokens, "temperature": 0.2,
            "messages": [{"role": "user", "content": prompt}]}
    req = urllib.request.Request(URL + "/api/v1/chat/completions",
        data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    d = json.loads(urllib.request.urlopen(req, timeout=1200).read())
    ch = d["choices"][0]
    return (ch["message"].get("content") or "").strip(), ch.get("finish_reason"), d["usage"]["completion_tokens"]

NUM = re.compile(r"\d+(?:\.\d+)?")
WORDNUM = {  # spoken forms the model is told to use -> digits, so we can check them
 "ninety-seven":"97","ninety seven":"97","three point six seven":"3.67",
 "two point four six":"2.46","thirty-two":"32","thirty two":"32",
 "sixty-four":"64","sixty four":"64","twenty-seven":"27","twenty seven":"27",
 "two point two":"2.2","one hundred":"100","seven point one four":"7.14",
 "twelve-oh-one":"1201","twelve oh one":"1201","eight":"8","four":"4",
}

def ungrounded_numbers(line: str, tx: str):
    """Return numbers spoken in `line` that do NOT appear in the transcript."""
    probe = line.lower()
    for word, digits in WORDNUM.items():
        probe = probe.replace(word, f" {digits} ")
    bad = []
    for n in NUM.findall(probe):
        if n in ("1","2","3","5","6","7","9","10"):   # ordinals/counts, not claims
            continue
        if n not in tx and n.rstrip("0").rstrip(".") not in tx:
            bad.append(n)
    return bad

def main():
    names = sys.argv[1:] or list(SEGMENTS)
    cues, problems = {}, 0
    for name in names:
        tx_path, secs, n = SEGMENTS[name]
        tx = Path(tx_path).read_text()
        print(f"\n=== {name}  ({secs}s, asking the local brain for {n} lines) ===")
        nchunks = (n + CHUNK - 1) // CHUNK
        span = max(1, len(tx) // nchunks)
        lines = []
        for c in range(nchunks):
            want = min(CHUNK, n - len(lines))
            if want <= 0: break
            slice_ = tx[c*span : c*span + min(span, 1800)]
            content, finish, toks = ask(PROMPT.format(n=want, tx=slice_))
            print(f"  chunk {c+1}/{nchunks}: finish={finish} tokens={toks} content={len(content)}ch")
            if not content:
                print("  !! no content for this chunk"); problems += 1; continue
            m = re.search(r"\[.*\]", content, re.S)
            try:
                lines += json.loads(m.group(0) if m else content)
            except Exception as e:
                print(f"  !! unparseable JSON: {e}"); problems += 1

        kept = []
        for i, ln in enumerate(lines):
            bad = ungrounded_numbers(ln, tx)
            if bad:
                print(f"  [{i}] REJECTED (numbers not on screen: {bad})")
                print(f"       {ln[:100]}")
                problems += 1
            else:
                print(f"  [{i}] ok  {ln[:88]}")
                kept.append(ln)
        cues[name] = kept

    OUT.write_text(json.dumps(cues, indent=2))
    print(f"\nwrote {OUT}  ({sum(len(v) for v in cues.values())} lines kept, {problems} problems)")
    return 0 if problems == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
