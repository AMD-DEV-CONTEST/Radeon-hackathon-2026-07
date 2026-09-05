"""Day4/5 E2E: full ScrewShell stack — orchestrator + tools + RAG + memory.

Runs the two demo-scenario queries (doc investigation, then code
investigation with multi-turn memory) end-to-end on the Radeon GPU.

Run on remote from /persistent/screwshell/app:
  source /opt/venv/bin/activate && HF_HOME=/persistent/hf-home \
  HF_HUB_OFFLINE=1 python scripts/day4_e2e_test.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from screwshell.app import build_app

WS = os.environ.get("SCREWSHELL_WS",
                    "/persistent/screwshell/app/demo_workspace")

ctx = build_app(workspace=WS)

events = []
def on_event(kind, data):
    events.append((kind, data))
    if kind == "lora_switch" and data.get("from") != data.get("to"):
        print(f"  [MoL] {data.get('from') or 'base'} -> {data.get('to') or 'base'}"
              f" ({data['ms']:.1f}ms, skill={data['skill']})", flush=True)
    elif kind == "plan":
        print("  [plan]", data["task"].replace("\n", " | ")[:220], flush=True)
    elif kind == "tool":
        print(f"  [tool] {data['tool']} ok={data['ok']}: {data['digest'][:100]}",
              flush=True)
ctx.orchestrator.on_event = on_event

results = {}
for i, q in enumerate([
    "What are the main risks in the ROCm migration plan? Cite the relevant documents.",
    "Which file and lines support the adapter hot-swap conclusion from the previous answer?",
], 1):
    print(f"\n===== QUERY {i}: {q}", flush=True)
    r = ctx.orchestrator.run(q)
    print(f"----- ANSWER {i} -----\n{r.answer[:900]}", flush=True)
    print(f"[stats] {json.dumps(r.stats['engine'])}", flush=True)
    results[f"q{i}"] = {"answer": r.answer, "stats": r.stats,
                        "task": r.task.render()}

with open("/persistent/screwshell/day4_e2e.json", "w") as f:
    json.dump({"results": results,
               "n_events": len(events),
               "switch_events": [e for k, e in events if k == "lora_switch"][-10:]},
              f, indent=2, ensure_ascii=False, default=str)
print("\nreport written to /persistent/screwshell/day4_e2e.json")
