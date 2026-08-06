from nexus.extraction import extract

def test_extract_core_relationships():
    text = (
        "Aria lives in Kochi. "
        "Aria works with Noah. "
        "Noah maintains the NexusAI backend. "
        "Maya advises the NexusAI project. "
        "Nexus Research Lab is located in Bengaluru."
    )
    result = extract(text)
    relations = {(r.source_name, r.target_name, r.relationship_type) for r in result.relationships}

    assert ("Aria", "Kochi", "LIVES_IN") in relations
    assert ("Aria", "Noah", "WORKS_WITH") in relations
    assert ("Noah", "NexusAI", "MAINTAINS") in relations
    assert ("Maya", "NexusAI", "ADVISES") in relations
    assert ("Nexus Research Lab", "Bengaluru", "LOCATED_IN") in relations
