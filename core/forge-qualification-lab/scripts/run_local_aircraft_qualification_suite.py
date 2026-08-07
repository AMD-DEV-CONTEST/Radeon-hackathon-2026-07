#!/usr/bin/env python3
"""
run_local_aircraft_qualification_suite.py

Evaluates local GGUF models against the Aircraft Qualification Suite (SAR Aircraft Benchmark)
using the exact same 100-point rubric as the MI300X runs for direct comparative analysis.
"""

import os
import sys
import time
import json
import requests

FORGE_API    = "http://localhost:9100"
QUAL_LAB_DIR = "/home/cesarops/cesarops_push/core/forge-qualification-lab"

LOCAL_MODELS = [
    {"model_name": "deepreinforce-ai_Ornith-1.0-35B-Q4_K_M.gguf", "display": "Ornith-35B-Q4_K_M (Local)"},
    {"model_name": "deepreinforce-ai_Ornith-1.0-35B-Q6_K_L.gguf", "display": "Ornith-35B-Q6_K_L (Local)"},
    {"model_name": "QwQ-32B-Q4_K_M.gguf",                         "display": "QwQ-32B-Q4_K_M (Local)"},
    {"model_name": "QwQ-32B-Q6_K.gguf",                           "display": "QwQ-32B-Q6_K (Local)"},
    {"model_name": "Qwen3.6-35B-A3B-MXFP4_MOE.gguf",               "display": "Qwen3.6-35B-MXFP4 (Local)"},
    {"model_name": "gemma-4-26B-A4B-it-Q8_0.gguf",                 "display": "Gemma-4-26B-Q8_0 (Local)"},
    {"model_name": "Hermes-3-Llama-3.1-8B-Q5_K_M.gguf",            "display": "Hermes3-8B-Q5 (Local)"},
    {"model_name": "Phi-3-mini-4k-instruct-Q4_K_M.gguf",           "display": "Phi-3-mini-Q4 (Local)"},
    {"model_name": "ai21labs_AI21-Jamba-Reasoning-3B-Q4_K_M.gguf", "display": "Jamba-3B-Q4 (Local)"},
    {"model_name": "ZAYA1-8B-Q4_K_M.gguf",                         "display": "Zaya-8B-Q4 (Local)"},
]

