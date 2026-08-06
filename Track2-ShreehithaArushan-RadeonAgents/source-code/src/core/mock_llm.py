"""
Lightweight mock LLM for demo purposes when full torch/ROCm model is not available.
"""

from typing import Dict, List, Any
import time
import random

class MockLLMEngine:
    def __init__(self, *args, **kwargs):
        self.model_name = "mock-phi-3-mini (Demo Mode)"
        self.device = "cuda (simulated)"
        self.quantize = "4bit (simulated)"
        print(">>> Running in DEMO / MOCK mode (no full model loaded)")

    def generate(self, messages: List[Dict[str, str]], max_new_tokens: int = 512, temperature: float = 0.3, top_p: float = 0.9) -> str:
        time.sleep(random.uniform(0.8, 1.6))

        last_user = ""
        for m in reversed(messages):
            if m["role"] == "user":
                last_user = m["content"].lower()
                break

        if "daily plan" in last_user or "standup" in last_user or "prioritized" in last_user or "schedule" in last_user:
            return """Thought: I need to create a realistic daily schedule.
Final Answer:
Here is a realistic prioritized daily plan (9:00 - 18:00):

09:00 - 09:45   Deep Work Block 1 (PR review)
09:45 - 10:00   Buffer / prepare for standup
10:00 - 10:30   Standup meeting
10:30 - 12:30   Deep Work Block 2
12:30 - 13:15   Lunch + short walk
13:15 - 14:00   Prepare for design review
14:00 - 15:00   Design Review meeting
15:00 - 16:30   Finish remaining tasks
16:30 - 17:15   Exercise (45 min)
17:15 - 18:00   Wrap-up and planning

This plan protects deep work while respecting meetings and exercise."""

        if "fibonacci" in last_user or "memoization" in last_user:
            return """Thought: Writing a clean memoized Fibonacci function.
Final Answer:
Here is a clean memoized Fibonacci implementation:

from functools import lru_cache

@lru_cache(maxsize=None)
def fibonacci(n: int) -> int:
    if n < 2:
        return n
    return fibonacci(n-1) + fibonacci(n-2)

Verification:
fibonacci(10) == 55
fibonacci(20) == 6765

Time complexity: O(n)
Space complexity: O(n)"""

        if "hierarchical" in last_user or "task planning" in last_user:
            return """Thought: Explaining hierarchical task planning.
Final Answer:
Hierarchical Task Planning breaks a high-level goal into ordered sub-tasks.

Benefits:
1. Better long-horizon coherence
2. Clear progress tracking
3. Natural specialization
4. Higher success rate

Example goal: Add OAuth2 authentication
1. Research libraries
2. Design data model
3. Implement endpoints
4. Write tests
5. Update docs
6. Security review
7. Open pull request"""

        return f"""Thought: I understand the request.
Final Answer:
(Demo Mode) Processed: {last_user[:80]}...

In full mode this would run on the AMD Radeon GPU with ROCm.
Architecture, tools, memory and multi-agent routing are fully implemented."""

    def get_stats(self) -> Dict[str, Any]:
        return {
            "model": self.model_name,
            "quantize": self.quantize,
            "device": self.device,
            "gpu_name": "AMD Radeon (Demo Mode)",
            "vram_allocated_gb": 3.8,
            "note": "Running in lightweight Demo/Mock mode"
        }