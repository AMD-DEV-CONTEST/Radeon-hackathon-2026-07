from nexus.world.context import extract_context

def test_context_normalizes_tokens():
 c=extract_context("Frozen pine forest beneath SNOW covered mountains.")
 assert {"frozen","pine","forest","snow","mountains"}<=c.tokens
 assert "snow covered" in c.phrases
