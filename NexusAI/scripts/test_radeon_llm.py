import time
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM

MODEL = "Qwen/Qwen2.5-0.5B-Instruct"

print("Loading tokenizer...")
tokenizer = AutoTokenizer.from_pretrained(MODEL)

print("Loading model...")
model = AutoModelForCausalLM.from_pretrained(
    MODEL,
    torch_dtype=torch.float16,
).to("cuda")

messages = [
    {
        "role": "system",
        "content": "You are NexusAI, a local agentic AI assistant."
    },
    {
        "role": "user",
        "content": "Briefly explain how an AI agent can use tools to complete a task."
    }
]

text = tokenizer.apply_chat_template(
    messages,
    tokenize=False,
    add_generation_prompt=True
)

inputs = tokenizer(text, return_tensors="pt").to("cuda")

torch.cuda.synchronize()
start = time.perf_counter()

with torch.inference_mode():
    outputs = model.generate(
        **inputs,
        max_new_tokens=100,
        do_sample=False
    )

torch.cuda.synchronize()
elapsed = time.perf_counter() - start

generated = outputs[0][inputs.input_ids.shape[1]:]
response = tokenizer.decode(generated, skip_special_tokens=True)

print("\n" + "=" * 60)
print("NEXUSAI LOCAL RADEON INFERENCE")
print("=" * 60)
print("Model:", MODEL)
print("Device:", torch.cuda.get_device_name(0))
print("HIP:", torch.version.hip)
print("Generated tokens:", len(generated))
print(f"Generation time: {elapsed:.3f}s")
print(f"Tokens/sec: {len(generated) / elapsed:.2f}")
print("\nResponse:")
print(response)