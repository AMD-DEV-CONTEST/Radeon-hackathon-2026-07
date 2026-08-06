#include <cassert>
#include "vector_store.h"

void test_tfidf_search() {
    VectorStore store;
    store.add_chunk("authentication token validation");
    store.add_chunk("database connection pool");
    store.finalize();
    auto results = store.search("authentication", 5);
    assert(!results.empty());
    assert(results[0].score > 0);
}

void test_cosine_similarity() {
    std::unordered_map<std::string, double> a = {{"hello", 1.0}, {"world", 0.5}};
    std::unordered_map<std::string, double> b = {{"hello", 1.0}, {"world", 0.5}};
    assert(cosine_similarity(a, b) > 0.99);
}
