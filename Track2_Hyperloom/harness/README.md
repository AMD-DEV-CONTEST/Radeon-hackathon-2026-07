# Harness — drive the agent from a browser, watch it work

```bash
python3 harness/serve.py      # then open http://127.0.0.1:8770  and GET /run
```

Binds to `127.0.0.1` and makes no outbound request. The page is a single file with
no external CSS or JS, so it works offline.

## What it is

An instrument panel over a live optimization run, not a chat window. It shows the
mission loop advancing, tool calls with their real output, memory accumulating,
and measurements landing as they are produced.

## The two rules it enforces

Any agent UI can show you a conversation. This one shows the difference between a
**measured** number and a **claimed** one:

1. **A metric is `UNVERIFIED` until a gate naming it has passed.** Throughput
   cannot be displayed as a result before its correctness gate lands. The link is
   per-metric — a gate on one shape does not verify another.

2. **A bandwidth above the measured DRAM roofline renders `INVALID`, in red — never
   green.** Above roofline does not mean fast, it means the working set fit in the
   64 MiB Infinity Cache and the reading is not a throughput result.

Run it and you will see rule 2 fire: the mission deliberately measures one
cache-resident shape alongside the DRAM-honest ones. The **largest** number on the
page is the one marked invalid. It passes its correctness gate — it is a *correct*
number that is not a *valid* claim, and the interface keeps those separate.

That is the whole point. This project has twice caught itself reporting a
cache-resident figure as a win; the interface now makes that mistake impossible to
display.

## Provenance

The dashboard was drafted by the local model (`agentworld`, on the Radeon GPU)
from a written spec, then corrected by hand — the generated version verified a
metric if *any* gate passed rather than the gate naming it, which was an
underspecification in the prompt rather than a modelling error. `serve.py` and the
mission loop are hand-written.
