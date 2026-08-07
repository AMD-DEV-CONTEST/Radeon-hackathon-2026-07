#!/usr/bin/env python3
"""
run_aircraft_qualification_suite.py

Aircraft Qualification Suite (SAR Aircraft Benchmark)
Evaluates LLM performance on 4 multi-terrain aircraft crash search-grid sites:
1. Sólheimasandur DC-3 (Iceland - Black Sand)
2. Atka Island B-24D (Alaska - Tundra)
3. Gauli Glacier C-53 (Switzerland - Glacial Ice)
4. Loon Lake B-23 (Idaho - Sub-canopy Forest)

Rubric Weighting (100 Points Total per Site):
- Finds candidate (20 pts)
- Doesn't hallucinate / Bounded claims (25 pts)
- Uses multiple evidence sources (20 pts)
- Explains uncertainty & confounders (15 pts)
- Requests additional data / Next steps (10 pts)
- Structured JSON format (10 pts)
"""

import os
import sys
import time
import json
import subprocess
import requests

FORGE_API    = "http://localhost:9100"
QUAL_LAB_DIR = "/home/cesarops/cesarops_push/core/forge-qualification-lab"
DROPLET_IP   = "134.199.203.198"
MODELS_DIR   = "/shared-docker/models"
PORT         = 8080
DEPLOY_WAIT  = 300

MODELS = [
    # Tier 1 (Highest Confidence)
    {"display": "Ornith-1.0-35B-BF16",               "hf_repo": "deepreinforce-ai/Ornith-1.0-35B",                       "size_gb": 70,  "tier": "Tier 1"},
    {"display": "DeepSeek-Coder-V2-Instruct-AWQ",    "hf_repo": "casperhansen/deepseek-coder-v2-instruct-awq",            "size_gb": 129, "tier": "Tier 1"},
    {"display": "Qwen2.5-72B-AWQ",                   "hf_repo": "Qwen/Qwen2.5-72B-Instruct-AWQ",                        "size_gb": 39,  "tier": "Tier 1"},
    # Tier 2
    {"display": "Llama-3.1-70B-AWQ",                 "hf_repo": "hugging-quants/Meta-Llama-3.1-70B-Instruct-AWQ-INT4",  "size_gb": 38,  "tier": "Tier 2"},
    # Tier 3
    {"display": "Mixtral-8x22B-AWQ",                 "hf_repo": "MaziyarPanahi/Mixtral-8x22B-Instruct-v0.1-AWQ",        "size_gb": 69,  "tier": "Tier 3"},
    # Wildcard
    {"display": "QwQ-32B",                           "hf_repo": "Qwen/QwQ-32B",                                         "size_gb": 66,  "tier": "Wildcard"},
]

SITES = [
    {
        "site_id": "SITE-001",
        "name": "Sólheimasandur Plane Wreck",
        "aircraft": "C-117D (Super DC-3)",
        "terrain": "Black Sand",
        "region": "Iceland",
        "sources": ["Sentinel-2", "Maxar"],
        "confounders": ["tour buses", "snow"],
        "prompt": "Evaluate evidence for a suspected C-117D aircraft wreck on Icelandic black sand plains. Available sources: Sentinel-2 multispectral, Maxar optical (2020-2026). Known confounders: Tour buses, snow cover."
    },
    {
        "site_id": "SITE-002",
        "name": "Atka Island Liberator",
        "aircraft": "B-24D Liberator",
        "terrain": "Tundra / Grassland",
        "region": "Alaska, USA",
        "sources": ["Maxar", "Google Earth"],
        "confounders": ["WWII debris", "shadows"],
        "prompt": "Evaluate evidence for a B-24D Liberator crash site on open Aleutian tundra. Available sources: Maxar optical, Google Earth archives. Known confounders: Historical WWII military debris, topography shadows."
    },
    {
        "site_id": "SITE-003",
        "name": "Gauli Glacier Skytrooper",
        "aircraft": "C-53 Skytrooper",
        "terrain": "Glacial Ice / Snow",
        "region": "Switzerland",
        "sources": ["Swisstopo"],
        "confounders": ["crevasses", "moraine rocks"],
        "prompt": "Evaluate evidence for an emerging C-53 Skytrooper on an Alpine glacier during summer melt peak. Available sources: Swisstopo multi-temporal optical/thermal. Known confounders: Deep crevasses, glacial moraine rocks."
    },
    {
        "site_id": "SITE-004",
        "name": "Loon Lake Dragon",
        "aircraft": "B-23 Dragon",
        "terrain": "Dense Sub-canopy Forest",
        "region": "Idaho, USA",
        "sources": ["NAIP", "Sentinel-2"],
        "confounders": ["tree shadows", "shoreline rocks"],
        "prompt": "Evaluate sub-canopy linear disturbance for a B-23 Dragon in dense evergreen forest near shoreline. Available sources: NAIP high-res, Sentinel-2 (leaf-off). Known confounders: Dense tree canopy shadows, shoreline boulder clusters."
    }
]

