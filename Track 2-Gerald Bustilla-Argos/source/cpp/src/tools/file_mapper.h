#pragma once

#include "text_utils.h"
#include <string>
#include <vector>
#include <filesystem>
#include <chrono>
#include <cstdint>

namespace aisearch {

namespace fs = std::filesystem;

struct FileEntry {
    std::string  path;           // Full absolute path
    std::string  relative_path;  // Path relative to scan root
    std::string  filename;       // Just the filename
    std::string  extension;      // Lowercase extension with dot
    FileType     type;           // Classified file type
    uintmax_t    size;           // File size in bytes
    std::string  modified_time;  // ISO 8601 formatted
    uint64_t     file_hash;      // FNV-1a hash of file content (for dedup/change detection)
    std::string  hex_hash;       // Hex representation of file_hash
    // AI enrichment fields
    std::string  language;       // Detected programming language
    size_t       line_count;     // Number of lines (for text files)
    std::string  encoding;       // Detected text encoding
    std::vector<std::string> imports; // Import/include references
    bool         is_symlink;     // Whether file is a symlink
};

struct ScanResult {
    std::string              root_path;
    std::vector<FileEntry>   files;
    std::vector<std::string> directories;
    size_t                   total_files;
    size_t                   total_directories;
    size_t                   total_text_files;
    size_t                   total_image_files;
    size_t                   total_binary_files;
    uintmax_t                total_size;
    std::chrono::milliseconds scan_duration;
};

// Scan a directory recursively and collect all file metadata
ScanResult scan_directory(const std::string& root_path, bool include_hidden = false);

// Scan and compute file hashes (slower but more useful for dedup)
ScanResult scan_directory_with_hashes(const std::string& root_path, bool include_hidden = false);

// Format a file_time_t to ISO 8601 string
std::string format_time(const fs::file_time_type& ftime);

// Convert FileType to string
std::string file_type_string(FileType type);

} // namespace aisearch
