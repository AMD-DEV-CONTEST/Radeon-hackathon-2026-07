# ForgeArena: Multi-Agent Decision Sandbox
# Core framework for AMD AI DevMaster Hackathon 2026

import json, os, sys, time, random
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Callable
from enum import Enum

# ── Project Root ──
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# ════════════════════════════════════════════════════════
# 1. Agent Types & Personalities
# ════════════════════════════════════════════════════════

class AgentArchetype(Enum):
    CONSERVATIVE = "conservative"
    AGGRESSIVE = "aggressive"
    EXPLORER = "explorer"


ARCHETYPE_PROFILES = {
    AgentArchetype.CONSERVATIVE: {
        "system_prompt": (
            "You are a risk-averse decision maker. "
            "You prioritize stability and safety over maximum gain. "
            "You prefer to maintain a strong economy and only act when success is highly probable. "
            "Always consider downside risk before proposing a move."
        ),
        "risk_tolerance": 0.2,
        "aggression": 0.1,
        "exploration": 0.15,
    },
    AgentArchetype.AGGRESSIVE: {
        "system_prompt": (
            "You are an aggressive optimizer. "
            "You pursue maximum advantage and are willing to take calculated risks. "
            "You believe in pressing advantages hard and forcing opponents to react to you. "
            "You prefer high-risk, high-reward strategies."
        ),
        "risk_tolerance": 0.7,
        "aggression": 0.9,
        "exploration": 0.1,
    },
    AgentArchetype.EXPLORER: {
        "system_prompt": (
            "You are an adaptive explorer. "
            "You try non-conventional approaches and learn from outcomes. "
            "You value information gathering and are quick to switch strategies. "
            "You believe flexibility is more important than any fixed plan."
        ),
        "risk_tolerance": 0.5,
        "aggression": 0.4,
        "exploration": 0.9,
    },
}


# ════════════════════════════════════════════════════════
# 2. World State
# ════════════════════════════════════════════════════════

@dataclass
class WorldState:
    """Structured environment state (通用认知模型)"""
    # TFT-specific fields (as example domain)
    stage: str = "1-1"
    hp: int = 100
    gold: int = 0
    level: int = 1
    exp: int = 0
    win_streak: int = 0
    loss_streak: int = 0
    alive_players: int = 8
    # Market-state style fields (for demonstration of generalizability)
    regime: str = "unknown"
    risk_pressure: float = 0.0
    signal_composite: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    def to_text(self) -> str:
        """转为自然语言描述（供 LLM 输入）"""
        return (
            f"Stage: {self.stage}, HP: {self.hp}, Gold: {self.gold}, "
            f"Level: {self.level}, Win streak: {self.win_streak}, "
            f"Loss streak: {self.loss_streak}, Players alive: {self.alive_players}"
        )


# ════════════════════════════════════════════════════════
# 3. Agent Memory
# ════════════════════════════════════════════════════════

@dataclass
class AgentMemory:
    """Agent-specific memory"""
    episode_id: int = 0
    history: List[dict] = field(default_factory=list)
    decisions: List[dict] = field(default_factory=list)
    outcomes: List[dict] = field(default_factory=list)

    def record_state(self, ws: WorldState, action: str, reasoning: str, score: float):
        self.history.append({
            "step": len(self.history),
            "state": ws.to_dict(),
            "action": action,
            "reasoning": reasoning,
            "score": score,
        })

    def get_recent(self, n: int = 5) -> str:
        recent = self.history[-n:]
        lines = []
        for h in recent:
            lines.append(f"Step {h['step']}: {h['action']} (score={h['score']})")
        return "\n".join(lines)


# ════════════════════════════════════════════════════════
# 4. Tool Router （显式工具调用）
# ════════════════════════════════════════════════════════