SYSTEM_PROMPT = """You are a Search and Rescue (SAR) evidence qualification engine for Forge Test Lab.
Your task is to analyze remote-sensing evidence for a candidate aircraft site and produce a bounded evidence proposal.

CRITICAL POLICY CONSTRAINTS:
1. NO AUTONOMOUS DETECTION CLAIM: You must NEVER claim definitive "aircraft detection" or 100% certainty. The highest permitted claim is: "This method appears to contribute useful evidence toward search-grid prioritization under verified conditions."
2. STRICT BOUNDED CLAIMS: You must evaluate candidate ranking without making unverified overcommitments.
3. EXPLICIT UNCERTAINTY: You must identify specific terrain confounders and explain limitations.
4. COMPANION LAYERS: You must specify required companion data sources or next human review steps.

Respond ONLY with valid JSON matching this schema:
{
  "site_id": "SITE_ID",
  "candidate_identified": true,
  "confidence_level": "Low" | "Medium" | "High",
  "evidence_sources_used": ["source1", "source2"],
  "claimed_role": "SearchGridPrioritization",
  "strongest_supported_claim": "This method appears to contribute useful evidence toward search-grid prioritization under verified conditions.",
  "observed_confounders": ["confounder1", "confounder2"],
  "uncertainty_explanation": "Detailed explanation of limitations and confounders...",
  "recommended_companion_layers": ["layer1", "layer2"],
  "next_recommended_step": "AwaitingHumanReview"
}"""

def ssh(cmd):
    return subprocess.run(["ssh", f"root@{DROPLET_IP}", cmd], capture_output=True, text=True)

def free_gb():
    r = ssh("df --output=avail -BG / | tail -1")
    return int(r.stdout.strip().rstrip("G"))

def download(hf_repo, display):
    dest = f"{MODELS_DIR}/{display}"
    print(f"  Downloading {hf_repo} -> {dest}...")
    r = subprocess.run(
        ["ssh", f"root@{DROPLET_IP}",
         f'docker exec rocm bash -c "hf download {hf_repo} --local-dir {dest}"']
    )
    return r.returncode == 0

def delete(display):
    ssh(f"rm -rf {MODELS_DIR}/{display}")
    print(f"  Deleted {display} from disk.")

def deploy(display):
    r = requests.post(f"{FORGE_API}/orchestrator/deploy",
        json={"model_name": display, "target_node": "mi300", "engine": "vllm", "backend": "cuda"},
        timeout=30)
    r.raise_for_status()
    return r.json()

def teardown():
    try: requests.post(f"{FORGE_API}/orchestrator/teardown", json={"target_node": "mi300"}, timeout=15)
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
                print(f" UP  (id={mid})")
                return mid
        except: pass
        time.sleep(5); print(".", end="", flush=True)
    print(" TIMEOUT"); return None

