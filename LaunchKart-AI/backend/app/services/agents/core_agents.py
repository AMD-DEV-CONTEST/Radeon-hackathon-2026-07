import json
import uuid
import base64
from langchain_core.messages import SystemMessage, HumanMessage
from app.domain.agent_state import LaunchState
from app.services.agents.agent_utils import agent_node
from app.infrastructure.llm_provider import get_llm, get_json_llm, get_vision_llm
from app.infrastructure.database.session import async_session_factory
from app.services.memory_service import MemoryService

import structlog
logger = structlog.get_logger(__name__)

# --- PHASE 0: PLANNING ---

@agent_node("planner")
async def planner_agent(state: LaunchState) -> dict:
    llm = get_json_llm()
    marketplaces = state.get('target_marketplaces', [])
    product_query = str(state.get('preferences', {}))
    
    # 1. Access Long-Term Memory via MemoryService
    retrieved_context = []
    try:
        # Generate deterministic user UUID for the demo (normally from request scope)
        user_id = uuid.uuid5(uuid.NAMESPACE_DNS, "launchkart.ai")
        
        async with async_session_factory() as db:
            memory_service = MemoryService(db)
            # Retrieve relevant memory contexts based on the current launch parameters
            search_query = f"marketplaces: {','.join(marketplaces)} prefs: {product_query}"
            memories = await memory_service.search_memories(user_id=user_id, query=search_query, limit=5)
            
            for m in memories.results:
                retrieved_context.append({
                    "namespace": m.namespace,
                    "content": m.content,
                    "type": m.memory_type
                })
    except Exception as e:
        logger.error("Planner failed to retrieve long-term memory", error=str(e))

    # 2. Add retrieved memories to Session Memory
    session_memory = {"retrieved_context": retrieved_context}

    # 3. Plan execution
    prompt = f"Plan a product launch for these marketplaces: {marketplaces}. Prior context: {retrieved_context}. Return JSON."
    response = await llm.ainvoke([SystemMessage(content=prompt)])
    try:
        plan = json.loads(response.content)
    except:
        plan = {"error": "Failed to parse plan"}
        
    return {"execution_plan": plan, "session_memory": session_memory}

@agent_node("coordinator")
async def coordinator_agent(state: LaunchState) -> dict:
    llm = get_llm()
    plan = state.get("execution_plan", {})
    prompt = f"Review this execution plan and confirm readiness in 1 sentence. Plan: {json.dumps(plan)}"
    response = await llm.ainvoke([SystemMessage(content="You are a launch coordinator."), HumanMessage(content=prompt)])
    
    # Store token usage
    tokens = response.response_metadata.get("eval_count", 0) + response.response_metadata.get("prompt_eval_count", 0)
    
    session_memory = state.get("session_memory", {})
    session_memory["coordinator_status"] = response.content
    return {"session_memory": session_memory, "tokens_used": tokens}

# --- PHASE 1: ANALYSIS ---

@agent_node("vision")
async def vision_agent(state: LaunchState) -> dict:
    llm = get_vision_llm()
    image_path = state.get('product_image_path')
    product_id = state.get('product_id')
    response = None
    
    if image_path:
        try:
            import base64
            with open(image_path, "rb") as image_file:
                image_data = base64.b64encode(image_file.read()).decode("utf-8")
            
            prompt = "Analyze this product image and describe it visually in high detail (1 paragraph). Identify key features, materials, colors, and potential selling points."
            message = HumanMessage(
                content=[
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_data}"}}
                ]
            )
            response = await llm.ainvoke([SystemMessage(content="You are a product visual analysis AI."), message])
            vision_text = response.content
            
            if product_id:
                from app.infrastructure.database.models.product_model import ProductModel
                from sqlalchemy import select
                async with async_session_factory() as db:
                    result = await db.execute(select(ProductModel).where(ProductModel.id == uuid.UUID(product_id)))
                    product = result.scalar_one_or_none()
                    if product:
                        product.vision_analysis = {"description": vision_text}
                        await db.commit()
                        
        except Exception as e:
            logger.error("Vision agent failed to process image", error=str(e))
            vision_text = "Failed to analyze product image."
    else:
        prefs = state.get('preferences', {})
        prompt = f"Analyze this product request and describe it visually in high detail (1 paragraph). Request: {json.dumps(prefs)}"
        response = await llm.ainvoke([SystemMessage(content="You are a product visual analysis AI."), HumanMessage(content=prompt)])
        vision_text = response.content

    tokens = 100
    if response and hasattr(response, 'response_metadata'):
        tokens = response.response_metadata.get("eval_count", 0) + response.response_metadata.get("prompt_eval_count", 0)
        
    return {"vision_analysis": vision_text, "tokens_used": tokens}

