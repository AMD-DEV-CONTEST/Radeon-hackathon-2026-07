"""
ForgeArena Tool Router — real function calls for agents.
Covers: RAG (retrieve_policy), Simulation (simulate_action), Memory (query_memory)
"""

import json, os, re, time
from difflib import SequenceMatcher

BASE = os.path.dirname(os.path.abspath(__file__))
POLICY_PATH = os.path.join(BASE, "policy_library.jsonl")
TFT_POLICY_PATH = os.path.join(BASE, "tft_policy.jsonl")
MEMORY_PATH = os.path.join(BASE, "memory_log.jsonl")

# ── Load Policy Libraries ──
_policies = []

def _load_policies(path, weight_multiplier=1.0):
    """Load policies from a JSONL file, with optional score weight."""
    count = 0
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        p = json.loads(line)
                        p["_weight"] = weight_multiplier
                        _policies.append(p)
                        count += 1
                    except json.JSONDecodeError:
                        continue
    return count

c1 = _load_policies(POLICY_PATH, weight_multiplier=1.0)
c2 = _load_policies(TFT_POLICY_PATH, weight_multiplier=5.0)
c3 = _load_policies(os.path.join(BASE, "football_policy.jsonl"), weight_multiplier=5.0)
c4 = _load_policies(os.path.join(BASE, "finance_policy.jsonl"), weight_multiplier=5.0)
print("[Tools] Loaded %d policies (%d general, %d TFT, %d football, %d finance)" % (len(_policies), c1, c2, c3, c4))


# ── Tool 1: retrieve_policy (RAG) ──

def retrieve_policy(query: str, domain: str = "", top_k: int = 3) -> list:
    """
    Search policy library by keyword similarity + domain filter.
    Returns top_k matching policies as formatted strings.
    """
    query_lower = query.lower()
    scored = []

    for p in _policies:
        score = 0.0

        # Domain match (high weight)
        p_domain = (p.get("domain") or "").lower()
        if domain.lower() in p_domain or p_domain in domain.lower():
            score += 3.0

        # Keyword match
        keywords = p.get("keywords") or []
        if isinstance(keywords, str):
            keywords = [keywords]
        for kw in keywords:
            kw_lower = kw.lower()
            if kw_lower in query_lower:
                score += 2.0
            # Partial match
            for q_word in query_lower.split():
                if len(q_word) > 3 and q_word in kw_lower:
                    score += 1.0

        # Trigger match
        trigger = p.get("trigger") or ""
        if isinstance(trigger, list):
            trigger = " ".join(trigger)
        trigger = trigger.lower()
        if trigger and trigger in query_lower:
            score += 2.0

        # Title/abstract similarity
        abstract = p.get("abstract_policy") or p.get("scene") or ""
        if isinstance(abstract, list):
            abstract = " ".join(abstract)
        abstract = abstract.lower()
        score += SequenceMatcher(None, query_lower[:50], abstract[:50]).ratio() * 1.5

        if score > 0:
            score *= p.get("_weight", 1.0)
            scored.append((score, p))

    scored.sort(key=lambda x: -x[0])
    results = scored[:top_k]

    formatted = []
    for score, p in results:
        entry = {
            "belief": p.get("belief", ""),
            "abstract": p.get("abstract_policy") or p.get("scene", ""),
            "goal": p.get("goal", ""),
            "dos": (p.get("dos") or [])[:2],
            "donts": (p.get("donts") or [])[:2],
            "domain": p.get("domain", ""),
            "action_chain": p.get("action_chain", {}),
            "_score": round(score, 2),
        }
        formatted.append(entry)

    return formatted


# ── Tool 2: simulate_action ──

def simulate_action(state: dict, action: str) -> dict:
    """
    Simple rule-based simulation of action outcomes.
    Returns projected results.
    """
    def _safe_int(val, default):
        try:
            v = val
            if isinstance(v, str):
                v = v.strip()
                if not v:
                    return default
            return int(float(v))
        except (ValueError, TypeError):
            return default

    hp = _safe_int(state.get("hp", 50), 50)
    gold = _safe_int(state.get("gold", 30), 30)
    level = _safe_int(state.get("level", 6), 6)

    action_lower = action.lower()
    result = {"action": action, "confidence": 0.5, "projected_impact": "unknown"}

    if "level" in action_lower or "roll" in action_lower:
        cost = min(gold, 20)
        new_gold = gold - cost
        result["projected_impact"] = "short-term power spike"
        result["estimated_survival"] = "moderate"
        result["gold_after"] = new_gold
        result["confidence"] = 0.65

    elif "save" in action_lower or "conserv" in action_lower or "stable" in action_lower:
        result["projected_impact"] = "long-term economy advantage"
        result["estimated_survival"] = "high"
        result["gold_after"] = gold + 5
        result["confidence"] = 0.80

    elif "draft" in action_lower or "buy" in action_lower or "item" in action_lower:
        cost = min(gold, 12)
        new_gold = gold - cost
        result["projected_impact"] = "immediate board strength"
        result["estimated_survival"] = "moderate"
        result["gold_after"] = new_gold
        result["confidence"] = 0.60

    elif "aggressive" in action_lower or "push" in action_lower or "risk" in action_lower:
        result["projected_impact"] = "high risk, high reward"
        result["estimated_survival"] = "low"
        result["gold_after"] = max(0, gold - 30)
        result["confidence"] = 0.45

    if hp < 30:
        result["urgency"] = "high"
    elif hp < 60:
        result["urgency"] = "medium"
    else:
        result["urgency"] = "low"

    return result


# ── Tool 3: query_memory (for multi-round memory) ──

def query_memory(agent_name: str, last_n: int = 3) -> list:
    """Retrieve past decisions for an agent from memory log."""
    if not os.path.exists(MEMORY_PATH):
        return []

    memories = []
    try:
        with open(MEMORY_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entry = json.loads(line)
                        if entry.get("agent") == agent_name:
                            memories.append(entry)
                    except:
                        continue
    except:
        return []

    return memories[-last_n:]


def get_all_memory(last_n: int = 3) -> list:
    """Retrieve most recent memory entries across all agents."""
    if not os.path.exists(MEMORY_PATH):
        return []

    memories = []
    try:
        with open(MEMORY_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        memories.append(json.loads(line))
                    except:
                        continue
    except:
        return []

    return memories[-last_n:]


def save_memory_entry(user_input: str, agent_name: str, scene: dict, result: dict):
    """Save a decision entry to memory log."""
    entry = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "agent": agent_name,
        "user_input": user_input[:200],
        "world_state": {k: str(v) for k, v in scene.get("world_state", {}).items()},
        "action": result.get("action", ""),
        "confidence": result.get("confidence", 0),
        "rationale": result.get("rationale", "")[:200],
    }
    try:
        with open(MEMORY_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except:
        pass
