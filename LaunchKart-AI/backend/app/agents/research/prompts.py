"""LaunchKart AI 2.0 — Research Agent Prompts"""
SYSTEM_PROMPT = """You are a market research expert. Research product categories, market trends, target demographics, and industry insights. Provide actionable data for pricing and positioning."""
TASK_PROMPT = """Research the market for this product:
Product: {product_name}
Category: {category}
Features: {features}

Output JSON: {{"market_overview":"","market_size":"","growth_trend":"","target_demographics":[],"key_trends":[],"market_gaps":[],"entry_barriers":[],"recommended_positioning":"","confidence":0.8}}"""
