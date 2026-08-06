#include "vector_store.h"
#include "text_utils.h"
#include <cmath>
#include <algorithm>
#include <set>

namespace aisearch {

VectorStore::VectorStore() : finalized_(false), avgdl_(0.0) {}

std::unordered_map<std::string, double> VectorStore::compute_tf(const std::string& text) const {
    auto tokens = tokenize(text);
    tokens = remove_stop_words(tokens);

    std::unordered_map<std::string, double> tf;
    for (const auto& token : tokens) {
        tf[token.text]++;
    }

    // Normalize by total tokens
    double total = static_cast<double>(tokens.size());
    if (total > 0) {
        for (auto& [term, count] : tf) {
            count /= total;
        }
    }

    return tf;
}

void VectorStore::compute_tfidf() {
    size_t N = chunks_.size();
    if (N == 0) return;

    for (auto& chunk : chunks_) {
        auto tf = compute_tf(chunk.text);

        chunk.tfidf_vector.clear();
        for (const auto& [term, freq] : tf) {
            // IDF = log(N / df)
            int df = vocabulary_[term];
            double idf = std::log(static_cast<double>(N) / static_cast<double>(df));
            chunk.tfidf_vector[term] = freq * idf;
        }
    }
}

double VectorStore::cosine_similarity(
    const std::unordered_map<std::string, double>& a,
    const std::unordered_map<std::string, double>& b
) {
    if (a.empty() || b.empty()) return 0.0;

    // Iterate over the smaller map
    const auto& smaller = (a.size() < b.size()) ? a : b;
    const auto& larger = (a.size() < b.size()) ? b : a;

    double dot = 0.0;
    for (const auto& [term, val] : smaller) {
        auto it = larger.find(term);
        if (it != larger.end()) {
            dot += val * it->second;
        }
    }

    // Compute magnitudes
    double mag_a = 0.0, mag_b = 0.0;
    for (const auto& [term, val] : a) mag_a += val * val;
    for (const auto& [term, val] : b) mag_b += val * val;

    mag_a = std::sqrt(mag_a);
    mag_b = std::sqrt(mag_b);

    if (mag_a < 1e-12 || mag_b < 1e-12) return 0.0;

    return dot / (mag_a * mag_b);
}

int VectorStore::add_chunk(const std::string& file_path,
                            const std::string& relative_path,
                            const std::string& text,
                            int chunk_index,
                            size_t start_pos,
                            size_t end_pos) {
    IndexedChunk chunk;
    chunk.id = static_cast<int>(chunks_.size());
    chunk.file_path = file_path;
    chunk.relative_path = relative_path;
    chunk.text = text;
    chunk.chunk_index = chunk_index;
    chunk.start_pos = start_pos;
    chunk.end_pos = end_pos;

    // Compute term frequency and update vocabulary (document frequency)
    auto tf = compute_tf(text);
    for (const auto& [term, freq] : tf) {
        vocabulary_[term]++; // document frequency
        inverted_index_[term].push_back({chunk.id, freq});
    }

    // Store chunk length for BM25
    auto tokens = tokenize(text);
    tokens = remove_stop_words(tokens);
    chunk_lengths_.push_back(tokens.size());

    chunks_.push_back(std::move(chunk));
    return chunks_.back().id;
}

void VectorStore::finalize() {
    if (finalized_) return;
    compute_tfidf();
    // Compute average document length for BM25
    if (!chunk_lengths_.empty()) {
        double total = 0.0;
        for (size_t l : chunk_lengths_) total += static_cast<double>(l);
        avgdl_ = total / static_cast<double>(chunk_lengths_.size());
    }
    finalized_ = true;
}

std::vector<VectorStore::SearchResult> VectorStore::search(const std::string& query, size_t top_k) const {
    std::vector<SearchResult> results;

    if (!finalized_ || chunks_.empty()) return results;

    // Compute query TF-IDF vector
    VectorStore* self = const_cast<VectorStore*>(this);
    auto query_tf = self->compute_tf(query);

    if (query_tf.empty()) return results;

    // Build query TF-IDF vector using the same IDF values
    size_t N = chunks_.size();
    std::unordered_map<std::string, double> query_vec;
    for (const auto& [term, freq] : query_tf) {
        auto it = vocabulary_.find(term);
        if (it != vocabulary_.end()) {
            double idf = std::log(static_cast<double>(N) / static_cast<double>(it->second));
            query_vec[term] = freq * idf;
        }
    }

    if (query_vec.empty()) return results;

    // Use inverted index to find candidate chunks
    std::set<int> candidates;
    for (const auto& [term, _] : query_vec) {
        auto it = inverted_index_.find(term);
        if (it != inverted_index_.end()) {
            for (const auto& posting : it->second) {
                candidates.insert(posting.chunk_id);
            }
        }
    }

    // Score each candidate
    for (int chunk_id : candidates) {
        if (chunk_id < 0 || chunk_id >= static_cast<int>(chunks_.size())) continue;
        double sim = cosine_similarity(query_vec, chunks_[chunk_id].tfidf_vector);
        if (sim > 0.0) {
            results.push_back({chunk_id, sim, sim});
        }
    }

    // Sort by score descending
    std::sort(results.begin(), results.end(),
              [](const SearchResult& a, const SearchResult& b) {
                  return a.score > b.score;
              });

    // Return top_k
    if (results.size() > top_k) {
        results.resize(top_k);
    }

    return results;
}

const IndexedChunk* VectorStore::get_chunk(int id) const {
    if (id < 0 || id >= static_cast<int>(chunks_.size())) return nullptr;
    return &chunks_[id];
}

const std::vector<IndexedChunk>& VectorStore::get_all_chunks() const {
    return chunks_;
}

size_t VectorStore::chunk_count() const {
    return chunks_.size();
}

size_t VectorStore::vocabulary_size() const {
    return vocabulary_.size();
}

const std::unordered_map<std::string, int>& VectorStore::get_vocabulary() const {
    return vocabulary_;
}

bool VectorStore::is_finalized() const {
    return finalized_;
}

std::vector<VectorStore::SearchResult> VectorStore::search_bm25(const std::string& query, size_t top_k) const {
    std::vector<SearchResult> results;
    if (!finalized_ || chunks_.empty() || avgdl_ < 1e-12) return results;

    VectorStore* self = const_cast<VectorStore*>(this);
    auto query_tokens = tokenize(query);
    query_tokens = remove_stop_words(query_tokens);
    if (query_tokens.empty()) return results;

    // Count query term frequencies
    std::unordered_map<std::string, int> query_tf;
    for (const auto& t : query_tokens) query_tf[t.text]++;

    // BM25 parameters
    const double k1 = 1.5;
    const double b = 0.75;
    size_t N = chunks_.size();

    // Score each candidate chunk
    std::unordered_map<int, double> scores;
    for (const auto& [term, qtf] : query_tf) {
        auto it = inverted_index_.find(term);
        if (it == inverted_index_.end()) continue;
        int df = 0;
        auto vit = vocabulary_.find(term);
        if (vit != vocabulary_.end()) df = vit->second;
        if (df == 0) continue;

        double idf = std::log((static_cast<double>(N) - df + 0.5) / (df + 0.5) + 1.0);

        for (const auto& posting : it->second) {
            if (posting.chunk_id < 0 || posting.chunk_id >= static_cast<int>(chunk_lengths_.size())) continue;
            size_t dl = chunk_lengths_[posting.chunk_id];
            double tf = posting.term_frequency;
            double tf_norm = tf * (k1 + 1.0) / (tf + k1 * (1.0 - b + b * static_cast<double>(dl) / avgdl_));
            scores[posting.chunk_id] += idf * tf_norm;
        }
    }

    for (const auto& [chunk_id, score] : scores) {
        if (score > 0.0) {
            double normalized = score / (score + 1.0); // normalize to 0-1
            results.push_back({chunk_id, normalized, normalized});
        }
    }

    std::sort(results.begin(), results.end(),
              [](const SearchResult& a, const SearchResult& b) { return a.score > b.score; });

    if (results.size() > top_k) results.resize(top_k);
    return results;
}

} // namespace aisearch
