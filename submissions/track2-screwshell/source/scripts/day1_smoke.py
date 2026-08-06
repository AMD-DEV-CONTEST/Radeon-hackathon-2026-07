#!/usr/bin/env python
# ⚠️ LEGACY (9B-PEFT era) — path-D uses llama.cpp + screwshell.core.mol_engine_llamacpp.
#    Targets the OLD PyTorch/PEFT Qwen3.5-9B core; retained as history only.
"""Day1 smoke test for ScrewShell MoL core on AMD Radeon PRO W7900 / ROCm.

Validates, in one run:
  1. Qwen3.5-9B (bf16, DevZone read-only mount) loads and generates on ROCm
     -> confirms hybrid GDN/Mamba kernels work on ROCm 7.2.4
  2. Reused community LoRA adapters load via PEFT
  3. Hot-swap: set_adapter (ms-level) vs load_adapter compatibility,
     depending on target_modules overlap
  4. Records VRAM / tokens/s / switch latency -> bench/day1_smoke.json

Run on remote:  source /opt/venv/bin/activate && python day1_smoke.py
"""
import json
import os
import time
import traceback

import torch

BASE = os.environ.get("SCREWSHELL_BASE", "/models/unsloth/Qwen3.5-9B")
LORA_DIR = os.environ.get("SCREWSHELL_LORA_DIR", "/persistent/loras")
OUT = os.environ.get("SCREWSHELL_SMOKE_OUT", "/persistent/screwshell/day1_smoke.json")

report = {"base": BASE, "steps": []}


def log(step, **kw):
    entry = {"step": step, **kw}
    report["steps"].append(entry)
    print(f"[day1] {step}: {json.dumps(kw, default=str)[:400]}", flush=True)


def vram_gb():
    free, total = torch.cuda.mem_get_info()
    return round((total - free) / 1e9, 2)


def main():
    from transformers import AutoModelForCausalLM, AutoTokenizer

    t0 = time.time()
    tok = AutoTokenizer.from_pretrained(BASE)
    model = AutoModelForCausalLM.from_pretrained(
        BASE, dtype=torch.bfloat16, device_map="cuda:0"
    )
    model.eval()
    log("base_loaded", seconds=round(time.time() - t0, 1), vram_gb=vram_gb())

    def _chat_ids(t, msgs, device):
        enc = t.apply_chat_template(
            msgs, add_generation_prompt=True, return_tensors="pt",
            return_dict=True)
        return enc["input_ids"].to(device)

    def gen(prompt, max_new_tokens=64):
        msgs = [{"role": "user", "content": prompt}]
        ids = _chat_ids(tok, msgs, model.device)
        torch.cuda.synchronize()
        t = time.time()
        with torch.no_grad():
            out = model.generate(
                ids, max_new_tokens=max_new_tokens, do_sample=False,
                pad_token_id=tok.eos_token_id,
            )
        torch.cuda.synchronize()
        dt = time.time() - t
        n_new = out.shape[1] - ids.shape[1]
        text = tok.decode(out[0, ids.shape[1]:], skip_special_tokens=True)
        return text, n_new / dt, dt

    # 1. base generation (GDN/ROCm smoke)
    text, tps, dt = gen("Say 'ROCm smoke OK' and nothing else.")
    log("base_generate", tokens_per_s=round(tps, 2), seconds=round(dt, 2),
        output=text[:200])

    # 2. load reused LoRA adapters
    from peft import PeftModel

    adapters = {}
    peft_model = None
    for name in sorted(os.listdir(LORA_DIR)) if os.path.isdir(LORA_DIR) else []:
        path = os.path.join(LORA_DIR, name)
        cfg = os.path.join(path, "adapter_config.json")
        if not os.path.isfile(cfg):
            # maybe nested (repo contains adapter in subdir)
            for root, _dirs, files in os.walk(path):
                if "adapter_config.json" in files:
                    path = root
                    cfg = os.path.join(root, "adapter_config.json")
                    break
        if not os.path.isfile(cfg):
            log("adapter_skip_no_config", name=name)
            continue
        with open(cfg) as f:
            c = json.load(f)
        tm = c.get("target_modules")
        try:
            t = time.time()
            if peft_model is None:
                peft_model = PeftModel.from_pretrained(
                    model, path, adapter_name=name, is_trainable=False
                )
            else:
                peft_model.load_adapter(path, adapter_name=name)
            adapters[name] = {"path": path, "target_modules": tm,
                              "r": c.get("r"), "load_s": round(time.time() - t, 2)}
            log("adapter_loaded", name=name, r=c.get("r"),
                target_modules=tm, load_s=adapters[name]["load_s"],
                vram_gb=vram_gb())
        except Exception as e:
            log("adapter_load_fail", name=name, error=f"{type(e).__name__}: {e}"[:300])

    if not adapters:
        log("no_adapters", note="hot-swap test skipped")
    else:
        m = peft_model

        def gen_p(prompt, max_new_tokens=48):
            msgs = [{"role": "user", "content": prompt}]
            ids = _chat_ids(tok, msgs, m.device)
            torch.cuda.synchronize()
            t = time.time()
            with torch.no_grad():
                out = m.generate(ids, max_new_tokens=max_new_tokens,
                                 do_sample=False, pad_token_id=tok.eos_token_id)
            torch.cuda.synchronize()
            dt = time.time() - t
            n = out.shape[1] - ids.shape[1]
            return tok.decode(out[0, ids.shape[1]:], skip_special_tokens=True), n / dt

        # 3. hot-swap latency: set_adapter between each pair
        names = list(adapters)
        for name in names:
            try:
                torch.cuda.synchronize()
                t = time.time()
                m.set_adapter(name)
                torch.cuda.synchronize()
                sw_ms = (time.time() - t) * 1000
                text, tps = gen_p("Reply with the single word: ready")
                log("hot_swap", adapter=name, set_adapter_ms=round(sw_ms, 1),
                    tokens_per_s=round(tps, 2), output=text[:120],
                    vram_gb=vram_gb())
            except Exception as e:
                log("hot_swap_fail", adapter=name,
                    error=f"{type(e).__name__}: {e}"[:300])

        # 4. target_modules compatibility summary
        tms = {n: tuple(sorted(a["target_modules"] or [])) for n, a in adapters.items()}
        log("target_modules_summary",
            identical=len(set(tms.values())) == 1, detail=tms)

    report["final_vram_gb"] = vram_gb()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"[day1] report written to {OUT}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        report["fatal"] = traceback.format_exc()
        with open(OUT, "w") as f:
            json.dump(report, f, indent=2, default=str)
        raise
