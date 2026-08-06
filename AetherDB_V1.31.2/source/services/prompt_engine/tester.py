"""Tester."""
from services.prompt_engine.composer import PromptComposer
class PromptTester:
    def __init__(s):s.c=PromptComposer()
    def test(s,pid=None,t="all",v=None):
        p=s.c.compose(t,v,pid)
        return{"prompt":p}
