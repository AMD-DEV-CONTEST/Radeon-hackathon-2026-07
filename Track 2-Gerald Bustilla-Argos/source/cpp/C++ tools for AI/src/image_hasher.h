#pragma once

#include <string>
#include <vector>
#include <cstdint>

namespace aisearch {

// Image fingerprint containing multiple identification methods
struct ImageFingerprint {
    std::string base64_hash;        // Base64-encoded content hash (exact match)
    std::string hex_hash;           // Hex-encoded content hash (exact match)
    uint64_t    content_hash;       // Raw FNV-1a hash
    uint64_t    perceptual_hash;    // Perceptual hash for similar image detection
    std::string perceptual_hex;     // Perceptual hash as hex string
    std::string file_signature;     // Detected file format (e.g. "PNG", "JPEG")
    size_t      file_size;          // File size in bytes
    int         width;              // Image width (if detectable)
    int         height;             // Image height (if detectable)
};

// Compute full fingerprint for an image file
ImageFingerprint fingerprint_image(const std::string& filepath);

// Compute fingerprint from raw bytes (for in-memory images)
ImageFingerprint fingerprint_image_bytes(const std::vector<uint8_t>& bytes);

// Compute perceptual hash from raw image bytes
// Uses a sampling-based approach that works without an image library:
// - Detects image dimensions from headers (PNG, JPEG, BMP, GIF, WebP)
// - Samples pixel-like data at regular intervals
// - Produces a 64-bit hash
uint64_t compute_perceptual_hash(const std::vector<uint8_t>& bytes);

// Detect image format from magic bytes
std::string detect_image_format(const std::vector<uint8_t>& bytes);

// Try to extract image dimensions from header bytes
std::pair<int, int> detect_image_dimensions(const std::vector<uint8_t>& bytes, const std::string& format);

// Hamming distance between two 64-bit hashes (for perceptual similarity)
int hamming_distance(uint64_t a, uint64_t b);

// Check if two fingerprints are similar (perceptual hash within threshold)
bool images_similar(const ImageFingerprint& a, const ImageFingerprint& b, int max_distance = 10);

} // namespace aisearch
