#include "json_writer.h"
#include "text_utils.h"
#include <sstream>
#include <iomanip>

namespace aisearch {

std::string file_entry_to_json(const FileEntry& entry) {
    std::ostringstream ss;
    ss << "{";
    ss << "\"path\":\"" << json_escape(entry.path) << "\",";
    ss << "\"relative_path\":\"" << json_escape(entry.relative_path) << "\",";
    ss << "\"filename\":\"" << json_escape(entry.filename) << "\",";
    ss << "\"extension\":\"" << json_escape(entry.extension) << "\",";
    ss << "\"type\":\"" << file_type_string(entry.type) << "\",";
    ss << "\"size\":" << entry.size << ",";
    ss << "\"modified_time\":\"" << entry.modified_time << "\"";
    if (entry.file_hash != 0) {
        ss << ",\"file_hash\":\"" << entry.hex_hash << "\"";
    }
    if (!entry.language.empty()) {
        ss << ",\"language\":\"" << json_escape(entry.language) << "\"";
    }
    if (entry.line_count > 0) {
        ss << ",\"line_count\":" << entry.line_count;
    }
    if (!entry.encoding.empty()) {
        ss << ",\"encoding\":\"" << json_escape(entry.encoding) << "\"";
    }
    if (entry.is_symlink) {
        ss << ",\"is_symlink\":true";
    }
    if (!entry.imports.empty()) {
        ss << ",\"imports\":[";
        for (size_t i = 0; i < entry.imports.size(); i++) {
            if (i > 0) ss << ",";
            ss << "\"" << json_escape(entry.imports[i]) << "\"";
        }
        ss << "]";
    }
    ss << "}";
    return ss.str();
}

std::string image_fingerprint_to_json(const ImageFingerprint& fp) {
    std::ostringstream ss;
    ss << "{";
    ss << "\"base64_hash\":\"" << json_escape(fp.base64_hash) << "\",";
    ss << "\"hex_hash\":\"" << json_escape(fp.hex_hash) << "\",";
    ss << "\"content_hash\":" << "\"" << fp.content_hash << "\",";
    ss << "\"perceptual_hash\":\"" << json_escape(fp.perceptual_hex) << "\",";
    ss << "\"file_format\":\"" << json_escape(fp.file_signature) << "\",";
    ss << "\"file_size\":" << fp.file_size << ",";
    ss << "\"width\":" << fp.width << ",";
    ss << "\"height\":" << fp.height;
    ss << "}";
    return ss.str();
}

std::string scan_result_to_json(const ScanResult& result) {
    std::ostringstream ss;
    ss << "{";
    ss << "\"root_path\":\"" << json_escape(result.root_path) << "\",";
    ss << "\"total_files\":" << result.total_files << ",";
    ss << "\"total_directories\":" << result.total_directories << ",";
    ss << "\"total_text_files\":" << result.total_text_files << ",";
    ss << "\"total_image_files\":" << result.total_image_files << ",";
    ss << "\"total_binary_files\":" << result.total_binary_files << ",";
    ss << "\"total_size\":" << result.total_size << ",";
    ss << "\"scan_duration_ms\":" << result.scan_duration.count() << ",";
    ss << "\"directories\":[";
    for (size_t i = 0; i < result.directories.size(); i++) {
        if (i > 0) ss << ",";
        ss << "\"" << json_escape(result.directories[i]) << "\"";
    }
    ss << "],";
    ss << "\"files\":[";
    for (size_t i = 0; i < result.files.size(); i++) {
        if (i > 0) ss << ",";
        ss << file_entry_to_json(result.files[i]);
    }
    ss << "]}";
    return ss.str();
}

std::string content_index_to_json(const ContentIndex& index) {
    std::ostringstream ss;
    ss << "{";
    ss << "\"root_path\":\"" << json_escape(index.scan_result.root_path) << "\",";
    ss << "\"statistics\":{";
    ss << "\"total_files\":" << index.scan_result.total_files << ",";
    ss << "\"total_text_files\":" << index.scan_result.total_text_files << ",";
    ss << "\"total_image_files\":" << index.scan_result.total_image_files << ",";
    ss << "\"total_binary_files\":" << index.scan_result.total_binary_files << ",";
    ss << "\"total_size\":" << index.scan_result.total_size << ",";
    ss << "\"total_text_indexed\":" << index.total_text_indexed << ",";
    ss << "\"total_chunks\":" << index.total_chunks << ",";
    ss << "\"total_images_indexed\":" << index.total_images_indexed << ",";
    ss << "\"vocabulary_size\":" << index.text_store.vocabulary_size() << ",";
    ss << "\"index_build_time_ms\":" << index.index_build_time_ms;
    ss << "},";
    ss << "\"scan_duration_ms\":" << index.scan_result.scan_duration.count();
    ss << "}";
    return ss.str();
}

std::string search_results_to_json(const SearchResults& results) {
    std::ostringstream ss;
    ss << "{";
    ss << "\"query\":\"" << json_escape(results.query) << "\",";
    ss << "\"total_hits\":" << results.total_hits << ",";
    ss << "\"search_time_ms\":" << std::fixed << std::setprecision(3) << results.search_time_ms << ",";
    ss << "\"text_hits\":[";
    for (size_t i = 0; i < results.text_hits.size(); i++) {
        if (i > 0) ss << ",";
        const auto& hit = results.text_hits[i];
        ss << "{";
        ss << "\"file_path\":\"" << json_escape(hit.file_path) << "\",";
        ss << "\"relative_path\":\"" << json_escape(hit.relative_path) << "\",";
        ss << "\"file_type\":\"" << json_escape(hit.file_type) << "\",";
        ss << "\"snippet\":\"" << json_escape(hit.snippet) << "\",";
        ss << "\"score\":" << std::fixed << std::setprecision(6) << hit.score << ",";
        ss << "\"cosine_similarity\":" << std::fixed << std::setprecision(6) << hit.cosine_similarity << ",";
        ss << "\"chunk_index\":" << hit.chunk_index << ",";
        ss << "\"start_pos\":" << hit.start_pos << ",";
        ss << "\"end_pos\":" << hit.end_pos << ",";
        ss << "\"match_type\":\"" << json_escape(hit.match_type) << "\"";
        if (!hit.context_snippet.empty()) {
            ss << ",\"context_snippet\":\"" << json_escape(hit.context_snippet) << "\"";
        }
        if (!hit.language.empty()) {
            ss << ",\"language\":\"" << json_escape(hit.language) << "\"";
        }
        if (hit.line_number > 0) {
            ss << ",\"line_number\":" << hit.line_number;
        }
        ss << "}";
    }
    ss << "],";
    ss << "\"image_hits\":[";
    for (size_t i = 0; i < results.image_hits.size(); i++) {
        if (i > 0) ss << ",";
        const auto& hit = results.image_hits[i];
        ss << "{";
        ss << "\"file_path\":\"" << json_escape(hit.file_path) << "\",";
        ss << "\"relative_path\":\"" << json_escape(hit.relative_path) << "\",";
        ss << "\"file_type\":\"" << json_escape(hit.file_type) << "\",";
        ss << "\"score\":" << std::fixed << std::setprecision(6) << hit.score << ",";
        ss << "\"base64_hash\":\"" << json_escape(hit.base64_hash) << "\",";
        ss << "\"perceptual_hash\":\"" << json_escape(hit.perceptual_hex) << "\",";
        ss << "\"hamming_distance\":" << hit.hamming_distance << ",";
        ss << "\"match_type\":\"" << json_escape(hit.match_type) << "\"";
        ss << "}";
    }
    ss << "],";
    ss << "\"filename_hits\":[";
    for (size_t i = 0; i < results.filename_hits.size(); i++) {
        if (i > 0) ss << ",";
        const auto& hit = results.filename_hits[i];
        ss << "{";
        ss << "\"file_path\":\"" << json_escape(hit.file_path) << "\",";
        ss << "\"relative_path\":\"" << json_escape(hit.relative_path) << "\",";
        ss << "\"file_type\":\"" << json_escape(hit.file_type) << "\",";
        ss << "\"score\":" << std::fixed << std::setprecision(6) << hit.score << ",";
        ss << "\"match_type\":\"" << json_escape(hit.match_type) << "\",";
        ss << "\"file_size\":" << hit.file_size;
        if (!hit.language.empty()) {
            ss << ",\"language\":\"" << json_escape(hit.language) << "\"";
        }
        ss << "}";
    }
    ss << "],";
    ss << "\"path_hits\":[";
    for (size_t i = 0; i < results.path_hits.size(); i++) {
        if (i > 0) ss << ",";
        const auto& hit = results.path_hits[i];
        ss << "{";
        ss << "\"file_path\":\"" << json_escape(hit.file_path) << "\",";
        ss << "\"relative_path\":\"" << json_escape(hit.relative_path) << "\",";
        ss << "\"file_type\":\"" << json_escape(hit.file_type) << "\",";
        ss << "\"score\":" << std::fixed << std::setprecision(6) << hit.score << ",";
        ss << "\"match_type\":\"" << json_escape(hit.match_type) << "\",";
        ss << "\"file_size\":" << hit.file_size;
        if (!hit.language.empty()) {
            ss << ",\"language\":\"" << json_escape(hit.language) << "\"";
        }
        ss << "}";
    }
    ss << "]}";
    return ss.str();
}

std::string indexed_images_to_json(const ContentIndex& index) {
    std::ostringstream ss;
    ss << "{";
    ss << "\"total_images\":" << index.images.size() << ",";
    ss << "\"images\":[";
    for (size_t i = 0; i < index.images.size(); i++) {
        if (i > 0) ss << ",";
        const auto& img = index.images[i];
        ss << "{";
        ss << "\"file_path\":\"" << json_escape(img.file_path) << "\",";
        ss << "\"relative_path\":\"" << json_escape(img.relative_path) << "\",";
        ss << "\"size\":" << img.size << ",";
        ss << "\"fingerprint\":" << image_fingerprint_to_json(img.fingerprint);
        ss << "}";
    }
    ss << "]}";
    return ss.str();
}

std::string text_chunks_to_json(const ContentIndex& index) {
    const auto& chunks = index.text_store.get_all_chunks();
    std::ostringstream ss;
    ss << "{";
    ss << "\"total_chunks\":" << chunks.size() << ",";
    ss << "\"vocabulary_size\":" << index.text_store.vocabulary_size() << ",";
    ss << "\"chunks\":[";
    for (size_t i = 0; i < chunks.size(); i++) {
        if (i > 0) ss << ",";
        const auto& chunk = chunks[i];
        ss << "{";
        ss << "\"id\":" << chunk.id << ",";
        ss << "\"file_path\":\"" << json_escape(chunk.file_path) << "\",";
        ss << "\"relative_path\":\"" << json_escape(chunk.relative_path) << "\",";
        ss << "\"chunk_index\":" << chunk.chunk_index << ",";
        ss << "\"start_pos\":" << chunk.start_pos << ",";
        ss << "\"end_pos\":" << chunk.end_pos << ",";
        ss << "\"text\":\"" << json_escape(chunk.text) << "\"";
        ss << "}";
    }
    ss << "]}";
    return ss.str();
}

std::string full_index_map_to_json(const ContentIndex& index) {
    std::ostringstream ss;
    ss << "{";
    ss << "\"version\":\"1.0.0\",";
    ss << "\"type\":\"full_index_map\",";
    ss << "\"root_path\":\"" << json_escape(index.scan_result.root_path) << "\",";

    // Statistics
    ss << "\"statistics\":{";
    ss << "\"total_files\":" << index.scan_result.total_files << ",";
    ss << "\"total_directories\":" << index.scan_result.total_directories << ",";
    ss << "\"total_text_files\":" << index.scan_result.total_text_files << ",";
    ss << "\"total_image_files\":" << index.scan_result.total_image_files << ",";
    ss << "\"total_binary_files\":" << index.scan_result.total_binary_files << ",";
    ss << "\"total_size\":" << index.scan_result.total_size << ",";
    ss << "\"total_text_indexed\":" << index.total_text_indexed << ",";
    ss << "\"total_chunks\":" << index.total_chunks << ",";
    ss << "\"total_images_indexed\":" << index.total_images_indexed << ",";
    ss << "\"vocabulary_size\":" << index.text_store.vocabulary_size() << ",";
    ss << "\"index_build_time_ms\":" << index.index_build_time_ms;
    ss << "},";

    // Directories
    ss << "\"directories\":[";
    for (size_t i = 0; i < index.scan_result.directories.size(); i++) {
        if (i > 0) ss << ",";
        ss << "\"" << json_escape(index.scan_result.directories[i]) << "\"";
    }
    ss << "],";

    // Files
    ss << "\"files\":[";
    for (size_t i = 0; i < index.scan_result.files.size(); i++) {
        if (i > 0) ss << ",";
        ss << file_entry_to_json(index.scan_result.files[i]);
    }
    ss << "],";

    // Text chunks (for RAG retrieval)
    const auto& chunks = index.text_store.get_all_chunks();
    ss << "\"text_chunks\":[";
    for (size_t i = 0; i < chunks.size(); i++) {
        if (i > 0) ss << ",";
        const auto& chunk = chunks[i];
        ss << "{";
        ss << "\"id\":" << chunk.id << ",";
        ss << "\"file_path\":\"" << json_escape(chunk.file_path) << "\",";
        ss << "\"relative_path\":\"" << json_escape(chunk.relative_path) << "\",";
        ss << "\"chunk_index\":" << chunk.chunk_index << ",";
        ss << "\"start_pos\":" << chunk.start_pos << ",";
        ss << "\"end_pos\":" << chunk.end_pos << ",";
        ss << "\"text\":\"" << json_escape(chunk.text) << "\"";
        ss << "}";
    }
    ss << "],";

    // Image fingerprints
    ss << "\"images\":[";
    for (size_t i = 0; i < index.images.size(); i++) {
        if (i > 0) ss << ",";
        const auto& img = index.images[i];
        ss << "{";
        ss << "\"file_path\":\"" << json_escape(img.file_path) << "\",";
        ss << "\"relative_path\":\"" << json_escape(img.relative_path) << "\",";
        ss << "\"size\":" << img.size << ",";
        ss << "\"fingerprint\":" << image_fingerprint_to_json(img.fingerprint);
        ss << "}";
    }
    ss << "]";

    ss << "}";
    return ss.str();
}

} // namespace aisearch
