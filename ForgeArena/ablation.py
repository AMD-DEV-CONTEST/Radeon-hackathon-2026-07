"""Ablation: same system prompt vs different prompts"""
import json, urllib.request, sys, time

sys.path.insert(0, "/workspace/forgearena")
from forgearena import create_sample_stages, ARCHETYPE_PROFILES, AgentArchetype

LLM_URL = "http://localhost:8000/v1/chat/completions"
MODEL = "/root/.cache/modelscope/models/qwen--Qwen2.5-7B-Instruct/snapshots/master"

def call_llm(prompt):
    payload = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 256,
        "temperature": 0.7,
    }).encode()
    req = urllib.request.Request(LLM_URL, data=payload,
        headers={"Content-Type": "application/json"})
    resp = json.loads(urllib.request.urlopen(req, timeout=120).read())
    return resp["choices"][0]["message"]["content"]

TEST_STATE = create_sample_stages()[2]  # Stage 3-2: 78HP, 45G, Lv6
STATE_TEXT = TEST_STATE.to_text()

def run_ablation(label, system_prompts):
    results = []
    for i, sys_prompt in enumerate(system_prompts):
        name = ["Agent_A", "Agent_B", "Agent_C"][i]
        prompt = f"""{sys_prompt}

## Current Game State
{STATE_TEXT}

## Decision Required
Analyze the current situation and decide on ONE action from:
- level_up: Spend gold to gain experience and level up
- roll: Refresh shop to find better units
- save_gold: Save gold for interest
- transition: Plan a composition transition

Respond in JSON:
{{"thinking":"...", "action":"...", "confidence":0.0-1.0, "expected_outcome":"..."}}"""
        t0 = time.time()
        resp = call_llm(prompt)
        elapsed = time.time() - t0
        results.append({"agent": name, "prompt_type": label, "response_raw": resp[:300], "time_s": round(elapsed, 1)})
    return results

print("=" * 60)
print("PERSONALITY ABLATION EXPERIMENT")
print("=" * 60)

# Case 1: Different prompts (personalities)
print("\n[CASE 1] Different personality profiles")
diff_results = run_ablation("different", [
    ARCHETYPE_PROFILES[AgentArchetype.CONSERVATIVE]["system_prompt"],
    ARCHETYPE_PROFILES[AgentArchetype.AGGRESSIVE]["system_prompt"],
    ARCHETYPE_PROFILES[AgentArchetype.EXPLORER]["system_prompt"],
])

# Case 2: Same prompt (control)
print("\n[CASE 2] Same neutral prompt (control)")
NEUTRAL = "You are a decision maker analyzing a game state. Make the best choice."
same_results = run_ablation("same", [NEUTRAL, NEUTRAL, NEUTRAL])

# Print comparison
print("\n" + "=" * 60)
print("RESULTS COMPARISON")
print("=" * 60)

print("\n--- CASE 1: Different Personalities ---")
for r in diff_results:
    print(f"\n  [{r['agent']}] ({r['time_s']}s)")
    print(f"  Raw: {r['response_raw'][:200]}")

print("\n--- CASE 2: Same Prompt (Control) ---")
for r in same_results:
    print(f"\n  [{r['agent']}] ({r['time_s']}s)")
    print(f"  Raw: {r['response_raw'][:200]}")

# Save
output = {"test_state": STATE_TEXT, "case_different": diff_results, "case_same": same_results}
with open("/workspace/forgearena/output/ablation.json", "w") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)
print("\nSaved to output/ablation.json")
