#include "search_engine.h"
#include "text_utils.h"
#include <chrono>
#include <algorithm>
#include <vector>
#include <unordered_set>
#include <set>
#include <sstream>
#include <cctype>

namespace aisearch {

// ---- Utility functions ----

int levenshtein_distance(const std::string& a, const std::string& b) {
    size_t m = a.size(), n = b.size();
    if (m == 0) return static_cast<int>(n);
    if (n == 0) return static_cast<int>(m);

    std::vector<int> prev(n + 1), curr(n + 1);
    for (size_t j = 0; j <= n; j++) prev[j] = static_cast<int>(j);

    for (size_t i = 1; i <= m; i++) {
        curr[0] = static_cast<int>(i);
        for (size_t j = 1; j <= n; j++) {
            int cost = (std::tolower(static_cast<unsigned char>(a[i-1])) ==
                        std::tolower(static_cast<unsigned char>(b[j-1]))) ? 0 : 1;
            curr[j] = std::min({prev[j] + 1, curr[j-1] + 1, prev[j-1] + cost});
        }
        std::swap(prev, curr);
    }
    return prev[n];
}

bool contains_ci(const std::string& haystack, const std::string& needle) {
    if (needle.empty()) return true;
    if (haystack.size() < needle.size()) return false;

    auto it = std::search(
        haystack.begin(), haystack.end(),
        needle.begin(), needle.end(),
        [](char a, char b) {
            return std::tolower(static_cast<unsigned char>(a)) ==
                   std::tolower(static_cast<unsigned char>(b));
        }
    );
    return it != haystack.end();
}

static SearchHit make_filename_hit(const FileEntry& fe, double score) {
    SearchHit hit;
    hit.file_path = fe.path;
    hit.relative_path = fe.relative_path;
    hit.file_type = file_type_string(fe.type);
    hit.snippet = "";
    hit.score = score;
    hit.cosine_similarity = 0.0;
    hit.chunk_index = -1;
    hit.start_pos = 0;
    hit.end_pos = 0;
    hit.match_type = "filename";
    hit.file_size = fe.size;
    hit.context_snippet = "";
    hit.language = fe.language;
    hit.line_number = 0;
    return hit;
}

std::vector<SearchHit> search_text(const ContentIndex& index, const std::string& query, size_t top_k) {
    std::vector<SearchHit> hits;

    auto results = index.text_store.search(query, top_k);

    for (const auto& result : results) {
        const auto* chunk = index.text_store.get_chunk(result.chunk_id);
        if (!chunk) continue;

        SearchHit hit;
        hit.file_path = chunk->file_path;
        hit.relative_path = chunk->relative_path;
        hit.file_type = "text";
        hit.snippet = get_snippet(chunk->text, chunk->text.size() / 2, 200);
        hit.score = result.score;
        hit.cosine_similarity = result.cosine_similarity;
        hit.chunk_index = chunk->chunk_index;
        hit.start_pos = chunk->start_pos;
        hit.end_pos = chunk->end_pos;
        hit.hamming_distance = 0;
        hit.match_type = "content";
        hit.file_size = 0;
        hit.context_snippet = get_context_snippet(chunk->text, chunk->text.size() / 2, 0, 3);
        // Find language from scan result
        for (const auto& fe : index.scan_result.files) {
            if (fe.path == chunk->file_path) {
                hit.language = fe.language;
                break;
            }
        }
        hit.line_number = 0;
        hits.push_back(std::move(hit));
    }

    return hits;
}

std::vector<SearchHit> search_image_by_hash(const ContentIndex& index, const std::string& base64_hash) {
    std::vector<SearchHit> hits;

    const auto* img = find_image_by_base64(index, base64_hash);
    if (!img) return hits;

    SearchHit hit;
    hit.file_path = img->file_path;
    hit.relative_path = img->relative_path;
    hit.file_type = "image";
    hit.snippet = "";
    hit.score = 1.0;
    hit.cosine_similarity = 0.0;
    hit.chunk_index = -1;
    hit.start_pos = 0;
    hit.end_pos = 0;
    hit.base64_hash = img->fingerprint.base64_hash;
    hit.perceptual_hex = img->fingerprint.perceptual_hex;
    hit.hamming_distance = 0;
    hit.match_type = "image_hash";
    hit.file_size = img->size;
    hits.push_back(std::move(hit));

    return hits;
}

std::vector<SearchHit> search_similar_images(const ContentIndex& index, const std::string& image_path, int max_distance) {
    std::vector<SearchHit> hits;

    ImageFingerprint target;
    try {
        target = fingerprint_image(image_path);
    } catch (...) {
        return hits;
    }

    for (const auto& img : index.images) {
        int dist = hamming_distance(target.perceptual_hash, img.fingerprint.perceptual_hash);
        if (dist <= max_distance) {
            SearchHit hit;
            hit.file_path = img.file_path;
            hit.relative_path = img.relative_path;
            hit.file_type = "image";
            hit.snippet = "";
            hit.score = 1.0 - (static_cast<double>(dist) / 64.0);
            hit.cosine_similarity = 0.0;
            hit.chunk_index = -1;
            hit.start_pos = 0;
            hit.end_pos = 0;
            hit.base64_hash = img.fingerprint.base64_hash;
            hit.perceptual_hex = img.fingerprint.perceptual_hex;
            hit.hamming_distance = dist;
            hit.match_type = "similar_image";
            hit.file_size = 0;
            hits.push_back(std::move(hit));
        }
    }

    std::sort(hits.begin(), hits.end(),
              [](const SearchHit& a, const SearchHit& b) {
                  return a.hamming_distance < b.hamming_distance;
              });

    return hits;
}

SearchResults search_all(const ContentIndex& index, const std::string& query, size_t top_k) {
    auto start = std::chrono::steady_clock::now();

    SearchResults results;
    results.query = query;

    // Search text content
    results.text_hits = search_text(index, query, top_k);

    // Try to interpret query as a base64 hash for image search
    results.image_hits = search_image_by_hash(index, query);

    // Also try as a file path for similar image search
    if (results.image_hits.empty()) {
        try {
            auto bytes = read_file_to_bytes(query);
            if (!bytes.empty()) {
                results.image_hits = search_similar_images(index, query);
            }
        } catch (...) {
        }
    }

    // Search by filename
    results.filename_hits = search_by_filename(index, query, top_k);

    // Search by path
    results.path_hits = search_by_path(index, query, top_k);

    results.total_hits = results.text_hits.size() + results.image_hits.size() +
                         results.filename_hits.size() + results.path_hits.size();

    auto end = std::chrono::steady_clock::now();
    results.search_time_ms = static_cast<double>(
        std::chrono::duration_cast<std::chrono::microseconds>(end - start).count()
    ) / 1000.0;

    return results;
}

// ---- New search implementations ----

std::vector<SearchHit> search_by_filename(const ContentIndex& index, const std::string& pattern, size_t top_k) {
    std::vector<SearchHit> hits;

    for (const auto& fe : index.scan_result.files) {
        if (contains_ci(fe.filename, pattern)) {
            double score = 1.0;
            // Exact match gets highest score
            if (fe.filename.size() == pattern.size()) score = 1.0;
            else score = static_cast<double>(pattern.size()) / fe.filename.size();

            hits.push_back(make_filename_hit(fe, score));
            if (hits.size() >= top_k) break;
        }
    }

    return hits;
}

std::vector<SearchHit> search_by_path(const ContentIndex& index, const std::string& pattern, size_t top_k) {
    std::vector<SearchHit> hits;

    // Normalize pattern: convert forward slashes to platform-specific separator
    std::string normalized_pattern = pattern;
#ifdef _WIN32
    for (auto& c : normalized_pattern) {
        if (c == '/') c = '\\';
    }
#endif

    for (const auto& fe : index.scan_result.files) {
        std::string search_path = fe.relative_path;
#ifdef _WIN32
        // On Windows, also try with forward slashes in case the relative_path uses them
        std::string fwd_path = fe.relative_path;
        for (auto& c : fwd_path) {
            if (c == '\\') c = '/';
        }
        if (contains_ci(search_path, normalized_pattern) || contains_ci(fwd_path, pattern) || contains_ci(fwd_path, normalized_pattern)) {
#else
        if (contains_ci(search_path, normalized_pattern)) {
#endif
            double score = static_cast<double>(normalized_pattern.size()) / fe.relative_path.size();
            SearchHit hit = make_filename_hit(fe, score);
            hit.match_type = "path";
            hits.push_back(hit);
            if (hits.size() >= top_k) break;
        }
    }

    return hits;
}

std::vector<SearchHit> search_by_extension(const ContentIndex& index, const std::string& extension, size_t top_k) {
    std::vector<SearchHit> hits;

    std::string ext = extension;
    if (ext.empty() || ext[0] != '.') {
        ext = "." + ext;
    }
    std::transform(ext.begin(), ext.end(), ext.begin(),
                   [](unsigned char c) { return std::tolower(c); });

    for (const auto& fe : index.scan_result.files) {
        if (fe.extension == ext) {
            hits.push_back(make_filename_hit(fe, 1.0));
            if (hits.size() >= top_k) break;
        }
    }

    return hits;
}

std::vector<SearchHit> search_by_size_range(const ContentIndex& index, uintmax_t min_size, uintmax_t max_size, size_t top_k) {
    std::vector<SearchHit> hits;

    for (const auto& fe : index.scan_result.files) {
        if (fe.size >= min_size && fe.size <= max_size) {
            SearchHit hit = make_filename_hit(fe, 1.0);
            hit.match_type = "size_filter";
            hits.push_back(hit);
            if (hits.size() >= top_k) break;
        }
    }

    return hits;
}

std::vector<SearchHit> search_exact_phrase(const ContentIndex& index, const std::string& phrase, size_t top_k) {
    std::vector<SearchHit> hits;

    if (phrase.empty()) return hits;

    std::string lower_phrase;
    lower_phrase.reserve(phrase.size());
    for (char c : phrase) {
        lower_phrase += static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    }

    const auto& chunks = index.text_store.get_all_chunks();
    for (const auto& chunk : chunks) {
        std::string lower_text;
        lower_text.reserve(chunk.text.size());
        for (char c : chunk.text) {
            lower_text += static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
        }

        size_t pos = lower_text.find(lower_phrase);
        if (pos != std::string::npos) {
            SearchHit hit;
            hit.file_path = chunk.file_path;
            hit.relative_path = chunk.relative_path;
            hit.file_type = "text";
            hit.snippet = get_snippet(chunk.text, pos + phrase.size() / 2, 200);
            hit.score = 1.0;
            hit.cosine_similarity = 0.0;
            hit.chunk_index = chunk.chunk_index;
            hit.start_pos = chunk.start_pos + pos;
            hit.end_pos = chunk.start_pos + pos + phrase.size();
            hit.match_type = "exact_phrase";
            hit.file_size = 0;
            hit.context_snippet = get_context_snippet(chunk.text, pos, phrase.size(), 3);
            // Find language and line number
            for (const auto& fe : index.scan_result.files) {
                if (fe.path == chunk.file_path) {
                    hit.language = fe.language;
                    break;
                }
            }
            // Calculate line number
            hit.line_number = 1;
            for (size_t i = 0; i < pos && i < chunk.text.size(); i++) {
                if (chunk.text[i] == '\n') hit.line_number++;
            }
            hits.push_back(std::move(hit));
            if (hits.size() >= top_k) break;
        }
    }

    return hits;
}

std::vector<SearchHit> search_fuzzy_text(const ContentIndex& index, const std::string& query, size_t top_k, int max_distance) {
    std::vector<SearchHit> hits;

    // Tokenize the query
    auto query_tokens = tokenize(query);
    query_tokens = remove_stop_words(query_tokens);
    if (query_tokens.empty()) return hits;

    // For each query token, find close matches in vocabulary
    const auto& vocab = index.text_store.get_vocabulary();
    std::unordered_set<int> candidate_chunks;

    for (const auto& qt : query_tokens) {
        for (const auto& [term, df] : vocab) {
            int dist = levenshtein_distance(qt.text, term);
            if (dist <= max_distance) {
                // Find chunks containing this term via inverted index search
                auto search_results = index.text_store.search(term, top_k);
                for (const auto& sr : search_results) {
                    candidate_chunks.insert(sr.chunk_id);
                }
            }
        }
    }

    // Score candidates by how well they match
    for (int chunk_id : candidate_chunks) {
        const auto* chunk = index.text_store.get_chunk(chunk_id);
        if (!chunk) continue;

        // Compute fuzzy match score
        auto chunk_tokens = tokenize(chunk->text);
        chunk_tokens = remove_stop_words(chunk_tokens);

        double best_score = 0.0;
        for (const auto& qt : query_tokens) {
            for (const auto& ct : chunk_tokens) {
                int dist = levenshtein_distance(qt.text, ct.text);
                if (dist <= max_distance) {
                    double sim = 1.0 - static_cast<double>(dist) / static_cast<double>(std::max(qt.text.size(), ct.text.size()));
                    best_score = std::max(best_score, sim);
                }
            }
        }

        if (best_score > 0.0) {
            SearchHit hit;
            hit.file_path = chunk->file_path;
            hit.relative_path = chunk->relative_path;
            hit.file_type = "text";
            hit.snippet = get_snippet(chunk->text, chunk->text.size() / 2, 200);
            hit.score = best_score;
            hit.cosine_similarity = best_score;
            hit.chunk_index = chunk->chunk_index;
            hit.start_pos = chunk->start_pos;
            hit.end_pos = chunk->end_pos;
            hit.match_type = "fuzzy";
            hit.file_size = 0;
            hit.context_snippet = get_context_snippet(chunk->text, chunk->text.size() / 2, 0, 3);
            for (const auto& fe : index.scan_result.files) {
                if (fe.path == chunk->file_path) {
                    hit.language = fe.language;
                    break;
                }
            }
            hit.line_number = 0;
            hits.push_back(std::move(hit));
        }
    }

    std::sort(hits.begin(), hits.end(),
              [](const SearchHit& a, const SearchHit& b) {
                  return a.score > b.score;
              });

    if (hits.size() > top_k) hits.resize(top_k);

    return hits;
}

std::vector<SearchHit> search_boolean(const ContentIndex& index, const std::string& query, size_t top_k) {
    std::vector<SearchHit> hits;

    // Parse boolean query: support AND, OR, NOT
    std::istringstream iss(query);
    std::string token;
    std::vector<std::string> terms;
    std::vector<std::string> operators;

    while (iss >> token) {
        std::string upper_token;
        upper_token.reserve(token.size());
        for (char c : token) upper_token += static_cast<char>(std::toupper(static_cast<unsigned char>(c)));

        if (upper_token == "AND" || upper_token == "OR" || upper_token == "NOT") {
            operators.push_back(upper_token);
        } else {
            terms.push_back(token);
        }
    }

    if (terms.empty()) return hits;

    // Get results for each term
    std::vector<std::vector<int>> term_chunk_ids;
    for (const auto& term : terms) {
        auto results = index.text_store.search(term, 1000);
        std::vector<int> ids;
        for (const auto& r : results) ids.push_back(r.chunk_id);
        term_chunk_ids.push_back(ids);
    }

    // Apply boolean logic
    std::set<int> result_ids;

    if (operators.empty() || operators[0] == "OR") {
        // Union
        for (const auto& ids : term_chunk_ids) {
            for (int id : ids) result_ids.insert(id);
        }
    } else if (operators[0] == "AND") {
        // Intersection
        if (!term_chunk_ids.empty()) {
            std::set<int> intersection;
            for (int id : term_chunk_ids[0]) intersection.insert(id);
            for (size_t i = 1; i < term_chunk_ids.size(); i++) {
                std::set<int> next;
                for (int id : term_chunk_ids[i]) {
                    if (intersection.count(id)) next.insert(id);
                }
                intersection = std::move(next);
            }
            result_ids = std::move(intersection);
        }
    } else if (operators[0] == "NOT") {
        // First term minus second term
        if (term_chunk_ids.size() >= 2) {
            std::set<int> exclude;
            for (int id : term_chunk_ids[1]) exclude.insert(id);
            for (int id : term_chunk_ids[0]) {
                if (!exclude.count(id)) result_ids.insert(id);
            }
        } else {
            for (int id : term_chunk_ids[0]) result_ids.insert(id);
        }
    }

    // Convert to hits
    for (int chunk_id : result_ids) {
        const auto* chunk = index.text_store.get_chunk(chunk_id);
        if (!chunk) continue;

        SearchHit hit;
        hit.file_path = chunk->file_path;
        hit.relative_path = chunk->relative_path;
        hit.file_type = "text";
        hit.snippet = get_snippet(chunk->text, chunk->text.size() / 2, 200);
        hit.score = 1.0;
        hit.cosine_similarity = 0.0;
        hit.chunk_index = chunk->chunk_index;
        hit.start_pos = chunk->start_pos;
        hit.end_pos = chunk->end_pos;
        hit.match_type = "boolean";
        hit.file_size = 0;
        hit.context_snippet = get_context_snippet(chunk->text, chunk->text.size() / 2, 0, 3);
        for (const auto& fe : index.scan_result.files) {
            if (fe.path == chunk->file_path) {
                hit.language = fe.language;
                break;
            }
        }
        hit.line_number = 0;
        hits.push_back(std::move(hit));
        if (hits.size() >= top_k) break;
    }

    return hits;
}

SearchResults search_universal(const ContentIndex& index, const std::string& query, size_t top_k) {
    auto start = std::chrono::steady_clock::now();

    SearchResults results;
    results.query = query;

    // Content search (TF-IDF)
    results.text_hits = search_text(index, query, top_k);

    // Exact phrase search
    auto phrase_hits = search_exact_phrase(index, query, top_k);
    // Merge phrase hits into text hits if not already present
    for (auto& ph : phrase_hits) {
        bool found = false;
        for (const auto& th : results.text_hits) {
            if (th.file_path == ph.file_path && th.chunk_index == ph.chunk_index) {
                found = true;
                break;
            }
        }
        if (!found) results.text_hits.push_back(std::move(ph));
    }

    // Fuzzy search
    auto fuzzy_hits = search_fuzzy_text(index, query, top_k);
    for (auto& fh : fuzzy_hits) {
        bool found = false;
        for (const auto& th : results.text_hits) {
            if (th.file_path == fh.file_path && th.chunk_index == fh.chunk_index) {
                found = true;
                break;
            }
        }
        if (!found) results.text_hits.push_back(std::move(fh));
    }

    // Boolean search
    auto bool_hits = search_boolean(index, query, top_k);
    for (auto& bh : bool_hits) {
        bool found = false;
        for (const auto& th : results.text_hits) {
            if (th.file_path == bh.file_path && th.chunk_index == bh.chunk_index) {
                found = true;
                break;
            }
        }
        if (!found) results.text_hits.push_back(std::move(bh));
    }

    // Sort text hits by score
    std::sort(results.text_hits.begin(), results.text_hits.end(),
              [](const SearchHit& a, const SearchHit& b) { return a.score > b.score; });
    if (results.text_hits.size() > top_k * 3) results.text_hits.resize(top_k * 3);

    // Image search
    results.image_hits = search_image_by_hash(index, query);
    if (results.image_hits.empty()) {
        try {
            auto bytes = read_file_to_bytes(query);
            if (!bytes.empty()) {
                results.image_hits = search_similar_images(index, query);
            }
        } catch (...) {
        }
    }

    // Filename search
    results.filename_hits = search_by_filename(index, query, top_k);

    // Path search
    results.path_hits = search_by_path(index, query, top_k);

    results.total_hits = results.text_hits.size() + results.image_hits.size() +
                         results.filename_hits.size() + results.path_hits.size();

    auto end = std::chrono::steady_clock::now();
    results.search_time_ms = static_cast<double>(
        std::chrono::duration_cast<std::chrono::microseconds>(end - start).count()
    ) / 1000.0;

    return results;
}

std::vector<SearchHit> search_related_files(const ContentIndex& index, const std::string& file_path, size_t top_k) {
    std::vector<SearchHit> hits;

    // Find the source file entry
    const FileEntry* source_fe = nullptr;
    std::string normalized_target = normalize_path(file_path);
    for (const auto& fe : index.scan_result.files) {
        if (normalize_path(fe.path) == normalized_target ||
            normalize_path(fe.relative_path) == normalized_target ||
            fe.filename == file_path) {
            source_fe = &fe;
            break;
        }
    }

    if (!source_fe || source_fe->imports.empty()) return hits;

    // For each import, find files that match
    for (const auto& imp : source_fe->imports) {
        for (const auto& fe : index.scan_result.files) {
            // Match by filename containing the import string
            std::string norm_filename = fe.filename;
            std::string norm_imp = imp;
            // Remove common path prefixes from import
            size_t last_sep = norm_imp.find_last_of("/\\");
            if (last_sep != std::string::npos) norm_imp = norm_imp.substr(last_sep + 1);

            if (contains_ci(norm_filename, norm_imp) || contains_ci(fe.relative_path, imp)) {
                // Don't include self
                if (fe.path == source_fe->path) continue;

                SearchHit hit = make_filename_hit(fe, 0.8);
                hit.match_type = "related";
                hit.snippet = "Related via import: " + imp;
                hits.push_back(std::move(hit));
                if (hits.size() >= top_k) return hits;
            }
        }
    }

    // Also find files that import this file
    std::string source_filename = source_fe->filename;
    // Remove extension for matching
    std::string source_base = source_filename;
    size_t dot = source_base.find_last_of('.');
    if (dot != std::string::npos) source_base = source_base.substr(0, dot);

    for (const auto& fe : index.scan_result.files) {
        if (fe.path == source_fe->path) continue;
        for (const auto& imp : fe.imports) {
            if (contains_ci(imp, source_base) || contains_ci(imp, source_filename)) {
                SearchHit hit = make_filename_hit(fe, 0.6);
                hit.match_type = "related_reverse";
                hit.snippet = "Imports this file: " + imp;
                hits.push_back(std::move(hit));
                if (hits.size() >= top_k) return hits;
                break;
            }
        }
    }

    return hits;
}

// ---------- Regex Search ----------

std::vector<SearchHit> search_regex(const ContentIndex& index, const std::string& pattern, size_t top_k) {
    std::vector<SearchHit> hits;

    for (const auto& fe : index.scan_result.files) {
        if (fe.type != FileType::TEXT) continue;

        try {
            std::string content = read_file_to_string(fe.path);
            auto matches = regex_search(content, pattern, 10);

            if (matches.empty()) continue;

            for (const auto& m : matches) {
                SearchHit hit;
                hit.file_path = fe.path;
                hit.relative_path = fe.relative_path;
                hit.file_type = "text";
                hit.snippet = get_snippet(content, m.position, 100);
                hit.score = 1.0;
                hit.cosine_similarity = 0.0;
                hit.chunk_index = 0;
                hit.start_pos = m.position;
                hit.end_pos = m.position + m.length;
                hit.match_type = "regex";
                hit.file_size = fe.size;
                hit.language = fe.language;
                hit.context_snippet = get_context_snippet(content, m.position, m.length);
                hit.line_number = 0;
                size_t line_start = 0;
                for (size_t i = 0; i < m.position && i < content.size(); i++) {
                    if (content[i] == '\n') { line_start = i + 1; hit.line_number++; }
                }
                hit.line_number++;

                hits.push_back(std::move(hit));
                if (hits.size() >= top_k) return hits;
            }
        } catch (...) {}
    }

    return hits;
}

// ---------- Synonym-Enhanced Search ----------

std::vector<SearchHit> search_with_synonyms(const ContentIndex& index, const std::string& query, size_t top_k) {
    std::string expanded = expand_query_with_synonyms(query);
    auto hits = search_text(index, expanded, top_k);

    for (auto& hit : hits) {
        hit.match_type = "synonym";
    }

    return hits;
}

// ---------- BM25 Search ----------

std::vector<SearchHit> search_bm25(const ContentIndex& index, const std::string& query, size_t top_k) {
    std::vector<SearchHit> hits;
    auto results = index.text_store.search_bm25(query, top_k);

    for (const auto& result : results) {
        const auto* chunk = index.text_store.get_chunk(result.chunk_id);
        if (!chunk) continue;

        SearchHit hit;
        hit.file_path = chunk->file_path;
        hit.relative_path = chunk->relative_path;
        hit.file_type = "text";
        hit.snippet = get_snippet(chunk->text, 0, 150);
        hit.score = result.score;
        hit.cosine_similarity = result.cosine_similarity;
        hit.chunk_index = chunk->chunk_index;
        hit.start_pos = chunk->start_pos;
        hit.end_pos = chunk->end_pos;
        hit.match_type = "bm25";
        hit.file_size = 0;

        for (const auto& fe : index.scan_result.files) {
            if (fe.path == chunk->file_path) {
                hit.file_size = fe.size;
                hit.language = fe.language;
                break;
            }
        }

        hit.context_snippet = get_context_snippet(chunk->text, 0, 0);
        hit.line_number = 0;

        hits.push_back(std::move(hit));
    }

    return hits;
}

} // namespace aisearch
