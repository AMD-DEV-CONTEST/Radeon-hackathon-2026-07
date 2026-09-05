// TF-IDF computation for text indexing
#include "tfidf.h"

double TfIdf::compute_tf(const std::string& term, const std::vector<std::string>& tokens) {
    int count = 0;
    for (const auto& t : tokens) {
        if (t == term) count++;
    }
    return static_cast<double>(count) / tokens.size();
}

double TfIdf::compute_idf(const std::string& term, size_t total_docs, int doc_freq) {
    return std::log(static_cast<double>(total_docs) / doc_freq);
}