class ToolRouter:
    """
    将内部能力封装为显式工具，用于展示"工具调用"能力
    """

    def __init__(self, policy_library_path: Optional[str] = None):
        self.policy_library = self._load_policies(policy_library_path)

    def _load_policies(self, path: Optional[str]) -> list:
        """加载策略库"""
        if path and os.path.exists(path):
            with open(path) as f:
                return json.load(f)
        # Fallback: built-in sample policies
        return [
            {"id": "conservative_econ", "domain": "economy", "goal": "stability",
             "abstract_policy": "Prioritize economy and interest accumulation"},
            {"id": "aggressive_roll", "domain": "board", "goal": "power_spike",
             "abstract_policy": "Roll early to secure power spike"},
            {"id": "adaptive_transition", "domain": "strategy", "goal": "flexibility",
             "abstract_policy": "Stay flexible and adapt to available units"},
        ]

    def retrieve_policy(self, context: dict) -> list:
        """Tool 1: 策略检索（RAG）"""
        query = context.get("query", "")
        domain = context.get("domain", "")
        results = []
        for p in self.policy_library:
            score = 0
            if domain and domain in p.get("domain", ""):
                score += 0.5
            if query and query.lower() in p.get("abstract_policy", "").lower():
                score += 0.3
            if score > 0:
                results.append({"policy": p, "match_score": score})
        results.sort(key=lambda x: -x["match_score"])
        return results[:3]

    def simulate_action(self, action: str, state: WorldState) -> dict:
        """Tool 2: 动作模拟（轻量推演）"""
        # Simplified simulation logic
        result = {"action": action, "expected_gain": 0, "risk": 0.5}
        if action == "level_up":
            cost = 4 * (state.level + 1)
            result["expected_gain"] = 0.2 if state.gold > cost else -0.1
            result["risk"] = 0.3 if state.gold > cost * 1.5 else 0.7
        elif action == "roll":
            result["expected_gain"] = 0.3 if state.gold > 30 else 0.1
            result["risk"] = 0.6
        elif action == "save_gold":
            result["expected_gain"] = 0.1
            result["risk"] = 0.1
        return result

    def query_memory(self, memory: AgentMemory, keyword: str) -> str:
        """Tool 3: 记忆检索"""
        results = []
        for h in memory.history:
            if keyword.lower() in h.get("action", "").lower() or \
               keyword.lower() in h.get("reasoning", "").lower():
                results.append(h)
        if not results:
            return "No relevant past experience found."
        return "\n".join([f"Step {r['step']}: {r['action']} → {r['score']:.2f}" for r in results[-3:]])


# ════════════════════════════════════════════════════════
# 5. Agent Runtime
# ════════════════════════════════════════════════════════

class AgentRuntime:
    """
    Agent 运行时：共享 LLM 实例，人格由 system prompt + memory 差异化
    """

    def __init__(self, name: str, archetype: AgentArchetype,
                 llm_call: Callable, tool_router: ToolRouter):
        self.name = name
        self.archetype = archetype
        self.profile = ARCHETYPE_PROFILES[archetype]
        self.llm_call = llm_call
        self.tools = tool_router
        self.memory = AgentMemory()

    def perceive(self, ws: WorldState) -> str:
        """感知环境状态，生成决策"""
        # Compose system prompt with personality
        sys_prompt = self.profile["system_prompt"]

        # Query tools for context
        policies = self.tools.retrieve_policy({
            "query": f"stage_{ws.stage}",
            "domain": "economy" if ws.gold < 30 else "board",
        })
        policy_text = "\n".join([f"- {p['policy']['abstract_policy'][:80]}" for p in policies])

        # Retrieve relevant memory
        memory_text = self.tools.query_memory(self.memory, "decision")

        # Build LLM prompt
        prompt = f"""{sys_prompt}

## Current Game State
{ws.to_text()}

## Relevant Strategies Retrieved
{policy_text}

## Past Experience
{memory_text}

## Decision Required
Analyze the current situation and decide on ONE action from:
- level_up: Spend gold to gain experience and level up
- roll: Refresh shop to find better units
- save_gold: Save gold for interest
- transition: Plan a composition transition

Provide your reasoning and decision in JSON format:
{{
  "thinking": "your step-by-step analysis",
  "action": "chosen action",
  "confidence": 0.0-1.0,
  "expected_outcome": "brief expectation"
}}
"""
        return self._call_llm(prompt)

    def _call_llm(self, prompt: str) -> dict:
        """调用共享 LLM（支持 vLLM 或模拟模式）"""
        try:
            response = self.llm_call(prompt)
            # Parse JSON from LLM response
            import re
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
            return {"action": "save_gold", "confidence": 0.5,
                     "thinking": response[:100], "expected_outcome": "uncertain"}
        except Exception as e:
            print(f"  [{self.name}] LLM error: {e}")
            return {"action": "save_gold", "confidence": 0.3,
                     "thinking": "fallback", "expected_outcome": "unknown"}


# ════════════════════════════════════════════════════════
# 6. Multi-Agent Manager
# ════════════════════════════════════════════════════════

