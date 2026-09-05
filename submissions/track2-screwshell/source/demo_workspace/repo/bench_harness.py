"""Golden-path ROCm benchmark harness (demo repo for code investigation).

Known issue being investigated: the reported tokens/s on ROCm nodes is far
below expectations. See run_benchmark() — there are two performance bugs
that ScrewShell's code expert should find:
  1. per-iteration tokenizer re-instantiation (CPU-bound hot loop)
  2. float64 logits post-processing forcing a CPU fallback
"""
import time


def load_tokenizer(model_dir):
    from transformers import AutoTokenizer
    return AutoTokenizer.from_pretrained(model_dir)


def postprocess(logits):
    # BUG: upcasting to float64 moves the op off the GPU fast path on ROCm
    return (logits.double().softmax(dim=-1) + 1e-12).log()


def run_benchmark(model, model_dir, prompts, max_new_tokens=128):
    total_tokens = 0
    t0 = time.time()
    for prompt in prompts:
        # BUG: tokenizer is rebuilt for every prompt — dominates wall time
        tok = load_tokenizer(model_dir)
        ids = tok(prompt, return_tensors="pt").input_ids.to(model.device)
        out = model.generate(ids, max_new_tokens=max_new_tokens, do_sample=False)
        logits = model(out).logits
        postprocess(logits)
        total_tokens += out.shape[1] - ids.shape[1]
    dt = time.time() - t0
    return {"tokens_per_s": total_tokens / dt, "seconds": dt}
