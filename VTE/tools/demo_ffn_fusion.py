"""
Demo: FFN fusion on/off, side by side, Qwen2.5 1.5B (the hackathon demo model).

Runs the same prompt through two subprocesses (VTE_ENABLE_FFN_FUSION must be
set before the model loads/compiles, so this can't be flipped mid-process)
and prints a clean before/after summary. See docs/PERFORMANCE.md
("FFN fusion: fixed, and its generalization limit") for the full
methodology and the 4-model generalization table this result is part of.

Usage:
    python tools/demo_ffn_fusion.py
"""
import json
import os
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
PYTHON = sys.executable

WORKER_SRC = '''
import json, sys, os
sys.path.insert(0, r"%s")
from vte.core.model import VTEModel

model = VTEModel.from_pretrained("qwen2.5:1.5b-q4_k_m", context_length=2048)
stats = {}
gen = model.generate("Explain what ROCm is in a few sentences.", max_tokens=40, temperature=0.0, stats=stats)
text = "".join(list(gen)) if hasattr(gen, "__iter__") else gen
print("###RESULT###" + json.dumps({"text": text, "tps": stats["decoding_speed_tps"]}))
''' % ROOT.replace("\\", "\\\\")


def run_one(fusion_on: bool) -> dict:
    env = os.environ.copy()
    if fusion_on:
        env["VTE_ENABLE_FFN_FUSION"] = "1"
    else:
        env.pop("VTE_ENABLE_FFN_FUSION", None)

    result = subprocess.run(
        [PYTHON, "-c", WORKER_SRC], env=env, capture_output=True, text=True, cwd=ROOT
    )
    for line in result.stdout.splitlines():
        if line.startswith("###RESULT###"):
            return json.loads(line[len("###RESULT###"):])
    print(result.stdout[-2000:])
    print(result.stderr[-2000:])
    raise RuntimeError("Worker did not report a result -- see output above.")


def main():
    print("Qwen2.5 1.5B, W7900, VTE_ENABLE_FFN_FUSION off vs on")
    print("=" * 60)

    print("\n[1/2] Sem fusao (baseline)...")
    off = run_one(fusion_on=False)
    print(f"  {off['tps']:.2f} tok/s")

    print("\n[2/2] Com fusao (header-cached, vectorized)...")
    on = run_one(fusion_on=True)
    print(f"  {on['tps']:.2f} tok/s")

    delta = (on["tps"] / off["tps"] - 1.0) * 100.0

    print("\n" + "=" * 60)
    print("RESUMO")
    print("=" * 60)
    print(f"Sem fusao:  {off['tps']:.2f} tok/s")
    print(f"Com fusao:  {on['tps']:.2f} tok/s")
    print(f"Delta:      {delta:+.1f}%")
    print(f"\nSaida (sem fusao):  {off['text'][:100]}")
    print(f"Saida (com fusao):  {on['text'][:100]}")
    same_text = off["text"] == on["text"]
    print(f"\nSaida identica: {'sim' if same_text else 'nao (esperado com temperature=0 em runs separados, verificar coerencia manualmente)'}")


if __name__ == "__main__":
    main()
