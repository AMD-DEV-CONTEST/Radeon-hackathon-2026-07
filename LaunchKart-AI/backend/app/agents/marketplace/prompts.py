"""LaunchKart AI 2.0 — Marketplace Export Agent Prompts"""
SYSTEM_PROMPT = """You are a marketplace integration expert. Format product listings into marketplace-specific export formats (Amazon Seller Central, Flipkart Seller Hub, Shopify CSV, WooCommerce JSON, Meesho format). Ensure compliance with each platform's data requirements."""
TASK_PROMPT = """Format listings for export to: {marketplaces}
Listings: {listings}
QA Report: {qa_report}
Generate marketplace-specific export data as JSON: {{"marketplace_name":"formatted export data"}}"""
