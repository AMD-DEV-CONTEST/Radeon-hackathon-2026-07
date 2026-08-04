import asyncio
import json
import uuid
import sys
import os
from app.services.agent_orchestrator import AgentOrchestrator

async def main():
    print("Starting product launch analysis...")
    orchestrator = AgentOrchestrator()
    
    launch_id = str(uuid.uuid4())
    product_id = str(uuid.uuid4())
    
    initial_state = {
        "launch_id": launch_id,
        "product_id": product_id,
        "product_image_path": "dummy_path.png",
        "target_marketplaces": ["amazon", "shopify"],
        "preferences": {
            "name": "Eco-friendly Water Bottle",
            "description": "A reusable, insulated water bottle made from recycled materials.",
            "target_audience": "Environmentally conscious consumers, athletes"
        }
    }
    
    try:
        final_state = await orchestrator.run_pipeline(initial_state)
        
        if final_state:
            with open("analysis_result.json", "w") as f:
                serializable_state = {}
                for k, v in final_state.items():
                    if isinstance(v, (str, dict, list, int, float, bool, type(None))):
                        serializable_state[k] = v
                json.dump(serializable_state, f, indent=2)
            print("Analysis complete. Saved to analysis_result.json.")
        else:
            print("Analysis failed to produce a final state.")
    except Exception as e:
        print(f"Error during analysis: {e}")

if __name__ == "__main__":
    asyncio.run(main())
