#include "file_mapper.h"
#include "text_utils.h"
#include <sstream>
#include <iomanip>
#include <algorithm>
#include <chrono>
#include <ctime>
#include <unordered_set>

namespace aisearch {

std::string format_time(const fs::file_time_type& ftime) {
    // Convert file_time_type to system_clock time
    auto sctp = std::chrono::time_point_cast<std::chrono::system_clock::duration>(
        ftime - fs::file_time_type::clock::now() + std::chrono::system_clock::now()
    );
    auto t = std::chrono::system_clock::to_time_t(sctp);
    std::tm tm_buf;
#if defined(_WIN32)
    localtime_s(&tm_buf, &t);
#elif defined(__ANDROID__) || defined(__APPLE__)
    // Android NDK and older iOS may not have localtime_r
    std::tm* tmp = std::localtime(&t);
    if (tmp) tm_buf = *tmp;
#else
    localtime_r(&t, &tm_buf);
#endif
    std::ostringstream ss;
    ss << std::put_time(&tm_buf, "%Y-%m-%dT%H:%M:%S");
    return ss.str();
}

std::string file_type_string(FileType type) {
    switch (type) {
        case FileType::TEXT:   return "text";
        case FileType::IMAGE:  return "image";
        case FileType::BINARY: return "binary";
        default:               return "unknown";
    }
}

ScanResult scan_directory(const std::string& root_path, bool include_hidden) {
    auto start = std::chrono::steady_clock::now();

    ScanResult result;
    result.root_path = root_path;
    result.total_files = 0;
    result.total_directories = 0;
    result.total_text_files = 0;
    result.total_image_files = 0;
    result.total_binary_files = 0;
    result.total_size = 0;

    fs::path root(root_path);

    if (!fs::exists(root)) {
        result.scan_duration = std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::steady_clock::now() - start);
        return result;
    }

    std::error_code ec;
    // Directories to always skip: build artifacts, VCS metadata, scratch/test dirs
    static const std::unordered_set<std::string> skip_dirs = {
        "build", ".git", ".vs", ".vscode", "node_modules", "__pycache__",
        "C++ tools for AI", "test_data", "Debug", "Release", "x64", "x86",
        "bin", "obj", ".idea"
    };
    for (auto it = fs::recursive_directory_iterator(root, fs::directory_options::skip_permission_denied, ec); it != fs::recursive_directory_iterator(); ) {
        if (ec) {
            ec.clear();
            it.increment(ec);
            continue;
        }

        const auto& entry = *it;

        // Skip hidden files/directories if requested
        if (!include_hidden) {
            std::string name = entry.path().filename().string();
            if (!name.empty() && name[0] == '.') {
            it.disable_recursion_pending();
            it.increment(ec);
            continue;
            }
        }

        // Skip known build/scratch/vcs directories entirely (don't recurse into them)
        {
            std::string name = entry.path().filename().string();
            bool isDir = entry.is_directory(ec);
            if (isDir && skip_dirs.count(name)) {
                it.disable_recursion_pending();
                it.increment(ec);
                continue;
            }
        }

        if (entry.is_directory(ec)) {
            result.directories.push_back(entry.path().string());
            result.total_directories++;
        } else if (entry.is_regular_file(ec)) {
            FileEntry fe;
            fe.path = entry.path().string();
            fe.relative_path = fs::relative(entry.path(), root).string();
            fe.filename = entry.path().filename().string();
            fe.extension = get_extension(fe.path);
            fe.type = classify_file(fe.extension);
            fe.size = entry.file_size(ec);
            fe.modified_time = format_time(entry.last_write_time(ec));
            fe.file_hash = 0;
            fe.hex_hash = "";
            fe.language = "";
            fe.line_count = 0;
            fe.encoding = "";
            fe.is_symlink = entry.is_symlink(ec);

            // Skip files larger than 100MB to avoid memory issues
            const uintmax_t MAX_FILE_SIZE = 100 * 1024 * 1024;
            if (fe.size > MAX_FILE_SIZE) {
                fe.type = FileType::BINARY;
            }

            result.total_size += fe.size;
            result.total_files++;

            switch (fe.type) {
                case FileType::TEXT:  result.total_text_files++;  break;
                case FileType::IMAGE: result.total_image_files++; break;
                case FileType::BINARY: result.total_binary_files++; break;
                default: break;
            }

            result.files.push_back(std::move(fe));
        }

        it.increment(ec);
    }

    result.scan_duration = std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::steady_clock::now() - start);

    return result;
}

ScanResult scan_directory_with_hashes(const std::string& root_path, bool include_hidden) {
    ScanResult result = scan_directory(root_path, include_hidden);

    for (auto& fe : result.files) {
        std::error_code ec;
        try {
            auto bytes = read_file_to_bytes(fe.path);
            fe.file_hash = fnv1a_hash(bytes.data(), bytes.size());
            fe.hex_hash = hash_to_hex(fe.file_hash);
        } catch (...) {
            fe.file_hash = 0;
            fe.hex_hash = "0000000000000000";
        }
    }

    return result;
}

} // namespace aisearch
