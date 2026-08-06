import json
import time
import requests

VLLM_URL = "http://localhost:8000/v1/chat/completions"
MODEL_NAME = "Qwen/Qwen2.5-7B-Instruct"

PROMPT = "Explain in detail how tool calling works in AI agents, covering the request format, common failure modes, and how a system might detect and repair a broken call. Aim for a thorough, several-paragraph answer."

NUM_TRIALS = 5
MAX_TOKENS = 300


def run_one_trial():
    payload = {
        "model": MODEL_NAME,
        "messages": [{"role": "user", "content": PROMPT}],
        "max_tokens": MAX_TOKENS,
        "temperature": 0.7,
        "stream": True,
        "stream_options": {"include_usage": True},
    }

    start = time.time()
    first_token_time = None
    completion_tokens = None

    with requests.post(VLLM_URL, json=payload, stream=True, timeout=60) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if not line:
                continue
            line = line.decode("utf-8")
            if not line.startswith("data: "):
                continue
            data_str = line[len("data: "):]
            if data_str.strip() == "[DONE]":
                break
            chunk = json.loads(data_str)

            choices = chunk.get("choices", [])
            if choices and choices[0].get("delta", {}).get("content") and first_token_time is None:
                first_token_time = time.time()

            usage = chunk.get("usage")
            if usage:
                completion_tokens = usage.get("completion_tokens")

    end = time.time()

    if first_token_time is None:
        first_token_time = end

    time_to_first_token = first_token_time - start
    generation_time = end - first_token_time
    total_time = end - start
    tokens_per_sec = (completion_tokens / generation_time) if completion_tokens and generation_time > 0 else None

    return {
        "time_to_first_token_sec": round(time_to_first_token, 3),
        "generation_time_sec": round(generation_time, 3),
        "total_time_sec": round(total_time, 3),
        "completion_tokens": completion_tokens,
        "tokens_per_sec": round(tokens_per_sec, 2) if tokens_per_sec else None,
    }


if __name__ == "__main__":
    print(f"Running {NUM_TRIALS} trials against {MODEL_NAME}...\n")
    results = []
    for i in range(1, NUM_TRIALS + 1):
        r = run_one_trial()
        print(f"Trial {i}: {r}")
        results.append(r)

    valid = [r["tokens_per_sec"] for r in results if r["tokens_per_sec"]]
    valid_ttft = [r["time_to_first_token_sec"] for r in results]

    avg_tps = sum(valid) / len(valid) if valid else None
    avg_ttft = sum(valid_ttft) / len(valid_ttft) if valid_ttft else None

    print("\n=== SUMMARY ===")
    print(f"Average time to first token: {avg_ttft:.3f} sec")
    print(f"Average tokens/sec during generation: {avg_tps:.2f}")

    with open("benchmarks/inference_speed_results.json", "w") as f:
        json.dump({
            "model": MODEL_NAME,
            "num_trials": NUM_TRIALS,
            "avg_time_to_first_token_sec": round(avg_ttft, 3) if avg_ttft else None,
            "avg_tokens_per_sec": round(avg_tps, 2) if avg_tps else None,
            "raw_trials": results,
        }, f, indent=2)
    print("\nSaved to benchmarks/inference_speed_results.json")