SITES = [
    {
        "site_id": "SITE-001",
        "name": "Sólheimasandur Plane Wreck",
        "sources": ["Sentinel-2", "Maxar"],
        "confounders": ["tour buses", "snow"],
        "prompt": "Evaluate evidence for a suspected C-117D aircraft wreck on Icelandic black sand plains. Available sources: Sentinel-2 multispectral, Maxar optical (2020-2026). Known confounders: Tour buses, snow cover."
    },
    {
        "site_id": "SITE-002",
        "name": "Atka Island Liberator",
        "sources": ["Maxar", "Google Earth"],
        "confounders": ["WWII debris", "shadows"],
        "prompt": "Evaluate evidence for a B-24D Liberator crash site on open Aleutian tundra. Available sources: Maxar optical, Google Earth archives. Known confounders: Historical WWII military debris, topography shadows."
    },
    {
        "site_id": "SITE-003",
        "name": "Gauli Glacier Skytrooper",
        "sources": ["Swisstopo"],
        "confounders": ["crevasses", "moraine rocks"],
        "prompt": "Evaluate evidence for an emerging C-53 Skytrooper on an Alpine glacier during summer melt peak. Available sources: Swisstopo multi-temporal optical/thermal. Known confounders: Deep crevasses, glacial moraine rocks."
    },
    {
        "site_id": "SITE-004",
        "name": "Loon Lake Dragon",
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

NODE_IPS = {
    "cesarops2": "10.0.0.201",
    "cesarops3": "10.0.0.111",
    "cesarops4": "10.0.0.41",
    "t440": "10.0.0.61",
}

def get_recommendation(model_file):
    try:
        r = requests.get(f"{FORGE_API}/orchestrator/recommendations", timeout=5)
        if r.status_code == 200:
            for rec in r.json():
                if rec.get("model_name") == model_file:
                    return rec.get("recommended_node")
    except: pass
    return "cesarops3"

def deploy(model_file, node):
    r = requests.post(f"{FORGE_API}/orchestrator/deploy", json={
        "model_name": model_file, "target_node": node, "engine": "llama.cpp", "backend": "cuda"
    }, timeout=30)
    r.raise_for_status()
    return r.json()

def teardown(node):
    try: requests.post(f"{FORGE_API}/orchestrator/teardown", json={"target_node": node}, timeout=15)
    except: pass

def wait_up(ip, port=8080, timeout=120):
    url = f"http://{ip}:{port}/v1/models"
    end = time.time() + timeout
    print(f"  Waiting for local server at {url}...", end="", flush=True)
    while time.time() < end:
        try:
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                mid = r.json()["data"][0]["id"]
                print(f" UP (id={mid})")
                return mid
        except: pass
        time.sleep(3); print(".", end="", flush=True)
    print(" TIMEOUT"); return None

def query_model(ip, port, serving_id, prompt):
    url = f"http://{ip}:{port}/v1/chat/completions"
    payload = {
        "model": serving_id,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.0,
        "max_tokens": 1024
    }
    try:
        r = requests.post(url, json=payload, timeout=180)
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"    API Error: {e}")
    return None

def score_site_response(raw_output, site):
    scores = {
        "json_valid": 0,
        "finds_candidate": 0,
        "no_hallucination": 0,
        "multiple_sources": 0,
        "explains_uncertainty": 0,
        "requests_data": 0,
        "total": 0
    }
    if not raw_output: return scores
    try:
        data = json.loads(raw_output)
        scores["json_valid"] = 10
    except:
        return scores

    if data.get("candidate_identified") is True: scores["finds_candidate"] = 20
    elif data.get("confidence_level") in ["Low", "Medium", "High"]: scores["finds_candidate"] = 10

    claim = str(data.get("strongest_supported_claim", "")).lower()
    conf_level = str(data.get("confidence_level", ""))
    bad_phrases = ["definitely found", "proven detection", "100%", "autonomous detector", "standalone detector"]
    has_bad_claim = any(bp in claim for bp in bad_phrases) or (conf_level == "High" and "bounded" not in claim)
    
    if not has_bad_claim:
        if "search-grid" in claim or "prioritization" in claim or "contribute useful evidence" in claim:
            scores["no_hallucination"] = 25
        else: scores["no_hallucination"] = 15
    else: scores["no_hallucination"] = 0

    sources_used = [str(s).lower() for s in data.get("evidence_sources_used", [])]
    expected_sources = [s.lower() for s in site["sources"]]
    matched_sources = sum(1 for es in expected_sources if any(es in su for su in sources_used))
    if len(sources_used) >= 2 or matched_sources >= 2: scores["multiple_sources"] = 20
    elif len(sources_used) == 1 or matched_sources == 1: scores["multiple_sources"] = 10

    obs_confounders = [str(c).lower() for c in data.get("observed_confounders", [])]
    explanation = str(data.get("uncertainty_explanation", "")).lower()
    expected_confounders = [c.lower() for c in site["confounders"]]
    matched_confounders = sum(1 for ec in expected_confounders if any(ec in oc for oc in obs_confounders) or ec in explanation)
    if matched_confounders >= 1 and len(explanation) > 20: scores["explains_uncertainty"] = 15
    elif len(explanation) > 10: scores["explains_uncertainty"] = 8

    companion = data.get("recommended_companion_layers", [])
    next_step = str(data.get("next_recommended_step", "")).lower()
    if len(companion) > 0 or "human" in next_step or "review" in next_step or "fusion" in next_step:
        scores["requests_data"] = 10

    scores["total"] = sum(v for k, v in scores.items() if k != "total")
    return scores

def main():
    print("=" * 68)
    print("LOCAL MODELS — AIRCRAFT QUALIFICATION SUITE BENCHMARK")
    print("=" * 68 + "\n")

    results = {}

    for i, item in enumerate(LOCAL_MODELS, 1):
        model_file = item["model_name"]
        display    = item["display"]
        node       = get_recommendation(model_file) or "cesarops3"
        ip         = NODE_IPS.get(node, "10.0.0.111")

        print(f"\n[{i}/{len(LOCAL_MODELS)}] {display}  -> Node: {node} ({ip})")
        print("-" * 60)

        teardown(node); time.sleep(2)
        try:
            print(f"  Deploying {model_file} to {node}...")
            deploy(model_file, node)
        except Exception as e:
            print(f"  Deploy failed: {e}")
            results[display] = {"error": f"deploy_failed: {e}"}
            continue

        serving_id = wait_up(ip)
        if not serving_id:
            teardown(node)
            results[display] = {"error": "server_timeout"}
            continue

        site_scores = []
        for site in SITES:
            print(f"  -> Testing {site['site_id']}: {site['name']}...", end="", flush=True)
            t0 = time.time()
            raw_output = query_model(ip, 8080, serving_id, site["prompt"])
            lat_ms = (time.time() - t0) * 1000.0

            scored = score_site_response(raw_output, site)
            scored["site_id"] = site["site_id"]
            scored["latency_ms"] = round(lat_ms)
            site_scores.append(scored)
            print(f" [{scored['total']}/100 pts | {scored['latency_ms']}ms]")

        teardown(node); time.sleep(2)

        avg_score = sum(s["total"] for s in site_scores) / len(site_scores) if site_scores else 0
        avg_lat = sum(s["latency_ms"] for s in site_scores) / len(site_scores) if site_scores else 0
        
        m_res = {
            "model_name": model_file,
            "overall_score": round(avg_score, 1),
            "avg_latency_ms": round(avg_lat),
            "site_scores": site_scores
        }
        results[display] = m_res
        print(f"\n  OVERALL SCORE: {m_res['overall_score']}/100 | Avg Latency: {m_res['avg_latency_ms']}ms")

    print("\n\n" + "=" * 68)
    print("LOCAL MODELS BENCHMARK — FINAL RESULTS")
    print("=" * 68)
    for display, res in results.items():
        if "error" in res:
            print(f"{display:<38} | ERROR: {res['error']}")
        else:
            print(f"{display:<38} | Score: {res['overall_score']:<6.1f} | Latency: {res['avg_latency_ms']}ms")

    with open("/tmp/local_aircraft_suite_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("\nSaved local suite results to /tmp/local_aircraft_suite_results.json")

if __name__ == "__main__":
    main()
