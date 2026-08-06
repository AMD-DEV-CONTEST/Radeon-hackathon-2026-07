import os, torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel

BASE = "/models/unsloth/Qwen3.5-9B"
ADAPTER = "/persistent/loras/sygnif"   # 标准层名, 预期和 Qwen3.5-9B 兼容

print("=== loading base ===", flush=True)
tok = AutoTokenizer.from_pretrained(BASE)
model = AutoModelForCausalLM.from_pretrained(BASE, dtype=torch.bfloat16, device_map="cuda:0")
model.eval()
free, total = torch.cuda.mem_get_info()
print("base vram used GB:", round((total - free) / 1e9, 2), flush=True)

print("=== attaching sygnif only ===", flush=True)
peft = PeftModel.from_pretrained(model, ADAPTER, adapter_name="sygnif", is_trainable=False)
peft.set_adapter("sygnif")
peft.eval()

ids = tok.apply_chat_template(
    [{"role": "user", "content": "Reply with the single word: ready"}],
    add_generation_prompt=True, return_tensors="pt", return_dict=True,
)["input_ids"].to("cuda:0")
with torch.no_grad():
    out = peft.generate(ids, max_new_tokens=16, do_sample=False, pad_token_id=tok.eos_token_id)
print("GEN OK:", tok.decode(out[0, ids.shape[1]:], skip_special_tokens=True)[:80], flush=True)

print("=== sygnif lora weight sanity ===", flush=True)
miss = 0
total = 0
for n, p in peft.named_parameters():
    if "sygnif" in n and "lora_" in n:
        total += 1
        if float(p.abs().sum().item()) == 0.0:
            miss += 1
print(f"sygnif lora params={total}, zero_params={miss}", flush=True)
print("VERIFY_DONE", flush=True)
