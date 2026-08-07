#!/usr/bin/env python3
import os
import glob
import subprocess
import time
import requests

MODEL_DIR = "/mnt/raid0/models"
PORT = 8080

NODES = {
    "cesarops3": {"ip": "10.0.0.111", "max_size_gb": 8},
    "cesarops4": {"ip": "10.0.0.41", "max_size_gb": 15},
    "t440": {"ip": "10.0.0.61", "max_size_gb": float("inf")}
}

def get_node_for_size(size_bytes):
    size_gb = size_bytes / (1024 ** 3)
    if size_gb < NODES["cesarops3"]["max_size_gb"]:
        return "cesarops3", NODES["cesarops3"]["ip"]
    elif size_gb < NODES["cesarops4"]["max_size_gb"]:
        return "cesarops4", NODES["cesarops4"]["ip"]
    else:
        return "t440", NODES["t440"]["ip"]

def wait_for_server(ip, port, timeout=120):
    url = f"http://{ip}:{port}/v1/models"
    start_time = time.time()
    print(f"Waiting for llama-server at {url}...")
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

def run_qualification(ip, port, model_name, node_name):
    print(f"Running qualification for {model_name} on {node_name} ({ip}:{port})...")
    cwd = "/home/cesarops/cesarops_push/core/forge-qualification-lab"
    cmd = [
        "cargo", "run", "--example", "run_qualification", "--",
        f"http://{ip}:{port}",
        model_name,
        "llama.cpp",
        "UNKNOWN",
        node_name
    ]
    try:
        subprocess.run(cmd, cwd=cwd, check=True)
        print(f"Qualification completed for {model_name}.")
    except subprocess.CalledProcessError as e:
        print(f"Error running qualification for {model_name}: {e}")

def kill_server(node):
    print(f"Killing llama-server on {node}...")
    subprocess.run(["ssh", node, "pkill", "-f", "llama-server"])
    time.sleep(2)

def main():
    models = glob.glob(os.path.join(MODEL_DIR, "*.gguf"))
    if not models:
        print(f"No .gguf models found in {MODEL_DIR}")
        return

    # To avoid skipping models that fail, we just sequentially run all of them.
    for model_path in sorted(models):
        size_bytes = os.path.getsize(model_path)
        model_filename = os.path.basename(model_path)
        # clean up model name for scorecard (strip extension)
        model_name = os.path.splitext(model_filename)[0]
        
        node, ip = get_node_for_size(size_bytes)
        print(f"--- Processing {model_name} (Size: {size_bytes / 1024**3:.2f} GB) ---")
        print(f"Assigned to node: {node} ({ip})")

        # 1. Kill any existing server
        kill_server(node)

        # 2. Start llama-server via SSH
        # NOTE: Using a wrapper or direct call in background
        print(f"Starting server on {node}...")
        # Since we just want to launch it and detach, we use nohup
        server_cmd = f"nohup /home/cesarops/bin/llama-server -m {model_path} -ngl 99 --port {PORT} --host 0.0.0.0 > /tmp/llama_{model_name}.log 2>&1 &"
        ssh_cmd = ["ssh", node, server_cmd]
        subprocess.run(ssh_cmd)

        # 3. Wait for it to be ready
        if wait_for_server(ip, PORT):
            # 4. Run qualification
            run_qualification(ip, PORT, model_name, node)
        else:
            print(f"Skipping qualification for {model_name} due to timeout.")

        # 5. Tear down
        kill_server(node)
        print("--------------------------------------------------\n")

if __name__ == "__main__":
    main()
