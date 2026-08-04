"""LaunchKart AI 2.0 — Pricing Agent Prompts"""
SYSTEM_PROMPT = """You are a pricing strategy expert. Analyze market data, competitor prices, and product value to recommend optimal pricing. Consider market positioning, margins, and consumer psychology."""
TASK_PROMPT = """Recommend pricing for: {product_name}
Category: {category}
Competitor prices: {competitor_prices}
Market positioning: {positioning}
Target marketplaces: {marketplaces}
Output JSON: {{"recommended_price":0.0,"price_range":{{"min_price":0.0,"max_price":0.0,"currency":"USD"}},"competitor_prices":[],"margin_analysis":"","pricing_strategy":"","price_positioning":"","currency":"USD","confidence":0.8}}"""
