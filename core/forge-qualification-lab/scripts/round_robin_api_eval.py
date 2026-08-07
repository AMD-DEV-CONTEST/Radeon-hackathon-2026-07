#!/usr/bin/env python3
import os
import time
import requests
import subprocess
import argparse

FORGE_API = "http://localhost:9100"
QUAL_LAB_DIR = "/home/cesarops/cesarops_push/core/forge-qualification-lab"
PORT = 8080

def get_recommendations():
    try:
        resp = requests.get(f"{FORGE_API}/orchestrator/recommendations")
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"Error fetching recommendations from Forge API: {e}")
        return []

def deploy_model(model_name, node):
    is_gguf = model_name.endswith(".gguf")
    engine = "llama.cpp" if is_gguf else "vllm"
    
    payload = {
        "model_name": model_name,
        "target_node": node,
        "engine": engine,
        "backend": "cuda",
    }
    
    # For large models, might need tensor split, but we rely on Forge default logic
    print(f"Deploying {model_name} to {node} via {engine}...")
    try:
        resp = requests.post(f"{FORGE_API}/orchestrator/deploy", json=payload)
        resp.raise_for_status()
        print(f"Deployment response: {resp.json()}")
        return True
    except Exception as e:
        print(f"Error deploying model: {e}")
        return False

def wait_for_server(ip, port, timeout=120):
    url = f"http://{ip}:{port}/v1/models"
    start_time = time.time()
    print(f"Waiting for inference server at {url}...")
    while time.time() - start_time < timeout:
        try:
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                print("Server is up!")
                return True
        except requests.exceptions.RequestException:
            pass
        time.sleep(2)
    print("Timed out waiting for server.")
    return False

def get_serving_model_id(ip, port):
    """Fetch the actual model ID as served by vLLM (e.g., full path)."""
    try:
        resp = requests.get(f"http://{ip}:{port}/v1/models", timeout=10)
        data = resp.json()
        return data["data"][0]["id"]
    except Exception as e:
        print(f"Could not determine serving model ID: {e}")
        return None

def get_node_ip(node):
    nodes = {
        "cesarops3": "10.0.0.111",
        "cesarops4": "10.0.0.41",
        "t440": "10.0.0.61",
        "mi300": "134.199.203.198"
    }
    return nodes.get(node, "127.0.0.1")

def tear_down_server(node):
    print(f"Tearing down any inference servers on {node} via Forge API...")
    try:
        resp = requests.post(f"{FORGE_API}/orchestrator/teardown", json={"target_node": node})
        resp.raise_for_status()
        print(f"Teardown response: {resp.json()}")
    except Exception as e:
        print(f"Error tearing down servers on {node}: {e}")


def run_qualification(ip, port, model_name, engine, node_name, model_id=None):
    # Strip .gguf extension for the scorecard / report name only
    display_name = model_name[:-5] if model_name.endswith(".gguf") else model_name
    # model_id is the name vLLM actually serves (e.g. full path); fall back to display_name
    serving_id = model_id if model_id else display_name
    print(f"Running qualification for {display_name} (serving as '{serving_id}') on {node_name} ({ip}:{port})...")
    
    cmd = [
        "cargo", "run", "--example", "run_qualification", "--",
        f"http://{ip}:{port}",
        serving_id,
        engine,
        "UNKNOWN",
        node_name,
        display_name,  # report dir / scorecard name
    ]
    try:
        subprocess.run(cmd, cwd=QUAL_LAB_DIR, check=True)
        print(f"Qualification completed for {display_name}.")
    except subprocess.CalledProcessError as e:
        print(f"Error running qualification for {display_name}: {e}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-only", action="store_true", help="Run only one test model (e.g., mamba)")
    parser.add_argument("--mi300-only", action="store_true", help="Run only the models on the MI300X droplet")
    args = parser.parse_args()

    if args.mi300_only:
        recommendations = [
            {"model_name": "Qwen1.5-MoE", "size_gb": 30.0, "recommended_node": "mi300"},
            {"model_name": "Llama-3.1-70B-AWQ", "size_gb": 40.0, "recommended_node": "mi300"},
            {"model_name": "Qwen2.5-72B-AWQ", "size_gb": 40.0, "recommended_node": "mi300"},
            {"model_name": "Mixtral-8x22B-AWQ", "size_gb": 80.0, "recommended_node": "mi300"},
        ]
    else:
        recommendations = get_recommendations()
        if not recommendations:
            print("No models found from Forge API.")
            return

    # Sort models by size ascending
    recommendations.sort(key=lambda x: x['size_gb'])

    for rec in recommendations:
        model_name = rec['model_name']
        node = rec['recommended_node']
        
        if args.test_only and "mamba" not in model_name.lower() and "hymba" not in model_name.lower():
            continue

        if not node:
            print(f"Skipping {model_name}: No recommended node (Too large?)")
            continue
            
        print(f"--- Processing {model_name} ({rec['size_gb']:.2f} GB) ---")
        
        if deploy_model(model_name, node):
            ip = get_node_ip(node)
            if wait_for_server(ip, PORT):
                engine = "llama.cpp" if model_name.endswith(".gguf") else "vllm"
                model_id = get_serving_model_id(ip, PORT)
                run_qualification(ip, PORT, model_name, engine, node, model_id=model_id)
            else:
                print(f"Skipping qualification for {model_name} due to timeout.")
            tear_down_server(node)
                
        print("--------------------------------------------------\n")

if __name__ == "__main__":
    main()
