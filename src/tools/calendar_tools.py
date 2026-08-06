import os
import json
import uuid
import logging
from typing import List, Dict, Any, Optional
from .registry import ToolRegistry

logger = logging.getLogger(__name__)

def register_calendar_tools(registry: ToolRegistry) -> None:
    """Register calendar tools with the registry."""
    registry.register(
        name="calendar_query",
        func=calendar_query,
        description="Query calendar events.",
        parameters={
            "start_date": {"type": "string", "description": "Start date (YYYY-MM-DD)"},
            "end_date": {"type": "string", "description": "End date (YYYY-MM-DD)", "required": False},
            "query": {"type": "string", "description": "Search query text", "required": False}
        },
        requires_permission=False
    )
    
    registry.register(
        name="calendar_create_event",
        func=calendar_create_event,
        description="Create a new calendar event.",
        parameters={
            "title": {"type": "string", "description": "Event title"},
            "start": {"type": "string", "description": "Start datetime (ISO)"},
            "end": {"type": "string", "description": "End datetime (ISO)"},
            "description": {"type": "string", "description": "Event description", "required": False},
            "attendees": {"type": "array", "description": "List of attendee emails", "required": False}
        },
        requires_permission=True
    )

def _get_events_file() -> str:
    """Get path to the events JSON file."""
    events_dir = "./data/documents/calendar"
    os.makedirs(events_dir, exist_ok=True)
    events_file = os.path.join(events_dir, "events.json")
    if not os.path.exists(events_file):
        with open(events_file, 'w', encoding='utf-8') as f:
            json.dump([], f)
    return events_file

def calendar_query(start_date: str, end_date: Optional[str] = None, query: str = "") -> List[Dict[str, Any]]:
    """Read and filter calendar events."""
    try:
        events_file = _get_events_file()
        with open(events_file, 'r', encoding='utf-8') as f:
            events = json.load(f)
            
        results = []
        for event in events:
            # Simple date filtering (assuming ISO format strings that sort lexically)
            ev_start = event.get("start", "")
            if ev_start < start_date:
                continue
            if end_date and ev_start > end_date:
                continue
                
            if query:
                search_text = f"{event.get('title', '')} {event.get('description', '')}".lower()
                if query.lower() not in search_text:
                    continue
                    
            results.append({
                "id": event.get("id", ""),
                "title": event.get("title", ""),
                "start": event.get("start", ""),
                "end": event.get("end", ""),
                "description": event.get("description", "")
            })
            
        return results
    except Exception as e:
        logger.error(f"Error querying calendar: {e}")
        return []

def calendar_create_event(title: str, start: str, end: str, description: str = "", attendees: Optional[List[str]] = None) -> Dict[str, str]:
    """Add a new calendar event."""
    try:
        events_file = _get_events_file()
        with open(events_file, 'r', encoding='utf-8') as f:
            events = json.load(f)
            
        event_id = uuid.uuid4().hex
        new_event = {
            "id": event_id,
            "title": title,
            "start": start,
            "end": end,
            "description": description,
            "attendees": attendees or []
        }
        
        events.append(new_event)
        
        with open(events_file, 'w', encoding='utf-8') as f:
            json.dump(events, f, indent=2)
            
        return {
            "event_id": event_id,
            "title": title,
            "start": start,
            "end": end
        }
    except Exception as e:
        logger.error(f"Error creating calendar event: {e}")
        return {"error": str(e)}
