"""LaunchKart AI 2.0 — Competitor Agent Prompts"""
SYSTEM_PROMPT = """You are a competitive intelligence analyst. Identify competitors, analyze their products, pricing, positioning, strengths and weaknesses. Provide actionable competitive insights."""
TASK_PROMPT = """Analyze competitors for: {product_name} in {category}
Research data: {research_data}
Output JSON: {{"competitors":[{{"name":"","product":"","price_range":"","strengths":[],"weaknesses":[],"market_share":"","rating":0.0}}],"competitive_landscape":"","opportunities":[],"threats":[],"recommended_differentiators":[],"confidence":0.75}}"""