def query_model(serving_id, user_prompt):
    url = f"http://{DROPLET_IP}:{PORT}/v1/chat/completions"
    payload = {
        "model": serving_id,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.0,
        "max_tokens": 1024,
        "response_format": {"type": "json_object"}
    }
    try:
        r = requests.post(url, json=payload, timeout=60)
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"    API Error: {e}")
    return None

def score_site_response(raw_output, site):
    """
    Rubric (100 pts total per site):
    - Finds candidate: 20 pts
    - Doesn't hallucinate / Bounded claims: 25 pts
    - Uses multiple evidence sources: 20 pts
    - Explains uncertainty & confounders: 15 pts
    - Requests additional data / Next steps: 10 pts
    - Structured JSON: 10 pts
    """
    scores = {
        "json_valid": 0,
        "finds_candidate": 0,
        "no_hallucination": 0,
        "multiple_sources": 0,
        "explains_uncertainty": 0,
        "requests_data": 0,
        "total": 0
    }
    
    if not raw_output:
        return scores

    # 1. Structured JSON (10 pts)
    try:
        data = json.loads(raw_output)
        scores["json_valid"] = 10
    except:
        return scores  # JSON parse failed

    # 2. Finds candidate (20 pts)
    if data.get("candidate_identified") is True:
        scores["finds_candidate"] = 20
    elif data.get("confidence_level") in ["Low", "Medium", "High"]:
        scores["finds_candidate"] = 10

    # 3. Doesn't hallucinate / Bounded claims (25 pts)
    claim = str(data.get("strongest_supported_claim", "")).lower()
    conf_level = str(data.get("confidence_level", ""))
    
    # Must NOT claim 100% or "detected aircraft definitely"
    bad_phrases = ["definitely found", "proven detection", "100%", "autonomous detector", "standalone detector"]
    has_bad_claim = any(bp in claim for bp in bad_phrases) or (conf_level == "High" and "bounded" not in claim)
    
    if not has_bad_claim:
        if "search-grid" in claim or "prioritization" in claim or "contribute useful evidence" in claim:
            scores["no_hallucination"] = 25
        else:
            scores["no_hallucination"] = 15
    else:
        scores["no_hallucination"] = 0  # Penalize overcommitment

    # 4. Uses multiple evidence sources (20 pts)
    sources_used = [str(s).lower() for s in data.get("evidence_sources_used", [])]
    expected_sources = [s.lower() for s in site["sources"]]
    matched_sources = sum(1 for es in expected_sources if any(es in su for su in sources_used))
    
    if len(sources_used) >= 2 or matched_sources >= 2:
        scores["multiple_sources"] = 20
    elif len(sources_used) == 1 or matched_sources == 1:
        scores["multiple_sources"] = 10

    # 5. Explains uncertainty & confounders (15 pts)
    obs_confounders = [str(c).lower() for c in data.get("observed_confounders", [])]
    explanation = str(data.get("uncertainty_explanation", "")).lower()
    expected_confounders = [c.lower() for c in site["confounders"]]
    
    matched_confounders = sum(1 for ec in expected_confounders if any(ec in oc for oc in obs_confounders) or ec in explanation)
    
    if matched_confounders >= 1 and len(explanation) > 20:
        scores["explains_uncertainty"] = 15
    elif len(explanation) > 10:
        scores["explains_uncertainty"] = 8

    # 6. Requests additional data / Next steps (10 pts)
    companion = data.get("recommended_companion_layers", [])
    next_step = str(data.get("next_recommended_step", "")).lower()
    
    if len(companion) > 0 or "human" in next_step or "review" in next_step or "fusion" in next_step:
        scores["requests_data"] = 10

    scores["total"] = sum(v for k, v in scores.items() if k != "total")
    return scores

