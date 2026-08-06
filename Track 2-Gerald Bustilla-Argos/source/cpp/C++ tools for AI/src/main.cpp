#include "text_utils.h"
#include "file_mapper.h"
#include "image_hasher.h"
#include "vector_store.h"
#include "content_indexer.h"
#include "search_engine.h"
#include "json_writer.h"

#include <iostream>
#include <string>
#include <vector>
#include <chrono>

using namespace aisearch;

static void print_usage() {
    std::cerr << R"USAGE(AI Search Tool - Vectorized File Content Search for AI
=====================================================

USAGE:
  aisearch <command> [options]

COMMANDS:
  map <directory> [--hidden]
      Map all files and folders in a directory.
      Outputs JSON with file metadata (path, size, type, modified time).

  index <directory> [--hidden]
      Index a directory: scan files, index text content (TF-IDF vectors),
      and fingerprint all images (base64 hash + perceptual hash).
      Outputs JSON with full index statistics.

  search <directory> --query "<text>" [--top-k N] [--hidden]
      Search text content using RAG-style vector retrieval.
      Returns ranked text chunks with snippets and cosine similarity scores.

  search-image <directory> --hash "<base64_hash>"
      Find an image by its exact base64 hash.

  search-similar <directory> --image "<path>" [--max-distance N]
      Find images similar to the given image file using perceptual hashing.

  search-all <directory> --query "<text>" [--top-k N] [--hidden]
      Combined search: searches text content, images, filenames, and paths.

  search-universal <directory> --query "<text>" [--top-k N] [--hidden]
      Universal search: tries all search modes (TF-IDF, exact phrase, fuzzy,
      boolean, filename, path, image) and combines results.

  search-filename <directory> --query "<pattern>" [--top-k N]
      Search by filename pattern (case-insensitive substring match).

  search-path <directory> --query "<pattern>" [--top-k N]
      Search by file path pattern (case-insensitive substring match).

  search-ext <directory> --query "<extension>" [--top-k N]
      Search by file extension (e.g. "cpp", ".py", "json").

  search-size <directory> --min <bytes> --max <bytes> [--top-k N]
      Filter files by size range in bytes.

  search-phrase <directory> --query "<phrase>" [--top-k N]
      Exact phrase search (find exact substring in text content).

  search-fuzzy <directory> --query "<text>" [--top-k N] [--max-distance N]
      Fuzzy text search using Levenshtein edit distance.

  search-boolean <directory> --query "<text>" [--top-k N]
      Boolean search with AND, OR, NOT operators.
      Example: "database AND authentication NOT redis"

  search-related <directory> --query "<file_path>" [--top-k N]
      Find files related to a given file by import/include references.
      Uses file relationship tracking to find dependencies.

  search-regex <directory> --query "<pattern>" [--top-k N]
      Regex pattern search in text content. Uses std::regex syntax.
      Example: "function\s+\w+\(.*\)" finds function declarations.

  search-synonyms <directory> --query "<text>" [--top-k N]
      Synonym-enhanced search. Expands query with programming-domain synonyms.
      Example: "auth" also searches for "authentication", "login", "credentials".

  search-bm25 <directory> --query "<text>" [--top-k N]
      BM25 scoring search (better relevance ranking than TF-IDF).

  save-index <directory> --output <filepath> [--hidden]
      Save a persistent index to a JSON file for later reuse.

  load-index <filepath>
      Load a previously saved index from a JSON file.
      Outputs the full index map JSON.

  index-mt <directory> [--hidden] [--threads N]
      Multi-threaded indexing. Uses all CPU cores by default.

  index-gitignore <directory> [--hidden]
      Index with .gitignore support. Respects .gitignore patterns.

  full-map <directory> [--hidden]
      Output the complete index as JSON: files, directories, text chunks,
      and image fingerprints. This is the main output for AI consumption.

  fingerprint <image_path>
      Compute and display the fingerprint of a single image file.

  stats <directory> [--hidden]
      Show index statistics only (counts, sizes, build time).

OPTIONS:
  --hidden            Include hidden files/directories (starting with .)
  --query <text>      Search query string
  --top-k <N>         Number of top results to return (default: 10)
  --hash <hash>       Base64 hash for exact image search
  --image <path>      Image file path for similar image search
  --max-distance <N>  Max hamming/edit distance (default: 10 for images, 2 for fuzzy)
  --min <bytes>       Minimum file size in bytes
  --max <bytes>       Maximum file size in bytes
  --output <filepath> Output file path for save-index
  --threads <N>       Number of threads for multi-threaded indexing

EXAMPLES:
  aisearch map ./my-project
  aisearch index ./my-project --hidden
  aisearch search ./my-project --query "error handling in authentication"
  aisearch search-image ./images --hash "iVBORw0KGgo="
  aisearch search-similar ./images --image ./test.png --max-distance 15
  aisearch search-filename ./my-project --query "config"
  aisearch search-path ./my-project --query "src/utils"
  aisearch search-ext ./my-project --query "cpp"
  aisearch search-size ./my-project --min 1000 --max 50000
  aisearch search-phrase ./my-project --query "TODO fix this"
  aisearch search-fuzzy ./my-project --query "autentication" --max-distance 2
  aisearch search-boolean ./my-project --query "database AND authentication NOT redis"
  aisearch search-related ./my-project --query "src/auth/service.cpp"
  aisearch search-universal ./my-project --query "config parser"
  aisearch full-map ./my-project > index.json
  aisearch fingerprint ./photo.jpg
)USAGE";
}

