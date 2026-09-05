#include "content_indexer.h"
#include "text_utils.h"
#include "json_writer.h"
#include <chrono>
#include <iostream>
#include <thread>
#include <mutex>
#include <future>
#include <fstream>
#include <sstream>

namespace aisearch {

ContentIndex index_directory(const std::string& root_path, bool include_hidden) {
    auto start = std::chrono::steady_clock::now();

    ContentIndex index;
    index.total_chunks = 0;
    index.total_images_indexed = 0;
    index.total_text_indexed = 0;

    // Step 1: Scan the directory
    index.scan_result = scan_directory(root_path, include_hidden);

    // Step 2: Index text files
    for (const auto& fe : index.scan_result.files) {
        if (fe.type != FileType::TEXT) continue;

        try {
            std::string content = read_file_to_string(fe.path);

            // Binary content detection - skip if actually binary despite extension
            if (is_binary_content(content)) {
                const_cast<FileEntry&>(fe).type = FileType::BINARY;
                index.scan_result.total_text_files--;
                index.scan_result.total_binary_files++;
                continue;
            }

            // Enrich file metadata
            const_cast<FileEntry&>(fe).language = detect_language(fe.extension, content);
            const_cast<FileEntry&>(fe).line_count = count_lines(content);
            const_cast<FileEntry&>(fe).encoding = detect_encoding(
                std::vector<uint8_t>(content.begin(), content.begin() + std::min(content.size(), static_cast<size_t>(4096))));
            const_cast<FileEntry&>(fe).imports = extract_imports(content, fe.language);

            // Chunk the text
            auto chunks = chunk_text(content);

            for (const auto& chunk : chunks) {
                index.text_store.add_chunk(
                    fe.path,
                    fe.relative_path,
                    chunk.text,
                    chunk.chunk_index,
                    chunk.start_pos,
                    chunk.end_pos
                );
                index.total_chunks++;
            }

            index.total_text_indexed++;
        } catch (const std::exception& e) {
            std::cerr << "Warning: Failed to index " << fe.path << ": " << e.what() << std::endl;
        }
    }

    // Finalize TF-IDF vectors
    index.text_store.finalize();

    // Step 3: Fingerprint image files
    for (const auto& fe : index.scan_result.files) {
        if (fe.type != FileType::IMAGE) continue;

        try {
            IndexedImage img;
            img.file_path = fe.path;
            img.relative_path = fe.relative_path;
            img.size = fe.size;
            img.fingerprint = fingerprint_image(fe.path);

            int img_idx = static_cast<int>(index.images.size());
            index.base64_to_image[img.fingerprint.base64_hash] = img_idx;
            index.images.push_back(std::move(img));
            index.total_images_indexed++;
        } catch (const std::exception& e) {
            std::cerr << "Warning: Failed to fingerprint " << fe.path << ": " << e.what() << std::endl;
        }
    }

    auto end = std::chrono::steady_clock::now();
    index.index_build_time_ms = static_cast<size_t>(
        std::chrono::duration_cast<std::chrono::milliseconds>(end - start).count()
    );

    return index;
}

const IndexedImage* find_image_by_base64(const ContentIndex& index, const std::string& base64_hash) {
    auto it = index.base64_to_image.find(base64_hash);
    if (it == index.base64_to_image.end()) return nullptr;
    return &index.images[it->second];
}

std::vector<const IndexedImage*> find_similar_images(const ContentIndex& index, const std::string& base64_hash, int max_distance) {
    std::vector<const IndexedImage*> results;

    auto it = index.base64_to_image.find(base64_hash);
    if (it == index.base64_to_image.end()) return results;

    const auto& target = index.images[it->second];

    for (const auto& img : index.images) {
        if (img.fingerprint.base64_hash == base64_hash) continue; // Skip exact match
        if (images_similar(target.fingerprint, img.fingerprint, max_distance)) {
            results.push_back(&img);
        }
    }

    // Sort by hamming distance (most similar first)
    std::sort(results.begin(), results.end(),
              [&target](const IndexedImage* a, const IndexedImage* b) {
                  int dist_a = hamming_distance(target.fingerprint.perceptual_hash, a->fingerprint.perceptual_hash);
                  int dist_b = hamming_distance(target.fingerprint.perceptual_hash, b->fingerprint.perceptual_hash);
                  return dist_a < dist_b;
              });

    return results;
}

std::vector<const IndexedImage*> find_similar_images_by_file(const ContentIndex& index, const std::string& image_path, int max_distance) {
    ImageFingerprint target;
    try {
        target = fingerprint_image(image_path);
    } catch (...) {
        return {};
    }

    std::vector<const IndexedImage*> results;

    for (const auto& img : index.images) {
        if (images_similar(target, img.fingerprint, max_distance)) {
            results.push_back(&img);
        }
    }

    std::sort(results.begin(), results.end(),
              [&target](const IndexedImage* a, const IndexedImage* b) {
                  int dist_a = hamming_distance(target.perceptual_hash, a->fingerprint.perceptual_hash);
                  int dist_b = hamming_distance(target.perceptual_hash, b->fingerprint.perceptual_hash);
                  return dist_a < dist_b;
              });

    return results;
}

// ---------- .gitignore support ----------

ContentIndex index_directory_with_gitignore(const std::string& root_path, bool include_hidden) {
    // Parse .gitignore if present
    fs::path gitignore_path = fs::path(root_path) / ".gitignore";
    std::vector<std::string> gitignore_patterns;
    if (fs::exists(gitignore_path)) {
        gitignore_patterns = parse_gitignore(gitignore_path.string());
    }

    auto start = std::chrono::steady_clock::now();

    ContentIndex index;
    index.total_chunks = 0;
    index.total_images_indexed = 0;
    index.total_text_indexed = 0;

    // Step 1: Scan the directory
    index.scan_result = scan_directory(root_path, include_hidden);

    // Filter out gitignore-matched files
    if (!gitignore_patterns.empty()) {
        std::vector<FileEntry> filtered;
        for (const auto& fe : index.scan_result.files) {
            if (!matches_gitignore(fe.relative_path, gitignore_patterns)) {
                filtered.push_back(fe);
            } else {
                // Update counts
                index.scan_result.total_files--;
                index.scan_result.total_size -= fe.size;
                switch (fe.type) {
                    case FileType::TEXT: index.scan_result.total_text_files--; break;
                    case FileType::IMAGE: index.scan_result.total_image_files--; break;
                    case FileType::BINARY: index.scan_result.total_binary_files--; break;
                    default: break;
                }
            }
        }
        index.scan_result.files = std::move(filtered);
    }

    // Step 2: Index text files (same as index_directory)
    for (const auto& fe : index.scan_result.files) {
        if (fe.type != FileType::TEXT) continue;
        try {
            std::string content = read_file_to_string(fe.path);
            if (is_binary_content(content)) {
                const_cast<FileEntry&>(fe).type = FileType::BINARY;
                index.scan_result.total_text_files--;
                index.scan_result.total_binary_files++;
                continue;
            }
            const_cast<FileEntry&>(fe).language = detect_language(fe.extension, content);
            const_cast<FileEntry&>(fe).line_count = count_lines(content);
            const_cast<FileEntry&>(fe).encoding = detect_encoding(
                std::vector<uint8_t>(content.begin(), content.begin() + std::min(content.size(), static_cast<size_t>(4096))));
            const_cast<FileEntry&>(fe).imports = extract_imports(content, fe.language);
            auto chunks = chunk_text(content);
            for (const auto& chunk : chunks) {
                index.text_store.add_chunk(fe.path, fe.relative_path, chunk.text, chunk.chunk_index, chunk.start_pos, chunk.end_pos);
                index.total_chunks++;
            }
            index.total_text_indexed++;
        } catch (const std::exception& e) {
            std::cerr << "Warning: Failed to index " << fe.path << ": " << e.what() << std::endl;
        }
    }

    index.text_store.finalize();

    // Step 3: Fingerprint images
    for (const auto& fe : index.scan_result.files) {
        if (fe.type != FileType::IMAGE) continue;
        try {
            IndexedImage img;
            img.file_path = fe.path;
            img.relative_path = fe.relative_path;
            img.size = fe.size;
            img.fingerprint = fingerprint_image(fe.path);
            int img_idx = static_cast<int>(index.images.size());
            index.base64_to_image[img.fingerprint.base64_hash] = img_idx;
            index.images.push_back(std::move(img));
            index.total_images_indexed++;
        } catch (const std::exception& e) {
            std::cerr << "Warning: Failed to fingerprint " << fe.path << ": " << e.what() << std::endl;
        }
    }

    auto end = std::chrono::steady_clock::now();
    index.index_build_time_ms = static_cast<size_t>(
        std::chrono::duration_cast<std::chrono::milliseconds>(end - start).count());

    return index;
}

// ---------- Multi-threaded indexing ----------

ContentIndex index_directory_mt(const std::string& root_path, bool include_hidden, size_t num_threads) {
    if (num_threads == 0) {
        num_threads = std::max(1u, std::thread::hardware_concurrency());
    }

    auto start = std::chrono::steady_clock::now();

    ContentIndex index;
    index.total_chunks = 0;
    index.total_images_indexed = 0;
    index.total_text_indexed = 0;

    // Step 1: Scan (single-threaded, fast)
    index.scan_result = scan_directory(root_path, include_hidden);

    // Partition text files for parallel indexing
    std::vector<size_t> text_indices;
    std::vector<size_t> image_indices;
    for (size_t i = 0; i < index.scan_result.files.size(); i++) {
        if (index.scan_result.files[i].type == FileType::TEXT) text_indices.push_back(i);
        else if (index.scan_result.files[i].type == FileType::IMAGE) image_indices.push_back(i);
    }

    // Parallel text indexing
    struct TextIndexResult {
        std::vector<IndexedChunk> chunks;
        std::vector<std::pair<int, size_t>> file_chunk_counts; // file_idx, chunk_count
        std::vector<std::tuple<int, std::string, size_t, std::string, std::vector<std::string>>> metadata; // file_idx, language, line_count, encoding, imports
        size_t text_indexed;
    };

    std::mutex mtx;
    std::vector<std::future<TextIndexResult>> futures;

    size_t files_per_thread = (text_indices.size() + num_threads - 1) / num_threads;
    if (files_per_thread == 0) files_per_thread = text_indices.size();

    for (size_t t = 0; t < num_threads && t * files_per_thread < text_indices.size(); t++) {
        size_t start_idx = t * files_per_thread;
        size_t end_idx = std::min(start_idx + files_per_thread, text_indices.size());

        futures.push_back(std::async(std::launch::async, [&, start_idx, end_idx]() {
            TextIndexResult result;
            result.text_indexed = 0;
            int chunk_id_counter = 0;

            for (size_t i = start_idx; i < end_idx; i++) {
                size_t fi = text_indices[i];
                const auto& fe = index.scan_result.files[fi];
                try {
                    std::string content = read_file_to_string(fe.path);
                    if (is_binary_content(content)) continue;

                    std::string lang = detect_language(fe.extension, content);
                    size_t lc = count_lines(content);
                    std::string enc = detect_encoding(
                        std::vector<uint8_t>(content.begin(), content.begin() + std::min(content.size(), static_cast<size_t>(4096))));
                    auto imports = extract_imports(content, lang);

                    result.metadata.emplace_back(static_cast<int>(fi), lang, lc, enc, imports);

                    auto chunks = chunk_text(content);
                    for (const auto& chunk : chunks) {
                        IndexedChunk ic;
                        ic.id = chunk_id_counter++;
                        ic.file_path = fe.path;
                        ic.relative_path = fe.relative_path;
                        ic.text = chunk.text;
                        ic.chunk_index = chunk.chunk_index;
                        ic.start_pos = chunk.start_pos;
                        ic.end_pos = chunk.end_pos;
                        result.chunks.push_back(std::move(ic));
                    }
                    result.text_indexed++;
                } catch (...) {}
            }
            return result;
        }));
    }

    // Collect results
    for (auto& f : futures) {
        auto res = f.get();
        for (const auto& chunk : res.chunks) {
            index.text_store.add_chunk(chunk.file_path, chunk.relative_path, chunk.text, chunk.chunk_index, chunk.start_pos, chunk.end_pos);
            index.total_chunks++;
        }
        for (const auto& [fi, lang, lc, enc, imports] : res.metadata) {
            auto& fe = index.scan_result.files[fi];
            const_cast<FileEntry&>(fe).language = lang;
            const_cast<FileEntry&>(fe).line_count = lc;
            const_cast<FileEntry&>(fe).encoding = enc;
            const_cast<FileEntry&>(fe).imports = imports;
        }
        index.total_text_indexed += res.text_indexed;
    }

    index.text_store.finalize();

    // Step 3: Fingerprint images (parallel)
    struct ImageResult {
        IndexedImage img;
        int idx;
    };

    std::vector<std::future<std::vector<ImageResult>>> img_futures;
    size_t imgs_per_thread = (image_indices.size() + num_threads - 1) / num_threads;
    if (imgs_per_thread == 0) imgs_per_thread = image_indices.size();

    for (size_t t = 0; t < num_threads && t * imgs_per_thread < image_indices.size(); t++) {
        size_t start_idx = t * imgs_per_thread;
        size_t end_idx = std::min(start_idx + imgs_per_thread, image_indices.size());

        img_futures.push_back(std::async(std::launch::async, [&, start_idx, end_idx]() {
            std::vector<ImageResult> results;
            for (size_t i = start_idx; i < end_idx; i++) {
                size_t fi = image_indices[i];
                const auto& fe = index.scan_result.files[fi];
                try {
                    ImageResult r;
                    r.img.file_path = fe.path;
                    r.img.relative_path = fe.relative_path;
                    r.img.size = fe.size;
                    r.img.fingerprint = fingerprint_image(fe.path);
                    r.idx = static_cast<int>(fi);
                    results.push_back(std::move(r));
                } catch (...) {}
            }
            return results;
        }));
    }

    for (auto& f : img_futures) {
        auto res = f.get();
        for (auto& r : res) {
            int img_idx = static_cast<int>(index.images.size());
            index.base64_to_image[r.img.fingerprint.base64_hash] = img_idx;
            index.images.push_back(std::move(r.img));
            index.total_images_indexed++;
        }
    }

    auto end = std::chrono::steady_clock::now();
    index.index_build_time_ms = static_cast<size_t>(
        std::chrono::duration_cast<std::chrono::milliseconds>(end - start).count());

    return index;
}

// ---------- Persistent Index ----------

bool save_index(const ContentIndex& index, const std::string& filepath) {
    std::string json = full_index_map_to_json(index);
    return save_index_to_file(filepath, json);
}

ContentIndex load_index(const std::string& filepath) {
    ContentIndex index;
    index.total_chunks = 0;
    index.total_images_indexed = 0;
    index.total_text_indexed = 0;
    index.index_build_time_ms = 0;

    std::string json = load_index_from_file(filepath);
    if (json.empty()) return index;

    // Simple JSON parsing for file entries and chunks
    // This is a lightweight parser - for production, use a proper JSON library

    // Count files
    size_t pos = 0;
    int file_count = 0;
    while ((pos = json.find("\"relative_path\":\"", pos)) != std::string::npos) {
        file_count++;
        pos++;
    }

    // Count chunks
    pos = 0;
    int chunk_count = 0;
    while ((pos = json.find("\"chunk_index\":", pos)) != std::string::npos) {
        chunk_count++;
        pos++;
    }

    index.total_text_indexed = file_count;
    index.total_chunks = chunk_count;
    index.scan_result.total_files = file_count;

    return index;
}

} // namespace aisearch
