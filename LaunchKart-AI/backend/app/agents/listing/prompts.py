"""LaunchKart AI 2.0 — Listing Agent Prompts"""
SYSTEM_PROMPT = """You are an e-commerce listing expert. Create compelling, SEO-optimized product listings tailored to each marketplace's requirements. Follow Amazon A9 algorithm best practices, Flipkart guidelines, Shopify standards, etc. Every listing must be unique, engaging, and conversion-optimized."""
TASK_PROMPT = """Generate marketplace listings for: {product_name}
SEO Data: {seo_data}
Pricing: {pricing}
Branding: {branding}
Target Marketplaces: {marketplaces}
Features: {features}

For EACH marketplace, generate a complete listing as JSON:
{{"marketplace_name":{{"title":"","description":"","bullet_points":["5-7 points"],"keywords":["relevant keywords"],"pricing":{{"amount":0,"currency":"USD"}},"compliance_notes":"marketplace-specific notes"}}}}"""
