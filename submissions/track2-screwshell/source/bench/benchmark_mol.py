#!/usr/bin/env python
"""MoL A/B benchmark — the Radeon inference-speed-optimization evidence.

Compares skill-switching strategies on AMD Radeon PRO W7900 (48GB, ROCm):

  A. Naive multi-model  : loading a dedicated 9B model per skill
                          (measured: full reload latency + VRAM; 3x resident
                           is impossible on 48GB -> recorded as infeasible)
  B. MoL hot-swap       : frozen base + PEFT set_adapter between LoRA experts

Outputs bench/benchmark_mol.csv + bench/benchmark_mol.json with:
  base load time, VRAM resident, adapter load time, switch latency (ms),
  tokens/s per adapter, reproduction commands.

Run:
  source /opt/venv/bin/activate
  HIP_VISIBLE_DEVICES=0 python benchmark_mol.py --repeats 5
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import time

import torch

BASE = os.environ.get("SCREWSHELL_BASE", "/models/unsloth/Qwen3.5-9B")
LORA_DIR = os.environ.get("SCREWSHELL_LORA_DIR", "/persistent/loras")
OUT_DIR = os.path.dirname(os.path.abspath(__file__))

PROMPT = "Summarize in one sentence why local AI inference matters for privacy."


def vram_gb():
    free, total = torch.cuda.mem_get_info()
    return round((total - free) / 1e9, 2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=5)
    ap.add_argument("--max-new-tokens", type=int, default=128)
    args = ap.parse_args()

    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import PeftModel

    results = {"env": {
        "gpu": torch.cuda.get_device_name(0),
        "torch": torch.__version__,
        "vram_total_gb": round(torch.cuda.mem_get_info()[1] / 1e9, 1),
        "base": BASE,
    }, "runs": []}

    # ---- A. baseline: full model (re)load cost ----
    t0 = time.time()
    tok = AutoTokenizer.from_pretrained(BASE)
    model = AutoModelForCausalLM.from_pretrained(BASE, dtype=torch.bfloat16,
                                                 device_map="cuda:0").eval()
    base_load_s = round(time.time() - t0, 1)
    base_vram = vram_gb()
    results["baseline"] = {
        "full_model_load_s": base_load_s,
        "vram_resident_gb": base_vram,
        "three_models_resident_gb_est": round(base_vram * 3, 1),
        "three_models_feasible_on_48gb": base_vram * 3 < 48,
        "note": "naive per-skill dedicated models require a full reload "
                f"({base_load_s}s) per switch, or 3x VRAM (infeasible on 48GB)",
    }

    def bench_gen(m, label):
        ids = tok.apply_chat_template([{"role": "user", "content": PROMPT}],
                                      add_generation_prompt=True,
                                      return_tensors="pt",
                                      return_dict=True)["input_ids"].to("cuda:0")
        tps_list = []
        for _ in range(args.repeats):
            torch.cuda.synchronize(); t = time.time()
            with torch.no_grad():
                out = m.generate(ids, max_new_tokens=args.max_new_tokens,
                                 do_sample=False, pad_token_id=tok.eos_token_id)
            torch.cuda.synchronize()
            dt = time.time() - t
            tps_list.append((out.shape[1] - ids.shape[1]) / dt)
        rec = {"config": label, "tokens_per_s_mean": round(statistics.mean(tps_list), 2),
               "tokens_per_s_stdev": round(statistics.stdev(tps_list), 2)
               if len(tps_list) > 1 else 0.0,
               "vram_gb": vram_gb()}
        results["runs"].append(rec)
        print(rec, flush=True)
        return rec

    bench_gen(model, "base_bf16_no_adapter")

    # ---- B. MoL: attach adapters, measure load + hot-swap ----
    adapters = []
    peft_model = None
    if os.path.isdir(LORA_DIR):
        for name in sorted(os.listdir(LORA_DIR)):
            path = os.path.join(LORA_DIR, name)
            cfg = None
            for root, _d, files in os.walk(path):
                if "adapter_config.json" in files:
                    cfg = root
                    break
            if not cfg:
                continue
            t = time.time()
            try:
                if peft_model is None:
                    peft_model = PeftModel.from_pretrained(
                        model, cfg, adapter_name=name, is_trainable=False)
                else:
                    peft_model.load_adapter(cfg, adapter_name=name)
                adapters.append({"name": name,
                                 "load_s": round(time.time() - t, 2),
                                 "vram_after_gb": vram_gb()})
                print("loaded", adapters[-1], flush=True)
            except Exception as e:
                print("adapter fail", name, e, flush=True)
    results["adapters"] = adapters

    switch_ms = {}
    if peft_model and adapters:
        names = [a["name"] for a in adapters]
        # warm
        peft_model.set_adapter(names[0])
        for i in range(len(names) * max(3, args.repeats)):
            frm = names[i % len(names)]
            to = names[(i + 1) % len(names)]
            torch.cuda.synchronize(); t = time.time()
            peft_model.set_adapter(to)
            torch.cuda.synchronize()
            switch_ms.setdefault(f"{frm}->{to}", []).append((time.time() - t) * 1000)
        results["hot_swap_ms"] = {
            k: {"mean": round(statistics.mean(v), 2),
                "min": round(min(v), 2), "max": round(max(v), 2)}
            for k, v in switch_ms.items()}
        print("hot swap:", results["hot_swap_ms"], flush=True)
        for a in adapters:
            peft_model.set_adapter(a["name"])
            bench_gen(peft_model, f"mol_adapter_{a['name']}")

    # ---- comparison summary ----
    all_sw = [x for v in switch_ms.values() for x in v]
    results["summary"] = {
        "naive_switch_cost_s": base_load_s,
        "mol_switch_cost_ms_mean": round(statistics.mean(all_sw), 2) if all_sw else None,
        "speedup_x": round(base_load_s * 1000 / statistics.mean(all_sw), 0)
        if all_sw else None,
        "vram_saved_vs_3_models_gb": round(base_vram * 3 - vram_gb(), 1),
    }
    print("SUMMARY:", json.dumps(results["summary"], indent=2), flush=True)

    with open(os.path.join(OUT_DIR, "benchmark_mol.json"), "w") as f:
        json.dump(results, f, indent=2)
    with open(os.path.join(OUT_DIR, "benchmark_mol.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["config", "tokens_per_s_mean", "tokens_per_s_stdev", "vram_gb"])
        for r in results["runs"]:
            w.writerow([r["config"], r["tokens_per_s_mean"],
                        r["tokens_per_s_stdev"], r["vram_gb"]])
        w.writerow([])
        w.writerow(["switch_pair", "mean_ms", "min_ms", "max_ms"])
        for k, v in results.get("hot_swap_ms", {}).items():
            w.writerow([k, v["mean"], v["min"], v["max"]])
        w.writerow([])
        w.writerow(["naive_full_reload_s", base_load_s])
        w.writerow(["mol_hot_swap_ms_mean", results["summary"]["mol_switch_cost_ms_mean"]])
        w.writerow(["speedup_x", results["summary"]["speedup_x"]])
    print("written benchmark_mol.{json,csv}")


if __name__ == "__main__":
    main()
