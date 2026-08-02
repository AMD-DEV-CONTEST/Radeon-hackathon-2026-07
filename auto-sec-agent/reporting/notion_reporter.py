"""
Notion Reporter — Document findings in Notion
"""
import json
import urllib.request
import os
from pathlib import Path

class NotionReporter:
    """Document security findings in Notion databases"""
    
    def __init__(self, api_key=None):
        self.api_key = api_key or os.environ.get("NOTION_API_KEY", "")
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Notion-Version": "2025-09-03",
            "Content-Type": "application/json"
        }
        self.workspace_connected = bool(self.api_key)
    
    def _api_call(self, method, endpoint, data=None):
        """Make Notion API call"""
        if not self.api_key:
            return {"error": "No API key"}
        
        url = f"https://api.notion.com/v1/{endpoint}"
        body = json.dumps(data).encode() if data else None
        
        req = urllib.request.Request(url, data=body, headers=self.headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())
        except Exception as e:
            return {"error": str(e)}
    
    def create_scan_page(self, target, summary, report_markdown):
        """Create a Notion page documenting scan results"""
        if not self.workspace_connected:
            return {"error": "Notion not configured"}
        
        # Search for existing "Security Scans" database
        search = self._api_call("POST", "search", {"query": "Security Scans"})
        
        # Create page in workspace
        parent = {"type": "workspace", "workspace": True}
        if search.get("results"):
            parent = {"type": "page_id", "page_id": search["results"][0]["id"]}
        
        page_data = {
            "parent": parent,
            "properties": {
                "title": [{"text": {"content": f"Security Scan: {target}"}}]
            },
            "markdown": report_markdown[:2000]  # Notion has limits
        }
        
        result = self._api_call("POST", "pages", page_data)
        return result
    
    def list_pages(self):
        """List recent pages"""
        result = self._api_call("POST", "search", {"page_size": 10})
        pages = []
        for r in result.get("results", []):
            pages.append({
                "id": r["id"],
                "title": r.get("properties", {}).get("title", {}).get("title", [{}])[0].get("plain_text", "Untitled"),
                "url": r.get("url", "")
            })
        return pages
