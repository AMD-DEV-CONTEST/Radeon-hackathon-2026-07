"""[LEGACY / 9B-PEFT era] Day2 integration demo: SkillRouter routes queries -> MoLEngine hot-swaps.

⚠️ This targets the OLD PyTorch/PEFT Qwen3.5-9B core (MoLEngine.load_base + set_adapter).
   Path-D uses llama.cpp: run `llama-server` with the 27B GGUF, then ScrewShell with
   MOL_BACKEND=llamacpp (see screwshell.core.mol_engine_llamacpp).

Run on remote from /persistent/screwshell/app (9B-PEFT era only):
  source /opt/venv/bin/activate && python scripts/day2_router_demo.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from screwshell.core.mol_engine import MoLEngine
from screwshell.core.router import SkillRouter

BASE = os.environ.get("SCREWSHELL_BASE", "/models/unsloth/Qwen3.5-9B")
LORA_DIR = os.environ.get("SCREWSHELL_LORA_DIR", "/persistent/loras")

QUERIES = [
    ("What are the main risks in the ROCm migration plan? Summarize the document.", None),
    ("Investigate why the benchmark in bench_harness.py is slow.", None),
    ("Plan a multi-step investigation to verify the VRAM budget claims.", None),
    ("run a grep for 'float64' across the repo", "tool"),
]


def main():
    engine = MoLEngine(BASE).load_base()
    for name in sorted(os.listdir(LORA_DIR)):
        engine.load_adapter(name, os.path.join(LORA_DIR, name))
    router = SkillRouter()

    out = {"routes": [], "engine": None}
    for q, tag in QUERIES:
        d = router.route(q, task_tag=tag)
        rec = engine.activate(d.adapter)
        text, stats = engine.chat(
            [{"role": "user", "content": q + " Reply in 2 sentences max."}],
            max_new_tokens=96)
        entry = {
            "query": q[:60], "skill": d.skill, "adapter": d.adapter,
            "reason": d.reason, "switch_ms": rec.latency_ms, "mode": rec.mode,
            "tokens_per_s": round(stats.tokens_per_s, 2),
            "reply": text[:180],
        }
        out["routes"].append(entry)
        print(json.dumps(entry, ensure_ascii=False), flush=True)

    out["engine"] = engine.status()
    print("ENGINE:", json.dumps(out["engine"]))
    with open("/persistent/screwshell/day2_router_demo.json", "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print("report written")


if __name__ == "__main__":
    main()
