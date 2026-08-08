// filepath: hackathon_ui_operator_distill/native/verifier_bridge.h
// Screen-AI Verification Bridge — Native C++ helpers for fast verification
// Used by CustomVerifier in pipeline/screenai_pipelines.js
// Build target: ai_pc_operator/data/native/verifier_bridge.node (Node addon)

#ifndef SCREENAI_VERIFIER_BRIDGE_H
#define SCREENAI_VERIFIER_BRIDGE_H

#include <string>
#include <cstdint>

namespace screenai {

// Verification result returned to JS
#ifndef SCREENAI_VERIFY_RESULT_DEFINED
#define SCREENAI_VERIFY_RESULT_DEFINED
struct VerifyResult {
    bool passed;
    std::string details;
};
#endif

// Check types supported by the native bridge
enum class CheckType : int {
    FileExists = 0,
    FileSize = 1,
    FileHash = 2,
    ProcessRunning = 3,
    WindowExists = 4,
    PixelMatch = 5,
    ImageDimensions = 6,
    StringContains = 7,
};

// Native verifier entry point
// Returns VerifyResult with passed flag and optional details string.
// `target` is a UTF-8 path/identifier; `options` is an optional JSON string.
VerifyResult verify_native(int check_type,
                           const char* target,
                           const char* options);

// Helper: compute SHA-256 of a file (used by FileHash check)
std::string sha256_file(const std::string& path);

// Helper: read PNG/JPEG dimensions without full decode
bool read_image_dimensions(const std::string& path, int& width, int& height);

// Helper: compare two image files byte-by-byte (fast path for small images)
double image_byte_diff_ratio(const std::string& path1, const std::string& path2);

} // namespace screenai

#endif // SCREENAI_VERIFIER_BRIDGE_H
