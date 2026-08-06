from nexus.retrieval import SemanticRetriever

def test_retrieval_ranks_matching_context_first():
    retriever = SemanticRetriever()
    documents = [
        "Aria lives in Kochi and works on artificial intelligence.",
        "The Nexus Research Lab is located in Bengaluru.",
        "Noah maintains the NexusAI backend services.",
    ]

    hits = retriever.search("Who maintains the NexusAI backend?", documents, top_k=3)
    assert hits
    assert hits[0].index == 2

def test_empty_query_returns_no_hits():
    retriever = SemanticRetriever()
    assert retriever.search("", ["some document"]) == []
