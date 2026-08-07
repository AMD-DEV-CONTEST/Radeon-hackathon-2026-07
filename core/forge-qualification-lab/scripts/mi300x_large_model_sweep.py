#!/usr/bin/env python3
"""
mi300x_large_model_sweep.py  —  Download → benchmark → delete on the MI300X.
All models are too large to run locally (>32GB VRAM at 4-bit).
"""
import os, sys, time, json, subprocess, requests

FORGE_API    = "http://localhost:9100"
QUAL_LAB_DIR = "/home/cesarops/cesarops_push/core/forge-qualification-lab"
DROPLET_IP   = "134.199.203.198"
MODELS_DIR   = "/shared-docker/models"
PORT         = 8080
DEPLOY_WAIT  = 360   # vLLM on ROCm JIT-compiles; large models take time

MODELS = [
    # ── Already benchmarked (cached) ─────────────────────────────────────────
    {"display":"Qwen1.5-MoE",       "hf_repo":"Qwen/Qwen1.5-MoE-A2.7B-Chat",                        "size_gb":27,  "arch":"moe"},
    {"display":"Llama-3.1-70B-AWQ", "hf_repo":"hugging-quants/Meta-Llama-3.1-70B-Instruct-AWQ-INT4", "size_gb":38,  "arch":"dense"},
    {"display":"Qwen2.5-72B-AWQ",   "hf_repo":"Qwen/Qwen2.5-72B-Instruct-AWQ",                       "size_gb":39,  "arch":"dense"},
    {"display":"Mixtral-8x22B-AWQ", "hf_repo":"MaziyarPanahi/Mixtral-8x22B-Instruct-v0.1-AWQ",       "size_gb":69,  "arch":"moe"},
    {"display":"Ornith-1.0-35B-BF16","hf_repo":"deepreinforce-ai/Ornith-1.0-35B",                    "size_gb":70,  "arch":"dense"},

    # ── DeepSeek Coder V2 Full — Q4 AWQ (128.7GB confirmed) ──────────────────
    {"display":"DeepSeek-Coder-V2-Instruct-AWQ",
     "hf_repo":"casperhansen/deepseek-coder-v2-instruct-awq",
     "size_gb":129, "arch":"code-moe"},

    # ── Qwen Coder 32B BF16 (Coder-Next equivalent, 65.5GB confirmed) ─────────
    {"display":"Qwen2.5-Coder-32B-Instruct",
     "hf_repo":"Qwen/Qwen2.5-Coder-32B-Instruct",
     "size_gb":66, "arch":"code"},

    # ── DeepSeek small MoE (31.4GB confirmed) ────────────────────────────────
    {"display":"DeepSeek-Coder-V2-Lite-Instruct",
     "hf_repo":"deepseek-ai/DeepSeek-Coder-V2-Lite-Instruct",
     "size_gb":32, "arch":"code-moe"},

    # ── Gemma 2 27B BF16 (61.1GB confirmed) ──────────────────────────────────
    {"display":"gemma-2-27b-it",
     "hf_repo":"google/gemma-2-27b-it",
     "size_gb":62, "arch":"dense"},

    # ── More large models ─────────────────────────────────────────────────────
    {"display":"Llama-3.3-70B-Instruct-AWQ",
     "hf_repo":"hugging-quants/Meta-Llama-3.3-70B-Instruct-AWQ-INT4",
     "size_gb":40, "arch":"dense"},

    {"display":"Qwen2.5-Coder-72B-Instruct-AWQ",
     "hf_repo":"Qwen/Qwen2.5-Coder-72B-Instruct-AWQ",
     "size_gb":40, "arch":"code"},

    {"display":"Qwen2-72B-Instruct-AWQ",
     "hf_repo":"Qwen/Qwen2-72B-Instruct-AWQ",
     "size_gb":40, "arch":"dense"},

    # QwQ-32B BF16 reasoning (65.5GB confirmed)
    {"display":"QwQ-32B",
     "hf_repo":"Qwen/QwQ-32B",
     "size_gb":66, "arch":"reasoning"},

    {"display":"Qwen3-32B-AWQ",
     "hf_repo":"Qwen/Qwen3-32B-AWQ",
     "size_gb":20, "arch":"dense"},

    {"display":"Mixtral-8x7B-Instruct-AWQ",
     "hf_repo":"MaziyarPanahi/Mixtral-8x7B-Instruct-v0.1-AWQ",
     "size_gb":26, "arch":"moe"},

    # Qwen3 30B MoE full BF16 (96.1GB confirmed)
    {"display":"Qwen3-30B-A3B",
     "hf_repo":"Qwen/Qwen3-30B-A3B",
     "size_gb":96, "arch":"moe"},

    # Qwen3-235B A22B AWQ (96.1GB confirmed — flagship MoE)
    {"display":"Qwen3-235B-A22B-AWQ",
     "hf_repo":"Qwen/Qwen3-235B-A22B-AWQ",
     "size_gb":96, "arch":"moe"},

    {"display":"Nemotron-70B-Instruct-AWQ",
     "hf_repo":"MaziyarPanahi/Llama-3.1-Nemotron-70B-Instruct-HF-AWQ",
     "size_gb":40, "arch":"aligned"},

    {"display":"Yi-1.5-34B-Chat-AWQ",
     "hf_repo":"MaziyarPanahi/Yi-1.5-34B-Chat-AWQ",
     "size_gb":20, "arch":"dense"},

    {"display":"Command-R-35B-AWQ",
     "hf_repo":"MaziyarPanahi/c4ai-command-r-v01-AWQ",
     "size_gb":20, "arch":"rag"},

    {"display":"DeepSeek-R1-Distill-Llama-70B-AWQ",
     "hf_repo":"MaziyarPanahi/DeepSeek-R1-Distill-Llama-70B-AWQ",
     "size_gb":40, "arch":"reasoning"},
]

