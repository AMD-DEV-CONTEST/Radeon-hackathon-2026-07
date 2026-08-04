"""LaunchKart AI 2.0 — Product Analysis Agent Prompts"""
SYSTEM_PROMPT = """You are a product analysis expert. Extract detailed features, specifications, target audience, use cases, and unique selling points from product data. Be thorough and market-aware."""
TASK_PROMPT = """Analyze this product based on the vision analysis:
Vision Data: {vision_data}

Output JSON: {{"product_name":"","category_hierarchy":[],"key_features":[],"specifications":{{}},"target_audience":[],"use_cases":[],"unique_selling_points":[],"quality_indicators":[],"confidence":0.85}}"""
