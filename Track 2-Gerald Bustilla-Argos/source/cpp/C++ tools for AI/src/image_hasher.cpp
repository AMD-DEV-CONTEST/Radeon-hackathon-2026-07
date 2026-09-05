#include "image_hasher.h"
#include "text_utils.h"
#include <algorithm>
#include <cstring>
#if defined(_MSC_VER)
#include <intrin.h>
#endif

namespace aisearch {

// Detect image format from magic bytes
std::string detect_image_format(const std::vector<uint8_t>& bytes) {
    if (bytes.size() < 4) return "UNKNOWN";

    // PNG: 89 50 4E 47 0D 0A 1A 0A
    if (bytes.size() >= 8 &&
        bytes[0] == 0x89 && bytes[1] == 0x50 && bytes[2] == 0x4E &&
        bytes[3] == 0x47 && bytes[4] == 0x0D && bytes[5] == 0x0A &&
        bytes[6] == 0x1A && bytes[7] == 0x0A) {
        return "PNG";
    }

    // JPEG: FF D8 FF
    if (bytes[0] == 0xFF && bytes[1] == 0xD8 && bytes[2] == 0xFF) {
        return "JPEG";
    }

    // BMP: 42 4D
    if (bytes[0] == 0x42 && bytes[1] == 0x4D) {
        return "BMP";
    }

    // GIF: 47 49 46 38
    if (bytes.size() >= 6 &&
        bytes[0] == 0x47 && bytes[1] == 0x49 && bytes[2] == 0x46 &&
        bytes[3] == 0x38 && (bytes[4] == 0x37 || bytes[4] == 0x39) && bytes[5] == 0x61) {
        return "GIF";
    }

    // WebP: RIFF....WEBP
    if (bytes.size() >= 12 &&
        bytes[0] == 0x52 && bytes[1] == 0x49 && bytes[2] == 0x46 &&
        bytes[3] == 0x46 &&
        bytes[8] == 0x57 && bytes[9] == 0x45 && bytes[10] == 0x42 &&
        bytes[11] == 0x50) {
        return "WEBP";
    }

    // TIFF: 49 49 2A 00 or 4D 4D 00 2A
    if (bytes.size() >= 4) {
        if ((bytes[0] == 0x49 && bytes[1] == 0x49 && bytes[2] == 0x2A && bytes[3] == 0x00) ||
            (bytes[0] == 0x4D && bytes[1] == 0x4D && bytes[2] == 0x00 && bytes[3] == 0x2A)) {
            return "TIFF";
        }
    }

    // ICO: 00 00 01 00
    if (bytes[0] == 0x00 && bytes[1] == 0x00 && bytes[2] == 0x01 && bytes[3] == 0x00) {
        return "ICO";
    }

    // HEIC: ftyp heic/heix/hevc
    if (bytes.size() >= 12 && bytes[4] == 0x66 && bytes[5] == 0x74 &&
        bytes[6] == 0x79 && bytes[7] == 0x70) {
        if ((bytes[8] == 0x68 && bytes[9] == 0x65 && bytes[10] == 0x69) ||
            (bytes[8] == 0x68 && bytes[9] == 0x65 && bytes[10] == 0x76)) {
            return "HEIC";
        }
    }

    return "UNKNOWN";
}

// Extract image dimensions from header bytes
std::pair<int, int> detect_image_dimensions(const std::vector<uint8_t>& bytes, const std::string& format) {
    if (format == "PNG" && bytes.size() >= 24) {
        // PNG: width at offset 16 (4 bytes BE), height at offset 20 (4 bytes BE)
        int w = (bytes[16] << 24) | (bytes[17] << 16) | (bytes[18] << 8) | bytes[19];
        int h = (bytes[20] << 24) | (bytes[21] << 16) | (bytes[22] << 8) | bytes[23];
        return {w, h};
    }

    if (format == "BMP" && bytes.size() >= 26) {
        // BMP: width at offset 18 (4 bytes LE), height at offset 22 (4 bytes LE)
        int w = bytes[18] | (bytes[19] << 8) | (bytes[20] << 16) | (bytes[21] << 24);
        int h = bytes[22] | (bytes[23] << 8) | (bytes[24] << 16) | (bytes[25] << 24);
        return {w, h};
    }

    if (format == "GIF" && bytes.size() >= 10) {
        // GIF: width at offset 6 (2 bytes LE), height at offset 8 (2 bytes LE)
        int w = bytes[6] | (bytes[7] << 8);
        int h = bytes[8] | (bytes[9] << 8);
        return {w, h};
    }

    if (format == "JPEG") {
        // JPEG: scan for SOF0 (FF C0) or SOF2 (FF C2) marker
        for (size_t i = 0; i + 9 < bytes.size(); i++) {
            if (bytes[i] == 0xFF) {
                uint8_t marker = bytes[i + 1];
                if (marker == 0xC0 || marker == 0xC1 || marker == 0xC2 ||
                    marker == 0xC3 || marker == 0xC5 || marker == 0xC6) {
                    if (i + 9 < bytes.size()) {
                        int h = (bytes[i + 5] << 8) | bytes[i + 6];
                        int w = (bytes[i + 7] << 8) | bytes[i + 8];
                        return {w, h};
                    }
                }
            }
        }
    }

    if (format == "WEBP" && bytes.size() >= 30) {
        // VP8X (extended): width at offset 24 (3 bytes LE + 1), height at offset 27
        // VP8 (lossy): width at offset 26, height at offset 28
        // VP8L (lossless): width at offset 21, height at offset 24
        std::string codec(bytes.begin() + 12, bytes.begin() + 16);
        if (codec == "VP8X" && bytes.size() >= 30) {
            int w = 1 + (bytes[24] | (bytes[25] << 8) | (bytes[26] << 16));
            int h = 1 + (bytes[27] | (bytes[28] << 8) | (bytes[29] << 16));
            return {w, h};
        }
        if (codec == "VP8 " && bytes.size() >= 30) {
            int w = bytes[26] | (bytes[27] << 8);
            int h = bytes[28] | (bytes[29] << 8);
            return {w, h};
        }
        if (codec == "VP8L" && bytes.size() >= 25) {
            int w = 1 + ((bytes[21] | (bytes[22] << 8) | ((bytes[23] & 0x3F) << 16)));
            int h = 1 + (((bytes[23] >> 6) | (bytes[24] << 2) | ((bytes[25] & 0x0F) << 10)));
            return {w, h};
        }
    }

    if (format == "ICO" && bytes.size() >= 10) {
        int w = bytes[6] | (bytes[7] << 8);
        int h = bytes[8] | (bytes[9] << 8);
        return {w, h};
    }

    return {0, 0};
}

// Compute a perceptual hash from raw image bytes
// This is a sampling-based approach that works without decoding the image:
// 1. We sample bytes at regular intervals across the file
// 2. We compare each sample to the running average
// 3. This produces a 64-bit hash that captures the "structure" of the file
// Images that are very similar will have similar byte patterns and thus similar hashes
uint64_t compute_perceptual_hash(const std::vector<uint8_t>& bytes) {
    if (bytes.size() < 64) {
        // For very small files, hash all bytes
        return fnv1a_hash(bytes.data(), bytes.size());
    }

    // Sample 64 bytes at regular intervals (skip header to focus on pixel data)
    // We skip the first 64 bytes (typically header) and sample from the rest
    size_t data_start = std::min((size_t)64, bytes.size() / 4);
    size_t data_range = bytes.size() - data_start;
    size_t step = data_range / 64;
    if (step == 0) step = 1;

    // Collect 64 samples
    uint8_t samples[64];
    for (int i = 0; i < 64; i++) {
        samples[i] = bytes[data_start + i * step];
    }

    // Compute average
    uint32_t sum = 0;
    for (int i = 0; i < 64; i++) {
        sum += samples[i];
    }
    uint8_t avg = static_cast<uint8_t>(sum / 64);

    // Build 64-bit hash: each bit is 1 if sample > avg, 0 otherwise
    uint64_t hash = 0;
    for (int i = 0; i < 64; i++) {
        if (samples[i] > avg) {
            hash |= (1ULL << i);
        }
    }

    return hash;
}

int hamming_distance(uint64_t a, uint64_t b) {
    uint64_t x = a ^ b;
#if defined(_MSC_VER)
    return static_cast<int>(__popcnt64(x));
#elif defined(__GNUC__) || defined(__clang__)
    return __builtin_popcountll(x);
#else
    // Portable fallback
    int count = 0;
    while (x) {
        count += static_cast<int>(x & 1);
        x >>= 1;
    }
    return count;
#endif
}

bool images_similar(const ImageFingerprint& a, const ImageFingerprint& b, int max_distance) {
    return hamming_distance(a.perceptual_hash, b.perceptual_hash) <= max_distance;
}

ImageFingerprint fingerprint_image_bytes(const std::vector<uint8_t>& bytes) {
    ImageFingerprint fp;
    fp.file_size = bytes.size();
    fp.content_hash = fnv1a_hash(bytes.data(), bytes.size());
    fp.hex_hash = hash_to_hex(fp.content_hash);
    fp.base64_hash = base64_encode(bytes.data(), std::min(bytes.size(), (size_t)48));
    fp.file_signature = detect_image_format(bytes);
    auto dims = detect_image_dimensions(bytes, fp.file_signature);
    fp.width = dims.first;
    fp.height = dims.second;
    fp.perceptual_hash = compute_perceptual_hash(bytes);
    fp.perceptual_hex = hash_to_hex(fp.perceptual_hash);
    return fp;
}

ImageFingerprint fingerprint_image(const std::string& filepath) {
    auto bytes = read_file_to_bytes(filepath);
    return fingerprint_image_bytes(bytes);
}

} // namespace aisearch
