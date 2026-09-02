import subprocess
import sys
from pathlib import Path

ADAPTER_DIR = Path("scripts/fine_tuning/outputs/engineer-go-fix")
MERGED_DIR = Path("scripts/fine_tuning/outputs/engineer-v13-merged")
MODELFILE = Path("scripts/fine_tuning/outputs/Modelfile.v13")
MODEL_TAG = "determinex-engineer-v13-gofix"

print("[MERGE] Checking adapter...", flush=True)
assert ADAPTER_DIR.exists(), f"Missing: {ADAPTER_DIR}"

print("[MERGE] Merging LoRA on CPU (~3 min)...", flush=True)
MERGED_DIR.mkdir(parents=True, exist_ok=True)

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

BASE = "Qwen/Qwen2.5-Coder-1.5B-Instruct"
print("  Loading base model...", flush=True)
tok = AutoTokenizer.from_pretrained(BASE, trust_remote_code=True)
mdl = AutoModelForCausalLM.from_pretrained(
    BASE, dtype=torch.bfloat16, device_map="cpu", trust_remote_code=True
)
print("  Loading adapter...", flush=True)
mdl = PeftModel.from_pretrained(mdl, str(ADAPTER_DIR))
print("  Merging weights...", flush=True)
mdl = mdl.merge_and_unload()
print("  Saving...", flush=True)
mdl.save_pretrained(str(MERGED_DIR), safe_serialization=True)
tok.save_pretrained(str(MERGED_DIR))
print("[MERGE] Merge complete.", flush=True)

s1 = chr(60) + "|im_end|" + chr(62)
s2 = chr(60) + "|endoftext|" + chr(62)
mf = "FROM " + str(MERGED_DIR.resolve()) + "\n"
mf += "TEMPLATE {{ .Prompt }}\n"
mf += "SYSTEM You are Determinex Engineer v13. Write Go/Rust/Python code using fmt.Errorf with %w for errors. Use context.WithCancel and defer cancel() properly. Output code only.\n"
mf += "PARAMETER stop " + s1 + "\n"
mf += "PARAMETER stop " + s2 + "\n"
mf += "PARAMETER temperature 0.1\n"
mf += "PARAMETER num_ctx 4096\n"
MODELFILE.write_text(mf, encoding="utf-8")
print(f"[MERGE] Modelfile: {MODELFILE}", flush=True)

r = subprocess.run(["ollama", "create", MODEL_TAG, "-f", str(MODELFILE)])
sys.exit(r.returncode)
