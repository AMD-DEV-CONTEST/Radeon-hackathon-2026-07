import re

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer


MODEL_NAME = "Qwen/Qwen2.5-3B-Instruct"


# Simple IDs exposed to the LLM.
# The LLM never directly controls executable Python functions.
TOOL_MAP = {
    "KNOWLEDGE": "search_knowledge",
    "GRAPH": "query_knowledge_graph",
    "SOURCE": "retrieve_source",
    "MEMORY_SEARCH": "search_memory",
    "MEMORY_SAVE": "save_memory",
    "WORLD": "explore_world",
}


TOOL_ACTIONS = {
    "KNOWLEDGE": "Search the NexusAI knowledge base",
    "GRAPH": "Query entities and relationships in the knowledge graph",
    "SOURCE": "Retrieve supporting source evidence",
    "MEMORY_SEARCH": "Search persistent NexusAI memory",
    "MEMORY_SAVE": "Save useful information to persistent memory",
    "WORLD": "Visualize relevant knowledge in WorldForge",
}


class RadeonNexusAgent:
    def __init__(self, model_name=MODEL_NAME):
        if not torch.cuda.is_available():
            raise RuntimeError(
                "AMD Radeon ROCm accelerator was not detected."
            )

        self.device = "cuda"
        self.model_name = model_name

        print(f"Loading Nexus Agent model: {model_name}")
        print(f"Radeon device: {torch.cuda.get_device_name(0)}")

        self.tokenizer = AutoTokenizer.from_pretrained(
            model_name
        )

        self.model = AutoModelForCausalLM.from_pretrained(
            model_name,
            torch_dtype=torch.float16,
        ).to(self.device)

        self.model.eval()

    def _build_system_prompt(self):
        return """
You are the NexusAI planning engine.

Analyze the user's request and decide which capabilities are needed.

Available capability IDs:

KNOWLEDGE
Use this to search the private knowledge base.

GRAPH
Use this to find entities and relationships.

SOURCE
Use this when supporting source evidence is explicitly needed.

MEMORY_SEARCH
Use this only when the user asks about remembered, previous,
historical, or stored personal context.

MEMORY_SAVE
Use this only when the user explicitly asks NexusAI to remember
or save something.

WORLD
Use this when the user asks to show, visualize, explore, or open
knowledge in WorldForge.

Return exactly two lines:

GOAL: <short description of the user's goal>
TOOLS: <comma-separated capability IDs>

Example:

GOAL: Find Aria's relationships and visualize them
TOOLS: KNOWLEDGE, GRAPH, WORLD

Rules:

1. Use only capability IDs listed above.
2. Select no more than 4 capabilities.
3. Do not repeat capabilities.
4. Put capabilities in execution order.
5. Use the minimum capabilities required.
6. Do not invent capability IDs.
7. Do not output JSON.
8. Do not output Markdown.
9. Do not add explanations.
10. Output only GOAL and TOOLS.
"""

    def _generate_plan_text(self, user_request):
        messages = [
            {
                "role": "system",
                "content": self._build_system_prompt()
            },
            {
                "role": "user",
                "content": user_request
            }
        ]

        prompt = self.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True
        )

        inputs = self.tokenizer(
            prompt,
            return_tensors="pt"
        ).to(self.device)

        with torch.inference_mode():
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=100,
                do_sample=False,
                repetition_penalty=1.1,
                no_repeat_ngram_size=3,
            )

        generated = outputs[
            0,
            inputs["input_ids"].shape[1]:
        ]

        return self.tokenizer.decode(
            generated,
            skip_special_tokens=True
        ).strip()

    @staticmethod
    def _extract_goal(response, user_request):
        match = re.search(
            r"GOAL\s*[:：]\s*(.+)",
            response,
            re.IGNORECASE
        )

        if match:
            goal = match.group(1).strip()

            # Prevent accidental capture of the next line.
            goal = goal.splitlines()[0].strip()

            if goal:
                return goal

        return user_request.strip()

    @staticmethod
    def _normalize_tool_id(tool_id):
        """
        Normalize common capability spelling mistakes produced by
        small local language models.
        """

        aliases = {
            "KNOWLEDGE": "KNOWLEDGE",
            "KNOWLDGE": "KNOWLEDGE",
            "KNOWLEDG": "KNOWLEDGE",
            "KNOWLEDGES": "KNOWLEDGE",
            "GRAPH": "GRAPH",
            "KNOWLEDGE_GRAPH": "GRAPH",
            "KNOWLDGE_GRAPH": "GRAPH",
            "SOURCE": "SOURCE",
            "SOURCES": "SOURCE",
            "EVIDENCE": "SOURCE",
            "MEMORY_SEARCH": "MEMORY_SEARCH",
            "SEARCH_MEMORY": "MEMORY_SEARCH",
            "MEMORY_SAVE": "MEMORY_SAVE",
            "SAVE_MEMORY": "MEMORY_SAVE",
            "WORLD": "WORLD",
            "WORLDFORGE": "WORLD",
            "WORLD_FORGE": "WORLD",
        }

        return aliases.get(tool_id)

    @classmethod
    def _extract_tools(cls, response):
        match = re.search(
            r"TOOLS\\s*[:：]\\s*(.+)",
            response,
            re.IGNORECASE
        )

        if not match:
            return []

        raw_tools = match.group(1).splitlines()[0]

        candidates = re.split(
            r"[,|;]+",
            raw_tools
        )

        validated = []

        for candidate in candidates:
            tool_id = candidate.strip().upper()

            tool_id = re.sub(
                r"[^A-Z_]",
                "",
                tool_id
            )

            normalized = cls._normalize_tool_id(
                tool_id
            )

            if (
                normalized
                and normalized in TOOL_MAP
                and normalized not in validated
            ):
                validated.append(normalized)

            if len(validated) >= 4:
                break

        return validated

    @staticmethod
    def _apply_semantic_guardrails(
        user_request,
        tool_ids
    ):
        """
        Validate the LLM plan against deterministic intent rules.

        The LLM proposes capabilities, but NexusAI retains final
        control over which capabilities are allowed and required.
        """

        request = user_request.lower()

        tools = list(tool_ids)

        memory_save_terms = [
            "remember that",
            "remember this",
            "save this",
            "store this",
            "save that",
            "store that",
        ]

        memory_search_terms = [
            "what did i previously",
            "what did i tell you",
            "previously tell you",
            "do you remember",
            "what do you remember",
            "last time",
            "earlier tell",
            "previous conversation",
        ]

        relationship_terms = [
            "relationship",
            "relationships",
            "connected to",
            "connection",
            "connections",
            "who she works with",
            "who he works with",
            "who they work with",
        ]

        evidence_terms = [
            "evidence",
            "source",
            "sources",
            "citation",
            "citations",
            "prove",
            "proof",
        ]

        world_terms = [
            "worldforge",
            "visualize",
            "visualise",
            "show her relationships",
            "show his relationships",
            "show their relationships",
            "explore the world",
        ]

        knowledge_terms = [
            "find everything we know",
            "find what we know",
            "find information",
            "search for information",
        ]

        is_memory_save = any(
            term in request
            for term in memory_save_terms
        )

        is_memory_search = any(
            term in request
            for term in memory_search_terms
        )

        # Explicit memory-storage requests should save only.
        if is_memory_save:
            return ["MEMORY_SAVE"]

        # Explicit memory-retrieval requests should search memory.
        if is_memory_search:
            return ["MEMORY_SEARCH"]

        # Remove memory operations when memory intent was not explicit.
        tools = [
            tool
            for tool in tools
            if tool not in {
                "MEMORY_SEARCH",
                "MEMORY_SAVE"
            }
        ]

        if any(
            term in request
            for term in knowledge_terms
        ):
            if "KNOWLEDGE" not in tools:
                tools.insert(0, "KNOWLEDGE")

        if any(
            term in request
            for term in relationship_terms
        ):
            if "GRAPH" not in tools:
                tools.append("GRAPH")

        if any(
            term in request
            for term in evidence_terms
        ):
            if "SOURCE" not in tools:
                tools.append("SOURCE")

        if any(
            term in request
            for term in world_terms
        ):
            if "WORLD" not in tools:
                tools.append("WORLD")

        # Canonical execution order.
        execution_order = [
            "KNOWLEDGE",
            "GRAPH",
            "SOURCE",
            "MEMORY_SEARCH",
            "MEMORY_SAVE",
            "WORLD",
        ]

        ordered = [
            tool
            for tool in execution_order
            if tool in tools
        ]

        return ordered[:4]

    @staticmethod
    def _fallback_tools(user_request):
        """
        Deterministic fallback when the model returns no valid tools.

        This does not replace LLM planning. It ensures NexusAI
        always produces a safe executable plan.
        """

        request = user_request.lower()
        tools = []

        knowledge_terms = [
            "find",
            "know",
            "information",
            "tell me",
            "search",
        ]

        graph_terms = [
            "relationship",
            "relationships",
            "connected",
            "connection",
            "who works with",
            "where",
        ]

        source_terms = [
            "source",
            "evidence",
            "prove",
            "citation",
        ]

        memory_search_terms = [
            "remember",
            "previous",
            "earlier",
            "last time",
            "what was i",
        ]

        memory_save_terms = [
            "remember that",
            "save this",
            "store this",
        ]

        world_terms = [
            "worldforge",
            "visualize",
            "show me",
            "explore",
            "open the world",
        ]

        if any(term in request for term in knowledge_terms):
            tools.append("KNOWLEDGE")

        if any(term in request for term in graph_terms):
            tools.append("GRAPH")

        if any(term in request for term in source_terms):
            tools.append("SOURCE")

        if any(term in request for term in memory_search_terms):
            tools.append("MEMORY_SEARCH")

        if any(term in request for term in memory_save_terms):
            tools.append("MEMORY_SAVE")

        if any(term in request for term in world_terms):
            tools.append("WORLD")

        # Preserve order while removing duplicates.
        return list(dict.fromkeys(tools))[:4]

    def _build_validated_plan(
        self,
        goal,
        tool_ids
    ):
        plan = []

        for index, tool_id in enumerate(
            tool_ids,
            start=1
        ):
            plan.append(
                {
                    "step": index,
                    "action": TOOL_ACTIONS[tool_id],
                    "tool": TOOL_MAP[tool_id],
                }
            )

        return {
            "goal": goal,
            "model": self.model_name,
            "backend": "rocm",
            "device": torch.cuda.get_device_name(0),
            "plan": plan,
        }

    def plan(self, user_request):
        raw_response = self._generate_plan_text(
            user_request
        )

        goal = self._extract_goal(
            raw_response,
            user_request
        )

        tool_ids = self._extract_tools(
            raw_response
        )

        used_fallback = False

        if not tool_ids:
            tool_ids = self._fallback_tools(
                user_request
            )

            used_fallback = True

        tool_ids = self._apply_semantic_guardrails(
            user_request,
            tool_ids
        )

        if not tool_ids:
            tool_ids = self._fallback_tools(
                user_request
            )

            used_fallback = True

        result = self._build_validated_plan(
            goal,
            tool_ids
        )

        result["planner_output"] = raw_response
        result["used_fallback"] = used_fallback

        return result


if __name__ == "__main__":
    import json

    agent = RadeonNexusAgent()

    test_requests = [
        (
            "Find everything we know about Aria, determine "
            "where she lives and who she works with, then "
            "show her relationships in WorldForge."
        ),
        (
            "What did I previously tell you about my "
            "research project?"
        ),
        (
            "Remember that Project Aurora has a deadline "
            "on August 10."
        ),
        (
            "Find the evidence showing how Aria is "
            "connected to Nexus Research Lab."
        ),
        (
            "Visualize the relationships between Aria "
            "and Noah in WorldForge."
        ),
    ]

    for index, request in enumerate(
        test_requests,
        start=1
    ):
        print("\n" + "=" * 70)
        print(f"TEST {index}")
        print("=" * 70)

        print("\nUSER REQUEST:")
        print(request)

        result = agent.plan(request)

        print("\nVALIDATED NEXUS AGENT PLAN:")
        print(
            json.dumps(
                result,
                indent=2
            )
        )