static std::string get_arg(int argc, char* argv[], int& i, const std::string& flag) {
    if (i + 1 < argc) {
        return argv[++i];
    }
    std::cerr << "Error: Missing value for " << flag << std::endl;
    return "";
}

static bool has_flag(int argc, char* argv[], const std::string& flag) {
    for (int i = 0; i < argc; i++) {
        if (std::string(argv[i]) == flag) return true;
    }
    return false;
}

int main(int argc, char* argv[]) {
    if (argc < 2) {
        print_usage();
        return 1;
    }

    std::string command = argv[1];

    if (command == "--help" || command == "-h" || command == "help") {
        print_usage();
        return 0;
    }

    if (command == "fingerprint") {
        if (argc < 3) {
            std::cerr << "Error: fingerprint requires an image path" << std::endl;
            return 1;
        }
        try {
            auto fp = fingerprint_image(argv[2]);
            std::cout << image_fingerprint_to_json(fp) << std::endl;
        } catch (const std::exception& e) {
            std::cerr << "Error: " << e.what() << std::endl;
            return 1;
        }
        return 0;
    }

    // All other commands require a directory
    if (argc < 3) {
        std::cerr << "Error: " << command << " requires a directory path" << std::endl;
        return 1;
    }

    std::string directory = argv[2];
    bool include_hidden = has_flag(argc, argv, "--hidden");

    // Parse common options
    std::string query;
    std::string hash_value;
    std::string image_path;
    std::string output_file;
    size_t top_k = 10;
    int max_distance = 10;
    uintmax_t min_size = 0;
    uintmax_t max_size = UINTMAX_MAX;
    size_t num_threads = 0;

    for (int i = 3; i < argc; i++) {
        std::string arg = argv[i];
        if (arg == "--query" && i + 1 < argc) {
            query = argv[++i];
        } else if (arg == "--hash" && i + 1 < argc) {
            hash_value = argv[++i];
        } else if (arg == "--image" && i + 1 < argc) {
            image_path = argv[++i];
        } else if (arg == "--output" && i + 1 < argc) {
            output_file = argv[++i];
        } else if (arg == "--top-k" && i + 1 < argc) {
            top_k = static_cast<size_t>(std::stoul(argv[++i]));
        } else if (arg == "--max-distance" && i + 1 < argc) {
            max_distance = std::stoi(argv[++i]);
        } else if (arg == "--min" && i + 1 < argc) {
            min_size = std::stoull(argv[++i]);
        } else if (arg == "--max" && i + 1 < argc) {
            max_size = std::stoull(argv[++i]);
        } else if (arg == "--threads" && i + 1 < argc) {
            num_threads = static_cast<size_t>(std::stoul(argv[++i]));
        } else if (arg == "--hidden") {
            // Already handled
        } else {
            std::cerr << "Warning: Unknown option: " << arg << std::endl;
        }
    }

    try {
        if (command == "map") {
            auto result = scan_directory_with_hashes(directory, include_hidden);
            std::cout << scan_result_to_json(result) << std::endl;
        }
        else if (command == "index") {
            auto index = index_directory(directory, include_hidden);
            std::cout << content_index_to_json(index) << std::endl;
        }
        else if (command == "search") {
            if (query.empty()) {
                std::cerr << "Error: search requires --query" << std::endl;
                return 1;
            }
            auto index = index_directory(directory, include_hidden);
            auto hits = search_text(index, query, top_k);
            std::cout << "{\"query\":\"" << json_escape(query) << "\",";
            std::cout << "\"total_hits\":" << hits.size() << ",\"text_hits\":[";
            for (size_t i = 0; i < hits.size(); i++) {
                if (i > 0) std::cout << ",";
                const auto& hit = hits[i];
                std::cout << "{";
                std::cout << "\"file_path\":\"" << json_escape(hit.file_path) << "\",";
                std::cout << "\"relative_path\":\"" << json_escape(hit.relative_path) << "\",";
                std::cout << "\"snippet\":\"" << json_escape(hit.snippet) << "\",";
                std::cout << "\"score\":" << hit.score << ",";
                std::cout << "\"cosine_similarity\":" << hit.cosine_similarity << ",";
                std::cout << "\"chunk_index\":" << hit.chunk_index << ",";
                std::cout << "\"start_pos\":" << hit.start_pos << ",";
                std::cout << "\"end_pos\":" << hit.end_pos << ",";
                std::cout << "\"match_type\":\"" << json_escape(hit.match_type) << "\"";
                if (!hit.context_snippet.empty())
                    std::cout << ",\"context_snippet\":\"" << json_escape(hit.context_snippet) << "\"";
                if (!hit.language.empty())
                    std::cout << ",\"language\":\"" << json_escape(hit.language) << "\"";
                if (hit.line_number > 0)
                    std::cout << ",\"line_number\":" << hit.line_number;
                std::cout << "}";
            }
            std::cout << "]}" << std::endl;
        }
        else if (command == "search-image") {
            if (hash_value.empty()) {
                std::cerr << "Error: search-image requires --hash" << std::endl;
                return 1;
            }
            auto index = index_directory(directory, include_hidden);
            auto hits = search_image_by_hash(index, hash_value);
            std::cout << "{\"hash\":\"" << json_escape(hash_value) << "\",";
            std::cout << "\"total_hits\":" << hits.size() << ",\"image_hits\":[";
            for (size_t i = 0; i < hits.size(); i++) {
                if (i > 0) std::cout << ",";
                const auto& hit = hits[i];
                std::cout << "{";
                std::cout << "\"file_path\":\"" << json_escape(hit.file_path) << "\",";
                std::cout << "\"relative_path\":\"" << json_escape(hit.relative_path) << "\",";
                std::cout << "\"base64_hash\":\"" << json_escape(hit.base64_hash) << "\",";
                std::cout << "\"perceptual_hash\":\"" << json_escape(hit.perceptual_hex) << "\"";
                std::cout << "}";
            }
            std::cout << "]}" << std::endl;
        }
        else if (command == "search-similar") {
            if (image_path.empty()) {
                std::cerr << "Error: search-similar requires --image" << std::endl;
                return 1;
            }
            auto index = index_directory(directory, include_hidden);
            auto hits = search_similar_images(index, image_path, max_distance);
            std::cout << "{\"source_image\":\"" << json_escape(image_path) << "\",";
            std::cout << "\"max_distance\":" << max_distance << ",";
            std::cout << "\"total_hits\":" << hits.size() << ",\"similar_images\":[";
            for (size_t i = 0; i < hits.size(); i++) {
                if (i > 0) std::cout << ",";
                const auto& hit = hits[i];
                std::cout << "{";
                std::cout << "\"file_path\":\"" << json_escape(hit.file_path) << "\",";
                std::cout << "\"relative_path\":\"" << json_escape(hit.relative_path) << "\",";
                std::cout << "\"score\":" << hit.score << ",";
                std::cout << "\"base64_hash\":\"" << json_escape(hit.base64_hash) << "\",";
                std::cout << "\"perceptual_hash\":\"" << json_escape(hit.perceptual_hex) << "\",";
                std::cout << "\"hamming_distance\":" << hit.hamming_distance;
                std::cout << "}";
            }
            std::cout << "]}" << std::endl;
        }
        else if (command == "search-all") {
            if (query.empty()) {
                std::cerr << "Error: search-all requires --query" << std::endl;
                return 1;
            }
            auto index = index_directory(directory, include_hidden);
            auto results = search_all(index, query, top_k);
            std::cout << search_results_to_json(results) << std::endl;
        }
        else if (command == "search-universal") {
            if (query.empty()) {
                std::cerr << "Error: search-universal requires --query" << std::endl;
                return 1;
            }
            auto index = index_directory(directory, include_hidden);
            auto results = search_universal(index, query, top_k);
            std::cout << search_results_to_json(results) << std::endl;
        }
        else if (command == "search-filename") {
            if (query.empty()) {
                std::cerr << "Error: search-filename requires --query" << std::endl;
                return 1;
            }
            auto index = index_directory(directory, include_hidden);
            auto hits = search_by_filename(index, query, top_k);
            std::cout << "{\"query\":\"" << json_escape(query) << "\",";
            std::cout << "\"total_hits\":" << hits.size() << ",\"filename_hits\":[";
            for (size_t i = 0; i < hits.size(); i++) {
                if (i > 0) std::cout << ",";
                const auto& hit = hits[i];
                std::cout << "{";
                std::cout << "\"file_path\":\"" << json_escape(hit.file_path) << "\",";
                std::cout << "\"relative_path\":\"" << json_escape(hit.relative_path) << "\",";
                std::cout << "\"file_type\":\"" << json_escape(hit.file_type) << "\",";
                std::cout << "\"score\":" << hit.score << ",";
                std::cout << "\"file_size\":" << hit.file_size;
                std::cout << "}";
            }
            std::cout << "]}" << std::endl;
        }
        else if (command == "search-path") {
            if (query.empty()) {
                std::cerr << "Error: search-path requires --query" << std::endl;
                return 1;
            }
            auto index = index_directory(directory, include_hidden);
            auto hits = search_by_path(index, query, top_k);
            std::cout << "{\"query\":\"" << json_escape(query) << "\",";
            std::cout << "\"total_hits\":" << hits.size() << ",\"path_hits\":[";
            for (size_t i = 0; i < hits.size(); i++) {
                if (i > 0) std::cout << ",";
                const auto& hit = hits[i];
                std::cout << "{";
                std::cout << "\"file_path\":\"" << json_escape(hit.file_path) << "\",";
                std::cout << "\"relative_path\":\"" << json_escape(hit.relative_path) << "\",";
                std::cout << "\"file_type\":\"" << json_escape(hit.file_type) << "\",";
                std::cout << "\"score\":" << hit.score << ",";
                std::cout << "\"file_size\":" << hit.file_size;
                std::cout << "}";
            }
            std::cout << "]}" << std::endl;
        }
        else if (command == "search-ext") {
            if (query.empty()) {
                std::cerr << "Error: search-ext requires --query" << std::endl;
                return 1;
            }
            auto index = index_directory(directory, include_hidden);
            auto hits = search_by_extension(index, query, top_k);
            std::cout << "{\"query\":\"" << json_escape(query) << "\",";
            std::cout << "\"total_hits\":" << hits.size() << ",\"extension_hits\":[";
            for (size_t i = 0; i < hits.size(); i++) {
                if (i > 0) std::cout << ",";
                const auto& hit = hits[i];
                std::cout << "{";
                std::cout << "\"file_path\":\"" << json_escape(hit.file_path) << "\",";
                std::cout << "\"relative_path\":\"" << json_escape(hit.relative_path) << "\",";
                std::cout << "\"file_type\":\"" << json_escape(hit.file_type) << "\",";
                std::cout << "\"file_size\":" << hit.file_size;
                std::cout << "}";
            }
            std::cout << "]}" << std::endl;
        }
        else if (command == "search-size") {
            auto index = index_directory(directory, include_hidden);
            auto hits = search_by_size_range(index, min_size, max_size, top_k);
            std::cout << "{\"min_size\":" << min_size << ",\"max_size\":" << max_size << ",";
            std::cout << "\"total_hits\":" << hits.size() << ",\"size_hits\":[";
            for (size_t i = 0; i < hits.size(); i++) {
                if (i > 0) std::cout << ",";
                const auto& hit = hits[i];
                std::cout << "{";
                std::cout << "\"file_path\":\"" << json_escape(hit.file_path) << "\",";
                std::cout << "\"relative_path\":\"" << json_escape(hit.relative_path) << "\",";
                std::cout << "\"file_type\":\"" << json_escape(hit.file_type) << "\",";
                std::cout << "\"file_size\":" << hit.file_size;
                std::cout << "}";
            }
            std::cout << "]}" << std::endl;
        }
        else if (command == "search-phrase") {
            if (query.empty()) {
                std::cerr << "Error: search-phrase requires --query" << std::endl;
                return 1;
            }
            auto index = index_directory(directory, include_hidden);
            auto hits = search_exact_phrase(index, query, top_k);
            std::cout << "{\"query\":\"" << json_escape(query) << "\",";
            std::cout << "\"total_hits\":" << hits.size() << ",\"phrase_hits\":[";
            for (size_t i = 0; i < hits.size(); i++) {
                if (i > 0) std::cout << ",";
                const auto& hit = hits[i];
                std::cout << "{";
                std::cout << "\"file_path\":\"" << json_escape(hit.file_path) << "\",";
                std::cout << "\"relative_path\":\"" << json_escape(hit.relative_path) << "\",";
                std::cout << "\"snippet\":\"" << json_escape(hit.snippet) << "\",";
                std::cout << "\"chunk_index\":" << hit.chunk_index << ",";
                std::cout << "\"start_pos\":" << hit.start_pos << ",";
                std::cout << "\"end_pos\":" << hit.end_pos << ",";
                std::cout << "\"match_type\":\"" << json_escape(hit.match_type) << "\"";
                if (!hit.context_snippet.empty())
                    std::cout << ",\"context_snippet\":\"" << json_escape(hit.context_snippet) << "\"";
                if (!hit.language.empty())
                    std::cout << ",\"language\":\"" << json_escape(hit.language) << "\"";
                if (hit.line_number > 0)
                    std::cout << ",\"line_number\":" << hit.line_number;
                std::cout << "}";
            }
            std::cout << "]}" << std::endl;
        }
        else if (command == "search-fuzzy") {
            if (query.empty()) {
                std::cerr << "Error: search-fuzzy requires --query" << std::endl;
                return 1;
            }
            auto index = index_directory(directory, include_hidden);
            auto hits = search_fuzzy_text(index, query, top_k, max_distance);
            std::cout << "{\"query\":\"" << json_escape(query) << "\",";
            std::cout << "\"max_distance\":" << max_distance << ",";
            std::cout << "\"total_hits\":" << hits.size() << ",\"fuzzy_hits\":[";
            for (size_t i = 0; i < hits.size(); i++) {
                if (i > 0) std::cout << ",";
                const auto& hit = hits[i];
                std::cout << "{";
                std::cout << "\"file_path\":\"" << json_escape(hit.file_path) << "\",";
                std::cout << "\"relative_path\":\"" << json_escape(hit.relative_path) << "\",";
                std::cout << "\"snippet\":\"" << json_escape(hit.snippet) << "\",";
                std::cout << "\"score\":" << hit.score << ",";
                std::cout << "\"chunk_index\":" << hit.chunk_index << ",";
                std::cout << "\"match_type\":\"" << json_escape(hit.match_type) << "\"";
                if (!hit.context_snippet.empty())
                    std::cout << ",\"context_snippet\":\"" << json_escape(hit.context_snippet) << "\"";
                if (!hit.language.empty())
                    std::cout << ",\"language\":\"" << json_escape(hit.language) << "\"";
                std::cout << "}";
            }
            std::cout << "]}" << std::endl;
        }
        else if (command == "search-boolean") {
            if (query.empty()) {
                std::cerr << "Error: search-boolean requires --query" << std::endl;
                return 1;
            }
            auto index = index_directory(directory, include_hidden);
            auto hits = search_boolean(index, query, top_k);
            std::cout << "{\"query\":\"" << json_escape(query) << "\",";
            std::cout << "\"total_hits\":" << hits.size() << ",\"boolean_hits\":[";
            for (size_t i = 0; i < hits.size(); i++) {
                if (i > 0) std::cout << ",";
                const auto& hit = hits[i];
                std::cout << "{";
                std::cout << "\"file_path\":\"" << json_escape(hit.file_path) << "\",";
                std::cout << "\"relative_path\":\"" << json_escape(hit.relative_path) << "\",";
                std::cout << "\"snippet\":\"" << json_escape(hit.snippet) << "\",";
                std::cout << "\"chunk_index\":" << hit.chunk_index << ",";
                std::cout << "\"match_type\":\"" << json_escape(hit.match_type) << "\"";
                if (!hit.context_snippet.empty())
                    std::cout << ",\"context_snippet\":\"" << json_escape(hit.context_snippet) << "\"";
                if (!hit.language.empty())
                    std::cout << ",\"language\":\"" << json_escape(hit.language) << "\"";
                std::cout << "}";
            }
            std::cout << "]}" << std::endl;
        }
        else if (command == "search-related") {
            if (query.empty()) {
                std::cerr << "Error: search-related requires --query (file path)" << std::endl;
                return 1;
            }
            auto index = index_directory(directory, include_hidden);
            auto hits = search_related_files(index, query, top_k);
            std::cout << "{\"source_file\":\"" << json_escape(query) << "\",";
            std::cout << "\"total_hits\":" << hits.size() << ",\"related_files\":[";
            for (size_t i = 0; i < hits.size(); i++) {
                if (i > 0) std::cout << ",";
                const auto& hit = hits[i];
                std::cout << "{";
                std::cout << "\"file_path\":\"" << json_escape(hit.file_path) << "\",";
                std::cout << "\"relative_path\":\"" << json_escape(hit.relative_path) << "\",";
                std::cout << "\"match_type\":\"" << json_escape(hit.match_type) << "\",";
                std::cout << "\"snippet\":\"" << json_escape(hit.snippet) << "\",";
                std::cout << "\"score\":" << hit.score;
                std::cout << "}";
            }
            std::cout << "]}" << std::endl;
        }
        else if (command == "search-regex") {
            if (query.empty()) {
                std::cerr << "Error: search-regex requires --query (regex pattern)" << std::endl;
                return 1;
            }
            auto index = index_directory(directory, include_hidden);
            auto hits = search_regex(index, query, top_k);
            std::cout << "{\"pattern\":\"" << json_escape(query) << "\",";
            std::cout << "\"total_hits\":" << hits.size() << ",\"regex_hits\":[";
            for (size_t i = 0; i < hits.size(); i++) {
                if (i > 0) std::cout << ",";
                const auto& hit = hits[i];
                std::cout << "{";
                std::cout << "\"file_path\":\"" << json_escape(hit.file_path) << "\",";
                std::cout << "\"relative_path\":\"" << json_escape(hit.relative_path) << "\",";
                std::cout << "\"snippet\":\"" << json_escape(hit.snippet) << "\",";
                std::cout << "\"start_pos\":" << hit.start_pos << ",";
                std::cout << "\"end_pos\":" << hit.end_pos << ",";
                std::cout << "\"match_type\":\"" << json_escape(hit.match_type) << "\"";
                if (!hit.context_snippet.empty())
                    std::cout << ",\"context_snippet\":\"" << json_escape(hit.context_snippet) << "\"";
                if (!hit.language.empty())
                    std::cout << ",\"language\":\"" << json_escape(hit.language) << "\"";
                if (hit.line_number > 0)
                    std::cout << ",\"line_number\":" << hit.line_number;
                std::cout << "}";
            }
            std::cout << "]}" << std::endl;
        }
        else if (command == "search-synonyms") {
            if (query.empty()) {
                std::cerr << "Error: search-synonyms requires --query" << std::endl;
                return 1;
            }
            auto index = index_directory(directory, include_hidden);
            auto hits = search_with_synonyms(index, query, top_k);
            std::cout << "{\"query\":\"" << json_escape(query) << "\",";
            std::cout << "\"total_hits\":" << hits.size() << ",\"synonym_hits\":[";
            for (size_t i = 0; i < hits.size(); i++) {
                if (i > 0) std::cout << ",";
                const auto& hit = hits[i];
                std::cout << "{";
                std::cout << "\"file_path\":\"" << json_escape(hit.file_path) << "\",";
                std::cout << "\"relative_path\":\"" << json_escape(hit.relative_path) << "\",";
                std::cout << "\"snippet\":\"" << json_escape(hit.snippet) << "\",";
                std::cout << "\"score\":" << hit.score << ",";
                std::cout << "\"match_type\":\"" << json_escape(hit.match_type) << "\"";
                if (!hit.context_snippet.empty())
                    std::cout << ",\"context_snippet\":\"" << json_escape(hit.context_snippet) << "\"";
                if (!hit.language.empty())
                    std::cout << ",\"language\":\"" << json_escape(hit.language) << "\"";
                std::cout << "}";
            }
            std::cout << "]}" << std::endl;
        }
        else if (command == "search-bm25") {
            if (query.empty()) {
                std::cerr << "Error: search-bm25 requires --query" << std::endl;
                return 1;
            }
            auto index = index_directory(directory, include_hidden);
            auto hits = search_bm25(index, query, top_k);
            std::cout << "{\"query\":\"" << json_escape(query) << "\",";
            std::cout << "\"total_hits\":" << hits.size() << ",\"bm25_hits\":[";
            for (size_t i = 0; i < hits.size(); i++) {
                if (i > 0) std::cout << ",";
                const auto& hit = hits[i];
                std::cout << "{";
                std::cout << "\"file_path\":\"" << json_escape(hit.file_path) << "\",";
                std::cout << "\"relative_path\":\"" << json_escape(hit.relative_path) << "\",";
                std::cout << "\"snippet\":\"" << json_escape(hit.snippet) << "\",";
                std::cout << "\"score\":" << hit.score << ",";
                std::cout << "\"match_type\":\"" << json_escape(hit.match_type) << "\"";
                if (!hit.context_snippet.empty())
                    std::cout << ",\"context_snippet\":\"" << json_escape(hit.context_snippet) << "\"";
                if (!hit.language.empty())
                    std::cout << ",\"language\":\"" << json_escape(hit.language) << "\"";
                std::cout << "}";
            }
            std::cout << "]}" << std::endl;
        }
        else if (command == "save-index") {
            if (output_file.empty()) {
                std::cerr << "Error: save-index requires --output <filepath>" << std::endl;
                return 1;
            }
            auto index = index_directory(directory, include_hidden);
            bool ok = save_index(index, output_file);
            std::cout << "{\"saved\":" << (ok ? "true" : "false") << ",";
            std::cout << "\"filepath\":\"" << json_escape(output_file) << "\",";
            std::cout << "\"total_files\":" << index.scan_result.total_files << ",";
            std::cout << "\"total_chunks\":" << index.total_chunks << "}" << std::endl;
        }
        else if (command == "load-index") {
            std::string json = load_index_from_file(directory);
            if (json.empty()) {
                std::cerr << "Error: Failed to load index from " << directory << std::endl;
                return 1;
            }
            std::cout << json << std::endl;
        }
        else if (command == "index-mt") {
            auto index = index_directory_mt(directory, include_hidden, num_threads);
            std::cout << content_index_to_json(index) << std::endl;
        }
        else if (command == "index-gitignore") {
            auto index = index_directory_with_gitignore(directory, include_hidden);
            std::cout << content_index_to_json(index) << std::endl;
        }
        else if (command == "full-map") {
            auto index = index_directory(directory, include_hidden);
            std::cout << full_index_map_to_json(index) << std::endl;
        }
        else if (command == "stats") {
            auto index = index_directory(directory, include_hidden);
            std::cout << content_index_to_json(index) << std::endl;
        }
        else {
            std::cerr << "Error: Unknown command: " << command << std::endl;
            print_usage();
            return 1;
        }
    } catch (const std::exception& e) {
        std::cerr << "Error: " << e.what() << std::endl;
        return 1;
    }

    return 0;
}
