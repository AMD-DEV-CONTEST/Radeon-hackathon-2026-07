#pragma once

#include "file_mapper.h"
#include "vector_store.h"
#include "image_hasher.h"
#include <string>
#include <vector>
#include <unordered_map>
#include <functional>

namespace aisearch {

// Indexed image entry
struct IndexedImage {
    std::string       file_path;
    std::string       relative_path;
    ImageFingerprint  fingerprint;
    uintmax_t         size;
};

// The content index combining text and image data
struct ContentIndex {
    ScanResult                  scan_result;
    VectorStore                 text_store;
    std::vector<IndexedImage>   images;
    std::unordered_map<std::string, int> base64_to_image; // base64_hash -> index in images

    // Statistics
    size_t total_chunks;
    size_t total_images_indexed;
    size_t total_text_indexed;
    size_t index_build_time_ms;
};

// Index all files in a directory
// - Scans the directory
// - Indexes text files into the vector store (chunked, TF-IDF)
// - Fingerprints all image files
ContentIndex index_directory(const std::string& root_path, bool include_hidden = false);

// Index a directory with progress reporting (0-100). Used for manual RAG folder sync.
// progress_cb is called periodically as files are processed (may be called from a
// background thread — caller is responsible for marshaling to UI thread if needed).
ContentIndex index_directory_with_progress(const std::string& root_path, bool include_hidden,
                                            const std::function<void(int)>& progress_cb);

// Index with .gitignore support
ContentIndex index_directory_with_gitignore(const std::string& root_path, bool include_hidden = false);

// Multi-threaded indexing
ContentIndex index_directory_mt(const std::string& root_path, bool include_hidden = false, size_t num_threads = 0);

// Save/load persistent index
bool save_index(const ContentIndex& index, const std::string& filepath);
ContentIndex load_index(const std::string& filepath);

// Find an image by its base64 hash (exact match)
const IndexedImage* find_image_by_base64(const ContentIndex& index, const std::string& base64_hash);

// Find similar images by perceptual hash
std::vector<const IndexedImage*> find_similar_images(const ContentIndex& index, const std::string& base64_hash, int max_distance = 10);

// Find similar images by providing an image file path
std::vector<const IndexedImage*> find_similar_images_by_file(const ContentIndex& index, const std::string& image_path, int max_distance = 10);

} // namespace aisearch
