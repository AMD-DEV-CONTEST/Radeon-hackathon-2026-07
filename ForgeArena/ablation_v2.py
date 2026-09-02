"""Ablation: same system prompt vs different prompts (v2)"""
import json, urllib.request, sys, time, re

sys.path.insert(0, "/workspace/forgearena")
from forgearena import create_sample_stages, ARCHETYPE_PROFILES, AgentArchetype

LLM_URL = "http://localhost:8000/v1/chat/completions"
MODEL = "/root/.cache/modelscope/models/qwen--Qwen2.5-7B-Instruct/snapshots/master"

def call_llm(prompt):
    payload = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 128,
        "temperature": 0.7,
    }).encode()
    req = urllib.request.Request(LLM_URL, data=payload,
        headers={"Content-Type": "application/json"})
    resp = json.loads(urllib.request.urlopen(req, timeout=120).read())
    return resp["choices"][0]["message"]["content"]

def extract_action(resp):
    """Extract action from JSON response, handling escaped quotes"""
    # Try direct JSON parse first
    resp_clean = resp.strip()
    if resp_clean.startswith("```"):
        resp_clean = resp_clean.split("```")[1].strip().lstrip("json")
    try:
        data = json.loads(resp_clean)
        return data.get("action", "?")
    except:
        pass
    # Fallback: regex search for action field
    m = re.search(r'[Aa]ction["\']?\s*[:=]\s*["\']([a-z_]+)["\']', resp)
    if m:
        return m.group(1)
    m = re.search(r'"action"\s*:\s*"([^"]+)"', resp)
    if m:
        return m.group(1)
    return "parse_error"

TEST_STATE = create_sample_stages()[2]
STATE_TEXT = TEST_STATE.to_text()

def run_ablation(label, system_prompts):
    results = []
    for i, sys_prompt in enumerate(system_prompts):
        name = [f"Agent_{chr(65+i)}" for i in range(3)][i]
        prompt = f"""{sys_prompt}

## Current Game State
{STATE_TEXT}

## Decision Required
Analyze and decide ONE action from:
level_up, roll, save_gold, transition

Respond in JSON:
{{"thinking":"...", "action":"...", "confidence":0.0-1.0}}"""
        t0 = time.time()
        resp = call_llm(prompt)
        action = extract_action(resp)
        elapsed = time.time() - t0
        results.append({"agent": name, "action": action, "time_s": round(elapsed, 1)})
        print(f"  {name}: {action} ({elapsed:.1f}s)")
    return results

print("=" * 60)
print("PERSONALITY ABLATION EXPERIMENT")
print("=" * 60)

print("\n[CASE 1] Different personality profiles")
diff = run_ablation("different", [
    ARCHETYPE_PROFILES[AgentArchetype.CONSERVATIVE]["system_prompt"],
    ARCHETYPE_PROFILES[AgentArchetype.AGGRESSIVE]["system_prompt"],
    ARCHETYPE_PROFILES[AgentArchetype.EXPLORER]["system_prompt"],
])

print("\n[CASE 2] Same neutral prompt (control)")
NEUTRAL = "You are a decision maker analyzing a game state. Make the best choice."
same = run_ablation("same", [NEUTRAL, NEUTRAL, NEUTRAL])

print(f"\n{'='*60}")
print("SUMMARY")
print(f"{'='*60}")
diff_actions = set(r["action"] for r in diff)
same_actions = set(r["action"] for r in same)
print(f"  Case 1 (different): {len(diff_actions)} unique actions - {[r['action'] for r in diff]}")
print(f"  Case 2 (same):      {len(same_actions)} unique actions - {[r['action'] for r in same]}")
print(f"  Conclusion: {'PERSONALITIES PRODUCE DIVERGENT BEHAVIOR' if len(diff_actions) > len(same_actions) else 'No significant difference detected'}")

json.dump({"state": STATE_TEXT, "case_different": diff, "case_same": same},
    open("/workspace/forgearena/output/ablation_v2.json", "w"), indent=2)
print("\nSaved to output/ablation_v2.json")
