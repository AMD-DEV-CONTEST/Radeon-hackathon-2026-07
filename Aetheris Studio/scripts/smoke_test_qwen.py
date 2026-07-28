"""
Smoke test script for testing Aetheris CLI with Qwen 2.5 1.5B model.
Measures time-to-first-token (TTFT), tokens per second (Tok/s), and validates model generation output.
"""

import os
import sys
import time
import requests

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from aetheris_cli.transport.client import AetherisClient


def run_smoke_test():
    client = AetherisClient()
    if not client.is_backend_alive():
        print("Backend is not running. Please start app.py first.")
        return 3

    model_name = "qwen2.5:1.5b-q4_k_m"
    print(f"Setting active model to: {model_name}...")
    try:
        resp = client.session.post(
            f"{client.base_url}/api/settings",
            json={"default_model": model_name, "context_length": 4096},
            timeout=10,
        )
        resp.raise_for_status()
        print(f"Settings updated: {resp.json()}")
    except Exception as e:
        print(f"Failed to set model settings: {e}")
        return 1

    prompt = "Hello! Please reply in 2 short sentences explaining what model you are."
    messages = [{"role": "user", "content": prompt}]

    print(f"\nSending prompt to CLI transport layer...\nPrompt: {prompt!r}\n")

    start_time = time.time()
    first_token_time = None
    accumulated_text = ""
    token_count = 0

    try:
        stream = client.stream_chat(
            messages=messages,
            mode="builder",
            chat_id="smoke_test_session",
            temperature=0.3,
            max_tokens=256,
            timeout=180,
        )

        for event in stream:
            if event.type == "delta":
                now = time.time()
                if first_token_time is None:
                    first_token_time = now
                delta_text = event.data.get("delta", "")
                accumulated_text += delta_text
                token_count += 1
                sys.stdout.write(delta_text)
                sys.stdout.flush()

        end_time = time.time()
        sys.stdout.write("\n")

        total_duration = end_time - start_time
        ttft = (first_token_time - start_time) if first_token_time else 0.0
        generation_time = (end_time - first_token_time) if first_token_time else total_duration
        tok_per_sec = (token_count / generation_time) if generation_time > 0 else 0.0

        print("\n" + "=" * 50)
        print("         SMOKE TEST BENCHMARK RESULTS         ")
        print("=" * 50)
        print(f"Model Name            : {model_name}")
        print(f"Total Response Length : {len(accumulated_text)} chars")
        print(f"Tokens Generated      : {token_count} tokens")
        print(f"TTFT (First Token)    : {ttft:.4f} seconds ({ttft * 1000:.1f} ms)")
        print(f"Total Generation Time : {generation_time:.4f} seconds")
        print(f"Total Turn Duration   : {total_duration:.4f} seconds")
        print(f"Throughput (Tok/s)    : {tok_per_sec:.2f} tokens/sec")
        print("=" * 50)

        if token_count > 0 and accumulated_text.strip():
            print("STATUS: SUCCESS - Model generated output successfully!")
            return 0
        else:
            print("STATUS: FAILED - Empty response received.")
            return 1

    except Exception as e:
        print(f"\nSmoke test execution failed with exception: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(run_smoke_test())