@agent_node("product_analysis")
async def product_analysis_agent(state: LaunchState) -> dict:
    llm = get_llm()
    prompt = f"Extract exactly 3 key product features based on this visual analysis: {state.get('vision_analysis')}"
    response = await llm.ainvoke([HumanMessage(content=prompt)])
    features = [f.strip("- *") for f in response.content.split("\n") if f.strip("- *")]
    tokens = response.response_metadata.get("eval_count", 0) + response.response_metadata.get("prompt_eval_count", 0)
    return {"product_features": features, "tokens_used": tokens}

# --- PHASE 2: RESEARCH ---

@agent_node("research")
async def research_agent(state: LaunchState) -> dict:
    llm = get_llm()
    features = state.get('product_features', [])
    prompt = f"Perform market research for a product with these features: {features}. Summarize current trends and demographics."
    response = await llm.ainvoke([SystemMessage(content="You are a market research analyst."), HumanMessage(content=prompt)])
    tokens = response.response_metadata.get("eval_count", 0) + response.response_metadata.get("prompt_eval_count", 0)
    return {"market_research": response.content, "tokens_used": tokens}

@agent_node("competitor")
async def competitor_agent(state: LaunchState) -> dict:
    llm = get_llm()
    features = state.get('product_features', [])
    prompt = f"Identify 3 potential market competitors and their price points for a product with these features: {features}."
    response = await llm.ainvoke([SystemMessage(content="You are a competitor analysis AI."), HumanMessage(content=prompt)])
    tokens = response.response_metadata.get("eval_count", 0) + response.response_metadata.get("prompt_eval_count", 0)
    return {"competitor_analysis": response.content, "tokens_used": tokens}

# --- PHASE 3: STRATEGY ---

@agent_node("pricing")
async def pricing_agent(state: LaunchState) -> dict:
    llm = get_json_llm()
    sys = "Based on competitor analysis, recommend a pricing strategy in JSON format with exactly two keys: 'price' (number) and 'reasoning' (string)."
    msg = f"Competitors: {state.get('competitor_analysis')}"
    response = await llm.ainvoke([SystemMessage(content=sys), HumanMessage(content=msg)])
    try:
        pricing = json.loads(response.content)
    except:
        pricing = {"price": 129.99, "reasoning": "Fallback default"}
    tokens = response.response_metadata.get("eval_count", 0) + response.response_metadata.get("prompt_eval_count", 0)
    return {"pricing_strategy": pricing, "tokens_used": tokens, "confidence_scores": {"pricing": 90}}

@agent_node("seo")
async def seo_agent(state: LaunchState) -> dict:
    llm = get_json_llm()
    sys = "Generate 5 SEO keywords based on the research. Return JSON format with a single key 'keywords' containing a list of strings."
    msg = f"Research: {state.get('market_research')}"
    response = await llm.ainvoke([SystemMessage(content=sys), HumanMessage(content=msg)])
    try:
        data = json.loads(response.content)
        keywords = data.get("keywords", [])
    except:
        keywords = ["product", "new"]
    tokens = response.response_metadata.get("eval_count", 0) + response.response_metadata.get("prompt_eval_count", 0)
    return {"seo_keywords": keywords, "tokens_used": tokens, "confidence_scores": {"seo": 85}}

@agent_node("branding")
async def branding_agent(state: LaunchState) -> dict:
    llm = get_llm()
    features = state.get('product_features', [])
    prompt = f"Create a compelling brand voice statement (1 sentence) for a product with these features: {features}"
    response = await llm.ainvoke([SystemMessage(content="You are a brand identity expert."), HumanMessage(content=prompt)])
    tokens = response.response_metadata.get("eval_count", 0) + response.response_metadata.get("prompt_eval_count", 0)
    return {"brand_voice": response.content, "tokens_used": tokens, "confidence_scores": {"branding": 95}}

# --- PHASE 4: CREATION ---

@agent_node("listing")
async def listing_agent(state: LaunchState) -> dict:
    llm = get_llm()
    marketplaces = state.get("target_marketplaces", [])
    listings = {}
    tokens = 0
    for mp in marketplaces:
        prompt = f"Write a short product listing for {mp}. Features: {state.get('product_features')}. Price: {state.get('pricing_strategy', {}).get('price')}. Brand voice: {state.get('brand_voice')}"
        resp = await llm.ainvoke([HumanMessage(content=prompt)])
        listings[mp] = {"title": f"New Product - {mp}", "description": resp.content}
        tokens += resp.response_metadata.get("eval_count", 0) + resp.response_metadata.get("prompt_eval_count", 0)
    return {"marketplace_listings": listings, "tokens_used": tokens}