class MultiAgentManager:
    """
    多 Agent 管理器：调度/同步/评估
    """

    def __init__(self, llm_call: Callable):
        self.tools = ToolRouter()
        self.agents: List[AgentRuntime] = []
        self.episode = 0

        # Create three agents with different archetypes
        for archetype in AgentArchetype:
            agent = AgentRuntime(
                name=archetype.value.capitalize(),
                archetype=archetype,
                llm_call=llm_call,
                tool_router=self.tools,
            )
            self.agents.append(agent)

    def step(self, ws: WorldState) -> List[dict]:
        """所有 Agent 在同一世界状态下进行决策"""
        results = []
        for agent in self.agents:
            print(f"  [{agent.name}] deciding...")
            decision = agent.perceive(ws)

            # Simulate outcome
            outcome = self.tools.simulate_action(
                decision.get("action", "save_gold"), ws
            )

            # Record to agent memory
            agent.memory.record_state(
                ws, decision.get("action", "unknown"),
                decision.get("thinking", ""),
                outcome.get("expected_gain", 0)
            )

            results.append({
                "agent": agent.name,
                "archetype": agent.archetype.value,
                "decision": decision,
                "outcome": outcome,
            })

        self.episode += 1
        return results

    def run_episode(self, states: List[WorldState]) -> List[List[dict]]:
        """跑完整的一轮决策推演"""
        full_log = []
        for i, ws in enumerate(states):
            print(f"\n--- Step {i+1}/{len(states)} ---")
            results = self.step(ws)
            full_log.append(results)
        return full_log

    def summary(self, log: List[List[dict]]) -> str:
        """生成决策摘要"""
        lines = []
        for step_i, step_results in enumerate(log):
            lines.append(f"\n## Step {step_i+1}")
            for r in step_results:
                decision = r.get('decision', {})
                outcome = r.get('outcome', {})
                lines.append(
                    f"- **{r['agent']}** ({r['archetype']}): "
                    f"`{decision.get('action', '?')}` "
                    f"conf={decision.get('confidence', 0):.2f} "
                    f"→ gain={outcome.get('expected_gain', 0):.2f}"
                )
        return "\n".join(lines)


# ════════════════════════════════════════════════════════
# 7. Demo Runner
# ════════════════════════════════════════════════════════

def create_sample_stages() -> List[WorldState]:
    """创建示例推演场景"""
    return [
        WorldState(stage="2-1", hp=100, gold=10, level=4, alive_players=8),
        WorldState(stage="2-5", hp=92, gold=30, level=5, alive_players=7),
        WorldState(stage="3-2", hp=78, gold=45, level=6, alive_players=6),
        WorldState(stage="4-1", hp=60, gold=50, level=7, alive_players=5),
        WorldState(stage="4-5", hp=40, gold=35, level=7, alive_players=4),
        WorldState(stage="5-3", hp=25, gold=20, level=8, alive_players=3),
    ]


def mock_llm(prompt: str) -> str:
    """模拟 LLM 调用，根据 Agent 人格差异化决策"""
    import json
    p = prompt.lower()
    
    # 根据人格关键词判断
    if "risk-averse" in p or "conservative" in p.lower():
        # Conservative: gold priority
        if "gold >= 50" in p or "gold: 4" in p or "gold: 5" in p:
            action = "level_up"
        elif "hp:" in p and int(p.split("hp:")[1].split(",")[0].strip()) < 30:
            action = "roll"
        else:
            action = "save_gold"
    elif "aggressive" in p.lower() or "maximum" in p:
        # Aggressive: always pushing
        if "gold:" in p:
            gold = int(p.split("gold:")[1].split(",")[0].strip())
            if gold > 40:
                action = "roll"
            elif gold > 20:
                action = "level_up"
            else:
                action = "roll"
        else:
            action = "level_up"
    else:
        # Explorer: varies by situation
        stage = p.split("stage:")[1].split(",")[0].strip() if "stage:" in p else "1-1"
        stage_num = int(stage.split("-")[0])
        if stage_num <= 2:
            action = "save_gold"
        elif stage_num <= 4:
            action = "level_up"
        elif "gold:" in p and int(p.split("gold:")[1].split(",")[0].strip()) > 30:
            action = "transition"
        else:
            action = "roll"
    
    return json.dumps({
        "thinking": f"Analyzing situation from {('conservative' if 'risk-averse' in p else 'aggressive' if 'maximum' in p else 'adaptive')} perspective, choosing {action}.",
        "action": action,
        "confidence": 0.7,
        "expected_outcome": f"Executing {action} should provide stable progression."
    })


def main():
    """本地测试：跑一轮推演"""
    print("=" * 60)
    print("ForgeArena: Multi-Agent Decision Sandbox")
    print("=" * 60)

    # Use mock LLM for offline testing
    manager = MultiAgentManager(llm_call=mock_llm)

    states = create_sample_stages()
    print(f"\nRunning {len(states)} decision steps with {len(manager.agents)} agents...")

    log = manager.run_episode(states)

    print("\n" + "=" * 60)
    print("Decision Summary")
    print("=" * 60)
    print(manager.summary(log))

    # Save results
    output = {"episodes": log}
    output_path = os.path.join(BASE_DIR, "demo_output.json")
    with open(output_path, "w") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\nSaved to {output_path}")


if __name__ == "__main__":
    main()
