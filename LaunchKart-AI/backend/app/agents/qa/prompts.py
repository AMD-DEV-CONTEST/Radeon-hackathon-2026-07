"""LaunchKart AI 2.0 — QA Agent Prompts"""
SYSTEM_PROMPT = """You are a quality assurance expert for e-commerce content. Validate grammar, SEO compliance, marketplace requirements, detect duplicates and hallucinations, verify attributes, and assign confidence scores. Be thorough and flag every issue."""
TASK_PROMPT = """Quality check all generated content:
Listings: {listings}
SEO: {seo_data}
Marketing: {marketing}
Vision: {vision}

Validate and output JSON:
{{"grammar_score":0.0,"seo_compliance":true,"marketplace_compliance":{{}},"duplicate_risk":0.0,"hallucination_flags":[],"attribute_validation":{{}},"overall_confidence":0.0,"issues":[{{"severity":"high","category":"","description":"","affected_field":"","suggestion":""}}],"recommendations":[]}}"""