def ssh(cmd, timeout=60):
    r = subprocess.run(["ssh", "-o", f"ConnectTimeout={timeout}",
                        f"root@{DROPLET_IP}", cmd], capture_output=True, text=True)
    return r

def free_gb():
    for attempt in range(5):
        r = ssh("df --output=avail -BG / | tail -1")
        val = r.stdout.strip().rstrip("G")
        if val.isdigit(): return int(val)
        print(f"  [ssh retry {attempt+1}/5 — droplet not ready]"); time.sleep(15)
    raise RuntimeError("Cannot reach droplet after 5 retries")

def scorecard_exists(display):
    base = f"{QUAL_LAB_DIR}/reports/qualification/thomas-translator/{display}"
    if not os.path.isdir(base): return False
    return any(os.path.exists(os.path.join(base, r, "scorecard.json")) for r in os.listdir(base))

def download(hf_repo, display):
    dest = f"{MODELS_DIR}/{display}"
    print(f"  Downloading {hf_repo}  →  {dest} ...")
    r = subprocess.run(["ssh", f"root@{DROPLET_IP}",
        f'docker exec rocm bash -c "hf download {hf_repo} --local-dir {dest}"'])
    return r.returncode == 0

def delete(display):
    ssh(f"rm -rf {MODELS_DIR}/{display}")
    print(f"  Deleted {display}")

def restart_socat():
    ssh("kill $(pgrep socat) 2>/dev/null; nohup socat TCP-LISTEN:8080,fork TCP:172.17.0.2:8080 >/dev/null 2>&1 &")
    time.sleep(2)

def deploy(display):
    r = requests.post(f"{FORGE_API}/orchestrator/deploy",
        json={"model_name":display,"target_node":"mi300","engine":"vllm","backend":"cuda"}, timeout=30)
    r.raise_for_status(); return r.json()

def teardown():
    try: requests.post(f"{FORGE_API}/orchestrator/teardown", json={"target_node":"mi300"}, timeout=15)
    except: pass

def wait_up(timeout=DEPLOY_WAIT):
    url = f"http://{DROPLET_IP}:{PORT}/v1/models"
    end = time.time() + timeout
    print(f"  Waiting for vLLM ({timeout}s max)", end="", flush=True)
    while time.time() < end:
        try:
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                mid = r.json()["data"][0]["id"]
                print(f"  UP  (id={mid})"); return mid
        except: pass
        time.sleep(5); print(".", end="", flush=True)
    print("  TIMEOUT"); return None

