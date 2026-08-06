package com.aisearch;

public class SearchEngine {
    private final VectorStore vectorStore;
    
    public SearchEngine() {
        this.vectorStore = new VectorStore();
    }
    
    public List<SearchResult> search(String query, int topK) {
        return vectorStore.search(query, topK);
    }
}
