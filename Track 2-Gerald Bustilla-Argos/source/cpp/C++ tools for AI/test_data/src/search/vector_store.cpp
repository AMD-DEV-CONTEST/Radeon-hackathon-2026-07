// TF-IDF vector store for RAG-style retrieval
#include "vector_store.h"

void VectorStore::add_chunk(const std::string& text) {
    auto tokens = tokenize(text);
    auto tf = compute_term_frequency(tokens);
    for (const auto& [term, freq] : tf) {
        vocabulary_[term]++;
        inverted_index_[term].push_back(current_chunk_id_);
    }
    chunks_.push_back({current_chunk_id_++, text, tf});
}

std::vector<SearchResult> VectorStore::search(const std::string& query, size_t top_k) {
    auto query_vec = compute_tfidf_vector(query);
    std::vector<SearchResult> results;
    for (const auto& chunk : chunks_) {
        double sim = cosine_similarity(query_vec, chunk.tfidf_vector);
        if (sim > 0) results.push_back({chunk.id, sim});
    }
    std::sort(results.begin(), results.end(), [](auto& a, auto& b) { return a.score > b.score; });
    if (results.size() > top_k) results.resize(top_k);
    return results;
}