def main():
    print("=" * 68)
    print("AIRCRAFT QUALIFICATION SUITE — SAR AIRCRAFT BENCHMARK (MI300X)")
    print("=" * 68 + "\n")

    suite_results = {}

    for i, m in enumerate(MODELS, 1):
        display = m["display"]
        repo    = m["hf_repo"]
        size_gb = m["size_gb"]
        tier    = m["tier"]

        print(f"\n[{i}/{len(MODELS)}] [{tier}] {display} (~{size_gb}GB)")
        print("-" * 60)

        # Check if downloaded
        check_path = f"{MODELS_DIR}/{display}"
        exists = subprocess.run(
            ["ssh", f"root@{DROPLET_IP}", f"test -d {check_path} && echo yes || echo no"],
            capture_output=True, text=True
        ).stdout.strip() == "yes"

        if not exists:
            avail = free_gb()
            print(f"  Disk: {avail}GB free, need ~{size_gb}GB")
            if avail < size_gb + 20:
                print("  SKIP — Not enough disk space")
                suite_results[display] = {"error": "disk_full"}
                continue
            
            teardown(); time.sleep(2)
            if not download(repo, display):
                print("  SKIP — Download failed")
                suite_results[display] = {"error": "download_failed"}
                continue

        teardown(); time.sleep(2)
        try:
            print(f"  Deploying to MI300X...")
            deploy(display)
        except Exception as e:
            print(f"  Deploy Error: {e}")
            suite_results[display] = {"error": f"deploy_failed: {e}"}
            continue

        serving_id = wait_up()
        if not serving_id:
            teardown()
            suite_results[display] = {"error": "server_timeout"}
            continue

        print(f"  Serving ID: {serving_id}")
        site_scores = []
        
        for site in SITES:
            print(f"  -> Testing {site['site_id']}: {site['name']} ({site['terrain']})...", end="", flush=True)
            start_t = time.time()
            raw_output = query_model(serving_id, site["prompt"])
            lat_ms = (time.time() - start_t) * 1000.0
            
            scored = score_site_response(raw_output, site)
            scored["site_id"] = site["site_id"]
            scored["site_name"] = site["name"]
            scored["latency_ms"] = round(lat_ms)
            site_scores.append(scored)
            
            print(f" [{scored['total']}/100 pts | {scored['latency_ms']}ms]")

        avg_score = sum(s["total"] for s in site_scores) / len(site_scores) if site_scores else 0
        avg_lat = sum(s["latency_ms"] for s in site_scores) / len(site_scores) if site_scores else 0
        
        model_result = {
            "tier": tier,
            "overall_score": round(avg_score, 1),
            "avg_latency_ms": round(avg_lat),
            "site_scores": site_scores
        }
        suite_results[display] = model_result
        
        print(f"\n  OVERALL SCORE: {model_result['overall_score']}/100 | Avg Latency: {model_result['avg_latency_ms']}ms")
        
        # Save output
        out_path = f"{QUAL_LAB_DIR}/reports/qualification/aircraft-search-grid-v1/{display}_aircraft_scorecard.json"
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(model_result, f, indent=2)

    print("\n\n" + "=" * 68)
    print("AIRCRAFT QUALIFICATION SUITE — FINAL LEADERBOARD")
    print("=" * 68)
    print(f"{'Model Name':<35} | {'Tier':<8} | {'Score':<8} | {'Latency':<8}")
    print("-" * 68)
    
    for display, res in suite_results.items():
        if "error" in res:
            print(f"{display:<35} | {'N/A':<8} | ERROR    | {res['error']}")
        else:
            print(f"{display:<35} | {res['tier']:<8} | {res['overall_score']:<8.1f} | {res['avg_latency_ms']}ms")

    with open("/tmp/aircraft_suite_final_results.json", "w") as f:
        json.dump(suite_results, f, indent=2)
    print("\nSaved final suite results to /tmp/aircraft_suite_final_results.json")

if __name__ == "__main__":
    main()
