import os
import logging
from typing import List, Dict, Any
from .registry import ToolRegistry

logger = logging.getLogger(__name__)

def register_web_tools(registry: ToolRegistry) -> None:
    """Register web tools with the registry."""
    registry.register(
        name="web_search",
        func=web_search,
        description="Search the web.",
        parameters={
            "query": {"type": "string", "description": "The search query"},
            "num_results": {"type": "integer", "description": "Number of results to return", "required": False}
        },
        requires_permission=True
    )

def web_search(query: str, num_results: int = 5) -> List[Dict[str, str]]:
    """Search the web.
    
    In demo mode, this returns mock results explaining this would do a real search.
    If SERPAPI_KEY env var set, it could use SerpAPI.
    If TAVILY_API_KEY set, it could use Tavily.
    """
    serpapi_key = os.environ.get("SERPAPI_KEY")
    tavily_key = os.environ.get("TAVILY_API_KEY")
    
    # Normally we would make actual API calls here if keys exist
    # For now, return mock results as specified
    if serpapi_key:
        logger.info("Would use SerpAPI for web search")
    elif tavily_key:
        logger.info("Would use Tavily for web search")
        
    return [
        {
            "title": f"Mock Search Result 1 for '{query}'",
            "url": "https://example.com/result1",
            "snippet": "This is a mock search result explaining that a real web search would happen here."
        },
        {
            "title": f"Mock Search Result 2 for '{query}'",
            "url": "https://example.com/result2",
            "snippet": "If API keys for SerpAPI or Tavily were active, actual internet data would be returned."
        }
    ][:num_results]
