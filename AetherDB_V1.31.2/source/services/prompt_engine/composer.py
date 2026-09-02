"""PromptComposer."""
from services.prompt_engine.manager import PromptProfileManager
class PromptComposer:
    def __init__(s):s._m=PromptProfileManager()
    def compose(s,t,v=None,pid=None):
        p=(s._m.get(pid)or{}).get("content","")if pid else(s._m.get_active(t)or{}).get("content","")
        return p
