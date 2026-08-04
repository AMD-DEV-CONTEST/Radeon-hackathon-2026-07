from typing import Annotated, Any
import operator
from typing_extensions import TypedDict

def update_dict(curr: dict, new: dict) -> dict:
    """Reducer to merge dictionary values."""
    if curr is None:
        return new
    if new is None:
        return curr
    return {**curr, **new}

class LaunchState(TypedDict):
    """
    State dictionary for the LaunchKart AI LangGraph pipeline.
    Uses operator.add for lists and a custom reducer for dicts to aggregate state 
    as the execution flows through parallel agent nodes.
    """
    
    launch_id: str
    product_id: str
    product_image_path: str
    target_marketplaces: list[str]
    preferences: dict | None
    
    # --- Phase 5: Memory Architecture ---
    # Working Memory: Context for the current agent/node execution
    working_memory: Annotated[dict, update_dict]
    # Session Memory: Short-term state persisting for the duration of the launch
    session_memory: Annotated[dict, update_dict]
    
    # Phase 0: Planning
    execution_plan: dict
    
    # Phase 1: Analysis
    vision_analysis: str
    product_features: Annotated[list[str], operator.add]
    
    # Phase 2: Research
    market_research: str
    competitor_analysis: str
    
    # Phase 3: Strategy
    pricing_strategy: dict
    seo_keywords: Annotated[list[str], operator.add]
    brand_voice: str
    
    # Phase 4: Creation
    marketplace_listings: Annotated[dict[str, dict], update_dict]
    marketing_campaigns: Annotated[list[dict], operator.add]
    
    # Phase 5: Review
    qa_report: dict
    
    # Phase 6: Metrics
    tokens_used: Annotated[int, operator.add]
    confidence_scores: Annotated[dict[str, int], update_dict]
