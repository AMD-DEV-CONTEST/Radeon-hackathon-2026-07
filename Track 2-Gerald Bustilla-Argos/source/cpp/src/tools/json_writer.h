#pragma once

#include "content_indexer.h"
#include "search_engine.h"
#include "file_mapper.h"
#include <string>

namespace aisearch {

// Serialize a ScanResult to JSON
std::string scan_result_to_json(const ScanResult& result);

// Serialize a ContentIndex to JSON (summary + statistics)
std::string content_index_to_json(const ContentIndex& index);

// Serialize search results to JSON
std::string search_results_to_json(const SearchResults& results);

// Serialize a single file entry to JSON
std::string file_entry_to_json(const FileEntry& entry);

// Serialize image fingerprints to JSON
std::string image_fingerprint_to_json(const ImageFingerprint& fp);

// Serialize all indexed images to JSON
std::string indexed_images_to_json(const ContentIndex& index);

// Serialize all text chunks to JSON
std::string text_chunks_to_json(const ContentIndex& index);

// Serialize the full index map (files + content) to JSON
// This is the main output for AI consumption
std::string full_index_map_to_json(const ContentIndex& index);

} // namespace aisearch
