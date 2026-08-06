"""Business data query tool: simulate insurance business data queries.

P1-5 fix: expand the sample data to 10+ products + 10+ claim records,
increase field richness (premium, coverage limit, waiting period, deductible, etc.),
showcasing the real functional completeness of the data_query path.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Sample business data (can be replaced with a database query in a real project) ──
# P1-5: expanded from 3+2 to 10+10, covering more insurance types and statuses
_SAMPLE_DATA: dict[str, list[dict]] = {
    "products": [
        {
            "id": "P001", "name": "Employer Liability Insurance - Plan A", "type": "Employer Liability Insurance",
            "premium_mode": "annual", "base_premium": 12000, "coverage_limit": 1000000,
            "waiting_period": 30, "deductible": 0,
            "target_audience": "Enterprises with 50+ employees", "features": ["Work injury supplementation", "Occupational disease coverage"],
        },
        {
            "id": "P002", "name": "Accident Insurance - Plan B", "type": "Accident Insurance",
            "premium_mode": "annual", "base_premium": 360, "coverage_limit": 500000,
            "waiting_period": 0, "deductible": 100,
            "target_audience": "Individual/Family", "features": ["Accidental medical", "Hospitalization allowance"],
        },
        {
            "id": "P003", "name": "Group Medical Insurance - Plan C", "type": "Group Medical Insurance",
            "premium_mode": "monthly", "base_premium": 200, "coverage_limit": 300000,
            "waiting_period": 90, "deductible": 500,
            "target_audience": "Groups of 10+ people", "features": ["Outpatient reimbursement", "Inpatient reimbursement"],
        },
        {
            "id": "P004", "name": "Comprehensive Property Insurance - Plan D", "type": "Property Insurance",
            "premium_mode": "annual", "base_premium": 5000, "coverage_limit": 5000000,
            "waiting_period": 0, "deductible": 1000,
            "target_audience": "Small and medium enterprises", "features": ["Fire", "Theft and burglary", "Natural disasters"],
        },
        {
            "id": "P005", "name": "Public Liability Insurance - Plan E", "type": "Liability Insurance",
            "premium_mode": "annual", "base_premium": 3000, "coverage_limit": 2000000,
            "waiting_period": 0, "deductible": 500,
            "target_audience": "Shops/Restaurants", "features": ["Third-party bodily injury", "Third-party property damage"],
        },
        {
            "id": "P006", "name": "Cargo Transportation Insurance - Plan F", "type": "Cargo Transportation Insurance",
            "premium_mode": "per_shipment", "base_premium": 50, "coverage_limit": 500000,
            "waiting_period": 0, "deductible": 200,
            "target_audience": "Logistics enterprises", "features": ["Total loss", "General average", "Salvage costs"],
        },
        {
            "id": "P007", "name": "Construction Engineering All Risks - Plan G", "type": "Engineering Insurance",
            "premium_mode": "annual", "base_premium": 8000, "coverage_limit": 10000000,
            "waiting_period": 0, "deductible": 2000,
            "target_audience": "Construction contractors", "features": ["Material damage", "Third-party liability"],
        },
        {
            "id": "P008", "name": "Employer Liability Insurance - Premium Plan", "type": "Employer Liability Insurance",
            "premium_mode": "annual", "base_premium": 25000, "coverage_limit": 3000000,
            "waiting_period": 15, "deductible": 0,
            "target_audience": "Enterprises with 200+ employees", "features": ["Work injury supplementation", "Occupational disease coverage", "24-hour coverage", "Overseas business trips"],
        },
        {
            "id": "P009", "name": "Short-term Accident Insurance - Travel Plan", "type": "Accident Insurance",
            "premium_mode": "per_trip", "base_premium": 30, "coverage_limit": 100000,
            "waiting_period": 0, "deductible": 0,
            "target_audience": "Travelers", "features": ["Aviation accident", "Baggage loss", "Trip delay"],
        },
        {
            "id": "P010", "name": "Group Medical Insurance - Upgrade Plan", "type": "Group Medical Insurance",
            "premium_mode": "annual", "base_premium": 3600, "coverage_limit": 600000,
            "waiting_period": 30, "deductible": 300,
            "target_audience": "Groups of 20+ people", "features": ["Outpatient reimbursement", "Inpatient reimbursement", "Dentistry", "Physical examination"],
        },
        {
            "id": "P011", "name": "Product Liability Insurance - Plan H", "type": "Liability Insurance",
            "premium_mode": "annual", "base_premium": 6000, "coverage_limit": 3000000,
            "waiting_period": 0, "deductible": 1000,
            "target_audience": "Manufacturers", "features": ["Product defects", "Recall costs", "Legal costs"],
        },
        {
            "id": "P012", "name": "Cyber Insurance - Plan I", "type": "New-type Insurance",
            "premium_mode": "annual", "base_premium": 15000, "coverage_limit": 5000000,
            "waiting_period": 30, "deductible": 5000,
            "target_audience": "Technology enterprises", "features": ["Data breach", "Ransomware", "Business interruption"],
        },
    ],
    "claims": [
        {
            "id": "CL001", "product_id": "P001", "status": "processing",
            "submit_date": "2026-01-15", "claim_amount": 50000,
            "incident_date": "2026-01-10", "description": "Employee work injury accident",
            "assigned_adjuster": "Zhang San", "estimated_days": 15,
        },
        {
            "id": "CL002", "product_id": "P002", "status": "completed",
            "submit_date": "2025-12-01", "claim_amount": 12000,
            "incident_date": "2025-11-25", "description": "Accidental hospitalization medical expenses",
            "assigned_adjuster": "Li Si", "estimated_days": 7, "settled_amount": 11000,
        },
        {
            "id": "CL003", "product_id": "P003", "status": "processing",
            "submit_date": "2026-02-20", "claim_amount": 35000,
            "incident_date": "2026-02-15", "description": "Group member hospitalization surgery",
            "assigned_adjuster": "Wang Wu", "estimated_days": 10,
        },
        {
            "id": "CL004", "product_id": "P001", "status": "completed",
            "submit_date": "2025-11-10", "claim_amount": 80000,
            "incident_date": "2025-11-01", "description": "Occupational disease diagnosis compensation",
            "assigned_adjuster": "Zhang San", "estimated_days": 20, "settled_amount": 75000,
        },
        {
            "id": "CL005", "product_id": "P004", "status": "rejected",
            "submit_date": "2026-01-05", "claim_amount": 200000,
            "incident_date": "2025-12-28", "description": "Warehouse fire loss",
            "assigned_adjuster": "Zhao Liu", "estimated_days": 30, "reject_reason": "Premium not paid on time; policy lapsed",
        },
        {
            "id": "CL006", "product_id": "P005", "status": "processing",
            "submit_date": "2026-02-01", "claim_amount": 150000,
            "incident_date": "2026-01-28", "description": "Customer slipped and was injured",
            "assigned_adjuster": "Li Si", "estimated_days": 12,
        },
        {
            "id": "CL007", "product_id": "P006", "status": "completed",
            "submit_date": "2025-12-15", "claim_amount": 280000,
            "incident_date": "2025-12-10", "description": "Total cargo loss during transportation",
            "assigned_adjuster": "Wang Wu", "estimated_days": 14, "settled_amount": 275000,
        },
        {
            "id": "CL008", "product_id": "P008", "status": "processing",
            "submit_date": "2026-03-01", "claim_amount": 500000,
            "incident_date": "2026-02-25", "description": "Accidental injury during an overseas business trip",
            "assigned_adjuster": "Zhang San", "estimated_days": 25,
        },
        {
            "id": "CL009", "product_id": "P009", "status": "completed",
            "submit_date": "2025-12-20", "claim_amount": 8000,
            "incident_date": "2025-12-18", "description": "Travel flight delay",
            "assigned_adjuster": "Zhao Liu", "estimated_days": 3, "settled_amount": 8000,
        },
        {
            "id": "CL010", "product_id": "P010", "status": "processing",
            "submit_date": "2026-02-10", "claim_amount": 45000,
            "incident_date": "2026-02-05", "description": "Group member dental treatment",
            "assigned_adjuster": "Li Si", "estimated_days": 8,
        },
        {
            "id": "CL011", "product_id": "P011", "status": "rejected",
            "submit_date": "2026-01-20", "claim_amount": 600000,
            "incident_date": "2026-01-15", "description": "Product defect recall",
            "assigned_adjuster": "Wang Wu", "estimated_days": 30, "reject_reason": "Known defects were not declared when purchasing insurance",
        },
        {
            "id": "CL012", "product_id": "P012", "status": "processing",
            "submit_date": "2026-03-05", "claim_amount": 1200000,
            "incident_date": "2026-03-01", "description": "Business interruption caused by a ransomware attack",
            "assigned_adjuster": "Zhao Liu", "estimated_days": 45,
        },
    ],
}


async def query_products(query_type: str = "list", **filters) -> list[dict]:
    """Query insurance products.

    Args:
        query_type: query type (list/detail/compare)
        **filters: filter conditions (type, name, product_id, etc.)

    Returns:
        product list
    """
    products = _SAMPLE_DATA["products"]

    # exact query by product ID
    if filters.get("product_id"):
        products = [p for p in products if p["id"] == filters["product_id"]]
    # filter by type
    if filters.get("type"):
        products = [p for p in products if p["type"] == filters["type"]]
    # fuzzy match by name
    if filters.get("name"):
        products = [p for p in products if filters["name"] in p["name"]]

    logger.info("queried products: %d results (query_type=%s)", len(products), query_type)
    return products


async def query_claims(**filters) -> list[dict]:
    """Query claim records.

    Args:
        **filters: filter conditions (product_id, status, claim_id, etc.)

    Returns:
        claim record list
    """
    claims = _SAMPLE_DATA["claims"]

    # exact query by claim ID
    if filters.get("claim_id"):
        claims = [c for c in claims if c["id"] == filters["claim_id"]]
    # filter by product ID
    if filters.get("product_id"):
        claims = [c for c in claims if c["product_id"] == filters["product_id"]]
    # filter by status
    if filters.get("status"):
        claims = [c for c in claims if c["status"] == filters["status"]]

    logger.info("queried claims: %d results", len(claims))
    return claims


def get_product_summary() -> dict[str, int]:
    """Return product data overview statistics (for UI / status checks)."""
    products = _SAMPLE_DATA["products"]
    type_counts: dict[str, int] = {}
    for p in products:
        type_counts[p["type"]] = type_counts.get(p["type"], 0) + 1
    return {
        "total_products": len(products),
        "total_claims": len(_SAMPLE_DATA["claims"]),
        "by_type": type_counts,
    }