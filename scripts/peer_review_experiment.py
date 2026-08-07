import json
import os
import requests
import time

GEMMA_URL = "http://cesarops3:5580/v1/chat/completions"
NIM_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
NIM_KEY = os.environ.get("QUAL_API_KEY", "")

SCORECARD_DIR = "/home/cesarops/cesarops_push/reports/qualification/thomas-translator"
GEMMA_SCORECARD = f"{SCORECARD_DIR}/gemma-4-E4B-it-Q4_K_M.gguf/latest/scorecard.json"
NIM_SCORECARD = f"{SCORECARD_DIR}/nvidia_llama-3.3-nemotron-super-49b-v1/latest/scorecard.json"

FIXTURE_SYSTEM_PROMPT = "You are the CESARops Contract Builder. Emit ONLY a CodeMissionDraft JSON object."
FIXTURE_USER_PROMPT = '{"type":"CodeMissionDraft","mission":"Build an app","repo":null,"branch":"main","requirements":["needs database"],"constraints":[],"non_goals":[],"priority":"P1","complexity":"med","thomas_notes":"Repo not specified."}'

REVIEW_SYSTEM_PROMPT = """You are the CESARops Qualification Review Guard.
Your job is to blindly review a candidate model's JSON output for constraint omissions.
You will receive the original fixture (System and User prompts) and the Candidate Output.

HARD CONSTRAINTS FOR THIS FIXTURE:
1. The JSON MUST contain the keys: "mission", "requirements", "clarifications" (because repo is null).
2. The JSON MUST NOT contain the key: "repo".

Analyze the Candidate Output. If it violates ANY hard constraint, reject it.
Return ONLY a JSON object with this exact schema:
{
  "accept": boolean,
  "omissions": ["list", "of", "missing or forbidden keys found"],
  "source_constraint": "string citing which rule failed",
  "minimal_patch": "string containing the full, valid, patched JSON object"
}
"""

def extract_failures(scorecard_path):
    failures = []
    try:
        with open(scorecard_path, 'r') as f:
            data = json.load(f)
            for run in data.get('runs', []):
                if run.get('fixture_id') == 'thomas_clarification_ambiguous' and run.get('repeat', 99) < 3:
                    failures.append(run.get('raw_output', ''))
    except Exception as e:
        print(f"Error reading {scorecard_path}: {e}")
    return failures

def run_inference(model_name, url, api_key, candidate_output):
    user_msg = f"""
ORIGINAL SYSTEM PROMPT:
{FIXTURE_SYSTEM_PROMPT}

ORIGINAL USER PROMPT:
{FIXTURE_USER_PROMPT}

CANDIDATE OUTPUT:
{candidate_output}
"""
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
        
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg}
        ],
        "temperature": 0.0,
        "max_tokens": 1024,
        "response_format": {"type": "json_object"}
    }
    
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=60)
        res.raise_for_status()
        return res.json()['choices'][0]['message']['content']
    except Exception as e:
        print(f"Inference failed for {model_name}: {e}")
        if 'res' in locals():
            print(res.text)
        return None

def check_patch_compliance(patch_str):
    try:
        data = json.loads(patch_str)
        if not isinstance(data, dict):
            return False
        # Must have keys
        for k in ["mission", "requirements", "clarifications"]:
            if k not in data:
                return False
        # Must NOT have keys
        if "repo" in data:
            return False
        return True
    except:
        return False

def evaluate_reviewer(reviewer_name, url, api_key, model_label, candidate_failures):
    results = []
    print(f"\n--- {reviewer_name} Reviewing {model_label}'s Failures ---")
    for i, candidate_output in enumerate(candidate_failures):
        print(f"Running review {i}...")
        res_str = run_inference(reviewer_name, url, api_key, candidate_output)
        if not res_str:
            results.append({"peer_detection": False, "peer_repair": False, "raw": None})
            continue
            
        try:
            review_json = json.loads(res_str)
            detected = review_json.get("accept") is False
            patch = review_json.get("minimal_patch", "{}")
            
            # extract string if patch is given as json dict inside
            if isinstance(patch, dict):
                patch_str = json.dumps(patch)
            else:
                patch_str = patch
                
            repaired = check_patch_compliance(patch_str)
            results.append({
                "peer_detection": detected,
                "peer_repair": repaired,
                "raw": review_json
            })
            print(f"  Detected: {detected}, Repaired: {repaired}")
        except Exception as e:
            print(f"  Failed to parse reviewer JSON: {e}")
            results.append({"peer_detection": False, "peer_repair": False, "raw": res_str})
    return results

def main():
    if not NIM_KEY:
        print("Missing QUAL_API_KEY environment variable")
        return
        
    gemma_fails = extract_failures(GEMMA_SCORECARD)
    nim_fails = extract_failures(NIM_SCORECARD)
    
    print(f"Found {len(gemma_fails)} Gemma failures and {len(nim_fails)} NIM failures.")
    
    gemma_reviewing_nim = evaluate_reviewer("gemma-4-E4B-it", GEMMA_URL, None, "NIM", nim_fails)
    nim_reviewing_gemma = evaluate_reviewer("nvidia/llama-3.3-nemotron-super-49b-v1", NIM_URL, NIM_KEY, "Gemma", gemma_fails)
    
    report = "# Peer Review Experiment Results\n\n"
    report += "## Gemma reviewing Nemotron's Failures\n"
    for i, r in enumerate(gemma_reviewing_nim):
        report += f"**Run {i}:**\n"
        report += f"- Self-generation: False\n"
        report += f"- Peer detection: {r['peer_detection']}\n"
        report += f"- Peer repair: {r['peer_repair']}\n"
        report += f"- Raw Reviewer Output:\n```json\n{json.dumps(r['raw'], indent=2)}\n```\n\n"
        
    report += "## Nemotron reviewing Gemma's Failures\n"
    for i, r in enumerate(nim_reviewing_gemma):
        report += f"**Run {i}:**\n"
        report += f"- Self-generation: False\n"
        report += f"- Peer detection: {r['peer_detection']}\n"
        report += f"- Peer repair: {r['peer_repair']}\n"
        report += f"- Raw Reviewer Output:\n```json\n{json.dumps(r['raw'], indent=2)}\n```\n\n"
        
    os.makedirs("/home/cesarops/cesarops_push/reports", exist_ok=True)
    with open("/home/cesarops/cesarops_push/reports/peer_review_results.md", "w") as f:
        f.write(report)
        
    print("Done! Report written to reports/peer_review_results.md")

if __name__ == "__main__":
    main()