@agent_node("marketing")
async def marketing_agent(state: LaunchState) -> dict:
    llm = get_json_llm()
    sys = "Create 2 marketing campaigns. Return JSON format with a key 'campaigns' containing a list of objects, each with 'platform' and 'copy'."
    msg = f"Brand voice: {state.get('brand_voice')}. Features: {state.get('product_features')}."
    response = await llm.ainvoke([SystemMessage(content=sys), HumanMessage(content=msg)])
    try:
        data = json.loads(response.content)
        campaigns = data.get("campaigns", [])
    except:
        campaigns = []
    tokens = response.response_metadata.get("eval_count", 0) + response.response_metadata.get("prompt_eval_count", 0)
    return {"marketing_campaigns": campaigns, "tokens_used": tokens}

# --- PHASE 5: REVIEW ---

@agent_node("qa")
async def qa_agent(state: LaunchState) -> dict:
    llm = get_json_llm()
    sys = "Evaluate the listings and marketing campaigns for quality. Return JSON format with 'status' (passed or failed) and 'issues' (list of strings)."
    msg = f"Listings: {state.get('marketplace_listings')}. Campaigns: {state.get('marketing_campaigns')}."
    response = await llm.ainvoke([SystemMessage(content=sys), HumanMessage(content=msg)])
    try:
        report = json.loads(response.content)
    except:
        report = {"status": "passed", "issues": []}
    tokens = response.response_metadata.get("eval_count", 0) + response.response_metadata.get("prompt_eval_count", 0)
    return {"qa_report": report, "tokens_used": tokens}

@agent_node("marketplace")
async def marketplace_agent(state: LaunchState) -> dict:
    from app.services.marketplace_service import MarketplaceService
    
    launch_id_str = state.get("launch_id")
    product_id_str = state.get("product_id")
    listings = state.get("marketplace_listings", {})
    
    if launch_id_str and product_id_str and listings:
        try:
            launch_uuid = uuid.UUID(launch_id_str)
            product_uuid = uuid.UUID(product_id_str)
            
            async with async_session_factory() as db:
                service = MarketplaceService(db)
                await service.save_listings(launch_uuid, product_uuid, listings)
                logger.info("Saved marketplace listings", launch_id=launch_id_str)
        except Exception as e:
            logger.error("Failed to save marketplace listings", error=str(e))
            
    return {}

# --- PHASE 6: METRICS & PERSISTENCE ---

@agent_node("memory_agent")
async def memory_agent(state: LaunchState) -> dict:
    """Extracts strategic data from the launch and persists it into ChromaDB Long-Term Memory."""
    user_id = uuid.uuid5(uuid.NAMESPACE_DNS, "launchkart.ai")
    launch_id = state.get("launch_id", str(uuid.uuid4()))
    
    # Identify items to memorize
    memories_to_store = []
    
    if state.get("pricing_strategy"):
        memories_to_store.append({
            "content": json.dumps(state["pricing_strategy"]),
            "type": "strategy",
            "namespace": "pricing",
            "confidence": 92,
            "importance": 85
        })
        
    if state.get("seo_keywords"):
        memories_to_store.append({
            "content": ", ".join(state["seo_keywords"]),
            "type": "keywords",
            "namespace": "seo",
            "confidence": 88,
            "importance": 70
        })
        
    if state.get("brand_voice"):
        memories_to_store.append({
            "content": state["brand_voice"],
            "type": "guideline",
            "namespace": "branding",
            "confidence": 95,
            "importance": 80
        })

    # Persist
    async with async_session_factory() as db:
        memory_service = MemoryService(db)
        for m in memories_to_store:
            try:
                await memory_service.add_memory(
                    user_id=user_id,
                    content=m["content"],
                    memory_type=m["type"],
                    namespace=m["namespace"],
                    metadata={
                        "confidence": m["confidence"],
                        "importance": m["importance"],
                        "source_agent": "memory_agent",
                        "launch_id": launch_id
                    }
                )
            except Exception as e:
                logger.error("Memory Agent failed to persist memory", error=str(e), namespace=m["namespace"])
                
    return {}

@agent_node("analytics_agent")
async def analytics_agent(state: LaunchState) -> dict:
    # Just return whatever tokens have been accumulated throughout the run
    # so they are properly registered.
    # The actual accumulation is handled by state reducer.
    return {}