def qualify(serving_id, display):
    cmd = ["cargo","run","--example","run_qualification","--",
           f"http://{DROPLET_IP}:{PORT}", serving_id, "vllm", "UNKNOWN", "mi300", display]
    return subprocess.run(cmd, cwd=QUAL_LAB_DIR).returncode == 0

def latest_score(display):
    base = f"{QUAL_LAB_DIR}/reports/qualification/thomas-translator/{display}"
    if not os.path.isdir(base): return None
    runs = sorted(os.listdir(base))
    if not runs: return None
    p = os.path.join(base, runs[-1], "scorecard.json")
    return json.load(open(p)) if os.path.exists(p) else None

def fmt(row):
    err = row.get("error","")
    if err: return f"  ✗  {row['model']:<54} ERROR: {err}"
    return (f"  ✓  {row['model']:<54} "
            f"score={int(row.get('score',0)*100):3d}  "
            f"{row.get('pass_rate','?'):6s}  "
            f"{row.get('latency_ms',0):.0f}ms  [{row.get('arch','?')}]")

def main():
    print(f"\n{'='*68}\nMI300X — Large-Model Benchmark Sweep  ({len(MODELS)} models)\n{'='*68}\n")
    summary = []

    for i, m in enumerate(MODELS, 1):
        d, repo, sz, arch = m["display"], m["hf_repo"], m["size_gb"], m["arch"]
        print(f"\n[{i:02d}/{len(MODELS)}] {d}  ({arch}, ~{sz}GB)")
        print("-"*62)

        if scorecard_exists(d):
            print("  Cached — reading scorecard.")
            sc = latest_score(d)
            if sc:
                fp = sc.get("first_pass",{})
                row = {"model":d,"arch":arch,"score":sc.get("standard_suite_ranking_score",0),
                       "pass_rate":f"{fp.get('validator_success')}/{fp.get('total_runs')}",
                       "latency_ms":fp.get("mean_latency_ms",0),"state":sc.get("qualification_state")}
                summary.append(row); print(fmt(row))
            continue

        # Ensure droplet + socat are up before disk check
        restart_socat()

        try: avail = free_gb()
        except RuntimeError as e:
            print(f"  ABORT — {e}"); break

        print(f"  Disk: {avail}GB free  (need ~{sz}GB)")
        if avail < sz + 20:
            print("  SKIP — not enough disk.")
            summary.append({"model":d,"arch":arch,"error":"disk_full"}); continue

        teardown(); time.sleep(2)

        if not download(repo, d):
            print("  SKIP — download failed.")
            summary.append({"model":d,"arch":arch,"error":"download_failed"}); continue

        try: print(f"  Deploy: {deploy(d)}")
        except Exception as e:
            print(f"  SKIP — deploy error: {e}")
            delete(d); summary.append({"model":d,"arch":arch,"error":"deploy_failed"}); continue

        serving_id = wait_up()
        if not serving_id:
            teardown(); delete(d)
            summary.append({"model":d,"arch":arch,"error":"server_timeout"}); continue

        qualify(serving_id, d)
        teardown(); time.sleep(3); delete(d)

        sc = latest_score(d)
        if sc:
            fp = sc.get("first_pass",{})
            row = {"model":d,"arch":arch,"score":sc.get("standard_suite_ranking_score",0),
                   "pass_rate":f"{fp.get('validator_success')}/{fp.get('total_runs')}",
                   "latency_ms":fp.get("mean_latency_ms",0),"state":sc.get("qualification_state")}
            print(f"\n  RESULT → score={row['score']:.4f} | {row['pass_rate']} passes | {row['latency_ms']:.0f}ms latency")
        else:
            row = {"model":d,"arch":arch,"error":"no_scorecard"}
        summary.append(row)

        with open("/tmp/mi300x_sweep_results.json","w") as f: json.dump(summary,f,indent=2)
        try: print(f"  Disk after cleanup: {free_gb()}GB free")
        except: pass

    print(f"\n\n{'='*68}\nSWEEP COMPLETE\n{'='*68}")
    for row in summary: print(fmt(row))
    with open("/tmp/mi300x_sweep_results.json","w") as f: json.dump(summary,f,indent=2)
    print("\nResults: /tmp/mi300x_sweep_results.json")

if __name__ == "__main__": main()
# NOTE: Ornith-397B entry for standalone llama.cpp run (appended)
# Run this separately after the main sweep with --ornith flag
