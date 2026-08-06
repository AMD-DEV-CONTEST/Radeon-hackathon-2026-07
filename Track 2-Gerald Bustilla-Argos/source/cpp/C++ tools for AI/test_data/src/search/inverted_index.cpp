// Inverted index for fast text search
#include "inverted_index.h"

void InvertedIndex::add(const std::string& term, int doc_id, double frequency) {
    postings_[term].push_back({doc_id, frequency});
}

std::vector<Posting> InvertedIndex::search(const std::string& term) {
    auto it = postings_.find(term);
    if (it == postings_.end()) return {};
    return it->second;
}
