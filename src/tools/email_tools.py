import os
import json
import uuid
import logging
from typing import List, Dict, Any
from .registry import ToolRegistry

logger = logging.getLogger(__name__)

def register_email_tools(registry: ToolRegistry) -> None:
    """Register email tools with the registry."""
    registry.register(
        name="email_draft",
        func=email_draft,
        description="Create a draft email.",
        parameters={
            "to": {"type": "string", "description": "Recipient email address"},
            "subject": {"type": "string", "description": "Email subject"},
            "body": {"type": "string", "description": "Email body content"},
            "cc": {"type": "string", "description": "CC recipients", "required": False}
        },
        requires_permission=True
    )
    
    registry.register(
        name="email_search",
        func=email_search,
        description="Search for emails.",
        parameters={
            "query": {"type": "string", "description": "Search query"},
            "folder": {"type": "string", "description": "Folder to search in", "required": False}
        },
        requires_permission=True
    )

def email_draft(to: str, subject: str, body: str, cc: str = "") -> Dict[str, str]:
    """Create a draft email locally."""
    draft_id = uuid.uuid4().hex
    draft_dir = "./data/documents/email_drafts"
    os.makedirs(draft_dir, exist_ok=True)
    
    draft = {
        "id": draft_id,
        "to": to,
        "cc": cc,
        "subject": subject,
        "body": body,
        "status": "draft"
    }
    
    file_path = os.path.join(draft_dir, f"{draft_id}.json")
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(draft, f, indent=2)
        return {"draft_id": draft_id, "to": to, "subject": subject, "saved_path": file_path}
    except Exception as e:
        logger.error(f"Error drafting email: {e}")
        return {"error": str(e)}

def email_search(query: str, folder: str = "inbox") -> List[Dict[str, str]]:
    """Search demo email data."""
    results = []
    email_dir = f"./data/documents/emails/{folder}"
    
    if not os.path.exists(email_dir):
        return results
        
    try:
        for file in os.listdir(email_dir):
            if file.endswith('.json'):
                try:
                    with open(os.path.join(email_dir, file), 'r', encoding='utf-8') as f:
                        email_data = json.load(f)
                        search_text = f"{email_data.get('subject', '')} {email_data.get('body', '')} {email_data.get('from', '')}".lower()
                        
                        if query.lower() in search_text:
                            snippet = email_data.get('body', '')[:100]
                            results.append({
                                "id": email_data.get("id", ""),
                                "from": email_data.get("from", ""),
                                "subject": email_data.get("subject", ""),
                                "snippet": snippet,
                                "date": email_data.get("date", "")
                            })
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        logger.error(f"Error searching emails: {e}")
        
    return results
