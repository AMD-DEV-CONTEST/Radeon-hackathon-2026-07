#pragma once

#include <string>
#include <vector>
#include <unordered_map>
#include <unordered_set>
#include <cstdint>
#include <cmath>
#include <algorithm>

namespace aisearch {

// A chunk of indexed text with its source file info
struct IndexedChunk {
    int          id;              // Unique chunk ID
    std::string  file_path;       // Source file path
    std::string  relative_path;   // Relative path
    std::string  text;            // The chunk text content
    int          chunk_index;     // Index within the source file
    size_t       start_pos;       // Start position in original document
    size_t       end_pos;         // End position in original document
    std::unordered_map<std::string, double> tfidf_vector; // TF-IDF vector for this chunk
};

// Inverted index entry
struct Posting {
    int    chunk_id;
    double term_frequency;
};

// The vector store implements a lightweight RAG-like retrieval system:
// - Text is chunked into pieces
// - Each chunk gets a TF-IDF vector
// - An inverted index maps terms to chunks
// - Cosine similarity ranks chunks by relevance
class VectorStore {
public:
    VectorStore();

    // Add a text chunk to the store
    // Returns the assigned chunk ID
    int add_chunk(const std::string& file_path,
                  const std::string& relative_path,
                  const std::string& text,
                  int chunk_index,
                  size_t start_pos,
                  size_t end_pos);

    // Finalize TF-IDF vectors after all chunks are added
    void finalize();

    // Search for text and return ranked chunk IDs with similarity scores
    struct SearchResult {
        int    chunk_id;
        double score;
        double cosine_similarity;
    };

    std::vector<SearchResult> search(const std::string& query, size_t top_k = 10) const;

    // BM25 search (better ranking than pure TF-IDF)
    std::vector<SearchResult> search_bm25(const std::string& query, size_t top_k = 10) const;

    // Get a chunk by ID
    const IndexedChunk* get_chunk(int id) const;

    // Get all chunks
    const std::vector<IndexedChunk>& get_all_chunks() const;

    // Statistics
    size_t chunk_count() const;
    size_t vocabulary_size() const;

    // Get vocabulary (all unique terms)
    const std::unordered_map<std::string, int>& get_vocabulary() const;

    // Check if finalized
    bool is_finalized() const;

private:
    std::vector<IndexedChunk> chunks_;
    std::unordered_map<std::string, std::vector<Posting>> inverted_index_;
    std::unordered_map<std::string, int> vocabulary_; // term -> document frequency
    bool finalized_;
    std::vector<size_t> chunk_lengths_; // token count per chunk for BM25
    double avgdl_; // average document length for BM25

    // Compute term frequency for a chunk
    std::unordered_map<std::string, double> compute_tf(const std::string& text) const;

    // Compute TF-IDF for all chunks
    void compute_tfidf();

    // Compute cosine similarity between two sparse vectors
    static double cosine_similarity(
        const std::unordered_map<std::string, double>& a,
        const std::unordered_map<std::string, double>& b
    );
};

} // namespace aisearch
