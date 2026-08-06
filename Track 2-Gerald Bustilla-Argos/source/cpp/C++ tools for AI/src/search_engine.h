#pragma once

#include "content_indexer.h"
#include <string>
#include <vector>

namespace aisearch {

// A single search result item
struct SearchHit {
    std::string  file_path;
    std::string  relative_path;
    std::string  file_type;        // "text" or "image"
    std::string  snippet;          // Text snippet (for text results)
    double       score;            // Relevance score (0-1)
    double       cosine_similarity;// For text search
    int          chunk_index;      // For text results
    size_t       start_pos;        // For text results
    size_t       end_pos;          // For text results
    // For image results:
    std::string  base64_hash;
    std::string  perceptual_hex;
    int          hamming_distance; // For similar image search
    // For filename/path results:
    std::string  match_type;       // "content", "filename", "path", "image_hash", "similar_image"
    uintmax_t    file_size;        // File size for filter results
    // AI enrichment fields
    std::string  context_snippet;  // Context-aware snippet with line numbers
    std::string  language;         // Programming language of the file
    int          line_number;      // Line number of match (0 if not applicable)
};

// Combined search results
struct SearchResults {
    std::string              query;
    std::vector<SearchHit>   text_hits;
    std::vector<SearchHit>   image_hits;
    std::vector<SearchHit>   filename_hits;
    std::vector<SearchHit>   path_hits;
    size_t                   total_hits;
    double                   search_time_ms;
};

// Search text content using the vector store (RAG-style retrieval)
std::vector<SearchHit> search_text(const ContentIndex& index, const std::string& query, size_t top_k = 10);

// Search for an image by base64 hash (exact match)
std::vector<SearchHit> search_image_by_hash(const ContentIndex& index, const std::string& base64_hash);

// Search for similar images by providing an image file path
std::vector<SearchHit> search_similar_images(const ContentIndex& index, const std::string& image_path, int max_distance = 10);

// Combined search: search both text and images
SearchResults search_all(const ContentIndex& index, const std::string& query, size_t top_k = 10);

// ---- New search capabilities ----

// Search by filename pattern (case-insensitive substring match)
std::vector<SearchHit> search_by_filename(const ContentIndex& index, const std::string& pattern, size_t top_k = 50);

// Search by file path pattern (case-insensitive substring match)
std::vector<SearchHit> search_by_path(const ContentIndex& index, const std::string& pattern, size_t top_k = 50);

// Search by file extension (e.g. "cpp", ".py", "json")
std::vector<SearchHit> search_by_extension(const ContentIndex& index, const std::string& extension, size_t top_k = 100);

// Filter files by size range
std::vector<SearchHit> search_by_size_range(const ContentIndex& index, uintmax_t min_size, uintmax_t max_size, size_t top_k = 100);

// Exact phrase search (find exact substring in text content)
std::vector<SearchHit> search_exact_phrase(const ContentIndex& index, const std::string& phrase, size_t top_k = 50);

// Fuzzy text search (find approximate matches using edit distance)
std::vector<SearchHit> search_fuzzy_text(const ContentIndex& index, const std::string& query, size_t top_k = 10, int max_distance = 2);

// Boolean search (supports AND, OR, NOT operators)
// Query format: "term1 AND term2" or "term1 OR term2" or "term1 NOT term2"
std::vector<SearchHit> search_boolean(const ContentIndex& index, const std::string& query, size_t top_k = 20);

// Universal search: tries all search modes and combines results
SearchResults search_universal(const ContentIndex& index, const std::string& query, size_t top_k = 10);

// Find files related to a given file by import/include references
std::vector<SearchHit> search_related_files(const ContentIndex& index, const std::string& file_path, size_t top_k = 20);

// Regex search: search text content using a regex pattern
std::vector<SearchHit> search_regex(const ContentIndex& index, const std::string& pattern, size_t top_k = 50);

// Synonym-enhanced search: expands query with programming synonyms before searching
std::vector<SearchHit> search_with_synonyms(const ContentIndex& index, const std::string& query, size_t top_k = 10);

// BM25 search: uses BM25 scoring for better relevance ranking
std::vector<SearchHit> search_bm25(const ContentIndex& index, const std::string& query, size_t top_k = 10);

// Levenshtein edit distance between two strings
int levenshtein_distance(const std::string& a, const std::string& b);

// Check if a string contains a substring (case-insensitive)
bool contains_ci(const std::string& haystack, const std::string& needle);

} // namespace aisearch
