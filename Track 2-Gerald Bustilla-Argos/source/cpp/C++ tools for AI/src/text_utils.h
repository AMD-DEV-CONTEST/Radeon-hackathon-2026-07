#pragma once

#include <string>
#include <vector>
#include <unordered_map>
#include <unordered_set>
#include <cstdint>

namespace aisearch {

// ---------- Base64 ----------
std::string base64_encode(const uint8_t* data, size_t len);
std::string base64_encode(const std::string& data);
std::string base64_encode(const std::vector<uint8_t>& data);

// ---------- Hashing ----------
// FNV-1a 64-bit hash
uint64_t fnv1a_hash(const uint8_t* data, size_t len);
uint64_t fnv1a_hash(const std::string& data);

// Hash to hex string
std::string hash_to_hex(uint64_t hash);

// ---------- Tokenization ----------
struct Token {
    std::string text;
    size_t position; // character offset in original text
};

// Tokenize text into lowercase word tokens
std::vector<Token> tokenize(const std::string& text);

// Simple stop word list
const std::unordered_set<std::string>& stop_words();

// Remove stop words from token list
std::vector<Token> remove_stop_words(const std::vector<Token>& tokens);

// ---------- Text Chunking ----------
struct TextChunk {
    std::string text;
    size_t start_pos; // character offset in original document
    size_t end_pos;
    int chunk_index;
};

// Split text into overlapping chunks for RAG-style retrieval
// chunk_size: max characters per chunk
// overlap: number of overlapping characters between chunks
std::vector<TextChunk> chunk_text(const std::string& text, size_t chunk_size = 512, size_t overlap = 64);

// ---------- File Type Detection ----------
enum class FileType {
    TEXT,
    IMAGE,
    BINARY,
    UNKNOWN
};

// Classify file by extension
FileType classify_file(const std::string& extension);

// Check if extension is a text-based file
bool is_text_file(const std::string& extension);

// Check if extension is an image file
bool is_image_file(const std::string& extension);

// Get lowercase extension (including the dot, e.g. ".txt")
std::string get_extension(const std::string& filepath);

// Read entire file as string
std::string read_file_to_string(const std::string& filepath);

// Read entire file as bytes
std::vector<uint8_t> read_file_to_bytes(const std::string& filepath);

// Get a snippet of text around a position
std::string get_snippet(const std::string& text, size_t pos, size_t radius = 100);

// Escape a string for JSON output
std::string json_escape(const std::string& s);

// ---------- AI Search Enhancements ----------

// Detect if content is binary by checking for null bytes and non-text byte ratio
bool is_binary_content(const std::string& content, size_t check_bytes = 8192);

// Detect programming language from file extension and content
std::string detect_language(const std::string& extension, const std::string& content = "");

// Count lines in text content
size_t count_lines(const std::string& text);

// Detect text encoding (UTF-8, UTF-16LE, UTF-16BE, ASCII, Latin-1, Binary)
std::string detect_encoding(const std::vector<uint8_t>& bytes, size_t check_bytes = 4096);

// Get a context-aware snippet with line numbers around a match position
// Returns snippet with surrounding lines and line number annotations
std::string get_context_snippet(const std::string& text, size_t match_pos, size_t match_len = 0, size_t context_lines = 3);

// Extract import/include/require references from source code
std::vector<std::string> extract_imports(const std::string& content, const std::string& language);

// Normalize path separators to forward slashes (for cross-platform comparison)
std::string normalize_path(const std::string& path);

// ---------- .gitignore Support ----------

// Parse a .gitignore file and return a list of glob patterns
std::vector<std::string> parse_gitignore(const std::string& gitignore_path);

// Check if a relative path matches any gitignore pattern
bool matches_gitignore(const std::string& relative_path, const std::vector<std::string>& patterns);

// ---------- Synonym Expansion ----------

// Get synonyms for a word (programming-domain synonyms)
std::vector<std::string> get_synonyms(const std::string& word);

// Expand a query with synonyms
std::string expand_query_with_synonyms(const std::string& query);

// ---------- Regex Search ----------

// Search text content using a regex pattern, return match positions
struct RegexMatch {
    size_t position;
    size_t length;
    std::string matched_text;
};

std::vector<RegexMatch> regex_search(const std::string& text, const std::string& pattern, size_t max_matches = 100);

// ---------- Persistent Index ----------

// Save index to a JSON file
bool save_index_to_file(const std::string& filepath, const std::string& json_data);

// Load index JSON from a file
std::string load_index_from_file(const std::string& filepath);

// Check if a file has been modified since the stored mtime
bool is_file_modified(const std::string& filepath, const std::string& stored_mtime);

} // namespace aisearch
