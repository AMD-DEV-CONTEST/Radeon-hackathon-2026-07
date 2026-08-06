#include "text_utils.h"
#include <fstream>
#include <sstream>
#include <algorithm>
#include <cctype>
#include <cstdio>
#include <stdexcept>
#include <regex>
#include <iomanip>
#include <chrono>
#include <ctime>
#include <filesystem>

namespace aisearch {

// ===================== Base64 =====================

static const char base64_chars[] =
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

std::string base64_encode(const uint8_t* data, size_t len) {
    std::string result;
    result.reserve(((len + 2) / 3) * 4);

    for (size_t i = 0; i < len; i += 3) {
        uint32_t triple = 0;
        int padding = 0;

        triple |= (uint32_t)data[i] << 16;
        if (i + 1 < len) {
            triple |= (uint32_t)data[i + 1] << 8;
        } else {
            padding++;
        }
        if (i + 2 < len) {
            triple |= (uint32_t)data[i + 2];
        } else {
            padding++;
        }

        result += base64_chars[(triple >> 18) & 0x3F];
        result += base64_chars[(triple >> 12) & 0x3F];
        if (padding < 2)
            result += base64_chars[(triple >> 6) & 0x3F];
        else
            result += '=';
        if (padding < 1)
            result += base64_chars[triple & 0x3F];
        else
            result += '=';
    }

    return result;
}

std::string base64_encode(const std::string& data) {
    return base64_encode(reinterpret_cast<const uint8_t*>(data.data()), data.size());
}

std::string base64_encode(const std::vector<uint8_t>& data) {
    return base64_encode(data.data(), data.size());
}

// ===================== Hashing =====================

uint64_t fnv1a_hash(const uint8_t* data, size_t len) {
    // FNV-1a 64-bit
    uint64_t hash = 0xcbf29ce484222325ULL;
    for (size_t i = 0; i < len; i++) {
        hash ^= (uint64_t)data[i];
        hash *= 0x100000001b3ULL;
    }
    return hash;
}

uint64_t fnv1a_hash(const std::string& data) {
    return fnv1a_hash(reinterpret_cast<const uint8_t*>(data.data()), data.size());
}

std::string hash_to_hex(uint64_t hash) {
    static const char hex[] = "0123456789abcdef";
    std::string result(16, '0');
    for (int i = 15; i >= 0; i--) {
        result[i] = hex[hash & 0xF];
        hash >>= 4;
    }
    return result;
}

// ===================== Tokenization =====================

std::vector<Token> tokenize(const std::string& text) {
    std::vector<Token> tokens;
    std::string current;
    size_t start = 0;

    for (size_t i = 0; i < text.size(); i++) {
        unsigned char c = static_cast<unsigned char>(text[i]);
        if (std::isalnum(c) || c == '_' || c == '-' || c == '.') {
            if (current.empty()) {
                start = i;
            }
            current += static_cast<char>(std::tolower(c));
        } else {
            if (!current.empty()) {
                tokens.push_back({current, start});
                current.clear();
            }
        }
    }
    if (!current.empty()) {
        tokens.push_back({current, start});
    }

    return tokens;
}

const std::unordered_set<std::string>& stop_words() {
    static const std::unordered_set<std::string> words = {
        "a", "an", "the", "and", "or", "but", "in", "on", "at", "to",
        "for", "of", "with", "by", "from", "is", "was", "are", "were",
        "be", "been", "being", "have", "has", "had", "do", "does", "did",
        "will", "would", "could", "should", "may", "might", "must", "can",
        "this", "that", "these", "those", "i", "you", "he", "she", "it",
        "we", "they", "what", "which", "who", "when", "where", "why", "how",
        "all", "each", "every", "both", "few", "more", "most", "other",
        "some", "such", "no", "not", "only", "own", "same", "so", "than",
        "too", "very", "just", "also", "as", "if", "then", "else", "about",
        "into", "through", "during", "before", "after", "above", "below",
        "up", "down", "out", "off", "over", "under", "again", "further",
        "here", "there", "any", "both", "each", "etc", "vs", "via"
    };
    return words;
}

std::vector<Token> remove_stop_words(const std::vector<Token>& tokens) {
    const auto& sw = stop_words();
    std::vector<Token> result;
    result.reserve(tokens.size());
    for (const auto& t : tokens) {
        if (sw.find(t.text) == sw.end()) {
            result.push_back(t);
        }
    }
    return result;
}

// ===================== Text Chunking =====================

std::vector<TextChunk> chunk_text(const std::string& text, size_t chunk_size, size_t overlap) {
    std::vector<TextChunk> chunks;
    if (text.empty()) return chunks;

    size_t pos = 0;
    int idx = 0;

    while (pos < text.size()) {
        size_t end = std::min(pos + chunk_size, text.size());

        // Try to break at a word boundary
        if (end < text.size()) {
            size_t break_pos = end;
            // Look for whitespace within the last 20% of the chunk
            size_t search_start = pos + (chunk_size * 4 / 5);
            for (size_t i = end; i > search_start; i--) {
                if (std::isspace(static_cast<unsigned char>(text[i]))) {
                    break_pos = i;
                    break;
                }
            }
            end = break_pos;
        }

        TextChunk chunk;
        chunk.text = text.substr(pos, end - pos);
        chunk.start_pos = pos;
        chunk.end_pos = end;
        chunk.chunk_index = idx++;
        chunks.push_back(chunk);

        if (end >= text.size()) break;

        // Move forward, accounting for overlap
        size_t next_start = end > overlap ? end - overlap : end;
        if (next_start <= pos) next_start = pos + 1; // Ensure progress
        pos = next_start;
    }

    return chunks;
}

// ===================== File Type Detection =====================

static const std::unordered_set<std::string> text_extensions = {
    ".txt", ".md", ".markdown", ".rst", ".rtf",
    ".c", ".cpp", ".cc", ".cxx", ".h", ".hpp", ".hxx", ".hh",
    ".java", ".kt", ".kts", ".scala", ".groovy",
    ".py", ".pyw", ".rb", ".pl", ".pm", ".lua", ".php",
    ".js", ".jsx", ".ts", ".tsx", ".mjs", ".vue", ".svelte",
    ".cs", ".go", ".rs", ".swift", ".dart",
    ".sh", ".bash", ".zsh", ".fish", ".ps1", ".bat", ".cmd",
    ".sql", ".graphql", ".gql",
    ".json", ".json5", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
    ".xml", ".svg", ".html", ".htm", ".xhtml", ".css", ".scss", ".sass", ".less",
    ".csv", ".tsv",
    ".log", ".tex", ".bib",
    ".gitignore", ".gitattributes", ".dockerfile", ".env",
    ".makefile", ".cmake", ".gradle", ".pom",
    ".r", ".m", ".jl", ".pl", ".asm", ".s",
    ".f", ".f90", ".f95", ".f03",
    ".vim", ".el", ".clj", ".cljs", ".edn", ".lisp", ".scm",
    ".txt", ".text", ".nfo", ".readme",
};

static const std::unordered_set<std::string> image_extensions = {
    ".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp",
    ".tiff", ".tif", ".ico", ".heic", ".heif",
    ".avif", ".raw", ".cr2", ".nef", ".arw",
    ".psd", ".ai", ".eps",
};

FileType classify_file(const std::string& extension) {
    if (is_text_file(extension)) return FileType::TEXT;
    if (is_image_file(extension)) return FileType::IMAGE;
    return FileType::BINARY;
}

bool is_text_file(const std::string& extension) {
    return text_extensions.count(extension) > 0;
}

bool is_image_file(const std::string& extension) {
    return image_extensions.count(extension) > 0;
}

std::string get_extension(const std::string& filepath) {
    size_t dot_pos = filepath.find_last_of('.');
    if (dot_pos == std::string::npos) return "";
    std::string ext = filepath.substr(dot_pos);
    std::transform(ext.begin(), ext.end(), ext.begin(),
                   [](unsigned char c) { return std::tolower(c); });
    return ext;
}

std::string read_file_to_string(const std::string& filepath) {
    std::ifstream file(filepath, std::ios::binary);
    if (!file) {
        throw std::runtime_error("Cannot open file: " + filepath);
    }
    std::ostringstream ss;
    ss << file.rdbuf();
    return ss.str();
}

std::vector<uint8_t> read_file_to_bytes(const std::string& filepath) {
    std::ifstream file(filepath, std::ios::binary | std::ios::ate);
    if (!file) {
        throw std::runtime_error("Cannot open file: " + filepath);
    }
    auto size = file.tellg();
    file.seekg(0, std::ios::beg);
    std::vector<uint8_t> data(static_cast<size_t>(size));
    if (size > 0) {
        file.read(reinterpret_cast<char*>(data.data()), size);
    }
    return data;
}

std::string get_snippet(const std::string& text, size_t pos, size_t radius) {
    size_t start = pos >= radius ? pos - radius : 0;
    size_t end = std::min(pos + radius, text.size());

    // Trim to word boundaries
    if (start > 0) {
        while (start < end && !std::isspace(static_cast<unsigned char>(text[start])))
            start++;
        while (start < end && std::isspace(static_cast<unsigned char>(text[start])))
            start++;
    }
    if (end < text.size()) {
        while (end > start && !std::isspace(static_cast<unsigned char>(text[end])))
            end--;
    }

    std::string snippet = text.substr(start, end - start);
    // Normalize whitespace
    std::string normalized;
    normalized.reserve(snippet.size());
    bool prev_space = false;
    for (char c : snippet) {
        if (std::isspace(static_cast<unsigned char>(c))) {
            if (!prev_space) {
                normalized += ' ';
                prev_space = true;
            }
        } else {
            normalized += c;
            prev_space = false;
        }
    }
    return normalized;
}

std::string json_escape(const std::string& s) {
    std::string result;
    result.reserve(s.size() + 8);
    for (char c : s) {
        switch (c) {
            case '"':  result += "\\\""; break;
            case '\\': result += "\\\\"; break;
            case '\b': result += "\\b"; break;
            case '\f': result += "\\f"; break;
            case '\n': result += "\\n"; break;
            case '\r': result += "\\r"; break;
            case '\t': result += "\\t"; break;
            default:
                if (static_cast<unsigned char>(c) < 0x20) {
                    char buf[8];
                    std::snprintf(buf, sizeof(buf), "\\u%04x", static_cast<unsigned int>(static_cast<unsigned char>(c)));
                    result += buf;
                } else {
                    result += c;
                }
        }
    }
    return result;
}

// ===================== AI Search Enhancements =====================

bool is_binary_content(const std::string& content, size_t check_bytes) {
    size_t len = std::min(content.size(), check_bytes);
    if (len == 0) return false;

    size_t non_text = 0;
    for (size_t i = 0; i < len; i++) {
        unsigned char c = static_cast<unsigned char>(content[i]);
        if (c == 0) return true; // Null byte = definitely binary
        if (c < 0x09 || (c > 0x0D && c < 0x20 && c != 0x1C && c != 0x1D && c != 0x1E && c != 0x1F)) {
            non_text++;
        }
    }
    // If more than 30% non-text bytes, treat as binary
    return (static_cast<double>(non_text) / static_cast<double>(len)) > 0.30;
}

std::string detect_language(const std::string& extension, const std::string& content) {
    static const std::unordered_map<std::string, std::string> ext_lang = {
        {".c", "c"}, {".h", "c"},
        {".cpp", "cpp"}, {".cc", "cpp"}, {".cxx", "cpp"}, {".hpp", "cpp"}, {".hxx", "cpp"}, {".hh", "cpp"},
        {".java", "java"},
        {".kt", "kotlin"}, {".kts", "kotlin"},
        {".scala", "scala"},
        {".py", "python"}, {".pyw", "python"},
        {".rb", "ruby"},
        {".pl", "perl"}, {".pm", "perl"},
        {".lua", "lua"},
        {".php", "php"},
        {".js", "javascript"}, {".mjs", "javascript"}, {".jsx", "javascript"},
        {".ts", "typescript"}, {".tsx", "typescript"},
        {".go", "go"},
        {".rs", "rust"},
        {".swift", "swift"},
        {".cs", "csharp"},
        {".sh", "shell"}, {".bash", "shell"}, {".zsh", "shell"},
        {".ps1", "powershell"},
        {".bat", "batch"}, {".cmd", "batch"},
        {".sql", "sql"},
        {".graphql", "graphql"}, {".gql", "graphql"},
        {".html", "html"}, {".htm", "html"},
        {".css", "css"}, {".scss", "css"}, {".sass", "css"}, {".less", "css"},
        {".json", "json"},
        {".yaml", "yaml"}, {".yml", "yaml"},
        {".toml", "toml"},
        {".xml", "xml"},
        {".ini", "ini"}, {".cfg", "ini"}, {".conf", "ini"},
        {".md", "markdown"}, {".markdown", "markdown"},
        {".tex", "latex"},
        {".r", "r"},
        {".dart", "dart"},
        {".vue", "vue"}, {".svelte", "svelte"},
        {".csv", "csv"}, {".tsv", "csv"},
        {".log", "log"},
        {".txt", "text"},
        {".dockerfile", "dockerfile"},
        {".makefile", "makefile"},
        {".cmake", "cmake"},
    };

    auto it = ext_lang.find(extension);
    if (it != ext_lang.end()) return it->second;

    // Try content-based detection
    if (!content.empty()) {
        std::string first_line = content.substr(0, content.find('\n'));
        if (first_line.find("#!/bin/") != std::string::npos || first_line.find("#!/usr/bin/env") != std::string::npos)
            return "shell";
        if (first_line.find("<?php") != std::string::npos) return "php";
        if (first_line.find("<!DOCTYPE html") != std::string::npos || first_line.find("<html") != std::string::npos)
            return "html";
        if (first_line.find("<?xml") != std::string::npos) return "xml";
    }

    return "unknown";
}

size_t count_lines(const std::string& text) {
    if (text.empty()) return 0;
    size_t count = 1;
    for (char c : text) {
        if (c == '\n') count++;
    }
    return count;
}

std::string detect_encoding(const std::vector<uint8_t>& bytes, size_t check_bytes) {
    size_t len = std::min(bytes.size(), check_bytes);
    if (len == 0) return "empty";

    // Check BOM
    if (len >= 3 && bytes[0] == 0xEF && bytes[1] == 0xBB && bytes[2] == 0xBF)
        return "utf-8-bom";
    if (len >= 2 && bytes[0] == 0xFF && bytes[1] == 0xFE)
        return "utf-16le";
    if (len >= 2 && bytes[0] == 0xFE && bytes[1] == 0xFF)
        return "utf-16be";

    // Check for binary
    bool has_null = false;
    size_t non_ascii = 0;
    for (size_t i = 0; i < len; i++) {
        if (bytes[i] == 0) { has_null = true; break; }
        if (bytes[i] > 0x7F) non_ascii++;
    }
    if (has_null) return "binary";

    // Validate UTF-8
    bool valid_utf8 = true;
    for (size_t i = 0; i < len; ) {
        uint8_t b = bytes[i];
        if (b <= 0x7F) { i++; continue; }
        int seq_len = 0;
        if ((b & 0xE0) == 0xC0) seq_len = 2;
        else if ((b & 0xF0) == 0xE0) seq_len = 3;
        else if ((b & 0xF8) == 0xF0) seq_len = 4;
        else { valid_utf8 = false; break; }

        if (i + seq_len > len) { valid_utf8 = false; break; }
        for (int j = 1; j < seq_len; j++) {
            if ((bytes[i + j] & 0xC0) != 0x80) { valid_utf8 = false; break; }
        }
        if (!valid_utf8) break;
        i += seq_len;
    }

    if (valid_utf8 && non_ascii > 0) return "utf-8";
    if (non_ascii == 0) return "ascii";
    return "latin-1";
}

std::string get_context_snippet(const std::string& text, size_t match_pos, size_t match_len, size_t context_lines) {
    if (text.empty()) return "";

    // Find line number of match position
    size_t line_num = 1;
    size_t line_start = 0;
    for (size_t i = 0; i < match_pos && i < text.size(); i++) {
        if (text[i] == '\n') {
            line_num++;
            line_start = i + 1;
        }
    }

    // Find the start of context (context_lines before)
    size_t context_start = line_start;
    size_t start_line = line_num;
    for (size_t i = 0, pos = 0; i < context_lines && pos < context_start; ) {
        if (text[pos] == '\n') {
            i++;
            if (i < context_lines) {
                context_start = pos + 1;
                start_line--;
            }
        }
        if (pos + 1 >= context_start) break;
        pos++;
    }

    // Actually find context_start by scanning backwards
    context_start = 0;
    start_line = 1;
    {
        size_t newlines_before = 0;
        size_t last_newline_before_match = 0;
        for (size_t i = 0; i < line_start; i++) {
            if (text[i] == '\n') {
                newlines_before++;
                last_newline_before_match = i;
            }
        }
        size_t target_newlines = newlines_before >= context_lines ? newlines_before - context_lines : 0;
        size_t nl_count = 0;
        for (size_t i = 0; i < line_start; i++) {
            if (text[i] == '\n') {
                if (nl_count == target_newlines) {
                    context_start = i + 1;
                    start_line = nl_count + 2;
                    break;
                }
                nl_count++;
            }
        }
    }

    // Find the end of context (context_lines after)
    size_t context_end = text.size();
    size_t end_line = line_num;
    {
        size_t newlines_after = 0;
        for (size_t i = line_start; i < text.size(); i++) {
            if (text[i] == '\n') {
                newlines_after++;
                if (newlines_after > context_lines) {
                    context_end = i;
                    break;
                }
            }
        }
        end_line = line_num + newlines_after;
        if (newlines_after > context_lines) end_line = line_num + context_lines;
    }

    // Build snippet with line numbers
    std::string result;
    size_t current_line = start_line;
    size_t pos = context_start;
    while (pos < context_end && pos < text.size()) {
        result += std::to_string(current_line) + ": ";
        size_t line_end = pos;
        while (line_end < context_end && line_end < text.size() && text[line_end] != '\n') {
            line_end++;
        }
        result += text.substr(pos, line_end - pos);
        result += '\n';
        current_line++;
        pos = line_end + 1;
    }

    // Trim trailing newline
    if (!result.empty() && result.back() == '\n') result.pop_back();

    return result;
}

std::vector<std::string> extract_imports(const std::string& content, const std::string& language) {
    std::vector<std::string> imports;

    if (language == "python") {
        // import X, from X import Y
        std::istringstream iss(content);
        std::string line;
        while (std::getline(iss, line)) {
            size_t pos = 0;
            while (pos < line.size() && std::isspace(static_cast<unsigned char>(line[pos]))) pos++;
            if (line.compare(pos, 7, "import ") == 0) {
                std::string mod = line.substr(pos + 7);
                size_t as_pos = mod.find(" as ");
                if (as_pos != std::string::npos) mod = mod.substr(0, as_pos);
                size_t comma = mod.find(',');
                if (comma != std::string::npos) mod = mod.substr(0, comma);
                imports.push_back(mod);
            } else if (line.compare(pos, 5, "from ") == 0) {
                size_t imp_pos = line.find(" import", pos + 5);
                if (imp_pos != std::string::npos) {
                    imports.push_back(line.substr(pos + 5, imp_pos - pos - 5));
                }
            }
        }
    } else if (language == "cpp" || language == "c") {
        // #include <X> or #include "X"
        std::istringstream iss(content);
        std::string line;
        while (std::getline(iss, line)) {
            size_t pos = line.find("#include");
            if (pos != std::string::npos) {
                size_t open = line.find('<', pos);
                size_t open_q = line.find('"', pos);
                if (open != std::string::npos) {
                    size_t close = line.find('>', open);
                    if (close != std::string::npos)
                        imports.push_back(line.substr(open + 1, close - open - 1));
                } else if (open_q != std::string::npos) {
                    size_t close_q = line.find('"', open_q + 1);
                    if (close_q != std::string::npos)
                        imports.push_back(line.substr(open_q + 1, close_q - open_q - 1));
                }
            }
        }
    } else if (language == "java" || language == "kotlin" || language == "scala") {
        // import X.Y.Z;
        std::istringstream iss(content);
        std::string line;
        while (std::getline(iss, line)) {
            size_t pos = 0;
            while (pos < line.size() && std::isspace(static_cast<unsigned char>(line[pos]))) pos++;
            if (line.compare(pos, 7, "import ") == 0) {
                std::string imp = line.substr(pos + 7);
                size_t semi = imp.find(';');
                if (semi != std::string::npos) imp = imp.substr(0, semi);
                imports.push_back(imp);
            }
        }
    } else if (language == "javascript" || language == "typescript") {
        // import X from 'Y', require('Y'), import 'Y'
        std::istringstream iss(content);
        std::string line;
        while (std::getline(iss, line)) {
            size_t pos = 0;
            while (pos < line.size() && std::isspace(static_cast<unsigned char>(line[pos]))) pos++;
            if (line.compare(pos, 7, "import ") == 0 || line.compare(pos, 7, "export ") == 0) {
                size_t from_pos = line.find("from ", pos);
                if (from_pos != std::string::npos) {
                    size_t q1 = line.find('\'', from_pos);
                    size_t q2 = line.find('"', from_pos);
                    if (q1 != std::string::npos) {
                        size_t q1e = line.find('\'', q1 + 1);
                        if (q1e != std::string::npos) imports.push_back(line.substr(q1 + 1, q1e - q1 - 1));
                    } else if (q2 != std::string::npos) {
                        size_t q2e = line.find('"', q2 + 1);
                        if (q2e != std::string::npos) imports.push_back(line.substr(q2 + 1, q2e - q2 - 1));
                    }
                } else {
                    size_t q1 = line.find('\'', pos);
                    size_t q2 = line.find('"', pos);
                    if (q1 != std::string::npos) {
                        size_t q1e = line.find('\'', q1 + 1);
                        if (q1e != std::string::npos) imports.push_back(line.substr(q1 + 1, q1e - q1 - 1));
                    } else if (q2 != std::string::npos) {
                        size_t q2e = line.find('"', q2 + 1);
                        if (q2e != std::string::npos) imports.push_back(line.substr(q2 + 1, q2e - q2 - 1));
                    }
                }
            }
            size_t req = line.find("require(");
            if (req != std::string::npos) {
                size_t q1 = line.find('\'', req);
                size_t q2 = line.find('"', req);
                if (q1 != std::string::npos) {
                    size_t q1e = line.find('\'', q1 + 1);
                    if (q1e != std::string::npos) imports.push_back(line.substr(q1 + 1, q1e - q1 - 1));
                } else if (q2 != std::string::npos) {
                    size_t q2e = line.find('"', q2 + 1);
                    if (q2e != std::string::npos) imports.push_back(line.substr(q2 + 1, q2e - q2 - 1));
                }
            }
        }
    } else if (language == "go") {
        // import "X" or import ( "X" ... )
        std::istringstream iss(content);
        std::string line;
        while (std::getline(iss, line)) {
            size_t pos = line.find("import");
            if (pos != std::string::npos) {
                size_t q = line.find('"', pos);
                if (q != std::string::npos) {
                    size_t qe = line.find('"', q + 1);
                    if (qe != std::string::npos) imports.push_back(line.substr(q + 1, qe - q - 1));
                }
            }
        }
    } else if (language == "rust") {
        // use X::Y;
        std::istringstream iss(content);
        std::string line;
        while (std::getline(iss, line)) {
            size_t pos = 0;
            while (pos < line.size() && std::isspace(static_cast<unsigned char>(line[pos]))) pos++;
            if (line.compare(pos, 4, "use ") == 0) {
                std::string imp = line.substr(pos + 4);
                size_t semi = imp.find(';');
                if (semi != std::string::npos) imp = imp.substr(0, semi);
                imports.push_back(imp);
            }
        }
    } else if (language == "ruby") {
        // require 'X', require_relative 'X'
        std::istringstream iss(content);
        std::string line;
        while (std::getline(iss, line)) {
            size_t pos = line.find("require");
            if (pos != std::string::npos) {
                size_t q = line.find('\'', pos);
                size_t q2 = line.find('"', pos);
                if (q != std::string::npos) {
                    size_t qe = line.find('\'', q + 1);
                    if (qe != std::string::npos) imports.push_back(line.substr(q + 1, qe - q - 1));
                } else if (q2 != std::string::npos) {
                    size_t qe = line.find('"', q2 + 1);
                    if (qe != std::string::npos) imports.push_back(line.substr(q2 + 1, qe - q2 - 1));
                }
            }
        }
    }

    return imports;
}

std::string normalize_path(const std::string& path) {
    std::string result = path;
    for (auto& c : result) {
        if (c == '\\') c = '/';
    }
    return result;
}

// ---------- .gitignore Support ----------

std::vector<std::string> parse_gitignore(const std::string& gitignore_path) {
    std::vector<std::string> patterns;
    std::ifstream f(gitignore_path);
    if (!f) return patterns;
    std::string line;
    while (std::getline(f, line)) {
        // Remove trailing whitespace
        while (!line.empty() && (line.back() == ' ' || line.back() == '\t' || line.back() == '\r')) line.pop_back();
        // Skip empty lines and comments
        if (line.empty() || line[0] == '#') continue;
        patterns.push_back(line);
    }
    return patterns;
}

static bool glob_match(const std::string& path, const std::string& pattern) {
    // Simple glob matching: supports * and ? and ** and leading /
    std::string p = pattern;
    std::string s = path;

    // Handle leading slash = anchor to root
    bool anchor = false;
    if (!p.empty() && p[0] == '/') {
        anchor = true;
        p = p.substr(1);
    }

    // Handle trailing slash = directory only (match any path containing it)
    bool dir_only = false;
    if (!p.empty() && p.back() == '/') {
        dir_only = true;
        p.pop_back();
    }

    // Negation
    bool negate = false;
    if (!p.empty() && p[0] == '!') {
        negate = true;
        p = p.substr(1);
    }

    // Convert glob to regex-like matching
    // Handle ** patterns
    if (p.find("**") != std::string::npos) {
        // ** matches any number of path segments
        // Replace ** with a placeholder and do segment matching
        std::string regex_pattern;
        for (size_t i = 0; i < p.size(); i++) {
            if (i + 1 < p.size() && p[i] == '*' && p[i+1] == '*') {
                regex_pattern += ".*";
                i++; // skip second *
            } else if (p[i] == '*') {
                regex_pattern += "[^/]*";
            } else if (p[i] == '?') {
                regex_pattern += "[^/]";
            } else if (p[i] == '.' || p[i] == '+' || p[i] == '(' || p[i] == ')' ||
                       p[i] == '[' || p[i] == ']' || p[i] == '{' || p[i] == '}' ||
                       p[i] == '^' || p[i] == '$' || p[i] == '|' || p[i] == '\\') {
                regex_pattern += '\\';
                regex_pattern += p[i];
            } else {
                regex_pattern += p[i];
            }
        }
        try {
            std::regex re(regex_pattern);
            if (std::regex_search(s, re)) return !negate;
        } catch (...) {}
        return negate ? false : false;
    }

    // Simple * and ? matching without **
    // Match against each path segment and full path
    std::string regex_pattern;
    for (size_t i = 0; i < p.size(); i++) {
        if (p[i] == '*') {
            regex_pattern += "[^/]*";
        } else if (p[i] == '?') {
            regex_pattern += "[^/]";
        } else if (p[i] == '.' || p[i] == '+' || p[i] == '(' || p[i] == ')' ||
                   p[i] == '[' || p[i] == ']' || p[i] == '{' || p[i] == '}' ||
                   p[i] == '^' || p[i] == '$' || p[i] == '|' || p[i] == '\\') {
            regex_pattern += '\\';
            regex_pattern += p[i];
        } else {
            regex_pattern += p[i];
        }
    }

    try {
        std::regex re(regex_pattern);
        // Match against full path and also just the filename
        std::string filename = s;
        size_t last_sep = s.find_last_of('/');
        if (last_sep != std::string::npos) filename = s.substr(last_sep + 1);

        if (anchor) {
            if (std::regex_search(s, re)) return !negate;
        } else {
            if (std::regex_search(s, re) || std::regex_search(filename, re)) return !negate;
            // Also check each path segment
            size_t start = 0;
            while (start < s.size()) {
                size_t end = s.find('/', start);
                if (end == std::string::npos) end = s.size();
                std::string segment = s.substr(start, end - start);
                if (std::regex_search(segment, re)) return !negate;
                start = end + 1;
            }
        }
    } catch (...) {}

    return false;
}

bool matches_gitignore(const std::string& relative_path, const std::vector<std::string>& patterns) {
    std::string norm_path = normalize_path(relative_path);
    bool ignored = false;

    for (const auto& pattern : patterns) {
        std::string p = pattern;
        bool negate = false;
        if (!p.empty() && p[0] == '!') {
            negate = true;
            p = p.substr(1);
        }
        if (glob_match(norm_path, p)) {
            ignored = !negate;
        }
    }
    return ignored;
}

// ---------- Synonym Expansion ----------

static const std::unordered_map<std::string, std::vector<std::string>> synonym_map = {
    {"auth", {"authentication", "authorization", "login", "credentials"}},
    {"authentication", {"auth", "login", "credentials", "signin"}},
    {"authorization", {"auth", "permissions", "access", "acl"}},
    {"login", {"authentication", "auth", "signin", "credentials"}},
    {"logout", {"signout", "session_end"}},
    {"config", {"configuration", "settings", "preferences", "conf"}},
    {"configuration", {"config", "settings", "preferences"}},
    {"settings", {"config", "configuration", "preferences"}},
    {"db", {"database", "storage", "persistence"}},
    {"database", {"db", "storage", "persistence", "sql"}},
    {"search", {"query", "find", "lookup", "retrieve"}},
    {"query", {"search", "find", "lookup", "request"}},
    {"error", {"exception", "failure", "fault", "bug"}},
    {"exception", {"error", "failure", "fault"}},
    {"test", {"testing", "spec", "assertion", "unit_test"}},
    {"testing", {"test", "spec", "assertion"}},
    {"user", {"account", "profile", "member"}},
    {"password", {"credential", "secret", "passphrase"}},
    {"token", {"jwt", "session", "credential", "bearer"}},
    {"jwt", {"token", "session", "bearer"}},
    {"api", {"endpoint", "route", "handler", "controller"}},
    {"endpoint", {"api", "route", "handler"}},
    {"route", {"api", "endpoint", "handler", "path"}},
    {"handler", {"controller", "api", "endpoint", "processor"}},
    {"controller", {"handler", "api", "endpoint", "manager"}},
    {"model", {"entity", "schema", "data_model", "object"}},
    {"view", {"template", "render", "ui", "display"}},
    {"template", {"view", "render", "layout"}},
    {"middleware", {"interceptor", "filter", "pipeline"}},
    {"cache", {"buffer", "memory", "store", "redis"}},
    {"redis", {"cache", "memory_store"}},
    {"queue", {"buffer", "pipeline", "fifo"}},
    {"logger", {"logging", "log", "trace"}},
    {"logging", {"logger", "log", "trace"}},
    {"file", {"document", "artifact", "resource"}},
    {"directory", {"folder", "path", "dir"}},
    {"folder", {"directory", "path", "dir"}},
    {"image", {"picture", "photo", "graphic", "img"}},
    {"hash", {"digest", "checksum", "fingerprint"}},
    {"encrypt", {"encode", "cipher", "scramble"}},
    {"decrypt", {"decode", "decipher", "unscramble"}},
    {"deploy", {"deployment", "release", "publish", "ship"}},
    {"docker", {"container", "image", "kubernetes"}},
    {"container", {"docker", "pod", "instance"}},
    {"async", {"asynchronous", "concurrent", "parallel"}},
    {"sync", {"synchronous", "blocking", "serial"}},
    {"http", {"rest", "web", "request"}},
    {"rest", {"http", "api", "web_service"}},
    {"json", {"javascript_object_notation", "data", "serialization"}},
    {"xml", {"markup", "data", "soap"}},
    {"yaml", {"yml", "configuration", "data"}},
    {"sql", {"database", "query", "db"}},
    {"python", {"py", "script", "django", "flask"}},
    {"java", {"jvm", "spring", "kotlin"}},
    {"cpp", {"c++", "cplusplus", "cc"}},
    {"javascript", {"js", "node", "ecmascript"}},
    {"typescript", {"ts", "tsc"}},
    {"react", {"jsx", "frontend", "component"}},
    {"vue", {"vuejs", "frontend", "component"}},
    {"kubernetes", {"k8s", "container", "orchestration"}},
    {"ci", {"continuous_integration", "pipeline", "automation"}},
    {"cd", {"continuous_deployment", "pipeline", "automation"}},
    {"refactor", {"cleanup", "restructure", "improve"}},
    {"bug", {"defect", "issue", "error", "problem"}},
    {"feature", {"functionality", "capability", "enhancement"}},
    {"todo", {"task", "pending", "fixme", "hack"}},
    {"fixme", {"todo", "bug", "issue", "fix"}},
    {"performance", {"speed", "optimization", "efficiency"}},
    {"security", {"vulnerability", "protection", "safety", "crypto"}},
    {"network", {"socket", "connection", "tcp", "http"}},
    {"memory", {"ram", "heap", "allocation", "buffer"}},
    {"thread", {"concurrent", "parallel", "worker"}},
    {"mutex", {"lock", "synchronization", "critical_section"}},
};

std::vector<std::string> get_synonyms(const std::string& word) {
    std::string lower_word;
    for (char c : word) lower_word += static_cast<char>(std::tolower(static_cast<unsigned char>(c)));

    auto it = synonym_map.find(lower_word);
    if (it != synonym_map.end()) return it->second;
    return {};
}

std::string expand_query_with_synonyms(const std::string& query) {
    auto tokens = tokenize(query);
    if (tokens.empty()) return query;

    std::string expanded = query;
    std::unordered_set<std::string> added;

    for (const auto& token : tokens) {
        auto syns = get_synonyms(token.text);
        for (const auto& syn : syns) {
            if (added.find(syn) == added.end()) {
                expanded += " " + syn;
                added.insert(syn);
            }
        }
    }

    return expanded;
}

// ---------- Regex Search ----------

std::vector<RegexMatch> regex_search(const std::string& text, const std::string& pattern, size_t max_matches) {
    std::vector<RegexMatch> matches;
    try {
        std::regex re(pattern, std::regex_constants::icase);
        auto begin = std::sregex_iterator(text.begin(), text.end(), re);
        auto end = std::sregex_iterator();

        for (auto it = begin; it != end && matches.size() < max_matches; ++it) {
            RegexMatch m;
            m.position = static_cast<size_t>(it->position());
            m.length = static_cast<size_t>(it->length());
            m.matched_text = it->str();
            matches.push_back(std::move(m));
        }
    } catch (const std::regex_error&) {
        // Invalid regex pattern
    }
    return matches;
}

// ---------- Persistent Index ----------

bool save_index_to_file(const std::string& filepath, const std::string& json_data) {
    std::ofstream f(filepath, std::ios::binary);
    if (!f) return false;
    f << json_data;
    f.close();
    return f.good();
}

std::string load_index_from_file(const std::string& filepath) {
    std::ifstream f(filepath, std::ios::binary);
    if (!f) return "";
    std::ostringstream ss;
    ss << f.rdbuf();
    return ss.str();
}

bool is_file_modified(const std::string& filepath, const std::string& stored_mtime) {
    try {
        namespace fsx = std::filesystem;
        auto ftime = fsx::last_write_time(filepath);
        // Convert to string format similar to format_time
        auto sctp = std::chrono::time_point_cast<std::chrono::system_clock::duration>(
            ftime - fsx::file_time_type::clock::now() + std::chrono::system_clock::now()
        );
        auto t = std::chrono::system_clock::to_time_t(sctp);
        std::tm tm_buf;
#if defined(_WIN32)
        localtime_s(&tm_buf, &t);
#elif defined(__ANDROID__) || defined(__APPLE__)
        std::tm* tmp = std::localtime(&t);
        if (tmp) tm_buf = *tmp;
#else
        localtime_r(&t, &tm_buf);
#endif
        std::ostringstream ss;
        ss << std::put_time(&tm_buf, "%Y-%m-%dT%H:%M:%S");
        return ss.str() != stored_mtime;
    } catch (...) {
        return true; // If we can't check, assume modified
    }
}

} // namespace aisearch
