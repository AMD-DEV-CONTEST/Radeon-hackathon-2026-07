import time
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Callable

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from app.api.v1.websocket import manager
from app.domain.agent_state import LaunchState

logger = structlog.get_logger(__name__)

def agent_node(agent_name: str):
    """
    Decorator for LangGraph agent nodes.
    Automatically handles:
    1. Broadcasting 'running' status to WebSockets
    2. Timing the execution
    3. Broadcasting 'completed' status and timeline events
    4. Error handling and 'failed' status
    """
    def decorator(func: Callable[[LaunchState], dict | Any]):
        @wraps(func)
        async def wrapper(state: LaunchState) -> dict:
            launch_id = state.get("launch_id")
            
            # 1. Broadcast Start
            if launch_id:
                await manager.broadcast_agent_status(
                    launch_id=launch_id,
                    agent_id=agent_name,
                    status="running",
                    progress=10,
                )
            
            start_time = time.time()
            try:
                # 2. Execute Node
                logger.info(f"Agent {agent_name} started", launch_id=launch_id)
                result = await func(state)
                
                duration = round(time.time() - start_time, 2)
                
                # 3. Broadcast Completion
                if launch_id:
                    await manager.broadcast_agent_status(
                        launch_id=launch_id,
                        agent_id=agent_name,
                        status="completed",
                        progress=100,
                    )
                    await manager.broadcast_timeline_event(
                        launch_id=launch_id,
                        event={
                            "id": f"{agent_name}_{time.time()}",
                            "timestamp": datetime.now().strftime("%H:%M:%S"),
                            "agent": agent_name.replace("_", " ").title(),
                            "status": "completed",
                            "duration": duration,
                        }
                    )
                
                logger.info(f"Agent {agent_name} completed", launch_id=launch_id, duration=duration)
                return result
                
            except Exception as e:
                logger.error(f"Agent {agent_name} failed", error=str(e), launch_id=launch_id)
                if launch_id:
                    await manager.broadcast_agent_status(
                        launch_id=launch_id,
                        agent_id=agent_name,
                        status="failed",
                        progress=0,
                    )
                # Still return an empty dict to not crash the entire graph unless necessary
                # In production, we might raise or handle differently
                return {}
                
        return wrapper
    return decorator
