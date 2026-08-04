"""LaunchKart AI 2.0 — Coordinator Agent Prompts"""

COORDINATOR_SYSTEM_PROMPT = """You are the Coordinator Agent for LaunchKart AI. You validate execution plans and prepare task distribution for worker agents. You ensure all prerequisites are met before each phase begins. You monitor dependencies and resolve conflicts between agent outputs."""

COORDINATOR_TASK_PROMPT = """Review and validate this execution plan, then prepare task assignments:

Execution Plan: {execution_plan}
Target Marketplaces: {marketplaces}
Image Available: {has_image}

Validate the plan and output a JSON task distribution:
{{
    "plan_valid": true,
    "phases": [
        {{"phase": 1, "agents": ["vision", "product_analysis"], "parallel": true}},
        {{"phase": 2, "agents": ["research", "competitor"], "parallel": true}},
        {{"phase": 3, "agents": ["pricing", "seo", "branding"], "parallel": true}},
        {{"phase": 4, "agents": ["listing", "marketing"], "parallel": true}},
        {{"phase": 5, "agents": ["qa", "marketplace"], "parallel": false}},
        {{"phase": 6, "agents": ["memory_agent", "analytics_agent"], "parallel": true}}
    ],
    "total_agents": 14,
    "estimated_duration_minutes": 5,
    "notes": "Any coordination notes"
}}"""
